"""Optional transport check against pinned FastMCP; no GUI, project file or bus.

uv run --no-project --python 3.13 --with fastmcp==4.2.0 --with aiohttp==3.13.2 \
    python pi_butler/tests/knx_mcp_smoke.py
"""
import asyncio
from pathlib import Path
import sys
import socket
from unittest.mock import patch
import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from butler.knx_bridge import call_editor


async def main():
    for json_response in (False, True):
        server = FastMCP('test', auth=StaticTokenVerifier(tokens={'internal-token': {'client_id': 'test', 'scopes': []}}))
        @server.tool
        def project_info() -> dict:
            return {'name': 'Synthetic Project', 'count': 40}
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        service = uvicorn.Server(uvicorn.Config(server.http_app(json_response=json_response), log_level='error'))
        task = asyncio.create_task(service.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(20):
                while not service.started:
                    await asyncio.sleep(.01)
            # Keep the production URL fixed; only redirect this smoke client's hop.
            from aiohttp import ClientSession
            original = ClientSession._request
            async def request(self, method, url, **kwargs):
                return await original(self, method, url.replace(':8512/', f':{port}/'), **kwargs)
            with patch.object(ClientSession, '_request', request):
                result = await call_editor('project_info', {}, 'internal-token')
                assert result == {'name': 'Synthetic Project', 'count': 40}, result
                try:
                    await call_editor('project_info', {}, 'wrong-token')
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Unauthenticated internal MCP access')
        finally:
            service.should_exit = True
            await task
    print('Pinned MCP JSON/SSE transport and internal authentication passed')


if __name__ == '__main__':
    asyncio.run(main())
