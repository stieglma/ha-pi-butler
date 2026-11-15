"""Container-local, atomic dual-stack KNX egress policy, installed before Pi starts."""
import ctypes
import json
from pathlib import Path
import subprocess

from .knx_config import normalize_options

TABLE = 'pi_butler_knx'
KNX_UID = 1003


class FirewallError(RuntimeError):
    pass


def ruleset(options, replace=False):
    options = normalize_options(options)
    addresses = options['gateway_addresses']
    lines = [f'delete table inet {TABLE}'] if replace else []
    lines += [f'table inet {TABLE} {{', ' chain output {',
              '  type filter hook output priority -300; policy accept;',
              # Kernel neighbour discovery/MLD packets have no application socket
              # owner. Agents have no NET_RAW capability to forge these messages.
              '  icmpv6 type { 130, 131, 132, 133, 135, 136, 143 } return',
              f'  meta skuid {KNX_UID} return']
    for address in addresses:
        family = 'ip6' if ':' in address else 'ip'
        lines.append(f'  {family} daddr {address} counter reject')
    lines += ['  ip daddr 224.0.0.0/4 counter reject', '  ip6 daddr ff00::/8 counter reject',
              '  meta nfproto ipv4 fib daddr type broadcast counter reject',
              '  udp dport 3671 counter reject', '  tcp dport 3671 counter reject', ' }', '}']
    return '\n'.join(lines) + '\n'


def nft(*arguments, input=None):
    try:
        result = subprocess.run(['/usr/sbin/nft', *arguments], input=input, text=True,
                                capture_output=True, timeout=10, check=False,
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FirewallError('KNX firewall unavailable; refusing to start agents') from exc
    if result.returncode:
        raise FirewallError('KNX firewall setup failed; NET_ADMIN and kernel nftables support are required. Refusing to start agents.')
    return result.stdout


def install(options):
    # Fail on malformed config even when called independently of the supervisor.
    options = normalize_options(options)
    try:
        tables = json.loads(nft('--json', 'list', 'tables'))['nftables']
        exists = any(entry.get('table', {}).get('family') == 'inet'
                     and entry.get('table', {}).get('name') == TABLE for entry in tables)
    except (ValueError, KeyError, TypeError) as exc:
        raise FirewallError('Cannot verify existing KNX firewall tables; refusing to start agents') from exc
    # Delete/recreate only our table, in ONE nftables transaction. On failure the
    # old rules remain; unrelated host/container tables are never flushed.
    nft('--file', '-', input=ruleset(options, replace=exists))


def drop_network_admin():
    """Remove NET_ADMIN from PID 1 too, after setup; children already drop all caps."""
    class Header(ctypes.Structure):
        _fields_ = [('version', ctypes.c_uint32), ('pid', ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [('effective', ctypes.c_uint32), ('permitted', ctypes.c_uint32),
                    ('inheritable', ctypes.c_uint32)]
    libc = ctypes.CDLL(None, use_errno=True)
    header, data = Header(0x20080522, 0), (Data * 2)()
    if libc.capget(ctypes.byref(header), ctypes.byref(data)) != 0:
        raise FirewallError('Cannot inspect capabilities; refusing to start agents')
    # PR_CAPBSET_DROP; CAP_NET_ADMIN. Drop bounding before permitted/effective.
    if libc.prctl(24, 12, 0, 0, 0) != 0:
        raise FirewallError('Cannot drop network capability bounding set; refusing to start agents')
    for field in ('effective', 'permitted', 'inheritable'):
        setattr(data[0], field, getattr(data[0], field) & ~(1 << 12))
    if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
        raise FirewallError('Cannot drop network capabilities; refusing to start agents')
    status = Path('/proc/self/status').read_text()
    for line in status.splitlines():
        if line.startswith(('CapEff:', 'CapPrm:', 'CapInh:', 'CapBnd:', 'CapAmb:')) and int(line.split()[1], 16) & (1 << 12):
            raise FirewallError('Network capability retained; refusing to start agents')
