"""ASGI API credential/method boundaries without a GUI, bus, or private project."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from butler.knx_runtime import EditorApi
from butler.knx_editor import protected_app


async def main():
    async def fallback(scope, receive, send):
        from starlette.responses import PlainTextResponse
        await PlainTextResponse('upstream')(scope, receive, send)
    runtime = SimpleNamespace(execute=Mock(return_value={'active':None}),audit=Mock())
    app = EditorApi(protected_app(fallback, 'web-private'), runtime,
                    {'web_token':'web-private','mcp_token':'mcp-private'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://editor') as client:
        for path in ('/', '/butler-api/status', '/butler-api/policy', '/butler-assistant'):
            assert (await client.get(path)).status_code == 403
        assert (await client.get('/butler-api/status', headers={'X-Butler-KNX-Token':'web-private'})).status_code == 200
        assert (await client.post('/butler-api/status', headers={'X-Butler-KNX-Token':'web-private'},json={})).status_code == 405
        assert (await client.post('/butler-assistant', headers={'X-Butler-KNX-Token':'web-private'},json={})).status_code == 403
        assert (await client.post('/butler-assistant', headers={'X-Butler-MCP-Token':'mcp-private'},json={})).status_code == 200
        assert (await client.get('/butler-api/status', headers=[('X-Butler-KNX-Token','web-private'),('X-Butler-KNX-Token','web-private')])).status_code == 403
        assert (await client.post('/butler-api/policy', headers={'X-Butler-KNX-Token':'web-private'},content=b'x'*32769)).status_code == 400
    print('KNX API credential separation, duplicate credentials, methods and request bound passed')

if __name__ == '__main__':
    asyncio.run(main())
