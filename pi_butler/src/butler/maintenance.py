"""Pi-user artifact retention. Never delete pi-controlled paths as root."""
import json
import os
from pathlib import Path
import time


def expire(root, cutoff):
    for directory, _, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            try:
                if path.lstat().st_mtime < cutoff and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass


def main():
    if os.getuid() != 1000:
        raise RuntimeError('Artifact retention must run as pi')
    days = json.loads(Path('/etc/pi-butler/limits.json').read_text())['retention_days']
    while True:
        expire('/data/diagnostics', time.time() - days * 86400)
        time.sleep(60)


if __name__ == '__main__':
    main()
