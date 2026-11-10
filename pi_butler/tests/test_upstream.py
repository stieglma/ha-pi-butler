import unittest
from unittest.mock import patch
from aiohttp import web
from butler.access import Upstream
from butler.policy import Rejected


class UpstreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.authenticated_ws = False
        app = web.Application()

        async def rest(request):
            self.requests.append((request.path, request.headers.get('Authorization')))
            if request.path.endswith('/big'):
                return web.Response(text='x'*2000)
            if request.path.endswith('/redirect'):
                raise web.HTTPFound('/core/api/secret')
            return web.json_response({'ok': True})

        async def websocket(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({'type': 'auth_required'})
            auth = await ws.receive_json()
            self.authenticated_ws = auth == {'type': 'auth', 'access_token': 'probe-token'}
            await ws.send_json({'type': 'auth_ok' if self.authenticated_ws else 'auth_invalid'})
            command = await ws.receive_json()
            await ws.send_json({'id': command['id'], 'type': 'result', 'success': True, 'result': [{'entity_id': 'light.test'}]})
            await ws.close()
            return ws

        app.router.add_get('/core/websocket', websocket)
        app.router.add_get('/{path:.*}', rest)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        self.base = 'http://127.0.0.1:' + str(self.site._server.sockets[0].getsockname()[1])
        self.client = Upstream('probe-token', 1000)
        await self.client.start()
        original_request = self.client.session._request

        async def local(method, url, **kwargs):
            return await original_request(method, url.replace('http://supervisor', self.base), **kwargs)
        self.patcher = patch.object(self.client.session, '_request', local)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.client.session.close()
        await self.runner.cleanup()

    async def test_bounded_rest_auth_and_no_redirects(self):
        self.assertEqual(await self.client.rest('/api/config'), {'ok': True})
        self.assertEqual(self.requests[0], ('/core/api/config', 'Bearer probe-token'))
        with self.assertRaises(Rejected):
            await self.client.rest('/api/big')
        with self.assertRaises(Rejected):
            await self.client.rest('/api/redirect')
        self.assertNotIn('/core/api/secret', [p for p, _ in self.requests])

    async def test_registry_handshake(self):
        result = await self.client.ws('config/entity_registry/list')
        self.assertTrue(self.authenticated_ws)
        self.assertEqual(result, [{'entity_id': 'light.test'}])
