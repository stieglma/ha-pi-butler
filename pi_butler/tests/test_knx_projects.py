import io
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from butler.knx import authorize, normalize_policy, validate
from butler.knx_projects import Projects, digest, remembered_project
from butler.knx_repository import read_source, unpack_checkpoint, deliver_checkpoint
from butler.policy import Rejected
import test_workspace


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'projects').mkdir()
        path = self.root / 'projects/manual.xknx'
        path.write_bytes(b'native state')
        self.project = SimpleNamespace(is_open=True, loading=False, working_path=path, path=path,
            ensure_guid=lambda: 'project-guid', state_key=lambda: 'state-one',
            get_project_metadata=lambda: SimpleNamespace(name='House'))
        self.ctx = SimpleNamespace(api=SimpleNamespace(project=self.project))
        self.projects = Projects(self.ctx, self.root, snapshot=shutil.copyfile,
            export=lambda src,dst: (dst.write_bytes(src.read_bytes()), [])[1])

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_checkpoint_bundle_and_state_tracking(self):
        self.assertTrue(self.projects.status()['dirty'])
        made = self.projects.checkpoint('Initial')
        self.assertFalse(self.projects.status()['dirty'])
        folder, meta = self.projects.find(made['id'])
        self.assertEqual(digest(folder / 'project.xknx'), meta['sha256']['project.xknx'])
        download = self.root / 'download.zip'
        self.projects.download(made['id'], 'zip', download)
        files, manifest = unpack_checkpoint(download.read_bytes())
        self.assertFalse((folder / 'checkpoint.zip').exists())
        self.assertEqual(manifest['id'], made['id'])
        self.assertEqual(files['project.knxproj'], b'native state')
        self.assertNotIn('path', manifest)
        self.assertEqual(self.projects.checkpoint(force=False)['id'], made['id'])
        self.assertEqual(len(self.projects.entries()), 1)
        self.project.state_key = lambda: 'state-two'
        self.assertTrue(self.projects.status()['dirty'])
        self.projects.checkpoint(force=False)
        self.assertEqual(len(self.projects.entries()), 2)

    def test_failed_export_retains_prior_checkpoint_and_marks_dirty(self):
        first = self.projects.checkpoint()
        self.project.state_key = lambda: 'new-state'
        self.projects.export_fn = Mock(side_effect=ValueError('export failed'))
        with self.assertRaises(ValueError):
            self.projects.checkpoint()
        status = self.projects.status()
        self.assertTrue(status['dirty'])
        self.assertTrue(status['error'])
        self.assertEqual([r['id'] for r in status['checkpoints']], [first['id']])
        self.assertFalse(any(p.name.startswith('.pending-') for p in self.projects.folder.iterdir()))

    def test_checkpoint_history_is_bounded_by_bytes_count_and_age(self):
        self.project.path.write_bytes(b'x' * 1024)
        self.projects.checkpoint_budget = 6500
        self.projects.max_checkpoints = 3
        for index in range(10):
            self.project.state_key = lambda index=index: str(index)
            self.projects.checkpoint()
            status = self.projects.status()
            self.assertLessEqual(status['storage']['bytes'], 6500)
            self.assertLessEqual(len(status['checkpoints']), 3)
            self.assertFalse(status['dirty'])
        self.assertEqual(len(self.projects.entries()), 2)
        self.projects.max_checkpoints = 1
        self.projects.prune()
        self.assertEqual(len(self.projects.entries()), 1)
        first = self.projects.entries()[0]
        path = self.projects.folder / first['id'] / 'checkpoint.json'
        first['created'] = '2000-01-01T00:00:00+00:00'
        path.write_text(json.dumps(first))
        self.projects.prune()
        self.assertEqual(len(self.projects.entries()), 1, 'Newest recovery point survives aging')
        self.project.state_key = lambda: 'fresh'
        self.projects.checkpoint()
        self.assertFalse(path.exists(), 'Expired checkpoint removed once a newer recovery point exists')

    def test_default_count_limit_keeps_the_latest_ten_checkpoints(self):
        made = []
        for index in range(12):
            self.project.state_key = lambda index=index: str(index)
            made.append(self.projects.checkpoint()['id'])
        self.assertEqual([row['id'] for row in self.projects.entries()], list(reversed(made[-10:])))
        self.assertFalse((self.projects.folder / made[0]).exists())
        self.assertFalse((self.projects.folder / made[1]).exists())

    def test_restore_source_and_download_copy_survive_pruning(self):
        first = self.projects.checkpoint()
        download = self.root / 'download.xknx'
        self.projects.download(first['id'], 'xknx', download)
        self.projects.max_checkpoints = 1
        self.project.state_key = lambda: 'second'
        self.projects.checkpoint(protected=(first['id'],))
        self.assertEqual(len(self.projects.entries()), 2, 'Restore can pin its source until replacement')
        self.projects.prune()
        self.assertEqual(len(self.projects.entries()), 1)
        self.assertFalse((self.projects.folder / first['id']).exists())
        self.assertEqual(download.read_bytes(), b'native state')

    def test_oversized_or_capacity_denied_checkpoint_keeps_recovery_point(self):
        first = self.projects.checkpoint()
        self.project.state_key = lambda: 'new'
        self.projects.checkpoint_budget = 1
        with self.assertRaisesRegex(ValueError, 'storage budget'):
            self.projects.checkpoint()
        self.assertEqual(self.projects.entries()[0]['id'], first['id'])
        self.assertIn('Increase storage_megabytes', self.projects.error)
        self.projects.checkpoint_budget = 512 * 1048576
        with patch('butler.knx_projects.shutil.disk_usage', return_value=SimpleNamespace(free=0)), \
                patch.object(self.projects, '_snapshot') as snapshot:
            with self.assertRaisesRegex(ValueError, 'Not enough storage'):
                self.projects.checkpoint()
            snapshot.assert_not_called()
        self.assertEqual(self.projects.entries()[0]['id'], first['id'])
        self.assertFalse(any(p.name.startswith('.pending-') for p in self.projects.folder.iterdir()))

    def test_legacy_duplicate_zip_is_removed(self):
        first = self.projects.checkpoint()
        legacy = self.projects.folder / first['id'] / 'checkpoint.zip'
        legacy.write_bytes(b'redundant archive')
        self.projects.prune()
        self.assertFalse(legacy.exists())
        self.projects.find(first['id'])

    def test_cross_project_and_corrupt_checkpoints_cannot_restore(self):
        first = self.projects.checkpoint()
        with self.assertRaises(ValueError):
            self.projects.find('../projects')
        self.project.ensure_guid = lambda: 'another-project'
        with self.assertRaises(ValueError):
            self.projects.find(first['id'])
        self.project.ensure_guid = lambda: 'project-guid'
        (self.projects.folder / first['id'] / 'project.xknx').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            self.projects.find(first['id'])
        with self.assertRaises(ValueError):
            self.projects.restore(first['id'], 'stale-state')

    def test_existing_manual_import_is_adopted_but_outside_or_symlink_is_not(self):
        path = self.project.path
        self.assertEqual(remembered_project(self.root, [str(path)]), str(path))
        self.projects.remember()
        self.assertEqual(remembered_project(self.root), str(path))
        path.unlink()
        outside = self.root / 'outside.xknx'
        outside.write_text('outside')
        path.symlink_to(outside)
        self.assertIsNone(remembered_project(self.root))
        self.assertIsNone(remembered_project(self.root, [str(outside)]))

    def test_source_copy_is_bounded_regular_and_never_follows_symlinks(self):
        folder = self.root / 'repository/knx_editor'
        folder.mkdir(parents=True)
        path = folder / 'project.knxproj'
        path.write_bytes(b'source')
        self.assertEqual(read_source({}, folder.parent), b'source')
        path.unlink()
        path.symlink_to(self.project.path)
        with self.assertRaises(OSError):
            read_source({}, folder.parent)
        path.unlink()
        path.mkdir()
        with self.assertRaises(ValueError):
            read_source({}, folder.parent)

    def test_bundle_rejects_traversal_extra_entries_and_wrong_hash(self):
        for names in (['../project.xknx'], ['project.xknx','project.knxproj','checkpoint.json','extra']):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw,'w') as z:
                for name in names:
                    z.writestr(name, b'content')
            with self.assertRaises(ValueError):
                unpack_checkpoint(raw.getvalue())


