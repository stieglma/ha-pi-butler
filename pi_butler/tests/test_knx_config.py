import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from butler.knx_config import DEFAULT, normalize_options, project_source_check
from butler.onboarding import Onboarding


class KnxConfigTests(unittest.TestCase):
    def test_old_options_keep_switches_and_gain_default_location(self):
        self.assertEqual(normalize_options({}), DEFAULT)
        options = normalize_options({'enabled': False, 'read_enabled': False})
        self.assertFalse(options['enabled'])
        self.assertFalse(options['read_enabled'])
        self.assertEqual(options['repository_directory'], 'knx_editor')
        self.assertEqual(options['project_filename'], 'project.knxproj')

    def test_invalid_locations_and_unknown_options_are_rejected(self):
        for key, values in {
            'repository_directory': ['', '/tmp/project', '../knx', 'knx/../other',
                                     'knx//nested', './knx', 'knx/', 'knx\\other', '.git/projects', 'knx\nother', None],
            'project_filename': ['', '../project.knxproj', '/project.knxproj', 'folder/project.knxproj',
                                 'folder\\project.knxproj', '.KNXPROJ', 'project.xknx', 'project.knxproj\n', None],
            'enabled': ['true', 1],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    normalize_options({key: value})
        with self.assertRaises(ValueError):
            normalize_options({'arbitrary_path': '/data'})

    def test_exact_configured_file_is_found_without_changing_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'knx').mkdir()
            (root / 'knx/entities.yaml').write_text('light: []')
            (root / 'knx_editor').mkdir()
            (root / 'knx_editor/other.knxproj').write_bytes(b'not the configured file')
            self.assertEqual(project_source_check(DEFAULT, root)['state'], 'pending')
            target = root / 'knx_editor/project.knxproj'
            target.write_bytes(b'presence check does not import or validate contents')
            result = project_source_check(DEFAULT, root)
            self.assertEqual(result['state'], 'ready')
            self.assertEqual(result['path'], 'knx_editor/project.knxproj')
            self.assertFalse(result['automatic_import'])
            self.assertEqual(target.read_bytes(), b'presence check does not import or validate contents')
            custom = root / 'archive/KNX files'
            custom.mkdir(parents=True)
            (custom / 'Our house.KNXPROJ').write_bytes(b'original copy')
            result = project_source_check({'repository_directory': 'archive/KNX files',
                                           'project_filename': 'Our house.KNXPROJ'}, root)
            self.assertEqual(result['state'], 'ready')
            self.assertEqual(result['path'], 'archive/KNX files/Our house.KNXPROJ')

    def test_symlinked_root_folder_and_file_and_nonregular_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repository'
            root.mkdir()
            external = Path(tmp) / 'external'
            external.mkdir()
            (external / 'project.knxproj').write_bytes(b'outside repository')
            folder = root / 'knx_editor'
            folder.symlink_to(external, target_is_directory=True)
            self.assertEqual(project_source_check(DEFAULT, root)['state'], 'pending')
            folder.unlink()
            folder.mkdir()
            target = folder / 'project.knxproj'
            target.symlink_to(external / target.name)
            self.assertEqual(project_source_check(DEFAULT, root)['state'], 'pending')
            target.unlink()
            target.mkdir()
            self.assertEqual(project_source_check(DEFAULT, root)['state'], 'pending')
            alias = Path(tmp) / 'repository-alias'
            alias.symlink_to(root, target_is_directory=True)
            self.assertEqual(project_source_check(DEFAULT, alias)['state'], 'pending')


class KnxSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_reports_custom_source_and_hides_it_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'repository/custom').mkdir(parents=True)
            (root / 'repository/custom/house.knxproj').write_bytes(b'not imported')
            config = root / 'knx.json'
            options = {'enabled': True, 'repository_directory': 'custom', 'project_filename': 'house.knxproj', 'gateway_addresses': ['192.0.2.10']}
            config.write_text(json.dumps(options))
            with patch('butler.onboarding.KNX_CONFIG', config), \
                 patch('butler.onboarding.workspace.ROOT', root), \
                 patch('butler.onboarding.workspace.STATUS', root / 'missing-status.json'), \
                 patch('butler.onboarding.register_projects', AsyncMock(return_value={})), \
                 patch('butler.onboarding.model_check', return_value={'state': 'pending'}):
                worker = Onboarding()
                await worker.refresh(None)
                self.assertEqual(worker.checks['checks']['knx_project']['path'], 'custom/house.knxproj')
                self.assertEqual(worker.checks['checks']['knx_project']['state'], 'ready')
                options['enabled'] = False
                config.write_text(json.dumps(options))
                await worker.refresh(None)
                self.assertNotIn('knx_project', worker.checks['checks'])
