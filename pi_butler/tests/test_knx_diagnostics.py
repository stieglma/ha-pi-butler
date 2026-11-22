"""Passive diagnostics: bounded queries and the same read gate as project reads."""
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import ClientSession, web
from butler.knx import DIAGNOSTICS, validate
from butler.knx_bridge import application
from butler.knx_runtime import Runtime
from butler.policy import Rejected


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.runtime.ctx = SimpleNamespace(run_locked=lambda fn, **kw: fn())
        self.runtime.projects = Mock()

    def call(self, name, args=None):
        return self.runtime.execute('assistant', {'tool': name, 'arguments': args or {}})

    def test_schema_rejects_unbounded_queries_and_side_effects(self):
        for name, args in [
            ('project_health', {'limit': 0}), ('project_health', {'limit': 201}),
            ('project_health', {'offset': True}), ('project_health', {'offset': -1}),
            ('project_health', {'severities': ['fatal']}),
            ('project_health', {'severities': 'warning'}),
            ('project_health', {'category': 'invented'}),
            ('connection_operations', {'history': 'false'}),
            ('project_history', {'since': 'yesterday'}),
            ('monitor_telegrams', {'limit': -1}),
            ('monitor_latest', {'address': 'x' * 201}),
            ('project_get_ga_assignments', {}),
            ('project_get_ga_assignments', {'group_address': '1/2/3', 'group_address_id': 1}),
            ('project_checkpoint_status', {'path': '/data/private'}),
            ('connection_cancel_operations', {}), ('monitor_send_read', {}),
            ('monitor_clear', {}), ('project_jump_to', {'event_id': 1}),
        ]:
            with self.subTest(name=name, args=args), self.assertRaises(Rejected):
                validate(name, args)

    def test_health_filters_and_pages_without_creating_checkpoint(self):
        self.runtime.tools['project_health'] = Mock(return_value={'items': [{'message': str(i)} for i in range(5)]})
        result = self.call('project_health', {'severities': ['warning'], 'offset': 1, 'limit': 2})
        self.assertEqual(result, {'items': [{'message': '1'}, {'message': '2'}], 'count': 2, 'total': 5, 'next_offset': 3})
        self.runtime.tools['project_health'].assert_called_once_with(severities=['warning'])
        self.runtime.projects.checkpoint.assert_not_called()

    def test_operations_device_filter_and_separate_pages(self):
        self.runtime.tools['connection_operations'] = Mock(return_value={
            'bus_operation': {'kind': 'scan'}, 'active': [{'node_id': 1}, {'node_id': 2}],
            'history': [{'node_id': 2}, {'node_id': 1}, {'node_id': 1}]})
        result = self.call('connection_operations', {'node_id': 1, 'limit': 1})
        self.assertIsNone(result['bus_operation'])
        self.assertEqual(result['active']['total'], 1)
        self.assertEqual(result['history']['total'], 2)
        self.assertEqual(result['history']['next_offset'], 1)
        self.runtime.tools['connection_operations'].assert_called_once_with()

    def test_telegrams_filter_before_pagination_and_compare_timezones(self):
        self.runtime.tools['monitor_telegrams'] = Mock(return_value={'items': [
            {'source': '1.1.1', 'destination': '1/2/3', 'timestamp': '2026-11-22T10:00:00+01:00'},
            {'source': '1.1.2', 'destination': '1/2/4', 'timestamp': '2026-11-22T11:00:00Z'},
            {'source': '1.1.1', 'destination': '1/2/3', 'timestamp': '2026-11-22T12:00:00Z'},
        ]})
        result = self.call('monitor_telegrams', {'destination': '1/2/3', 'since': '2026-11-22T10:00:00Z', 'limit': 1})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['timestamp'], '2026-11-22T12:00:00Z')
        self.runtime.tools['monitor_telegrams'].assert_called_once_with(limit=0)

    def test_project_log_pages_and_cached_value_is_returned_unchanged(self):
        self.runtime.tools['project_log'] = Mock(return_value={'items': [{'comment': None, 'encrypted': True}], 'count': 1, 'total': 3})
        self.assertEqual(self.call('project_log', {'offset': 1, 'limit': 1})['next_offset'], 2)
        self.runtime.tools['project_log'].assert_called_once_with(offset=1, limit=1)
        value = {'address': '1/2/3', 'timestamp': '2020-01-01T00:00:00Z', 'payload': '01'}
        self.runtime.tools['monitor_latest'] = Mock(return_value=value)
        self.assertEqual(self.call('monitor_latest', {'address': '1/2/3'}), value)

    def test_checkpoint_status_excludes_paths_admin_identity_and_grants(self):
        self.runtime.projects.status.return_value = {
            'active': {'guid': 'g', 'state': 's', 'name': 'House', 'path': '/private/project'},
            'dirty': True, 'error': 'Export failed', 'storage': {'bytes': 10},
            'checkpoints': [{'id': 'a', 'created': 'today', 'actor': 'admin', 'path': '/private', 'comment': 'Before edit'}]}
        result = self.call('project_checkpoint_status')
        self.assertEqual(result['error'], 'Export failed')
        self.assertTrue(result['dirty'])
        self.assertEqual(result['checkpoints']['items'][0]['created'], 'today')
        self.assertNotIn('path', result['active'])
        self.assertNotIn('actor', result['checkpoints']['items'][0])
        self.runtime.projects.checkpoint.assert_not_called()


class DiagnosticGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_reads_use_private_adapter_without_mutation_grants(self):
        received = []
        async def adapter(request):
            received.append((request.path, request.headers.get('X-Butler-MCP-Token'), await request.json()))
            return web.json_response({'items': [], 'count': 0, 'total': 0, 'next_offset': None})
        backend = web.Application()
        backend.router.add_post('/butler-assistant', adapter)
        async with TestClient(TestServer(backend)) as editor:
            original = ClientSession._request
            async def redirect(session, method, url, **kwargs):
                if str(url).startswith('http://127.0.0.1:8511/'):
                    url = str(editor.make_url('/butler-assistant'))
                return await original(session, method, url, **kwargs)
            with patch.object(ClientSession, '_request', redirect):
                async with TestClient(TestServer(application('private', True, logging.getLogger('test')))) as client:
                    reply = await client.post('/call', json={'tool': 'project_health', 'arguments': {'limit': 1}})
                    self.assertEqual(reply.status, 200)
                    self.assertEqual((await reply.json())['result']['items'], [])
        self.assertEqual(received, [('/butler-assistant', 'private', {'tool': 'project_health', 'arguments': {'limit': 1}})])

    async def test_every_diagnostic_is_denied_when_reads_are_disabled(self):
        call = AsyncMock()
        with patch('butler.knx_bridge.ClientSession') as editor:
            async with TestClient(TestServer(application('private', False, logging.getLogger('test'), call))) as client:
                for entry in DIAGNOSTICS:
                    args = {'address': '1/2/3'} if entry['name'] == 'monitor_latest' else {}
                    if entry['name'] == 'project_get_ga_assignments':
                        args = {'group_address_id': 1}
                    if entry['name'] == 'project_get_com_object_links':
                        args = {'node_id': 1, 'com_object_ref_id': 'O-1'}
                    reply = await client.post('/call', json={'tool': entry['name'], 'arguments': args})
                    self.assertEqual(reply.status, 400)
                    self.assertIn('reads are disabled', (await reply.json())['error'])
            editor.assert_not_called()
            call.assert_not_called()
