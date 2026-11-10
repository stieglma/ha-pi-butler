import json
from pathlib import Path
import tempfile
import unittest
from butler.profile import initialize, seed_packages

RUNTIME = Path('/opt/runtime')


class ProfileTests(unittest.TestCase):
    def test_existing_settings_and_resource_filters_preserved(self):
        settings = {'defaultModel': 'chosen-model', 'packages': [
            {'source': 'npm:@example/tools@1.0.0', 'skills': [], 'extensions': ['allowed.ts']},
            'npm:personal-package']}
        result, seen = seed_packages(settings, [], ['@example/tools', 'bundled'], RUNTIME)
        self.assertEqual(result['defaultModel'], 'chosen-model')
        self.assertEqual(result['packages'][:2], settings['packages'])
        self.assertEqual(result['packages'][2:], ['/opt/runtime/node_modules/bundled'])
        self.assertNotIn('bundled', settings['packages'])

    def test_idempotent_and_new_image_defaults_added(self):
        result, seen = seed_packages({}, [], ['first'], RUNTIME)
        again, seen = seed_packages(result, seen, ['first'], RUNTIME)
        self.assertEqual(result, again)
        newer, seen = seed_packages(again, seen, ['first', 'second'], RUNTIME)
        self.assertEqual(len(newer['packages']), 2)

    def test_user_removal_is_not_reversed(self):
        result, seen = seed_packages({}, [], ['bundled'], RUNTIME)
        result['packages'] = []
        result, seen = seed_packages(result, seen, ['bundled'], RUNTIME)
        self.assertEqual(result['packages'], [])

    def test_invalid_settings_or_manifest_fail_without_replacement(self):
        for settings, seen, names in [([], [], ['x']), ({'packages': {}}, [], ['x']),
                                      ({}, {}, ['x']), ({}, [], ['../escape']), ({}, [], ['x', 'x'])]:
            with self.subTest(settings=settings, names=names), self.assertRaises(ValueError):
                seed_packages(settings, seen, names, RUNTIME)

    def test_real_files_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime, agent = root / 'runtime', root / 'agent'
            runtime.mkdir(); agent.mkdir()
            (runtime / 'package.json').write_text(json.dumps({'piButler': {'packages': ['example']}}))
            package = runtime / 'node_modules' / 'example'
            package.mkdir(parents=True)
            (package / 'package.json').write_text(json.dumps({'name': 'example'}))
            initialize(agent, runtime)
            initialize(agent, runtime)
            self.assertEqual(json.loads((agent / 'settings.json').read_text())['packages'], [str(package)])
            (agent / 'settings.json').unlink()
            external = root / 'external.json'
            external.write_text('{"keep": true}')
            (agent / 'settings.json').symlink_to(external)
            with self.assertRaises(ValueError):
                initialize(agent, runtime)
            self.assertEqual(external.read_text(), '{"keep": true}')
