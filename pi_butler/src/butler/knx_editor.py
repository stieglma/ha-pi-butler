"""Pinned upstream launcher: authenticate every web route, including WebSockets.

The upstream loopback proxy allowlist alone cannot distinguish ingress from Pi.
The random credential is inserted by ingress and is never sent to the browser.
"""
import hmac
import os
from pathlib import Path


def protected_app(app, token):
    async def guarded(scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            values = [v for k, v in scope.get('headers', []) if k.lower() == b'x-butler-knx-token']
            if len(values) != 1 or not hmac.compare_digest(values[0], token.encode()):
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 4403})
                else:
                    await send({'type': 'http.response.start', 'status': 403, 'headers': []})
                    await send({'type': 'http.response.body', 'body': b'Ingress required'})
                return
        await app(scope, receive, send)
    return guarded


def main():
    import json
    from editor_gui.web.server import WebHub
    from editor_gui.plugins.mcp import plugin
    from editor_gui.main import main as editor_main
    credentials = json.loads(Path('/data/knx/credentials.json').read_text())
    original = WebHub.app
    WebHub.app = lambda self: protected_app(original(self), credentials['web_token'])
    # UI settings must not turn the internal MCP endpoint into an unauthenticated
    # endpoint accessible from the agent. Force the supervisor-owned token.
    build_auth = plugin._build_auth
    plugin._build_auth = lambda token='': build_auth(credentials['mcp_token'])
    os.environ['XKNX_MCP_AUTH_TOKEN'] = credentials['mcp_token']
    editor_main()


if __name__ == '__main__':
    main()
