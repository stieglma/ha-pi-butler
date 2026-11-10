"""Pi-user Git lifecycle. Delivery is explicit and never resets or force-pushes."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
import uuid

ROOT = Path('/data/workspaces')
CONFIG = Path('/etc/pi-butler/workspace.json')
STATUS = Path('/data/status/repository.json')


class WorkspaceError(ValueError):
    pass


def run(*args, cwd=None, timeout=120, strip=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise WorkspaceError('Command timed out; work preserved. Check terminal authentication/network and retry.') from None
    if result.returncode:
        # Git stderr can contain credential-bearing remote URLs. Do not persist it.
        raise WorkspaceError(f'{args[0]} {args[1] if len(args)>1 else ""} failed; inspect the repository/authentication in the terminal. Work preserved.')
    return result.stdout.strip() if strip else result.stdout


def branch(value):
    if not value or value.startswith('-'):
        raise WorkspaceError('Invalid branch')
    run('git', 'check-ref-format', '--branch', value)
    return value


def validate_config(config):
    for key in ('checkout_branch', 'destination_branch', 'base_branch'):
        branch(config[key])
    branch(config['work_branch_prefix'] + 'check')
    if config['delivery'] not in ('push', 'pull_request') or config['forge'] not in ('github', 'gitlab'):
        raise WorkspaceError('Invalid delivery mode/forge')
    url = config['url']
    if url:
        if any(c.isspace() or ord(c) < 32 for c in url) or url.startswith('-') or '::' in url:
            raise WorkspaceError('Invalid repository URL')
        if '://' in url:
            parsed = urlsplit(url)
            if parsed.scheme not in ('ssh', 'https') or not parsed.hostname or parsed.password:
                raise WorkspaceError('Use SSH/HTTPS URL without embedded passwords')
            if parsed.scheme == 'https' and parsed.username:
                raise WorkspaceError('Use terminal credential helpers instead of URL credentials')
        elif not re.fullmatch(r'(?:[\w.-]+@)?[\w.-]+:[^\s]+', url):
            raise WorkspaceError('Use an SSH or HTTPS repository URL')
    return config


@contextlib.contextmanager
def locked():
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / '.butler.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def status(state, help_text):
    value = {'state': state, 'help': help_text}
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temp = STATUS.with_suffix('.tmp')
    temp.write_text(json.dumps(value))
    temp.chmod(0o644)
    temp.replace(STATUS)
    return value


def setup(config):
    if not config['url']:
        return status('not_configured', 'Pi Web and HA tools are ready without a Git repository. Use /data/workspaces/scratch.')
    repo = ROOT / 'repository'
    with locked():
        if not repo.exists():
            temp = ROOT / ('clone-' + uuid.uuid4().hex)
            try:
                run('git', 'clone', '--branch', config['checkout_branch'], '--', config['url'], str(temp))
                temp.rename(repo)
            except WorkspaceError:
                # Preserve partial clone under its unique name for inspection.
                return status('pending', 'Authenticate in the terminal, then run butler-workspace setup. Partial clone, if any, is preserved.')
        if not (repo / '.git').exists():
            raise WorkspaceError('Repository path already exists and is not a Git checkout')
        if run('git', 'remote', 'get-url', 'origin', cwd=repo) != config['url']:
            raise WorkspaceError('Repository URL changed. Existing checkout preserved; move it aside manually before retrying.')
        for key, option in [('author_name', 'user.name'), ('author_email', 'user.email')]:
            if config[key]:
                run('git', 'config', '--local', option, config[key], cwd=repo)
        return status('ready', 'Repository ready. Pi Web project registration retries automatically; use butler-workspace settings and prepare NAME before editing.')


def settings(config):
    """Expose workflow conventions without repository URLs or credentials."""
    return {key: config[key] for key in (
        'delivery', 'checkout_branch', 'destination_branch', 'base_branch',
        'work_branch_prefix', 'forge')}


def prepare(config, name):
    """Select the configured workflow before edits; preserve existing work."""
    if not config['url']:
        raise WorkspaceError('No repository configured; run setup first')
    if config['delivery'] == 'pull_request':
        return worktree(config, name)
    repo = ROOT / 'repository'
    target = branch(config['destination_branch'])
    with locked():
        if run('git', 'remote', 'get-url', 'origin', cwd=repo) != config['url']:
            raise WorkspaceError('Workspace origin differs from configured repository')
        if run('git', 'status', '--porcelain', cwd=repo):
            raise WorkspaceError('Checkout has existing changes; preserve and resolve them before preparing another task')
        run('git', 'fetch', 'origin', target, cwd=repo)
        # Refuse divergence before changing branches or files.
        refs = run('git', 'for-each-ref', '--format=%(refname)', 'refs/heads/', cwd=repo).splitlines()
        if f'refs/heads/{target}' in refs:
            run('git', 'merge-base', '--is-ancestor', target, f'refs/remotes/origin/{target}', cwd=repo)
            run('git', 'switch', target, cwd=repo)
        else:
            run('git', 'switch', '--track', '-c', target, f'origin/{target}', cwd=repo)
        run('git', 'merge', '--ff-only', f'refs/remotes/origin/{target}', cwd=repo)
        return {'path': str(repo), 'branch': target, 'delivery': 'push'}


def worktree(config, name):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', name):
        raise WorkspaceError('Worktree name must contain letters, digits, underscore or hyphen')
    repo = ROOT / 'repository'
    name_branch = branch(config['work_branch_prefix'] + name)
    base = config['base_branch'] if config['delivery'] == 'pull_request' else config['destination_branch']
    with locked():
        run('git', 'fetch', 'origin', base, cwd=repo)
        path = ROOT / 'tasks' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'worktree', 'add', '-b', name_branch, str(path), f'refs/remotes/origin/{base}', cwd=repo)
        return {'path': str(path), 'branch': name_branch}


def check_changes(cwd):
    run('git', 'diff', '--check', cwd=cwd)
    run('git', 'diff', '--cached', '--check', cwd=cwd)
    changed = run('git', 'diff', '--cached', '--name-only', '--diff-filter=ACM', '-z', cwd=cwd).split('\0')
    import ast
    import yaml
    for name in filter(None, changed):
        # Validate the exact staged candidate, even when working tree differs.
        text = run('git', 'show', ':' + name, cwd=cwd, strip=False)
        try:
            if name.endswith(('.yaml', '.yml')):
                class HALoader(yaml.SafeLoader):
                    pass
                HALoader.add_multi_constructor('!', lambda loader, tag, node: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node))
                list(yaml.load_all(text, Loader=HALoader))
            elif name.endswith('.json'):
                json.loads(text)
            elif name.endswith('.py'):
                ast.parse(text)
            elif name.endswith('.sh'):
                result = subprocess.run(['bash', '-n'], input=text, capture_output=True, text=True)
                if result.returncode:
                    raise ValueError()
        except Exception:
            raise WorkspaceError(f'Syntax check failed for {name}; candidate preserved') from None


def forge_delivery(config, cwd, current):
    """Create/update by exact head+base and verify the server-reported target."""
    base = config['base_branch']
    if config['forge'] == 'github':
        existing = json.loads(run('gh', 'pr', 'list', '--head', current, '--base', base, '--state', 'open', '--json', 'url,baseRefName,headRefName', cwd=cwd))
        if not existing:
            run('gh', 'pr', 'create', '--head', current, '--base', base, '--fill', cwd=cwd)
            existing = json.loads(run('gh', 'pr', 'list', '--head', current, '--base', base, '--state', 'open', '--json', 'url,baseRefName,headRefName', cwd=cwd))
        if len(existing) != 1 or existing[0]['baseRefName'] != base or existing[0]['headRefName'] != current:
            raise WorkspaceError('Could not verify exact PR head/base; pushed work preserved')
        return existing[0]['url']
    existing = json.loads(run('glab', 'mr', 'list', '--source-branch', current, '--target-branch', base, '--output', 'json', cwd=cwd))
    if not existing:
        run('glab', 'mr', 'create', '--source-branch', current, '--target-branch', base, '--fill', '--push=false', '--yes', cwd=cwd)
        existing = json.loads(run('glab', 'mr', 'list', '--source-branch', current, '--target-branch', base, '--output', 'json', cwd=cwd))
    if len(existing) != 1 or existing[0]['target_branch'] != base or existing[0]['source_branch'] != current:
        raise WorkspaceError('Could not verify exact MR head/base; pushed work preserved')
    return existing[0]['web_url']


def deliver(config, cwd, message):
    cwd = Path(run('git', 'rev-parse', '--show-toplevel', cwd=cwd)).resolve()
    if not cwd.is_relative_to(ROOT.resolve()):
        raise WorkspaceError('Delivery must run inside an app workspace')
    if run('git', 'remote', 'get-url', 'origin', cwd=cwd) != config['url']:
        raise WorkspaceError('Workspace origin differs from configured repository')
    current = run('git', 'symbolic-ref', '--short', 'HEAD', cwd=cwd)
    branch(current)
    target = config['destination_branch'] if config['delivery'] == 'push' else current
    if config['delivery'] == 'pull_request' and (not current.startswith(config['work_branch_prefix']) or current == config['base_branch']):
        raise WorkspaceError('PR delivery requires a work branch with the configured prefix')
    with locked():
        if run('git', 'ls-files', '--unmerged', cwd=cwd):
            raise WorkspaceError('Resolve conflicts before delivery')
        if run('git', 'diff', '--name-only', cwd=cwd) or run('git', 'ls-files', '--others', '--exclude-standard', cwd=cwd):
            raise WorkspaceError('Review and stage all intended changes first; unstaged/untracked files preserved')
        # Fetch before committing; a destination ahead of HEAD requires manual reconciliation.
        base = target if config['delivery'] == 'push' else config['base_branch']
        run('git', 'fetch', 'origin', base, cwd=cwd)
        if config['delivery'] == 'push':
            run('git', 'merge-base', '--is-ancestor', f'refs/remotes/origin/{base}', 'HEAD', cwd=cwd)
        check_changes(cwd)
        if run('git', 'diff', '--cached', '--name-only', cwd=cwd):
            if not message.strip():
                raise WorkspaceError('Commit message required')
            run('git', 'commit', '-m', message, cwd=cwd)
        run('git', 'push', 'origin', f'HEAD:refs/heads/{target}', cwd=cwd)
        commit = run('git', 'rev-parse', 'HEAD', cwd=cwd)
        if config['delivery'] == 'push':
            remote = run('git', 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + target, cwd=cwd)
            if remote.split()[0] != commit:
                raise WorkspaceError('Remote commit could not be verified')
            return {'commit': commit, 'branch': target, 'checks': 'Local syntax only; HA deployment validation not performed'}
        return {'commit': commit, 'url': forge_delivery(config, cwd, current), 'base': config['base_branch']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('setup')
    sub.add_parser('status')
    sub.add_parser('settings')
    sub.add_parser('prepare').add_argument('name')
    sub.add_parser('worktree').add_argument('name')
    delivery = sub.add_parser('deliver')
    delivery.add_argument('--message', required=True)
    args = parser.parse_args()
    try:
        config = validate_config(json.loads(CONFIG.read_text()))
        if args.command == 'setup':
            result = setup(config)
        elif args.command == 'status':
            result = json.loads(STATUS.read_text()) if STATUS.exists() else {'state': 'pending'}
        elif args.command == 'settings':
            result = settings(config)
        elif args.command == 'prepare':
            result = prepare(config, args.name)
        elif args.command == 'worktree':
            result = worktree(config, args.name)
        else:
            result = deliver(config, Path.cwd(), args.message)
        print(json.dumps(result, indent=2))
    except (WorkspaceError, OSError, ValueError) as exc:
        if args.command == 'setup':
            status('pending', 'Repository setup failed. Check terminal configuration/authentication, then run butler-workspace setup. Existing work is preserved.')
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
