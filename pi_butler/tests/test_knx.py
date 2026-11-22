"""KNX trust boundaries, independent of a bus or an editor GUI session."""
import json
import logging
import unittest
from unittest.mock import AsyncMock, Mock, patch
from aiohttp import DummyCookieJar, web
from aiohttp.test_utils import TestClient, TestServer
from butler.access import applications
from butler.ingress import proxy, CLIENT, CATALOG_CLIENT, KNX_CONFIG
from butler.knx import TOOLS, READ_TOOLS, WRITES, validate
from butler.knx_bridge import application, call_editor
from butler.knx_editor import protected_app
from butler.mcp import dispatch
from butler.policy import Rejected


class KnxTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_guard_covers_http_websocket_and_duplicate_headers(self):
        upstream = AsyncMock()
        guard = protected_app(upstream, 'private-token')
        for kind in ('http', 'websocket'):
            for headers in ([], [(b'x-butler-knx-token', b'wrong')],
                            [(b'x-butler-knx-token', b'private-token')] * 2):
                send = AsyncMock()
                await guard({'type': kind, 'headers': headers}, AsyncMock(), send)
                self.assertEqual(send.call_args_list[0].args[0]['type'],
                                 'http.response.start' if kind == 'http' else 'websocket.close')
                upstream.assert_not_called()
            await guard({'type': kind, 'headers': [(b'x-butler-knx-token', b'private-token')]}, AsyncMock(), AsyncMock())
            upstream.assert_awaited_once()
            upstream.reset_mock()

    async def test_read_surface_rejects_generic_dispatch_paths_and_writes(self):
        for name, args in [('call_tool', {'name': 'project_delete'}), ('project_batch', {}),
                           ('settings_get', {}), ('keyring_export', {}), ('monitor_send_write', {}),
                           ('project_info', {'path': '/data/pi/evil.xknx'}),
                           ('project_get_device', {'node_id': True}),
                           ('project_get_device', {'node_id': -1})]:
            with self.subTest(name=name), self.assertRaises(Rejected):
                validate(name, args)
        result = await dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, None, TOOLS)
        self.assertEqual(result['result']['tools'], TOOLS)
        self.assertEqual(len(READ_TOOLS), 15)
        self.assertEqual(len(TOOLS), len(READ_TOOLS) + len(WRITES))

    async def test_gateway_policy_and_errors_never_leak_token(self):
        call = AsyncMock(return_value={'count': 40})
        for enabled in (False, True):
            async with TestClient(TestServer(application('private-token', enabled, logging.getLogger('test'), call))) as client:
                reply = await client.post('/call', json={'tool': 'project_info', 'arguments': {}})
                self.assertEqual(reply.status, 200 if enabled else 400)
                reply = await client.post('/call', json={'tool': 'settings_set', 'arguments': {}})
                self.assertEqual(reply.status, 400)
                reply = await client.post('/permissions', json={})
                self.assertEqual(reply.status, 404)
                call.side_effect = RuntimeError('private-token')
                reply = await client.post('/call', json={'tool': 'project_info', 'arguments': {}})
                self.assertNotIn('private-token', await reply.text())
                call.side_effect = None
        self.assertEqual(call.await_count, 2)

    async def test_identity_requires_current_active_admin_and_is_not_an_agent_route(self):
        access = Mock()
        access.upstream.ws = AsyncMock()
        agent, admin = applications(access)
        async with TestClient(TestServer(admin)) as client, TestClient(TestServer(agent)) as unprivileged:
            user_id = 'a' * 32
            for fields, status in [({'is_active': True, 'group_ids': ['system-admin']}, 200),
                                   ({'is_active': True, 'is_owner': True}, 200),
                                   ({'is_active': False, 'is_owner': True}, 403),
                                   ({'is_active': True, 'group_ids': ['system-users']}, 403)]:
                access.upstream.ws.return_value = [{'id': user_id, **fields}]
                reply = await client.get('/identity?user_id=' + user_id)
                self.assertEqual(reply.status, status)
            access.upstream.ws.side_effect = RuntimeError()
            self.assertEqual((await client.get('/identity?user_id=' + user_id)).status, 503)
            self.assertEqual((await client.get('/identity?user_id=invalid')).status, 403)
            self.assertEqual((await unprivileged.get('/identity?user_id=' + user_id)).status, 404)

    async def test_ingress_gates_all_editor_routes_and_preserves_prefix_and_websocket(self):
        backend = web.Application()
        received = []
        async def echo(request):
            received.append((request.path_qs, request.headers.get('X-Butler-KNX-Token'), request.headers.get('Cookie')))
            if request.headers.get('Upgrade') == 'websocket':
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                await ws.send_str(await ws.receive_str())
                await ws.close()
                return ws
            return web.Response(text='editor', headers={'Set-Cookie': 'secret=never-forward'})
        backend.router.add_route('*', '/{path:.*}', echo)
        async with TestClient(TestServer(backend), cookie_jar=DummyCookieJar()) as back:
            class LocalClient:
                def request(self, method, url, **kwargs):
                    return back.request(method, url.removeprefix('http://127.0.0.1:8511'), **kwargs)
                def ws_connect(self, url, **kwargs):
                    return back.ws_connect(url.removeprefix('http://127.0.0.1:8511'), **kwargs)
            identity = Mock()
            identity.get.return_value.__aenter__ = AsyncMock(return_value=Mock(status=200, json=AsyncMock(return_value={'admin': True})))
            identity.get.return_value.__aexit__ = AsyncMock(return_value=False)
            app = web.Application()
            app[CLIENT] = LocalClient()
            app[CATALOG_CLIENT] = identity
            config = {'enabled': True, 'web_token': 'internal-token'}
            app[KNX_CONFIG] = config
            app.router.add_route('*', '/{path:.*}', proxy)
            async with TestClient(TestServer(app)) as client:
                with patch('butler.ingress.INGRESS_PEER', '127.0.0.1'):
                    for route in ('/', '/ws', '/upload', '/files/123/project.xknx', '/projects/', '/butler-api/status', '/butler-api/policy', '/butler-assistant'):
                        self.assertEqual((await client.get('/butler/knx' + route)).status, 403)
                    headers = {'X-Remote-User-Id': 'a' * 32, 'X-Butler-KNX-Token': 'forged', 'Cookie': 'x=y'}
                    self.assertEqual((await client.post('/butler/knx/butler-api/policy', headers=headers, json={})).status, 403)
                    self.assertEqual((await client.post('/butler/knx/butler-assistant', headers=headers, json={})).status, 404)
                    self.assertEqual((await client.get('/butler/knx/projects/', headers=headers)).status, 200)
                    reply = await client.get('/butler/knx/client.js?q=1', headers=headers)
                    self.assertEqual(reply.status, 200)
                    self.assertNotIn('Set-Cookie', reply.headers)
                    async with client.ws_connect('/butler/knx/ws', headers=headers) as ws:
                        await ws.send_str('frame')
                        self.assertEqual(await ws.receive_str(), 'frame')
                    self.assertEqual(received, [('/client.js?q=1', 'internal-token', None), ('/ws', 'internal-token', None)])
                    self.assertEqual((await client.get('/butler/knx/host', headers=headers)).status, 404)
                    config['enabled'] = False
                    self.assertEqual((await client.get('/butler/knx/', headers=headers)).status, 404)

    async def test_admin_repository_exchange_streams_without_exposing_paths_or_credentials(self):
        from butler.ingress import WORKSPACE_CLIENT
        received = []
        async def editor(request):
            received.append(('editor', request.path, await request.read(),
                             request.headers.get('X-Butler-KNX-Token'), request.headers.get('X-Butler-Admin-Id')))
            return web.Response(body=b'checkpoint bundle') if request.method == 'GET' else web.json_response({'imported':'new.xknx'})
        async def repository(request):
            if request.method == 'GET':
                return web.Response(body=b'repository project bytes')
            received.append(('delivery', await request.read()))
            return web.json_response({'commit':'test-commit','branch':'configured'})
        backapp, repoapp = web.Application(), web.Application()
        backapp.router.add_route('*','/{path:.*}',editor)
        repoapp.router.add_route('*','/{path:.*}',repository)
        async with TestClient(TestServer(backapp)) as back, TestClient(TestServer(repoapp)) as repo:
            class EditorClient:
                def post(self,url,**kwargs):
                    return back.post(url.removeprefix('http://127.0.0.1:8511'),**kwargs)
                def get(self,url,**kwargs):
                    return back.get(url.removeprefix('http://127.0.0.1:8511'),**kwargs)
            class RepoClient:
                def get(self,url,**kwargs):
                    return repo.get(url.removeprefix('http://localhost'),**kwargs)
                def post(self,url,**kwargs):
                    return repo.post(url.removeprefix('http://localhost'),**kwargs)
            identity = Mock()
            identity.get.return_value.__aenter__ = AsyncMock(return_value=Mock(status=200,json=AsyncMock(return_value={'admin':True})))
            identity.get.return_value.__aexit__ = AsyncMock(return_value=False)
            app=web.Application()
            app[CLIENT],app[WORKSPACE_CLIENT],app[CATALOG_CLIENT]=EditorClient(),RepoClient(),identity
            app[KNX_CONFIG]={'enabled':True,'web_token':'private-web-token'}
            app.router.add_route('*','/{path:.*}',proxy)
            async with TestClient(TestServer(app)) as client:
                with patch('butler.ingress.INGRESS_PEER','127.0.0.1'):
                    headers={'X-Remote-User-Id':'a'*32,'X-Butler-Settings':'1','X-Butler-Admin-Id':'forged'}
                    response=await client.post('/butler/knx/butler-api/import',headers=headers,json={})
                    self.assertEqual(response.status,200)
                    self.assertEqual(received[0],('editor','/butler-api/import',b'repository project bytes','private-web-token','a'*32))
                    self.assertNotIn('private-web-token',await response.text())
                    self.assertEqual((await client.post('/butler/knx/butler-api/import',headers=headers,json={'path':'/data/pi/evil'})).status,400)
                    response=await client.post('/butler/knx/butler-api/deliver',headers=headers,json={'id':'b'*32})
                    self.assertEqual(response.status,200)
                    self.assertEqual(received[-1],('delivery',b'checkpoint bundle'))
                    self.assertEqual((await client.post('/butler/knx/butler-api/deliver',headers=headers,json={'id':'../other'})).status,400)
