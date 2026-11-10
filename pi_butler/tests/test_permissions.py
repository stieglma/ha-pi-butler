import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from butler.access import Access, applications
from butler.permissions import DEFAULT, PermissionStore, migrate_permissions
from butler.policy import Rejected
from test_access import OPTIONS, FakeHA


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'permissions.json'
        migrate_permissions(self.path, OPTIONS['ha_access'])
        self.store = PermissionStore(self.path)
        self.access = Access(OPTIONS, FakeHA(), store=self.store)

    async def test_save_applies_and_survives_restart(self):
        version = self.access.policy.version
        result = await self.access.save_permissions({'policy': DEFAULT, 'version': version})
        self.assertNotEqual(result['version'], version)
        restarted = Access(OPTIONS, FakeHA(), store=self.store)
        self.assertEqual(restarted.policy.config, DEFAULT)
        self.assertFalse(self.access.policy.permits('light.yes', 'control', {}))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    async def test_stale_page_cannot_overwrite(self):
        before = self.path.read_text()
        with self.assertRaises(Rejected):
            await self.access.save_permissions({'policy': DEFAULT, 'version': 'old'})
        self.assertEqual(self.path.read_text(), before)

    async def test_invalid_or_unknown_entity_does_not_change_permissions(self):
        for entity in ('typo', 'light.typo'):
            candidate = {'enabled': True, 'allow': [{'capability': 'control', 'entity_ids': [entity]}]}
            before = self.path.read_text()
            with self.assertRaises(Rejected):
                await self.access.save_permissions({'policy': candidate, 'version': self.access.policy.version})
            self.assertEqual(self.path.read_text(), before)

    async def test_disk_failure_preserves_active_policy(self):
        before = self.access.policy.version
        with patch.object(self.store, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                await self.access.save_permissions({'policy': DEFAULT, 'version': before})
        self.assertEqual(self.access.policy.version, before)

    def test_migration_never_overwrites_saved_permissions(self):
        migrate_permissions(self.path, DEFAULT)
        self.assertEqual(self.store.load()[0].config, OPTIONS['ha_access'])

    def test_invalid_migration_preserves_input_and_disables_writes(self):
        self.path.unlink()
        invalid = {'enabled': True, 'allow': [{'capability': 'control', 'entity_ids': ['typo']}]}
        migrate_permissions(self.path, invalid)
        policy, warning = self.store.load()
        self.assertEqual(policy.config, DEFAULT)
        self.assertTrue(warning)
        self.assertEqual(json.loads(self.path.with_name('permissions-import.json').read_text()), invalid)

    async def test_existing_missing_exclusion_is_preserved(self):
        config = dict(OPTIONS['ha_access'], deny_entity_ids=['light.removed'])
        self.store.save(config)
        access = Access(OPTIONS, FakeHA(), store=self.store)
        await access.save_permissions({'policy': config, 'version': access.policy.version})
        self.assertEqual(access.policy.config['deny_entity_ids'], ['light.removed'])

    async def test_agent_socket_has_no_management_routes(self):
        from aiohttp.test_utils import TestClient, TestServer
        tools, admin = applications(self.access)
        async with TestClient(TestServer(tools)) as client:
            for path in ('/permissions', '/catalog'):
                response = await client.post(path, json={})
                self.assertEqual(response.status, 404)
            response = await client.post('/call', json={'tool': 'permissions', 'arguments': {}})
            self.assertEqual(response.status, 400)
        async with TestClient(TestServer(admin)) as client:
            response = await client.post('/permissions', json={'policy': DEFAULT, 'version': self.access.policy.version})
            self.assertEqual(response.status, 200)
            self.assertEqual(self.access.policy.config, DEFAULT)
