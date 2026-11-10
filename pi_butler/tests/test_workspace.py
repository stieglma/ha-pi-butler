import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from butler import workspace as w


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.seed = self.root / 'seed'
        w.run('git', 'init', '--bare', str(self.remote))
        w.run('git', 'init', '-b', 'deploy', str(self.seed))
        w.run('git', 'config', 'user.name', 'Test', cwd=self.seed)
        w.run('git', 'config', 'user.email', 'test@example.com', cwd=self.seed)
        (self.seed / 'config.yaml').write_text('light: []\n')
        w.run('git', 'add', '.', cwd=self.seed)
        w.run('git', 'commit', '-m', 'initial', cwd=self.seed)
        w.run('git', 'remote', 'add', 'origin', str(self.remote), cwd=self.seed)
        w.run('git', 'push', '-u', 'origin', 'deploy', cwd=self.seed)
        self.config = {'url': str(self.remote), 'checkout_branch': 'deploy', 'destination_branch': 'deploy',
                       'base_branch': 'deploy', 'author_name': 'Butler', 'author_email': 'butler@example.com',
                       'delivery': 'push', 'work_branch_prefix': 'butler/', 'forge': 'github'}
        self.patches = [patch.object(w, 'ROOT', self.root / 'workspaces'), patch.object(w, 'STATUS', self.root / 'status.json')]
        for p in self.patches:
            p.start()
        self.assertEqual(w.setup(self.config)['state'], 'ready')

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def candidate(self, name='task'):
        task = Path(w.worktree(self.config, name)['path'])
        (task / 'config.yaml').write_text('light: [office]\n')
        w.run('git', 'add', 'config.yaml', cwd=task)
        return task

    def test_optional_repository(self):
        self.assertEqual(w.setup(dict(self.config, url=''))['state'], 'not_configured')

    def test_delivery_honors_non_main_branch(self):
        task = self.candidate()
        result = w.deliver(self.config, task, 'configure office')
        self.assertEqual(result['branch'], 'deploy')
        self.assertEqual(w.run('git', '--git-dir', str(self.remote), 'rev-parse', 'deploy'), result['commit'])

    def test_divergent_remote_preserves_staged_changes(self):
        task = self.candidate()
        (self.seed / 'other.yaml').write_text('switch: []\n')
        w.run('git', 'add', '.', cwd=self.seed)
        w.run('git', 'commit', '-m', 'external update', cwd=self.seed)
        w.run('git', 'push', cwd=self.seed)
        head = w.run('git', 'rev-parse', 'HEAD', cwd=task)
        with self.assertRaises(w.WorkspaceError):
            w.deliver(self.config, task, 'ours')
        self.assertEqual(w.run('git', 'rev-parse', 'HEAD', cwd=task), head)
        self.assertIn('config.yaml', w.run('git', 'diff', '--cached', '--name-only', cwd=task))

    def test_invalid_yaml_preserves_work(self):
        task = self.candidate()
        (task / 'config.yaml').write_text('light: [unterminated\n')
        w.run('git', 'add', '.', cwd=task)
        with self.assertRaises(w.WorkspaceError):
            w.deliver(self.config, task, 'bad')
        self.assertIn('config.yaml', w.run('git', 'diff', '--cached', '--name-only', cwd=task))

    def test_ha_yaml_tags_and_dirty_files(self):
        task = self.candidate()
        (task / 'config.yaml').write_text('light: !include lights.yaml\npassword: !secret password\n')
        w.run('git', 'add', '.', cwd=task)
        w.check_changes(task)
        (task / 'untracked').write_text('preserve')
        with self.assertRaises(w.WorkspaceError):
            w.deliver(self.config, task, 'dirty')
        self.assertTrue((task / 'untracked').exists())

    def test_pending_auth_does_not_erase_existing_checkout(self):
        (w.ROOT / 'repository' / 'dirty').write_text('keep')
        result = w.setup(self.config)
        self.assertEqual(result['state'], 'ready')
        self.assertTrue((w.ROOT / 'repository' / 'dirty').exists())
        with self.assertRaises(w.WorkspaceError):
            w.setup(dict(self.config, url='https://example.org/other.git'))

    def test_pr_failure_never_falls_back_to_destination_push(self):
        self.config['delivery'] = 'pull_request'
        task = self.candidate()
        before = w.run('git', '--git-dir', str(self.remote), 'rev-parse', 'deploy')
        with patch.object(w, 'forge_delivery', side_effect=w.WorkspaceError('auth failed')):
            with self.assertRaises(w.WorkspaceError):
                w.deliver(self.config, task, 'candidate')
        self.assertEqual(w.run('git', '--git-dir', str(self.remote), 'rev-parse', 'deploy'), before)
        self.assertEqual(w.run('git', '--git-dir', str(self.remote), 'rev-parse', 'butler/task'), w.run('git', 'rev-parse', 'HEAD', cwd=task))

    def test_reject_unsafe_transport_and_branches(self):
        for url in ['file:///etc', 'https://user:secret@host/repo', '-flag', 'https://user@host/repo', 'ext::command']:
            with self.subTest(url=url), self.assertRaises(w.WorkspaceError):
                w.validate_config(dict(self.config, url=url))
        for name in ['../escape', '--help', 'a/b']:
            with self.assertRaises(w.WorkspaceError):
                w.worktree(self.config, name)

    def test_ssh_custom_ports_supported(self):
        self.assertEqual(w.validate_config(dict(self.config, url='ssh://git@example.org:2222/team/repo.git'))['forge'], 'github')

    def test_forge_target_verified(self):
        commands = []
        def fake(*args, **kwargs):
            commands.append(args)
            return json.dumps([{'url': 'https://example/pr/1', 'baseRefName': 'wrong', 'headRefName': 'butler/task'}])
        with patch.object(w, 'run', side_effect=fake), self.assertRaises(w.WorkspaceError):
            w.forge_delivery(self.config, self.seed, 'butler/task')
        self.assertIn('deploy', commands[0])

    def test_exact_staged_python_whitespace_is_validated(self):
        task = self.candidate()
        (task / 'bad.py').write_text('    unexpected_indent = True\n')
        w.run('git', 'add', '.', cwd=task)
        with self.assertRaises(w.WorkspaceError):
            w.check_changes(task)
