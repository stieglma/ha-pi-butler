"""Real kernel policy test in a disposable dual-stack Docker namespace only.

No real KNX gateway is used. All echo endpoints belong to this container.
Can also run with native Linux Python + nftables for an Apple Silicon kernel test.
"""
import json
import os
import socket
import subprocess
import sys

from butler.knx_firewall import FirewallError, TABLE, drop_network_admin, install, nft


def identity(uid):
    return ['setpriv', '--reuid', str(uid), '--regid', str(uid), '--clear-groups',
            '--no-new-privs', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all']


SERVER = r'''
import json,socket,sys,threading
addresses=json.loads(sys.argv[1])
ports=[]
def serve(sock, tcp):
    while True:
        if tcp:
            peer,_=sock.accept()
            with peer: peer.sendall(peer.recv(100))
        else:
            body,peer=sock.recvfrom(100)
            sock.sendto(body,peer)
for address in addresses:
    family=socket.AF_INET6 if ':' in address else socket.AF_INET
    for tcp in (True,False):
        sock=socket.socket(family,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
        if family==socket.AF_INET6: sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
        sock.bind((address,0))
        if tcp: sock.listen()
        threading.Thread(target=serve,args=(sock,tcp),daemon=True).start()
        ports.append([address,sock.getsockname()[1],tcp])
# A standard-port endpoint on an UNCONFIGURED address proves port-wide blocking.
sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
sock.bind(('127.0.0.2',3671))
threading.Thread(target=serve,args=(sock,False),daemon=True).start()
ports.append(['127.0.0.2',3671,False])
print(json.dumps(ports),flush=True)
threading.Event().wait()
'''
CLIENT = r'''
import socket,sys
address,port,tcp=sys.argv[1],int(sys.argv[2]),sys.argv[3]=='True'
family=socket.AF_INET6 if ':' in address else socket.AF_INET
sock=socket.socket(family,socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
if family==socket.AF_INET6: sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
sock.settimeout(.6)
sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
try:
    target=(address,port)
    if '%' in address:
        addr,interface=address.split('%')
        target=(addr,port,0,socket.if_nametoindex(interface))
    sock.connect(target)
    sock.send(b'firewall-test')
    assert sock.recv(100)==b'firewall-test'
except OSError:
    sys.exit(23)
'''


def client(uid, endpoint):
    reply = subprocess.run(identity(uid) + [sys.executable, '-c', CLIENT, *map(str, endpoint)],
                           capture_output=True, text=True, timeout=5)
    assert not reply.stderr, reply.stderr
    return reply.returncode


def rejected_packets():
    result = json.loads(nft('--json', 'list', 'table', 'inet', TABLE))
    return sum(expr.get('counter', {}).get('packets', 0)
               for entry in result['nftables'] for expr in entry.get('rule', {}).get('expr', []))


def blocked(uid, endpoint):
    before = rejected_packets()
    assert client(uid, endpoint) == 23, f'UID {uid} reached {endpoint}'
    assert rejected_packets() > before, f'No kernel rejection for {endpoint}'


def main():
    assert os.getuid() == 0
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None)
                                   if item[0] in (socket.AF_INET, socket.AF_INET6)))
    assert any(':' in address for address in addresses), 'Disposable test network must support IPv6'
    assert any(':' not in address for address in addresses), 'Disposable test network must support IPv4'
    server = subprocess.Popen(identity(1003) + [sys.executable, '-u', '-c', SERVER, json.dumps(addresses)],
                              stdout=subprocess.PIPE, text=True)
    try:
        endpoints = json.loads(server.stdout.readline())
        for endpoint in endpoints:
            assert client(1000, endpoint) == 0, f'Baseline connectivity failed: {endpoint}'
            assert client(1003, endpoint) == 0
        mapped = [["::ffff:" + address, port, tcp] for address, port, tcp in endpoints
                  if ':' not in address and address != '127.0.0.2']
        for endpoint in mapped:
            assert client(1000, endpoint) == 0, 'Mapped IPv6 baseline failed'
        endpoints += mapped
        options = {'enabled': True, 'gateway_addresses': addresses}
        install(options)
        for endpoint in endpoints:
            blocked(1000, endpoint)
            blocked(1001, endpoint)
            assert client(1003, endpoint) == 0, f'KNX service denied {endpoint}'
        for address in ('224.0.23.12', '255.255.255.255', 'ff02::1%eth0'):
            blocked(1000, [address, 45678, False])
        for uid in (1000, 1003):
            result = subprocess.run(identity(uid) + ['/usr/sbin/nft', 'flush', 'ruleset'], capture_output=True)
            assert result.returncode != 0, f'UID {uid} could change firewall'
        raw = subprocess.run(identity(1000) + [sys.executable, '-c',
            'import socket; socket.socket(socket.AF_PACKET, socket.SOCK_RAW)'], capture_output=True, text=True)
        assert raw.returncode != 0 and 'PermissionError' in raw.stderr, 'Agent could create raw packet sockets'
        result = subprocess.run(identity(1000) + ['setpriv', '--reuid', '1003', 'true'], capture_output=True)
        assert result.returncode != 0, 'Agent could impersonate KNX service'
        nft('add', 'table', 'inet', 'unrelated_test_table')
        install(options)  # Atomic replacement/restart, not duplicate rules.
        assert 'unrelated_test_table' in nft('--json', 'list', 'tables')
        try:
            nft('--file', '-', input=f'delete table inet {TABLE}\ninvalid deliberate test syntax\n')
        except FirewallError:
            pass
        else:
            raise AssertionError('Invalid policy unexpectedly accepted')
        blocked(1000, endpoints[0])  # Failed transaction retained previous guard.
        drop_network_admin()
        result = subprocess.run(['/usr/sbin/nft', 'list', 'tables'], capture_output=True)
        assert result.returncode != 0, 'Root test controller retained/regained NET_ADMIN after drop'
        assert client(1000, endpoints[0]) == 23
        assert client(1003, endpoints[0]) == 0
        print('Firewall passed: IPv4/IPv6 TCP/UDP, custom gateway ports, standard port on unlisted address, multicast/broadcast, UID spoof/tamper denial, atomic restart/rollback, NET_ADMIN drop.')
    finally:
        server.terminate()
        server.wait(timeout=5)
        server.stdout.close()


if __name__ == '__main__':
    main()
