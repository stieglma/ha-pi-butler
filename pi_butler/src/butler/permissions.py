"""Private, atomic permission storage shared only with the trusted service."""
import json
import os
from pathlib import Path
import tempfile

from .policy import Policy, Rejected

DEFAULT = {'enabled': False, 'allow': [], 'deny_entity_ids': []}


class PermissionStore:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, config):
        policy = Policy(config)
        if self.path.is_symlink():
            raise Rejected('Refusing permission file symlink')
        fd, temporary = tempfile.mkstemp(prefix='.permissions-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(policy.config, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return policy

    def load(self):
        try:
            if self.path.is_symlink():
                raise Rejected('Refusing permission file symlink')
            return Policy(json.loads(self.path.read_text())), None
        except (OSError, ValueError, TypeError):
            return Policy(DEFAULT), 'Saved permissions could not be loaded. Writes are disabled. Review and save permissions to repair them.'


def migrate_permissions(path, legacy):
    """Run once as root before removing legacy options; retain invalid input."""
    store = PermissionStore(path)
    if store.path.exists() or store.path.is_symlink():
        return
    try:
        store.save(legacy)
    except (Rejected, TypeError):
        backup = store.path.with_name('permissions-import.json')
        if not backup.exists():
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(legacy, stream)
        # Leave invalid data in the main file so load() shows the recovery notice.
        fd = os.open(store.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(legacy, stream)
