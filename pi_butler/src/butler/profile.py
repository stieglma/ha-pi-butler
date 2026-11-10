"""Register image-bundled Pi packages as pi, preserving user choices and settings."""
import json
import os
from pathlib import Path
import re
import tempfile

NPM_NAME = re.compile(r'(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+\Z')
NPM_SOURCE = re.compile(r'npm:((?:@[^/]+/)?[^@/]+)(?:@.+)?\Z')


def package_name(entry, runtime):
    source = entry.get('source') if isinstance(entry, dict) else entry
    if not isinstance(source, str):
        return None
    match = NPM_SOURCE.fullmatch(source)
    if match:
        return match[1]
    prefix = str(runtime / 'node_modules') + '/'
    if source.startswith(prefix):
        name = source[len(prefix):]
        return name if NPM_NAME.fullmatch(name) else None
    return None


def seed_packages(settings, seen, names, runtime):
    """Seed newly shipped defaults once; removals/filters persist across restarts."""
    if not isinstance(settings, dict) or not isinstance(settings.get('packages', []), list):
        raise ValueError('Pi settings must be an object with a packages list')
    if not isinstance(seen, list) or not all(isinstance(n, str) for n in seen):
        raise ValueError('Invalid bundled package history')
    if not isinstance(names, list) or len(set(names)) != len(names) or not all(isinstance(n, str) and NPM_NAME.fullmatch(n) for n in names):
        raise ValueError('Invalid image package manifest')
    result = dict(settings)
    entries = list(settings.get('packages', []))
    existing = {package_name(entry, runtime) for entry in entries}
    for name in names:
        if name not in seen and name not in existing:
            entries.append(str(runtime / 'node_modules' / name))
    result['packages'] = entries
    return result, sorted(set(seen) | set(names))


def write_json(path, value):
    if path.is_symlink():
        raise ValueError('Refusing profile symlink: ' + str(path))
    fd, temporary = tempfile.mkstemp(prefix='.butler-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def initialize(agent_dir=Path('/data/pi'), runtime=Path('/opt/runtime')):
    manifest = json.loads((runtime / 'bundled-packages.json').read_text())
    names = manifest['packages']
    for name in names:
        if not isinstance(name, str) or not NPM_NAME.fullmatch(name):
            raise ValueError('Invalid bundled package name')
        package = runtime / 'node_modules' / name / 'package.json'
        if not package.is_file() or json.loads(package.read_text()).get('name') != name:
            raise ValueError('Bundled package missing from image: ' + name)
    settings_path = agent_dir / 'settings.json'
    history_path = agent_dir / 'butler-bundles.json'
    for path in (settings_path, history_path):
        if path.is_symlink():
            raise ValueError('Refusing profile symlink: ' + str(path))
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    settings, history = seed_packages(settings, history, names, runtime)
    # Settings first: interrupted initialization can safely retry without duplicates.
    write_json(settings_path, settings)
    write_json(history_path, history)


if __name__ == '__main__':
    if os.getuid() != 1000:
        raise RuntimeError('Profile initialization must run as pi')
    initialize()