class KnxGrantTests(unittest.TestCase):
    def test_default_denied_scoped_and_implicit_delete(self):
        args = {'node_id': 7, 'parameter_ref_id': 'parameter', 'value': '1'}
        validate('project_set_parameter', args)
        for policy in ({'grants': []}, {'grants': [{'project_guid':'guid','capabilities':['change'],'node_ids':[7]}]}):
            with self.assertRaises(Rejected):
                authorize(policy, 'project_set_parameter', args, 'guid')
        policy = {'grants':[{'project_guid':'guid','capabilities':['change','delete'],'node_ids':[7]}]}
        authorize(policy, 'project_set_parameter', args, 'guid')
        for changed, guid in (({**args, 'node_id':8}, 'guid'), (args, 'other')):
            with self.assertRaises(Rejected):
                authorize(policy,'project_set_parameter',changed,guid)
        with self.assertRaises(Rejected):
            authorize(policy,'project_remove_group_address',{'group_address_id': 1},'guid')
        with self.assertRaises(Rejected):
            validate('project_set_parameter', {**args, 'path':'/tmp/evil'})
        for value in ({'grants':[{'project_guid':'guid','capabilities':['program'],'node_ids':[]}]}, {'grants':{},'enabled':True}):
            with self.assertRaises(Rejected):
                normalize_policy(value)


