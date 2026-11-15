"""Production launcher headless startup/restart in a disposable Linux container.

No firewall or bus operations; --no-connect is required. Uses a synthetic project.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import httpx

from butler.maintenance import CAPACITY_SOCKET, storage_server


def main():
    assert sys.platform == 'linux' and os.getuid() == 0
    root = Path('/data/knx')
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / 'credentials.json').exists(), 'Use a fresh disposable container'
    projects = root / 'projects'
    projects.mkdir()
    from editor_gui.plugins.catalog.service import CatalogService
    from editor_gui.plugins.project.service import ProjectService
    catalog = CatalogService(root / 'catalog.xknxcatalog')
    project = ProjectService(catalog)
    from editor_gui.plugins.base import Logger
    from editor_gui.plugins.logger.service import LogService
    project.set_logger(Logger(LogService(), 'project'))
    project.new(projects / 'manual.xknx', name='Runtime Synthetic')
    project.close()
    (root / 'credentials.json').write_text(json.dumps({'web_token':'smoke-web-token','mcp_token':'smoke-mcp-token'}))
    # Existing manual import: upstream recent settings, no Butler marker yet.
    config = root / 'config'
    config.mkdir()
    env = {'PATH':'/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH':os.environ.get('PYTHONPATH', '/opt/butler'),
           'HOME':str(root),'LANG':'C.UTF-8','XDG_CONFIG_HOME':str(config),
           'XDG_DATA_HOME':str(root/'data'),'XDG_CACHE_HOME':str(root/'cache'),
           'XDG_STATE_HOME':str(root/'state')}
    subprocess.run([sys.executable, '-c', "from editor_gui.settings import save_settings; save_settings('app', {'recent_files':['/data/knx/projects/manual.xknx']})"], env=env, check=True)
    for path in [root, *root.rglob('*')]:
        os.chown(path,1003,1003)
    root.chmod(0o700)
    command=['setpriv','--reuid','1003','--regid','1003','--clear-groups','--no-new-privs',
             '--bounding-set=-all',sys.executable,'-m','butler.knx_editor',
             '--web=127.0.0.1:8511','--web-no-browser','--web-no-tray',
             '--web-files=/data/knx/projects','--no-connect','--mcp=127.0.0.1:8512']
    CAPACITY_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    os.chown(CAPACITY_SOCKET.parent, 0, 1003)
    CAPACITY_SOCKET.parent.chmod(0o2750)
    with storage_server('/data', 4096 * 1048576):
        for attempt in range(2):
            with open('/tmp/knx-runtime.log','w') as output:
                process=subprocess.Popen(command,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    deadline=time.monotonic()+180
                    with httpx.Client(timeout=40) as client:
                        while True:
                            assert process.poll() is None, Path('/tmp/knx-runtime.log').read_text()[-8000:]
                            try:
                                reply=client.get('http://127.0.0.1:8511/butler-api/status',headers={'X-Butler-KNX-Token':'smoke-web-token'})
                                status=reply.json()
                                if reply.status_code==200 and status.get('active') and status.get('checkpoints'):
                                    break
                            except httpx.TransportError:
                                pass
                            assert time.monotonic()<deadline, Path('/tmp/knx-runtime.log').read_text()[-8000:]
                            time.sleep(.5)
                        assert status['active']['name']=='Runtime Synthetic', status
                        assert not status['dirty'],status
                        assert (root/'active-project.json').exists()
                        assert client.get('http://127.0.0.1:8511/butler-api/status').status_code==403
                        reply=client.post('http://127.0.0.1:8511/butler-assistant',headers={'X-Butler-MCP-Token':'smoke-mcp-token'},
                            json={'tool':'project_create_group_address','arguments':{'address':'1/2/3','name':'Denied'}})
                        assert reply.status_code==400, reply.text
                        if attempt == 0:
                            private = Path('/data/service')
                            private.mkdir(mode=0o700, exist_ok=True)
                            quota_file = private / 'quota-probe'
                            with quota_file.open('wb') as stream:
                                stream.truncate(4032 * 1048576)
                            try:
                                before = {row['id'] for row in status['checkpoints']}
                                reply = client.post('http://127.0.0.1:8511/butler-api/checkpoint',
                                    headers={'X-Butler-KNX-Token':'smoke-web-token'}, json={'comment':'Capacity denied'})
                                assert reply.status_code == 400, reply.text
                                assert 'app-wide storage headroom' in reply.json()['error'], reply.text
                                after = client.get('http://127.0.0.1:8511/butler-api/status',
                                    headers={'X-Butler-KNX-Token':'smoke-web-token'}).json()
                                assert {row['id'] for row in after['checkpoints']} == before, after
                                assert not after['dirty'], after
                            finally:
                                quota_file.unlink()
                finally:
                    try:
                        os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL)
                        process.wait()
    print('Production KNX headless launcher: migration, checkpoints, private app-quota headroom, denied mutation and restart reopening passed')


if __name__ == '__main__':
    main()
