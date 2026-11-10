import asyncio
import json
import unittest
from unittest.mock import AsyncMock
from butler.access import Access, REGISTRIES, redact, interval, validate_args
from butler.policy import Rejected

OPTIONS = {'ha_access': {'enabled': True, 'allow': [{'capability': 'control', 'domains': ['light']}], 'deny_entity_ids': ['light.no']},
           'limits': {'parallel_requests': 2, 'response_bytes': 65536, 'log_lines': 20}}


class FakeHA:
    token = 'secret-upstream-token'

    def __init__(self):
        self.actions = []
        self.registry = [{'entity_id': 'light.yes', 'labels': []}, {'entity_id': 'light.no', 'labels': []}]

    async def ws(self, command):
        return self.registry

    async def rest(self, path, **kwargs):
        if path == '/api/states':
            return [{'entity_id': 'light.yes', 'attributes': {'token': self.token}}, {'entity_id': 'light.no'}]
        if path == '/api/services':
            return [{'domain': 'light', 'services': {'turn_on': {}}}]
        if path.startswith('/api/services/'):
            self.actions.append((path, kwargs['data']))
            return []
        if path == '/core/logs':
            return 'token=' + self.token + '\n' + '\n'.join(str(n) for n in range(30))
        return {}


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ha = FakeHA()
        self.access = Access(OPTIONS, self.ha)

    async def test_no_partial_execution(self):
        with self.assertRaises(Rejected):
            await self.access.call('action', {'domain': 'light', 'action': 'turn_on', 'target': {'domains': ['light']}})
        self.assertEqual(self.ha.actions, [])

    async def test_explicit_forwarded_entities_only(self):
        await self.access.call('action', {'domain': 'light', 'action': 'turn_on', 'target': {'entity_ids': ['light.yes']}, 'data': {'brightness_pct': 20}})
        self.assertEqual(self.ha.actions, [('/api/services/light/turn_on', {'brightness_pct': 20, 'entity_id': ['light.yes']})])

    async def test_registry_failure_fails_closed(self):
        self.ha.ws = AsyncMock(side_effect=RuntimeError('unavailable'))
        with self.assertRaises(RuntimeError):
            await self.access.call('action', {'domain': 'light', 'action': 'turn_on', 'target': {'entity_ids': ['light.yes']}})
        self.assertFalse(self.ha.actions)

    async def test_pagination_and_redaction(self):
        result = await self.access.call('states', {'limit': 1})
        self.assertTrue(result['truncated'])
        self.assertEqual(result['next_offset'], 1)
        self.assertEqual(result['items'][0]['attributes']['token'], '[REDACTED]')
        result = await self.access.call('states', {'offset': 1, 'limit': 1})
        self.assertIsNone(result['next_offset'])
        self.assertFalse(result['truncated'])

    async def test_logs_bounded(self):
        result = await self.access.call('diagnostics', {'source': 'core', 'lines': 3})
        self.assertEqual(result['text'].splitlines(), ['27', '28', '29'])
        self.assertTrue(result['truncated'])
        with self.assertRaises(Rejected):
            await self.access.call('diagnostics', {'source': 'core', 'lines': 21})

    async def test_oversized_result(self):
        self.ha.rest = AsyncMock(return_value=[{'entity_id': 'light.big', 'text': 'x'*70000}])
        with self.assertRaises(Rejected):
            await self.access.call('states', {})

    async def test_unknown_fields_and_routes(self):
        for name, args in [('template', {}), ('config', {'url': '/api/auth'}), ('registry', {'kind': 'auth'}), ('states', {'limit': True})]:
            with self.subTest(name=name), self.assertRaises(Rejected):
                await self.access.call(name, args)

    async def test_summary_reports_policy_without_token(self):
        result = await self.access.call('access_summary', {})
        self.assertEqual([r['entity_id'] for r in result['items']], ['light.yes'])
        self.assertNotIn(self.ha.token, json.dumps(result))

    def test_interval(self):
        for args in [{'start': '2026-11-10'}, {'start': '2026-01-01T00:00:00Z', 'end': '2026-11-10T00:00:00Z'}]:
            with self.assertRaises(Rejected):
                interval(args)

    def test_redaction(self):
        value = redact({'nested': {'api_key': 'hidden'}, 'text': 'Authorization: Bearer abc.def\npassword=xyz\nknown-secret'}, 'known-secret')
        self.assertNotIn('hidden', json.dumps(value))
        self.assertNotIn('abc.def', json.dumps(value))
        self.assertNotIn('xyz', json.dumps(value))
        self.assertNotIn('known-secret', json.dumps(value))
