import unittest
from unittest.mock import Mock
from aiohttp import web
from butler.ingress import proxy, CLIENT


class IngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_untrusted_peer_cannot_spoof_ingress(self):
        for ip in ['127.0.0.1', '172.30.33.9', '192.168.1.2']:
            req = Mock()
            req.transport.get_extra_info.return_value = (ip, 1234)
            req.headers = {'X-Forwarded-For': '172.30.32.2', 'X-Ingress-Path': '/api/hassio_ingress/fake'}
            with self.assertRaises(web.HTTPForbidden):
                await proxy(req)

    async def test_missing_peer_denied(self):
        req = Mock()
        req.transport.get_extra_info.return_value = None
        with self.assertRaises(web.HTTPForbidden):
            await proxy(req)

    async def test_http_and_websocket_proxy_preserve_public_headers(self):
        from aiohttp import ClientSession
        from unittest.mock import patch
        backend = web.Application()
        received = []
        async def echo(request):
            if request.path.startswith('//'):
                return web.json_response({'code': 'FST_STATIC_FORBIDDEN_PATH'}, status=403)
            if request.path == '/':
                return web.Response(text='<html><body><div id="root">Pi Web</div></body></html>', content_type='text/html', headers={'ETag': 'original'})
            received.append((request.path_qs, request.headers.get('Host'), request.headers.get('Origin')))
            if request.headers.get('Upgrade', '').lower() == 'websocket':
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                msg = await ws.receive_str()
                await ws.send_str('echo:' + msg)
                await ws.close()
                return ws
            return web.Response(text='proxied')
        backend.router.add_route('*', '/{path:.*}', echo)
        back_runner = web.AppRunner(backend)
        await back_runner.setup()
        back_site = web.TCPSite(back_runner, '127.0.0.1', 0)
        await back_site.start()
        back_url = 'http://127.0.0.1:' + str(back_site._server.sockets[0].getsockname()[1])
        session = ClientSession()
        class LocalClient:
            def request(self, method, url, **kwargs):
                return session.request(method, url.replace('http://127.0.0.1:8504', back_url), **kwargs)
            def ws_connect(self, url, **kwargs):
                return session.ws_connect(url.replace('http://127.0.0.1:8504', back_url), **kwargs)
        front = web.Application()
        front[CLIENT] = LocalClient()
        front.router.add_route('*', '/{path:.*}', proxy)
        front_runner = web.AppRunner(front)
        await front_runner.setup()
        front_site = web.TCPSite(front_runner, '127.0.0.1', 0)
        await front_site.start()
        front_url = 'http://127.0.0.1:' + str(front_site._server.sockets[0].getsockname()[1])
        headers = {'Host': 'ha.example:8123', 'Origin': 'https://ha.example:8123'}
        try:
            with patch('butler.ingress.INGRESS_PEER', '127.0.0.1'):
                async with session.get(front_url + '/', headers=headers) as response:
                    body = await response.text()
                    self.assertIn('Pi Web', body)
                    self.assertIn('href="butler/" target="_blank"', body)
                    self.assertNotIn('ETag', response.headers)
                async with session.get(front_url + '//', headers=headers) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn('Manage HA AI Access', await response.text())
                async with session.get(front_url + '//butler/', headers=headers) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn('Save and apply', await response.text())
                # Module MIME types must not depend on the container's MIME database.
                from aiohttp.web_fileresponse import CONTENT_TYPES
                with patch.dict(CONTENT_TYPES.types_map[True], {'.js': 'text/plain', '.mjs': 'application/octet-stream'}):
                    for asset in ('access-loader.js', 'access.js', 'policy-model.mjs'):
                        async with session.get(front_url + '/butler/assets/' + asset + '?v=test', headers=headers) as response:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(response.content_type, 'text/javascript')
                            self.assertEqual(response.headers['Cache-Control'], 'no-store')
                async with session.get(front_url + '/api/test?q=1', headers=headers) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(await response.text(), 'proxied')
                async with session.ws_connect(front_url + '/socket', headers=headers) as ws:
                    await ws.send_str('hello')
                    self.assertEqual(await ws.receive_str(), 'echo:hello')
            self.assertEqual(received, [('/api/test?q=1', headers['Host'], headers['Origin']),
                                        ('/socket', headers['Host'], headers['Origin'])])
        finally:
            await front_runner.cleanup()
            await back_runner.cleanup()
            await session.close()

    async def test_picker_page_assets_and_method_boundary(self):
        from unittest.mock import patch
        req = Mock()
        req.transport.get_extra_info.return_value = ('172.30.32.2', 1234)
        req.method = 'GET'
        req.path = '/butler/'
        result = await proxy(req)
        self.assertEqual(result.status, 200)
        self.assertIn("script-src 'self'", result.headers['Content-Security-Policy'])
        req.path = '/butler/assets/access.js'
        result = await proxy(req)
        self.assertEqual(result.status, 200)
        req.path = '/butler/assets/../../access.py'
        with self.assertRaises(web.HTTPNotFound):
            await proxy(req)
        req.path = '/butler/catalog'
        req.method = 'POST'
        with self.assertRaises(web.HTTPMethodNotAllowed):
            await proxy(req)
        req.path = '/butler/permissions'
        req.method = 'GET'
        with self.assertRaises(web.HTTPMethodNotAllowed):
            await proxy(req)
        req.method = 'POST'
        req.headers = {}
        with self.assertRaises(web.HTTPForbidden):
            await proxy(req)
