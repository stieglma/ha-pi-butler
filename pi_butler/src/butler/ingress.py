"""HA ingress gate and streaming HTTP/WebSocket proxy."""
import asyncio
import json
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

# HA's documented ingress peer. Forwarded headers are never authentication.
INGRESS_PEER = '172.30.32.2'
CLIENT = web.AppKey('client', ClientSession)
HOP = {'connection', 'upgrade', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'content-length'}


async def proxy(request):
    peer = request.transport.get_extra_info('peername')
    if not peer or peer[0] != INGRESS_PEER:
        raise web.HTTPForbidden(text='Home Assistant ingress required')
    if request.path == '/butler/status':
        try:
            status = json.loads(Path('/data/status/repository.json').read_text())
        except (OSError, ValueError):
            status = {'state': 'pending', 'help': 'Run butler-workspace setup in the terminal.'}
        return web.json_response({'repository': status, 'help': 'Use butler-workspace setup to retry. HA access: Pi MCP pi_butler.'})
    if request.path in ('/butler', '/butler/'):
        return web.Response(content_type='text/html', text='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Pi Butler setup</title>
<h1>Pi Butler</h1><p><a href="../">Open Pi Web</a></p><p>Authenticate your model provider using Pi Web.
Open the terminal for Git setup, then run <code>butler-workspace setup</code>.
Read status with <code>butler-workspace status</code> and policy with the Pi Butler access_summary tool.</p>
<p><a href="status">Repository status (JSON)</a></p></html>''')
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP and not k.lower().startswith('x-forwarded-') and k.lower() != 'forwarded'}
    # Preserve public Host and Origin for Pi Web's own Origin guard.
    url = 'http://127.0.0.1:8504' + request.rel_url.raw_path_qs
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
        response = web.StreamResponse(status=upstream.status, headers={k: v for k, v in upstream.headers.items() if k.lower() not in HOP})
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(65536):
            await response.write(chunk)
        await response.write_eof()
        return response


async def main():
    app = web.Application(client_max_size=16777216)
    app[CLIENT] = ClientSession(timeout=ClientTimeout(total=None, sock_connect=10), auto_decompress=False, trust_env=False)
    app.router.add_route('*', '/{path:.*}', proxy)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8099).start()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await app[CLIENT].close()


if __name__ == '__main__':
    asyncio.run(main())
