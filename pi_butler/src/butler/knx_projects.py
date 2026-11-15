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
from datetime import datetime, timezone
import uuid
import zipfile

ROOT = Path('/data/knx')
MAX_PROJECT = 64 * 1024 * 1024


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
    def __init__(self, ctx, root=ROOT, snapshot=None, export=None):
        self.ctx, self.root = ctx, root
        self.folder = root / 'checkpoints'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.error = ''
        self.last = None
        self.snapshot_fn, self.export_fn = snapshot, export

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
        for name, expected in meta['sha256'].items():
            if name not in ('project.xknx', 'project.knxproj') or digest(folder / name) != expected:
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

    def checkpoint(self, comment='', source='admin', actor='', force=True):
        if self.snapshot_fn is None and self.project.is_open and not self.project.loading:
            # Pinned upstream keeps newly added products and calculated values
            # pending in memory. Finish them as its normal close path does.
            self.project._finish_product_data()
            self.project._store_calculated(refresh=False)
        active = self.active()
        if not active:
            raise ValueError('Open a project first')
        rows = self.entries()
        if not force and rows and rows[0]['state'] == active['state']:
            self.last = rows[0]
            self.error = ''
            return rows[0]
        ident = uuid.uuid4().hex
        temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=self.folder))
        try:
            self._snapshot(temporary / 'project.xknx')
            warnings = self._export(temporary / 'project.xknx', temporary / 'project.knxproj') or []
            meta = {**active, 'id': ident, 'created': datetime.now(timezone.utc).isoformat(),
                    'comment': comment[:500], 'source': source, 'actor': actor[:80], 'warnings': warnings,
                    'sha256': {name: digest(temporary / name) for name in ('project.xknx', 'project.knxproj')}}
            # Internal file paths are neither exported nor used as restore destinations.
            meta.pop('path')
            atomic_json(temporary / 'checkpoint.json', meta)
            with zipfile.ZipFile(temporary / 'checkpoint.zip', 'w', compression=zipfile.ZIP_STORED) as archive:
                for name in ('project.xknx', 'project.knxproj', 'checkpoint.json'):
                    archive.write(temporary / name, name)
            for artifact in temporary.iterdir():
                with artifact.open('rb') as stream:
                    os.fsync(stream.fileno())
            os.replace(temporary, self.folder / ident)
            self.last, self.error = meta, ''
            self.remember()
            return meta
        except Exception:
            self.error = 'Checkpoint/export failed. Changes remain in the live project; retry after inspecting the editor.'
            raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def status(self):
        active = self.active()
        rows = self.entries()
        latest = rows[0] if rows else None
        return {'active': active, 'checkpoints': rows, 'error': self.error,
                'dirty': bool(active and (not latest or latest['state'] != active['state']))}

    def restore(self, ident, expected, actor=''):
        active = self.active()
        if not active or active['state'] != expected:
            raise ValueError('Project changed. Refresh before restoring.')
        folder, meta = self.find(ident)
        # Validate credentials and integrity BEFORE replacing or checkpointing anything.
        from xknxeditor.proj.core.project_secrets import check_project_password
        check_project_password(folder / 'project.xknx', self.project.project_password)
        self.checkpoint('Before restore ' + ident, 'restore', actor)
        self.project.replace_with(folder / 'project.xknx', self.project.project_password)
        try:
            return self.checkpoint('Restored ' + ident, 'restore', actor)
        except Exception:
            raise ValueError('Project restored, but its new checkpoint/export failed. Previous checkpoints are retained.') from None
