"""Exercise the production launcher and pinned plugin without a GUI or KNX bus.

Run with /opt/knx/venv/bin/python in the production image.
"""
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from editor_gui import host
from editor_gui.main import KnxGuiApp
from editor_gui.plugins.mcp import plugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from butler.knx_editor import main


def exercise_editor():
    assert 'XKNX_MCP_AUTH_TOKEN' not in os.environ
    # Exercise the exact UI method that previously disclosed the private token.
    ui = SimpleNamespace(_mcp_token='user-settings-token')
    with patch.object(host, '_current', host.HostOptions(mcp_host='127.0.0.1', mcp_port=8512)):
        assert KnxGuiApp._mcp_command_token(ui) == ''
    service = plugin.McpServerPlugin(Mock(), Mock(), Mock(), Mock(), Mock())
    port = None
    try:
        for settings_token in ('', 'user-settings-token', ''):
            service.start('127.0.0.1', port or 0, token=settings_token)
            deadline = time.monotonic() + 30
            while service._server is None or not service._server.started:
                assert service.is_running, 'Pinned MCP plugin exited during startup'
                assert time.monotonic() < deadline, 'Pinned MCP plugin startup timed out'
                time.sleep(.02)
            port = service._server.config.port
            with httpx.Client(timeout=10) as client:
                for token in (None, 'wrong-token', 'user-settings-token', 'supervisor-private-token'):
                    headers = {'Accept': 'application/json, text/event-stream'}
                    if token is not None:
                        headers['Authorization'] = f'Bearer {token}'
                    response = client.post(f'http://127.0.0.1:{port}/mcp', headers=headers,
                                           json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                                 'params': {'protocolVersion': '2025-03-26',
                                                            'capabilities': {},
                                                            'clientInfo': {'name': 'auth-smoke', 'version': '1'}}})
                    if token == 'supervisor-private-token':
                        assert response.status_code == 200, response.text
                        assert 'serverInfo' in response.text, response.text
                    else:
                        assert response.status_code == 401, response.text
            service.stop()
            assert not service.is_running, 'Pinned MCP plugin did not stop'
    finally:
        service.stop()


if __name__ == '__main__':
    import json
    read_text = Path.read_text
    def read_credentials(path, *args, **kwargs):
        if str(path) == '/data/knx/credentials.json':
            return json.dumps({'web_token': 'private-web-token', 'mcp_token': 'supervisor-private-token'})
        return read_text(path, *args, **kwargs)
    with patch.dict(os.environ, {'XKNX_MCP_AUTH_TOKEN': 'supervisor-private-token'}), \
         patch('butler.knx_editor.Path.read_text', read_credentials), \
         patch('editor_gui.main.main', side_effect=exercise_editor), \
         patch('butler.knx_runtime.Runtime.attach'):
        main()
    print('Pinned editor launcher: no UI token disclosure; restart authentication passed')
