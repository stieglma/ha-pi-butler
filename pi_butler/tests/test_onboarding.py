import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
from butler.onboarding import (INITIAL_MEMORY, MAX_MEMORY, Onboarding, create_app,
                               memory_snapshot, save_memory, register_projects)


class MemoryTests(unittest.TestCase):
    def test_persistence_conflict_and_unrelated_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'house-memory.md'
            initial = memory_snapshot(path)
            saved = save_memory(initial['text'] + '\nKitchen switch stays powered.\n', initial['version'], path)
            self.assertEqual(memory_snapshot(path), saved)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                save_memory('stale edit', initial['version'], path)
            self.assertIn('Kitchen switch', path.read_text())
            self.assertIn('User-provided', path.read_text())

    def test_size_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'house-memory.md'
            initial = memory_snapshot(path)
            with self.assertRaises(ValueError):
                save_memory('x' * (MAX_MEMORY + 1), initial['version'], path)
            external = Path(tmp) / 'external'
            external.write_text('unchanged')
            path.symlink_to(external)
            with self.assertRaises(ValueError):
                save_memory('replacement', initial['version'], path)
            self.assertEqual(external.read_text(), 'unchanged')


class OnboardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_preserves_existing_projects_and_names(self):
        projects = [{'id': 'old', 'path': '/data/workspaces/scratch', 'name': 'My existing name'}]
        calls = []
        async def request(client, method, path, **kwargs):
            calls.append((method, path))
            if method == 'GET':
                return list(projects)
            value = {'id': 'repo', **kwargs['json']}
            projects.append(value)
            return value
        with patch('butler.onboarding.pi_request', side_effect=request):
            first = await register_projects(None, 'pending')
            self.assertEqual(calls, [('GET', '/api/projects')])
            self.assertIn('My existing name', first['scratch']['help'])
            await register_projects(None, 'ready')
            await register_projects(None, 'ready')
        self.assertEqual(len(projects), 2)
        self.assertEqual(sum(method == 'POST' for method, _ in calls), 1)
        self.assertEqual(projects[0]['id'], 'old')

    async def test_startup_failure_can_retry(self):
        with patch('butler.onboarding.pi_request', AsyncMock(side_effect=[
                OSError('not ready'), [], {'id': 'scratch', 'path': '/data/workspaces/scratch'}])):
            with self.assertRaises(OSError):
                await register_projects(None, 'not_configured')
            result = await register_projects(None, 'not_configured')
            self.assertEqual(result['scratch']['state'], 'ready')

    async def test_repository_optional_and_model_check_does_not_block_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / 'repository.json'
            status.write_text(json.dumps({'state': 'not_configured', 'help': 'Optional'}))
            with patch('butler.onboarding.workspace.STATUS', status), \
                 patch('butler.onboarding.register_projects', AsyncMock(return_value={'scratch': {'state': 'ready'}})), \
                 patch('butler.onboarding.model_check', return_value={'state': 'pending'}):
                onboarding = Onboarding()
                await onboarding.refresh(None)
                self.assertEqual(onboarding.checks['checks']['git']['state'], 'optional')
                self.assertEqual(onboarding.checks['checks']['repository_project']['state'], 'optional')
                self.assertEqual(onboarding.checks['checks']['scratch']['state'], 'ready')

    async def test_memory_api_rejects_stale_browser_save_and_missing_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'house-memory.md'
            client = TestClient(TestServer(create_app(Onboarding(), path)))
            await client.start_server()
            try:
                snapshot = await (await client.get('/memory')).json()
                payload = {'text': 'User note', 'version': snapshot['version']}
                response = await client.post('/memory', json=payload)
                self.assertEqual(response.status, 403)
                response = await client.post('/memory', json=payload, headers={'X-Butler-Settings': '1'})
                self.assertEqual(response.status, 200)
                response = await client.post('/memory', json=payload, headers={'X-Butler-Settings': '1'})
                self.assertEqual(response.status, 409)
                self.assertEqual(path.read_text(), 'User note')
            finally:
                await client.close()
