"""Unprivileged retention and a separate storage accounting worker."""
import json
import os
from pathlib import Path
import time
import sys


def expire(root, cutoff):
    for directory, _, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            try:
                if path.lstat().st_mtime < cutoff and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass


def storage_bytes(root):
    """Count file sizes without following links, including during directory races."""
    total = 0
    for _, _, files, directory_fd in os.fwalk(root, follow_symlinks=False):
        for name in files:
            try:
                total += os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_size
            except OSError:
                pass
    return total


def monitor_storage():
    if os.getuid() != 0:
        raise RuntimeError('Full storage accounting must run as the storage worker')
    while True:
        # Only a byte count crosses the pipe to PID 1; no file contents or paths.
        print(storage_bytes('/data'), flush=True)
        time.sleep(60)


def main():
    if os.getuid() != 1000:
        raise RuntimeError('Artifact retention must run as pi')
    days = json.loads(Path('/etc/pi-butler/limits.json').read_text())['retention_days']
    while True:
        expire('/data/diagnostics', time.time() - days * 86400)
        time.sleep(60)


if __name__ == '__main__':
    if sys.argv[1:] == ['--storage']:
        monitor_storage()
    elif sys.argv[1:]:
        raise SystemExit('Unknown maintenance arguments')
    else:
        main()
