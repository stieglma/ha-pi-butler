"""Unprivileged MCP stdio transport; never holds an upstream HA credential."""
import asyncio
import json
import sys
from aiohttp import ClientSession, ClientTimeout, UnixConnector
from .access import TOOLS


async def dispatch(message, session):
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
        return {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                'error': {'code': -32600, 'message': 'Invalid request'}}
    if 'id' not in message:
        return None
    response = {'jsonrpc': '2.0', 'id': message['id']}
    method = message['method']
    params = message.get('params', {})
    if not isinstance(params, dict):
        return {**response, 'error': {'code': -32602, 'message': 'Invalid params'}}
    if method == 'initialize':
        supported = ['2024-11-05', '2025-03-26', '2025-06-18']
        response['result'] = {'protocolVersion': params.get('protocolVersion') if params.get('protocolVersion') in supported else supported[-1],
                              'capabilities': {'tools': {}}, 'serverInfo': {'name': 'pi-butler', 'version': '0.1.4'}}
    elif method == 'ping':
        response['result'] = {}
    elif method == 'tools/list':
        response['result'] = {'tools': TOOLS}
    elif method == 'tools/call':
        try:
            async with session.post('http://localhost/call', json={'tool': params.get('name'), 'arguments': params.get('arguments', {})}) as reply:
                raw = bytearray()
                async for chunk in reply.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > 8388608:
                        raise ValueError()
                result = json.loads(raw)
                failed = reply.status != 200 or 'error' in result
                response['result'] = {'content': [{'type': 'text', 'text': json.dumps(result.get('error') if failed else result['result'])}], 'isError': failed}
        except Exception:
            response['result'] = {'content': [{'type': 'text', 'text': 'Pi Butler access service unavailable'}], 'isError': True}
    else:
        response['error'] = {'code': -32601, 'message': 'Method not found'}
    return response


async def main():
    connector = UnixConnector(path='/run/butler/access/access.sock')
    async with ClientSession(connector=connector, timeout=ClientTimeout(total=30)) as session:
        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline, 32770)
            if not line:
                return
            try:
                if len(line) > 32768:
                    # Drain the oversized frame rather than interpreting its tail.
                    while line and not line.endswith(b'\n'):
                        line = await asyncio.to_thread(sys.stdin.buffer.readline, 32770)
                    raise ValueError()
                response = await dispatch(json.loads(line), session)
            except (ValueError, TypeError):
                response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid or oversized JSON frame'}}
            if response is not None:
                print(json.dumps(response), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
