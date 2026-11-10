import asyncio
import json
import os
import sys
import unittest
from aiohttp import ClientSession, web
from butler.mcp import dispatch


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_and_catalog(self):
        reply = await dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}}, None)
        self.assertEqual(reply['result']['protocolVersion'], '2025-03-26')
        reply = await dispatch({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, None)
        self.assertIn('action', [t['name'] for t in reply['result']['tools']])
        self.assertIsNone(await dispatch({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, None))

    async def test_errors_and_unavailable_service(self):
        for request, code in [(None, -32600), ({'jsonrpc': '2.0', 'id': 1, 'method': 'unknown'}, -32601),
                              ({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': []}, -32602)]:
            self.assertEqual((await dispatch(request, None))['error']['code'], code)
        reply = await dispatch({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'states'}}, None)
        self.assertTrue(reply['result']['isError'])

    async def test_actual_stdio_and_frame_recovery(self):
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'butler.mcp', stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        requests = b'x'*40000+b'\n'+b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        stdout, stderr = await asyncio.wait_for(process.communicate(requests), 10)
        replies = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0]['error']['code'], -32700)
        self.assertEqual(replies[1]['result'], {})
        self.assertEqual(stderr, b'')

    async def test_chunked_tool_result_is_fully_read(self):
        app = web.Application()
        async def serve(request):
            body = await request.json()
            self.assertEqual(body['tool'], 'states')
            reply = web.StreamResponse()
            await reply.prepare(request)
            raw = json.dumps({'result': {'text': 'x' * 200000}}).encode()
            for start in range(0, len(raw), 4096):
                await reply.write(raw[start:start+4096])
                await asyncio.sleep(0)
            await reply.write_eof()
            return reply
        app.router.add_post('/call', serve)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        url = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]) + '/call'
        try:
            async with ClientSession() as session:
                class LocalSession:
                    def post(self, ignored, **kwargs):
                        return session.post(url, **kwargs)
                reply = await dispatch({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'states'}}, LocalSession())
                self.assertFalse(reply['result']['isError'])
                self.assertEqual(len(json.loads(reply['result']['content'][0]['text'])['text']), 200000)
        finally:
            await runner.cleanup()