class KnxDeliveryTests(unittest.TestCase):
    setUp = test_workspace.WorkspaceTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown
    # Inherit the temporary bare-remote setup, not all workspace tests.
    def test_concurrent_push_deliveries_publish_the_requested_checkpoint(self):
        from butler import workspace
        def bundle(label):
            files = {'project.xknx': label.encode(), 'project.knxproj': ('export ' + label).encode()}
            meta = {'created': label, 'sha256': {n: hashlib.sha256(v).hexdigest() for n, v in files.items()}}
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                for name, data in files.items():
                    archive.writestr(name, data)
                archive.writestr('checkpoint.json', json.dumps(meta))
            return raw.getvalue()

        first_prepared, release_first, second_started, second_prepared = (threading.Event() for _ in range(4))
        original_prepare = workspace.prepare
        def prepare(config, name):
            result = original_prepare(config, name)
            if not first_prepared.is_set():
                first_prepared.set()
                if not release_first.wait(5):
                    raise AssertionError('First delivery was not released')
            else:
                second_prepared.set()
            return result
        def second():
            second_started.set()
            return deliver_checkpoint(bundle('B'), {}, self.config)

        with patch.object(workspace, 'validate_config', side_effect=lambda value: value), \
                patch.object(workspace, 'prepare', side_effect=prepare), \
                ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(deliver_checkpoint, bundle('A'), {}, self.config)
            try:
                self.assertTrue(first_prepared.wait(5))
                b = pool.submit(second)
                self.assertTrue(second_started.wait(5))
                self.assertFalse(second_prepared.wait(0.1), 'Second preparation escaped the transaction lock')
            finally:
                release_first.set()
            results = [a.result(timeout=10), b.result(timeout=10)]
        self.assertNotEqual(results[0]['commit'], results[1]['commit'])
        for label, result in zip(('A', 'B'), results):
            for name, expected in [('project.xknx', label), ('project.knxproj', 'export ' + label)]:
                self.assertEqual(workspace.run('git', '--git-dir', str(self.remote), 'show',
                    result['commit'] + ':knx_editor/' + name), expected)

    def test_binary_checkpoint_delivery_and_preservation_of_unrelated_work(self):
        private = self.root / 'private'
        (private / 'projects').mkdir(parents=True)
        native = private / 'projects/manual.xknx'
        native.write_bytes(b'\x00\xff SQLite synthetic data')
        project = SimpleNamespace(is_open=True, loading=False, path=native, working_path=native,
            ensure_guid=lambda:'guid',state_key=lambda:'state',get_project_metadata=lambda:SimpleNamespace(name='House'))
        projects=Projects(SimpleNamespace(api=SimpleNamespace(project=project)), private,
            snapshot=shutil.copyfile,export=lambda src,dst:(dst.write_bytes(b'\xffPK export'),[])[1])
        checkpoint=projects.checkpoint('Delivery')
        download=private/'download.zip'
        projects.download(checkpoint['id'], 'zip', download)
        raw=download.read_bytes()
        with patch('butler.workspace.validate_config', side_effect=lambda value: value):
            result=deliver_checkpoint(raw,{},self.config)
        repo=self.root/'workspaces/repository'
        self.assertEqual((repo/'knx_editor/project.xknx').read_bytes(),native.read_bytes())
        self.assertEqual(result['branch'],'deploy')
        (repo/'unfinished').write_text('keep me')
        with self.assertRaises(Exception):
            deliver_checkpoint(raw,{},self.config)
        self.assertEqual((repo/'unfinished').read_text(),'keep me')
