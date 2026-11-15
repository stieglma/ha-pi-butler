"""HA ingress gate and streaming HTTP/WebSocket proxy."""
import asyncio
import json
from pathlib import Path
import re
from urllib.parse import quote
from .onboarding import read_bounded, read_bounded_request
from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, UnixConnector, WSMsgType, web

# HA's documented ingress peer. Forwarded headers are never authentication.
INGRESS_PEER = '172.30.32.2'
CLIENT = web.AppKey('client', ClientSession)
CATALOG_CLIENT = web.AppKey('catalog_client', ClientSession)
KNX_CONFIG = web.AppKey('knx_config', dict)
WORKSPACE_CLIENT = web.AppKey('workspace_client', ClientSession)
WEB_ROOT = Path(__file__).parent / 'web'
ASSET_TYPES = {'access.js': 'text/javascript', 'access-loader.js': 'text/javascript',
               'policy-model.mjs': 'text/javascript', 'access.css': 'text/css', 'navigation.css': 'text/css', 'navigation.js': 'text/javascript',
               'knx-projects.js': 'text/javascript', 'knx-projects.css': 'text/css', 'setup.js': 'text/javascript', 'setup.css': 'text/css',
               'starters.js': 'text/javascript', 'starter-model.mjs': 'text/javascript', 'starters.css': 'text/css'}
