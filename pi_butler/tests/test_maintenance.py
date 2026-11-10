import os
from pathlib import Path
import tempfile
import time
import unittest
from butler.maintenance import expire


class RetentionTests(unittest.TestCase):
    def test_old_artifacts_removed_fresh_and_symlink_targets_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / 'diagnostics'
            artifacts.mkdir()
            old = artifacts / 'old.log'
            old.write_text('old')
            os.utime(old, (1, 1))
            fresh = artifacts / 'fresh.log'
            fresh.write_text('fresh')
            external = root / 'protected'
            external.mkdir()
            target = external / 'secret'
            target.write_text('preserve')
            os.utime(target, (1, 1))
            (artifacts / 'linked-directory').symlink_to(external, target_is_directory=True)
            (artifacts / 'linked-file').symlink_to(target)
            expire(artifacts, time.time() - 100)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertEqual(target.read_text(), 'preserve')
            self.assertTrue((artifacts / 'linked-file').is_symlink())
