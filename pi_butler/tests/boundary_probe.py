"""Run as pi INSIDE the running app: no secret values are printed."""
import os
from pathlib import Path
import socket

assert os.getuid() == 1000, 'Run this probe as pi'
assert not any('SUPERVISOR_TOKEN' in key or 'HASSIO_TOKEN' in key for key in os.environ), 'Credential in environment'
for path in ['/data/options.json', '/data/service/options.json', '/data/service', '/proc/1/environ', '/proc/1/mem']:
    try:
        fd = os.open(path, os.O_RDONLY)
    except (PermissionError, FileNotFoundError, IsADirectoryError):
        pass
    else:
        os.close(fd)
        raise AssertionError('Protected path is readable: ' + path)
for path in ['/data', '/etc/passwd', '/etc/pi-butler/workspace.json', '/opt/butler/butler/access.py', '/opt/butler-marketplace', '/usr/local/bin/butler-mcp', '/run/butler/access']:
    assert not os.access(path, os.W_OK), 'Trusted path writable: ' + path
for proc in Path('/proc').iterdir():
    if proc.name.isdigit():
        try:
            environment = (proc / 'environ').read_bytes()
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
        assert b'SUPERVISOR_TOKEN=' not in environment and b'HASSIO_TOKEN=' not in environment, 'Upstream credential in readable process environment'
status = Path('/proc/self/status').read_text()
for field in ['CapEff:', 'CapPrm:', 'CapBnd:']:
    line = next(line for line in status.splitlines() if line.startswith(field))
    assert int(line.split()[1], 16) == 0, 'Capabilities retained: ' + field
assert 'NoNewPrivs:\t1' in status, 'no-new-privileges missing'
try:
    os.setuid(0)
except PermissionError:
    pass
else:
    raise AssertionError('Could become root')
with socket.socket(socket.AF_UNIX) as connection:
    connection.connect('/run/butler/access/access.sock')
with socket.socket(socket.AF_UNIX) as connection:
    try:
        connection.connect('/run/butler/admin/settings.sock')
    except PermissionError:
        pass
    else:
        raise AssertionError('Agent can reach permission management socket')
print('Boundary probe passed: file/process credential access denied, trusted paths protected, capabilities absent, approved socket reachable.')
