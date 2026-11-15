"""Unprivileged retention and a separate storage accounting worker."""
import json
import contextlib
import os
from pathlib import Path
import socket
import socketserver
import threading
import time
import sys

CAPACITY_SOCKET = Path('/run/butler/storage/capacity.sock')


class StorageCapacityError(ValueError):
    """Safe capacity errors for callers that cannot inspect all private storage."""


class StorageCapacity:
    def __init__(self, root, limit):
        self.root, self.limit = root, limit
        self.reserved = 0
        self.lock = threading.Lock()

    @contextlib.contextmanager
    def reserve(self, amount):
        if type(amount) is not int or not 0 < amount <= self.limit:
            yield False
            return
        with self.lock:
            allowed = storage_bytes(self.root) + self.reserved + amount <= self.limit
            if allowed:
                self.reserved += amount
        try:
            yield allowed
        finally:
            if allowed:
                with self.lock:
                    self.reserved -= amount


class CapacityHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        try:
            raw = self.rfile.readline(32)
            amount = int(raw) if raw.endswith(b'\n') else 0
            with self.server.capacity.reserve(amount) as allowed:
                self.wfile.write(b'1\n' if allowed else b'0\n')
                self.wfile.flush()
                if allowed:
                    # Keep the lease until the caller closes, bounded beyond the
                    # editor's 600-second operation timeout for crashed clients.
                    self.connection.settimeout(660)
                    self.rfile.read(1)
            if allowed:
                self.wfile.write(b'0\n')
                self.wfile.flush()
        except (OSError, ValueError):
            pass


@contextlib.contextmanager
def storage_server(root, limit, path=CAPACITY_SOCKET):
    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
    path = Path(path)
    path.unlink(missing_ok=True)
    with Server(str(path), CapacityHandler) as server:
        server.capacity = StorageCapacity(root, limit)
        # The root-owned parent has setgid KNX; Pi cannot replace or use this socket.
        path.chmod(0o660)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.capacity
        finally:
            server.shutdown()
            thread.join()
            path.unlink(missing_ok=True)


@contextlib.contextmanager
def reserve_storage(amount, path=CAPACITY_SOCKET):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(30)
        try:
            connection.connect(str(path))
            connection.sendall(str(amount).encode('ascii') + b'\n')
            with connection.makefile('rb') as stream:
                result = stream.readline(3)
        except OSError:
            raise StorageCapacityError('Storage accounting unavailable; retry after the app finishes starting.') from None
        if result != b'1\n':
            raise StorageCapacityError('Not enough app-wide storage headroom. Free space or increase storage_megabytes.')
        try:
            yield
        finally:
            # Acknowledge release before another operation requests capacity.
            try:
                connection.sendall(b'\n')
                with connection.makefile('rb') as stream:
                    stream.readline(3)
            except OSError:
                pass


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
    limit = json.loads(Path('/etc/pi-butler/limits.json').read_text())['storage_megabytes'] * 1048576
    with storage_server('/data', limit):
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
