"""HA ingress gate and streaming HTTP/WebSocket proxy."""
import asyncio
import json
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout, UnixConnector, WSMsgType, web

# HA's documented ingress peer. Forwarded headers are never authentication.
INGRESS_PEER = '172.30.32.2'
CLIENT = web.AppKey('client', ClientSession)
CATALOG_CLIENT = web.AppKey('catalog_client', ClientSession)
WEB_ROOT = Path(__file__).parent / 'web'
ASSET_TYPES = {'access.js': 'text/javascript', 'access-loader.js': 'text/javascript',
               'policy-model.mjs': 'text/javascript', 'access.css': 'text/css', 'navigation.css': 'text/css'}
PAGE_HEADERS = {'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'", 'X-Content-Type-Options': 'nosniff'}
HOP = {'connection', 'upgrade', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'content-length'}


async def proxy(request):
    peer = request.transport.get_extra_info('peername')
    if not peer or peer[0] != INGRESS_PEER:
        raise web.HTTPForbidden(text='Home Assistant ingress required')
    # Older ingress_entry='/' produced a second slash after HA's prefix.
    path = '/' + request.path.lstrip('/')
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
    if path in ('/butler/catalog', '/butler/permissions'):
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
            async with request.app[CATALOG_CLIENT].request(expected, 'http://localhost' + ('/permissions' if saving else '/catalog'), data=payload, headers={'Content-Type': 'application/json'}) as reply:
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
    if request.method == 'GET' and path == '/':
        headers = {k: v for k, v in headers.items() if k.lower() not in {'if-none-match', 'if-modified-since'}}
        headers['Accept-Encoding'] = 'identity'
    # Preserve public Host and Origin for Pi Web's own Origin guard.
    url = 'http://127.0.0.1:8504' + '/' + request.rel_url.raw_path_qs.lstrip('/')
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
            navigation = b'<link rel="stylesheet" href="butler/assets/navigation.css"><a id="butler-settings-link" href="butler/" target="_blank" rel="noopener">Manage HA AI Access</a>'
            body = body.replace(b'</body>', navigation + b'</body>', 1)
            for key in list(response_headers):
                if key.lower() in {'etag', 'last-modified'}:
                    del response_headers[key]
            response_headers['Cache-Control'] = 'no-store'
            return web.Response(body=body, status=upstream.status, headers=response_headers)
        response = web.StreamResponse(status=upstream.status, headers=response_headers)
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(65536):
            await response.write(chunk)
        await response.write_eof()
        return response


async def main():
    app = web.Application(client_max_size=16777216)
    app[CLIENT] = ClientSession(timeout=ClientTimeout(total=None, sock_connect=10), auto_decompress=False, trust_env=False)
    app[CATALOG_CLIENT] = ClientSession(connector=UnixConnector(path='/run/butler/admin/settings.sock'), timeout=ClientTimeout(total=30), trust_env=False)
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


if __name__ == '__main__':
    asyncio.run(main())
