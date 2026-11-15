import io
import json
from pathlib import Path
import shutil
import tempfile
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
        files, manifest = unpack_checkpoint((folder / 'checkpoint.zip').read_bytes())
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
        raw=(projects.folder/checkpoint['id']/'checkpoint.zip').read_bytes()
        with patch('butler.workspace.validate_config', side_effect=lambda value: value):
            result=deliver_checkpoint(raw,{},self.config)
        repo=self.root/'workspaces/repository'
        self.assertEqual((repo/'knx_editor/project.xknx').read_bytes(),native.read_bytes())
        self.assertEqual(result['branch'],'deploy')
        (repo/'unfinished').write_text('keep me')
        with self.assertRaises(Exception):
            deliver_checkpoint(raw,{},self.config)
        self.assertEqual((repo/'unfinished').read_text(),'keep me')
