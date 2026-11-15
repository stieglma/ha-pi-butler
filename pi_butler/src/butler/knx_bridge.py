"""Agent-accessible finite KNX gateway; internal MCP credentials stay private."""
import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout, web
from .knx import validate
from .policy import Rejected


async def call_editor(name, args, token):
    headers = {'Authorization': 'Bearer ' + token,
               'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-06-18'}
    url = 'http://127.0.0.1:8512/mcp'
    async with ClientSession(timeout=ClientTimeout(total=20), trust_env=False) as client:
        async def rpc(method, params, ident=None):
            payload = {'jsonrpc': '2.0', 'method': method, 'params': params}
            if ident is not None:
                payload['id'] = ident
            async with client.post(url, headers=headers, json=payload, allow_redirects=False) as reply:
                if reply.status not in (200, 202):
                    raise RuntimeError('Editor request failed')
                session_id = reply.headers.get('Mcp-Session-Id')
                if session_id:
                    headers['Mcp-Session-Id'] = session_id
                raw = bytearray()
                async for chunk in reply.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > 2097152:
                        raise Rejected('KNX result too large; narrow the query')
                if ident is None:
                    return None
                if reply.content_type == 'text/event-stream':
                    messages = [json.loads(line[5:].strip()) for line in raw.decode().splitlines() if line.startswith('data:')]
                    result = next(m for m in messages if m.get('id') == ident)
                else:
                    result = json.loads(raw)
                if 'error' in result:
                    raise RuntimeError('Editor RPC failed')
                return result['result']
        try:
            await rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                    'clientInfo': {'name': 'pi-butler-knx', 'version': '1.1.0'}}, 1)
            await rpc('notifications/initialized', {})
            result = await rpc('tools/call', {'name': name, 'arguments': args}, 2)
            if result.get('isError'):
                raise RuntimeError('Editor read failed')
            return result.get('structuredContent') or {'content': [c['text'] for c in result.get('content', []) if c.get('type') == 'text']}
        finally:
            if 'Mcp-Session-Id' in headers:
                async with client.delete(url, headers=headers, allow_redirects=False):
                    pass


def application(token, read_enabled, audit, call=call_editor):
    semaphore = asyncio.Semaphore(2)
    async def read(request):
        name = None
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'tool', 'arguments'}:
                raise Rejected('Invalid KNX request')
            name, args = body['tool'], body['arguments']
            validate(name, args)
            if not read_enabled:
                raise Rejected('KNX assistant reads are disabled in app options')
            async with semaphore, asyncio.timeout(25):
                result = await call(name, args, token)
                if len(json.dumps(result).encode()) > 2097152:
                    raise Rejected('KNX result too large; narrow the query')
            audit.info(json.dumps({'tool': name, 'decision': 'read'}))
            return web.json_response({'result': result})
        except Rejected as exc:
            audit.info(json.dumps({'tool': name if isinstance(name, str) and len(name) < 80 else None, 'decision': 'denied'}))
            return web.json_response({'error': str(exc)}, status=400)
        except Exception:
            audit.info('KNX read failed')
            return web.json_response({'error': 'KNX editor unavailable or read failed; open a project in the admin UI.'}, status=502)
    app = web.Application(client_max_size=32768)
    app.router.add_post('/call', read)
    return app


async def main():
    credentials = json.loads(Path('/data/knx/credentials.json').read_text())
    options = json.loads(Path('/etc/pi-butler/knx.json').read_text())
    audit = logging.getLogger('knx')
    audit.setLevel(logging.INFO)
    audit.addHandler(RotatingFileHandler('/data/knx/audit.log', maxBytes=1048576, backupCount=2))
    runner = web.AppRunner(application(credentials['mcp_token'], options['read_enabled'], audit), access_log=None)
    await runner.setup()
    path = '/run/butler/knx/read.sock'
    Path(path).unlink(missing_ok=True)
    await web.UnixSite(runner, path).start()
    os.chmod(path, 0o660)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