PAGE_HEADERS = {'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'", 'X-Content-Type-Options': 'nosniff'}
HOP = {'connection', 'upgrade', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'content-length'}


async def knx_admin(request):
    user_id = request.headers.get('X-Remote-User-Id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', user_id):
        return False
    try:
        async with request.app[CATALOG_CLIENT].get('http://localhost/identity?user_id=' + user_id) as reply:
            return reply.status == 200 and (await reply.json()).get('admin') is True
    except Exception:
        return False


async def proxy(request):
    peer = request.transport.get_extra_info('peername')
    if not peer or peer[0] != INGRESS_PEER:
        raise web.HTTPForbidden(text='Home Assistant ingress required')
    # Older ingress_entry='/' produced a second slash after HA's prefix.
    path = '/' + request.path.lstrip('/')
    knx = request.app.get(KNX_CONFIG, {'enabled': False})
    editor = path == '/butler/knx' or path.startswith('/butler/knx/')
    if editor:
        if not knx['enabled']:
            raise web.HTTPNotFound(text='KNX editor disabled')
        if not await knx_admin(request):
            raise web.HTTPForbidden(text='Home Assistant administrator verification required')
        if path == '/butler/knx':
            raise web.HTTPFound('knx/')
        # Host integration and login are not browser-facing interfaces.
        if path.removeprefix('/butler/knx/') in ('host', 'login'):
            raise web.HTTPNotFound()
    if editor and path == '/butler/knx/projects/':
        if request.method != 'GET':
            raise web.HTTPMethodNotAllowed(request.method, ['GET'])
        return web.FileResponse(WEB_ROOT / 'knx-projects.html', headers=PAGE_HEADERS)
    if editor and (path.startswith('/butler/knx/butler-api/') or path == '/butler/knx/butler-assistant'):
        action = path.removeprefix('/butler/knx/butler-api/')
        if action not in ('status', 'policy', 'checkpoint', 'restore', 'import', 'download', 'deliver'):
            raise web.HTTPNotFound()
        expected = 'GET' if action in ('status', 'download') else 'POST'
        if request.method != expected:
            raise web.HTTPMethodNotAllowed(request.method, [expected])
        if expected == 'POST' and (request.headers.get('X-Butler-Settings') != '1' or request.content_type != 'application/json'):
            raise web.HTTPForbidden(text='Settings request required')
        if action in ('import', 'deliver'):
            try:
                body = json.loads(await read_bounded_request(request, 32768))
                client = request.app[CLIENT]
                headers = {'X-Butler-KNX-Token': knx['web_token'],
                           'X-Butler-Admin-Id': request.headers['X-Remote-User-Id']}
                if action == 'import':
                    if body != {}:
                        raise ValueError('Import uses the configured repository source')
                    async with request.app[WORKSPACE_CLIENT].get('http://localhost/knx-source') as source:
                        if source.status != 200:
                            raise ValueError('Repository source is unavailable. Check the configured project filename in Setup.')
                        async with client.post('http://127.0.0.1:8511/butler-api/import',
                                headers=headers, data=source.content.iter_chunked(65536), allow_redirects=False) as reply:
                            return web.json_response(json.loads(await read_bounded(reply, 1048576)), status=reply.status)
                if not isinstance(body, dict) or set(body) != {'id'} or not re.fullmatch(r'[a-f0-9]{32}', body.get('id', '')):
                    raise ValueError('Select a checkpoint to deliver')
                async with client.get('http://127.0.0.1:8511/butler-api/download?id=' + body['id'] + '&kind=zip', headers=headers) as source:
                    if source.status != 200:
                        raise ValueError('Checkpoint is unavailable')
                    async with request.app[WORKSPACE_CLIENT].post('http://localhost/knx-deliver',
                            data=source.content.iter_chunked(65536), timeout=ClientTimeout(total=650)) as reply:
                        return web.json_response(json.loads(await read_bounded(reply, 1048576)), status=reply.status)
            except (ValueError, OSError) as exc:
                return web.json_response({'error': str(exc)}, status=400)
            except Exception:
                return web.json_response({'error': 'KNX repository exchange unavailable; inspect project and Git status before retrying.'}, status=502)
    if path == '/butler/starters/':
        if request.method != 'GET':
            raise web.HTTPMethodNotAllowed(request.method, ['GET'])
        return web.FileResponse(WEB_ROOT / 'starters.html', headers=PAGE_HEADERS)
    if path == '/butler/setup/':
        if request.method != 'GET':
            raise web.HTTPMethodNotAllowed(request.method, ['GET'])
        return web.FileResponse(WEB_ROOT / 'setup.html', headers=PAGE_HEADERS)
    if path in ('/butler/setup/status', '/butler/setup/memory'):
        saving = request.method == 'POST' and path.endswith('/memory')
        if request.method != 'GET' and not saving:
            raise web.HTTPMethodNotAllowed(request.method, ['GET', 'POST'] if path.endswith('/memory') else ['GET'])
        if saving and (request.headers.get('X-Butler-Settings') != '1' or request.content_type != 'application/json'):
            raise web.HTTPForbidden(text='Settings request required')
        payload = await request.read() if saving else None
        if payload is not None and len(payload) > 524288:
            raise web.HTTPRequestEntityTooLarge(max_size=524288, actual_size=len(payload))
        try:
            async with request.app[WORKSPACE_CLIENT].request(request.method, 'http://localhost/' + path.rsplit('/', 1)[1],
                    data=payload, headers={'Content-Type': 'application/json', 'X-Butler-Settings': '1'}) as reply:
                body = await read_bounded(reply, 1048576)
                result = json.loads(body)
                if path.endswith('/status') and reply.status == 200:
                    try:
                        async with request.app[CATALOG_CLIENT].get('http://localhost/health') as health:
                            connected = health.status == 200
                    except Exception:
                        connected = False
                    result.setdefault('checks', {})['ha'] = {'state': 'ready' if connected else 'pending',
                        'help': 'HA read connection verified.' if connected else 'HA read check failed. Inspect app/Core logs and retry.'}
                return web.json_response(result, status=reply.status, headers={'Cache-Control': 'no-store'})
        except Exception:
            return web.json_response({'error': 'Setup service is starting or unavailable. Retry shortly.'}, status=502)
    if path == '/butler/status':
        try:
            status = json.loads(Path('/data/status/repository.json').read_text())
        except (OSError, ValueError):
            status = {'state': 'pending', 'help': 'Run butler-workspace setup in the terminal.'}
        return web.json_response({'repository': status, 'help': 'Use butler-workspace setup to retry. HA access: Pi MCP pi_butler.'})
    if path in ('/butler', '/butler/'):
        if request.method != 'GET':
            raise web.HTTPMethodNotAllowed(request.method, ['GET'])
        if path == '/butler':
            # Canonical relative URL: preserve HA's dynamic ingress prefix.
            raise web.HTTPFound('butler/')
        return web.FileResponse(WEB_ROOT / 'access.html', headers=PAGE_HEADERS)
    if path.startswith('/butler/assets/'):
        name = path.removeprefix('/butler/assets/')
        if request.method != 'GET' or name not in ASSET_TYPES:
            raise web.HTTPNotFound()
        return web.FileResponse(WEB_ROOT / name, headers={'X-Content-Type-Options': 'nosniff',
                                                        'Content-Type': ASSET_TYPES[name], 'Cache-Control': 'no-store'})
    if path in ('/butler/catalog', '/butler/starters/catalog', '/butler/permissions'):
        saving = path.endswith('/permissions')
        expected = 'POST' if saving else 'GET'
        if request.method != expected:
            raise web.HTTPMethodNotAllowed(request.method, [expected])
        if saving and (request.headers.get('X-Butler-Settings') != '1' or request.content_type != 'application/json'):
            raise web.HTTPForbidden(text='Settings request required')
        try:
            payload = await request.read() if saving else None
            if payload is not None and len(payload) > 131072:
                raise web.HTTPRequestEntityTooLarge(max_size=131072, actual_size=len(payload))
            async with request.app[CATALOG_CLIENT].request(expected, 'http://localhost' + ('/permissions' if saving else '/starter-catalog' if path == '/butler/starters/catalog' else '/catalog'), data=payload, headers={'Content-Type': 'application/json'}) as reply:
                body = bytearray()
                async for chunk in reply.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > 8388608:
                        raise ValueError('Catalog too large')
                return web.Response(body=bytes(body), status=reply.status, content_type='application/json', headers={'Cache-Control': 'no-store'})
        except web.HTTPException:
            raise
        except Exception:
            return web.json_response({'error': 'HA picker service is unavailable; retry after the app finishes starting.'}, status=502)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP and not k.lower().startswith('x-forwarded-') and k.lower() != 'forwarded'}
    if editor:
        # Never accept a browser-supplied internal credential or cookie. Authenticate
        # this hop independently of upstream's browser sessions.
        headers = {k: v for k, v in headers.items() if k.lower() not in
                   {'x-butler-knx-token', 'cookie', 'authorization', 'x-remote-user-id',
                    'x-remote-user-name', 'x-remote-user-display-name', 'x-butler-admin-id', 'x-butler-mcp-token'}}
        headers['X-Butler-KNX-Token'] = knx['web_token']
        headers['X-Butler-Admin-Id'] = request.headers['X-Remote-User-Id']
        headers['X-Forwarded-Host'] = request.host
    if request.method == 'GET' and path == '/':
        headers = {k: v for k, v in headers.items() if k.lower() not in {'if-none-match', 'if-modified-since'}}
        headers['Accept-Encoding'] = 'identity'
    # Preserve public Host and Origin for Pi Web's own Origin guard.
    url = 'http://127.0.0.1:8504' + '/' + request.rel_url.raw_path_qs.lstrip('/')
    if editor:
        # Re-encode the decoded tail so encoded separators/dot paths cannot escape
        # the editor origin or route to another service.
        tail = path.removeprefix('/butler/knx/')
        if any(part in ('.', '..') for part in tail.split('/')) or '\\' in tail:
            raise web.HTTPBadRequest()
        url = 'http://127.0.0.1:8511/' + quote(tail, safe='/')
        if request.query_string:
            url += '?' + request.rel_url.raw_query_string
    client = request.app[CLIENT]
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        protocols = [p.strip() for p in request.headers.get('Sec-WebSocket-Protocol', '').split(',') if p.strip()]
        ws_headers = {k: v for k, v in headers.items() if not k.lower().startswith('sec-websocket-')}
        async with client.ws_connect(url, headers=ws_headers, protocols=protocols, max_msg_size=8388608, heartbeat=30) as upstream:
            browser = web.WebSocketResponse(protocols=[upstream.protocol] if upstream.protocol else [], max_msg_size=8388608, heartbeat=30)
            await browser.prepare(request)

            async def copy(source, dest):
                async for msg in source:
                    if msg.type == WSMsgType.TEXT:
                        await dest.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await dest.send_bytes(msg.data)
                    elif msg.type == WSMsgType.ERROR:
                        break
                await dest.close()
            tasks = [asyncio.create_task(copy(browser, upstream)), asyncio.create_task(copy(upstream, browser))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            return browser
    async with client.request(request.method, url, headers=headers, data=request.content.iter_chunked(65536) if request.can_read_body else None, allow_redirects=False) as upstream:
        response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP}
        if request.method == 'GET' and path == '/' and upstream.status == 200 and upstream.content_type == 'text/html' and not upstream.headers.get('Content-Encoding'):
            body = await upstream.read()
            navigation = b'<link rel="stylesheet" href="butler/assets/navigation.css"><nav id="butler-navigation" aria-label="Butler"><button id="butler-navigation-toggle" type="button" aria-label="Toggle Butler menu" aria-expanded="false" aria-controls="butler-navigation-links">+</button><div id="butler-navigation-links"><a id="butler-settings-link" href="butler/" target="_blank" rel="noopener">Manage HA AI Access</a><a href="butler/setup/" target="_blank" rel="noopener">Setup &amp; house notes</a><a id="butler-starters-link" href="butler/starters/" target="_blank" rel="noopener">Investigate your home</a></div></nav><script src="butler/assets/navigation.js" defer></script>'
            if knx['enabled'] and await knx_admin(request):
                navigation = navigation.replace(b'</div></nav>', b'<a href="butler/knx/" target="_blank" rel="noopener">KNX Editor</a><a href="butler/knx/projects/" target="_blank" rel="noopener">KNX projects &amp; access</a></div></nav>')
            body = body.replace(b'</body>', navigation + b'</body>', 1)
            for key in list(response_headers):
                if key.lower() in {'etag', 'last-modified'}:
                    del response_headers[key]
            response_headers['Cache-Control'] = 'no-store'
            return web.Response(body=body, status=upstream.status, headers=response_headers)
        if editor:
            response_headers = {k: v for k, v in response_headers.items() if k.lower() != 'set-cookie'}
            response_headers['Cache-Control'] = 'no-store'
        response = web.StreamResponse(status=upstream.status, headers=response_headers)
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(65536):
            await response.write(chunk)
        await response.write_eof()
        return response


async def main():
    app = web.Application(client_max_size=16777216)
    app[KNX_CONFIG] = json.loads(Path('/run/butler/knx-proxy.json').read_text())
    app[CLIENT] = ClientSession(timeout=ClientTimeout(total=None, sock_connect=10), auto_decompress=False, trust_env=False, cookie_jar=DummyCookieJar())
    app[CATALOG_CLIENT] = ClientSession(connector=UnixConnector(path='/run/butler/admin/settings.sock'), timeout=ClientTimeout(total=30), trust_env=False)
    app[WORKSPACE_CLIENT] = ClientSession(connector=UnixConnector(path='/run/butler/workspace/ui.sock'), timeout=ClientTimeout(total=25), trust_env=False)
    app.router.add_route('*', '/{path:.*}', proxy)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8099).start()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await app[CLIENT].close()
        await app[CATALOG_CLIENT].close()
        await app[WORKSPACE_CLIENT].close()


if __name__ == '__main__':
    asyncio.run(main())
