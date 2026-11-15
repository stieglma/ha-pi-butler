"""Private KNX checkpoints. Called on the editor UI thread under its I/O lock.

A checkpoint is published only when its native snapshot and exchange export are
complete. The repository is never the live project. No project passwords are saved.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
import uuid
import zipfile

from .maintenance import StorageCapacityError, reserve_storage, storage_bytes

ROOT = Path('/data/knx')
MAX_PROJECT = 64 * 1024 * 1024


class CheckpointStorageError(StorageCapacityError):
    """Safe, actionable capacity errors that can be shown in project status."""


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.butler-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Invalid checkpoint identifier')
    return value


def remembered_project(root=ROOT, recent=()):
    """Migrate existing manual imports via upstream recents; only native private files."""
    if root.is_symlink() or (root / 'projects').is_symlink():
        return None
    marker = root / 'active-project.json'
    try:
        candidates = [json.loads(marker.read_text())['path']]
    except (OSError, ValueError, KeyError, TypeError):
        candidates = list(recent)[:1] if isinstance(recent, (list, tuple)) else []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        path = Path(candidate)
        try:
            relative = path.resolve().relative_to((root / 'projects').resolve())
            if '..' in relative.parts or any(p.is_symlink() for p in [path, *path.parents] if p.resolve().is_relative_to(root.resolve())):
                continue
            if path.suffix.lower() == '.xknx' and path.is_file():
                return str(path)
        except (ValueError, OSError):
            pass
    return None


class Projects:
    def __init__(self, ctx, root=ROOT, snapshot=None, export=None, limits=None, storage_reserver=None):
        self.ctx, self.root = ctx, root
        self.folder = root / 'checkpoints'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.error = ''
        self.last = None
        self.snapshot_fn, self.export_fn = snapshot, export
        self.storage_reserver = storage_reserver or reserve_storage
        if limits is None:
            try:
                limits = json.loads(Path('/etc/pi-butler/limits.json').read_text())
            except FileNotFoundError:
                limits = {}
        self.storage_limit = limits.get('storage_megabytes', 4096) * 1048576
        self.checkpoint_budget = min(512 * 1048576, self.storage_limit // 4)
        self.retention_days = limits.get('retention_days', 7)
        self.max_checkpoints = 10

    def _folders(self):
        rows = []
        for folder in self.folder.iterdir():
            if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'[a-f0-9]{32}', folder.name):
                continue
            try:
                meta = json.loads((folder / 'checkpoint.json').read_text())
                created = datetime.fromisoformat(meta['created']).timestamp()
                # Older releases stored a redundant full ZIP. Downloads now build it on demand.
                (folder / 'checkpoint.zip').unlink(missing_ok=True)
                rows.append((created, folder, storage_bytes(folder)))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(rows, key=lambda row: row[0], reverse=True)

    def prune(self, protected=()):
        """Bound history globally, preserving the newest complete recovery point."""
        rows = self._folders()
        protected = set(protected)
        if rows:
            protected.add(rows[0][1].name)
        used, kept = 0, 0
        cutoff = time.time() - self.retention_days * 86400
        # Account protected revisions first so optional history fits around them.
        for _, folder, size in rows:
            if folder.name in protected:
                used += size
                kept += 1
        for created, folder, size in rows:
            if folder.name in protected:
                continue
            if created < cutoff or kept >= self.max_checkpoints or used + size > self.checkpoint_budget:
                shutil.rmtree(folder)
            else:
                used += size
                kept += 1

    def download(self, ident, kind, destination):
        """Copy under the project lock so later pruning cannot break a download."""
        folder, _ = self.find(ident)
        if kind == 'zip':
            with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as archive:
                for name in ('project.xknx', 'project.knxproj', 'checkpoint.json'):
                    archive.write(folder / name, name)
        else:
            name = 'checkpoint.json' if kind == 'json' else 'project.' + kind
            shutil.copyfile(folder / name, destination)

    @property
    def project(self):
        return self.ctx.api.project

    def active(self):
        project = self.project
        if not project.is_open or project.loading or project.working_path is None:
            return None
        return {'guid': project.ensure_guid(), 'state': project.state_key(),
                'name': project.get_project_metadata().name, 'path': str(project.path)}

    def remember(self):
        active = self.active()
        if active:
            path = Path(active['path'])
            try:
                path.resolve().relative_to((self.root / 'projects').resolve())
                if path.suffix.lower() == '.xknx':
                    atomic_json(self.root / 'active-project.json', {'path': str(path)})
            except ValueError:
                pass

    def entries(self):
        active = self.active()
        if not active:
            return []
        entries = []
        for folder in self.folder.iterdir():
            if not re.fullmatch(r'[a-f0-9]{32}', folder.name) or folder.is_symlink():
                continue
            try:
                meta = json.loads((folder / 'checkpoint.json').read_text())
                if meta['guid'] == active['guid']:
                    entries.append(meta)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(entries, key=lambda row: row['created'], reverse=True)

    def find(self, ident):
        ident = identifier(ident)
        meta = next((row for row in self.entries() if row['id'] == ident), None)
        if meta is None:
            raise ValueError('Checkpoint does not belong to the active project')
        folder = self.folder / ident
        hashes = meta.get('sha256')
        if not isinstance(hashes, dict) or set(hashes) != {'project.xknx', 'project.knxproj'}:
            raise ValueError('Checkpoint checksums are incomplete')
        for name, expected in hashes.items():
            path = folder / name
            if path.is_symlink() or not path.is_file() or digest(path) != expected:
                raise ValueError('Checkpoint checksum failed')
        return folder, meta

    def _snapshot(self, dest):
        if self.snapshot_fn:
            return self.snapshot_fn(self.project.working_path, dest)
        from editor_gui.plugins.backups.store import snapshot, check_project_file
        snapshot(self.project.working_path, dest)
        problem = check_project_file(dest)
        if problem:
            raise ValueError('Native snapshot failed validation')

    def _export(self, source, dest):
        if self.export_fn:
            return self.export_fn(source, dest)
        from editor_gui.plugins.project.knxproj_manufacturer import collect_manufacturer_bundle
        from editor_gui.plugins.project.plugin_export import binary_data_for_export
        from editor_gui.settings import export_schema
        from xknxeditor.proj import export_knxproj
        project = self.project
        bundle = collect_manufacturer_bundle(project.program_refs(), self.ctx.api.catalog)
        result = export_knxproj(source, dest, schema=export_schema(),
            password=project.project_password, extra_files=bundle.extra_files,
            master_xml=bundle.master_xml, fetch_master=False,
            module_arguments=project.module_arguments(), group_object_trees=project.group_object_trees(),
            binary_data_transform=binary_data_for_export)
        if result.missing_references:
            raise ValueError('Export is incomplete: missing manufacturer references')
        return ['Exchange export is unsigned; ETS acceptance has not been verified.']

    def checkpoint(self, comment='', source='admin', actor='', force=True, protected=()):
        if self.snapshot_fn is None and self.project.is_open and not self.project.loading:
            # Pinned upstream keeps newly added products and calculated values
            # pending in memory. Finish them as its normal close path does.
            self.project._finish_product_data()
            self.project._store_calculated(refresh=False)
        active = self.active()
        if not active:
            raise ValueError('Open a project first')
        self.prune(protected)
        rows = self.entries()
        if not force and rows and rows[0]['state'] == active['state']:
            try:
                _, existing = self.find(rows[0]['id'])
            except (ValueError, OSError, KeyError, TypeError):
                # A matching state key is insufficient if its recovery files were lost.
                pass
            else:
                self.last, self.error = existing, ''
                return existing
        ident = uuid.uuid4().hex
        temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=self.folder))
        try:
            # Allow for two maximum-size project artifacts plus manifest/staging overhead.
            reserve = 2 * MAX_PROJECT + 1048576
            if shutil.disk_usage(self.root).free < reserve:
                raise CheckpointStorageError('Not enough storage for a safe checkpoint. Free space or increase storage_megabytes.')
            with self.storage_reserver(reserve):
                self._snapshot(temporary / 'project.xknx')
                warnings = self._export(temporary / 'project.xknx', temporary / 'project.knxproj') or []
                if any((temporary / name).stat().st_size > MAX_PROJECT for name in ('project.xknx', 'project.knxproj')):
                    raise CheckpointStorageError('Checkpoint artifacts must each be at most 64 MiB.')
                meta = {**active, 'id': ident, 'created': datetime.now(timezone.utc).isoformat(),
                        'comment': comment[:500], 'source': source, 'actor': actor[:80], 'warnings': warnings,
                        'sha256': {name: digest(temporary / name) for name in ('project.xknx', 'project.knxproj')}}
                # Internal file paths are neither exported nor used as restore destinations.
                meta.pop('path')
                atomic_json(temporary / 'checkpoint.json', meta)
                if storage_bytes(temporary) > self.checkpoint_budget:
                    raise CheckpointStorageError('Checkpoint exceeds its storage budget. Increase storage_megabytes or reduce the project size.')
                for artifact in temporary.iterdir():
                    with artifact.open('rb') as stream:
                        os.fsync(stream.fileno())
                os.replace(temporary, self.folder / ident)
                self.last, self.error = meta, ''
                self.remember()
                self.prune(protected)
                return meta
        except Exception as exc:
            self.error = 'Checkpoint/export failed. Changes remain in the live project; retry after inspecting the editor.'
            if isinstance(exc, StorageCapacityError):
                self.error += ' ' + str(exc)
            raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def status(self):
        active = self.active()
        rows = self.entries()
        latest = rows[0] if rows else None
        return {'active': active, 'checkpoints': rows, 'error': self.error,
                'storage': {'bytes': sum(row[2] for row in self._folders()),
                            'budget_bytes': self.checkpoint_budget, 'max_checkpoints': self.max_checkpoints,
                            'retention_days': self.retention_days},
                'dirty': bool(active and (not latest or latest['state'] != active['state']))}

    def restore(self, ident, expected, actor=''):
        active = self.active()
        if not active or active['state'] != expected:
            raise ValueError('Project changed. Refresh before restoring.')
        folder, _ = self.find(ident)
        # Closing callbacks can checkpoint/prune again during replace_with(). Keep
        # the validated source outside history until replacement has finished.
        with tempfile.TemporaryDirectory(prefix='.restore-', dir=self.root) as temporary:
            staged = Path(temporary) / 'project.xknx'
            shutil.copyfile(folder / 'project.xknx', staged)
            from xknxeditor.proj.core.project_secrets import check_project_password
            check_project_password(staged, self.project.project_password)
            self.checkpoint('Before restore ' + ident, 'restore', actor, protected=(ident,))
            self.project.replace_with(staged, self.project.project_password)
        try:
            return self.checkpoint('Restored ' + ident, 'restore', actor)
        except Exception:
            raise ValueError('Project restored, but its new checkpoint/export failed. Previous checkpoints are retained.') from None
