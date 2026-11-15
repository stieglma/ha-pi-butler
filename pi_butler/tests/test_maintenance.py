import os
from pathlib import Path
import tempfile
import time
import unittest
from butler.maintenance import StorageCapacityError, expire, reserve_storage, storage_bytes, storage_server


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


class StorageTests(unittest.TestCase):
    def test_reservations_account_for_live_usage_and_release_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            data.mkdir()
            path = root / 'capacity.sock'
            with storage_server(data, 100, path) as capacity:
                self.assertEqual(path.stat().st_mode & 0o777, 0o660)
                with reserve_storage(60, path):
                    with self.assertRaises(StorageCapacityError):
                        with reserve_storage(41, path):
                            self.fail('Concurrent reservations exceeded the app limit')
                    self.assertEqual(capacity.reserved, 60)
                self.assertEqual(capacity.reserved, 0)
                with self.assertRaisesRegex(RuntimeError, 'failed operation'):
                    with reserve_storage(100, path):
                        raise RuntimeError('failed operation')
                self.assertEqual(capacity.reserved, 0)
                private = data / 'private'
                private.mkdir(mode=0o700)
                (private / 'file').write_bytes(b'x' * 70)
                with self.assertRaises(StorageCapacityError):
                    with reserve_storage(31, path):
                        self.fail('Private data was omitted from accounting')
                with reserve_storage(30, path):
                    pass
            self.assertFalse(path.exists())

    def test_counts_nested_files_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            data.mkdir()
            nested = data / 'nested'
            nested.mkdir()
            (nested / 'file').write_bytes(b'12345')
            outside = root / 'outside'
            outside.mkdir()
            (outside / 'secret').write_bytes(b'x' * 1000)
            directory_link = data / 'linked-directory'
            directory_link.symlink_to(outside, target_is_directory=True)
            file_link = data / 'linked-file'
            file_link.symlink_to(outside / 'secret')
            broken = data / 'broken'
            broken.symlink_to(root / 'missing')
            self.assertEqual(storage_bytes(data), 5 + file_link.lstat().st_size + broken.lstat().st_size)
