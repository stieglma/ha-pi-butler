"""Unprivileged, bounded repository exchange. Never opens the editor database."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import uuid
import zipfile

from . import workspace
from .knx_config import normalize_options
from .knx_projects import MAX_PROJECT


@contextlib.contextmanager
def source_file(options, repository):
    options = normalize_options(options)
    fd = os.open(repository, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in options['repository_directory'].split('/'):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        source = os.open(options['project_filename'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_PROJECT:
            os.close(source)
            raise ValueError('Source must be a regular .knxproj file of at most 64 MiB')
        with os.fdopen(source, 'rb') as stream:
            yield stream
    finally:
        os.close(fd)


def read_source(options, repository):
    with source_file(options, repository) as stream:
        data = stream.read(MAX_PROJECT + 1)
        if len(data) > MAX_PROJECT:
            raise ValueError('Repository project exceeds 64 MiB')
        return data


def unpack_checkpoint(raw):
    names = {'project.xknx', 'project.knxproj', 'checkpoint.json'}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) != 3 or set(archive.namelist()) != names:
            raise ValueError('Expected a complete checkpoint bundle')
        if any(info.file_size > MAX_PROJECT or info.compress_size > MAX_PROJECT for info in archive.infolist()):
            raise ValueError('Checkpoint file exceeds 64 MiB')
        files = {name: archive.read(name) for name in names}
    meta = json.loads(files['checkpoint.json'])
    for name in names - {'checkpoint.json'}:
        if hashlib.sha256(files[name]).hexdigest() != meta['sha256'][name]:
            raise ValueError('Checkpoint checksum mismatch')
    return files, meta


def deliver_checkpoint(raw, options, config):
    """Deliver a validated bundle in a separate worktree, preserving interactive files."""
    options = normalize_options(options)
    config = workspace.validate_config(config)
    files, meta = unpack_checkpoint(raw)
    # All modes use a fresh task worktree; interactive edits never enter delivery.
    with workspace.locked():
        prepared = workspace.worktree(config, 'knx-' + uuid.uuid4().hex[:12])
        root = Path(prepared['path'])
        # Refuse any concurrent/existing changes before replacing exact delivery files.
        if workspace.run('git', 'status', '--porcelain', cwd=root):
            raise ValueError('Prepared checkout changed elsewhere; delivery stopped')
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        paths = []
        try:
            for part in options['repository_directory'].split('/'):
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            names = {'project.knxproj': options['project_filename'],
                     'project.xknx': options['project_filename'][:-8] + '.xknx',
                     'checkpoint.json': 'checkpoint.json'}
            # Refuse symlink destinations, including existing project exports.
            for name in names.values():
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('Delivery destination must be a regular file')
                except FileNotFoundError:
                    pass
            for source, name in names.items():
                temporary = '.checkpoint-' + uuid.uuid4().hex
                output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                try:
                    with os.fdopen(output, 'wb') as stream:
                        stream.write(files[source])
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.rename(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=fd)
                    except FileNotFoundError:
                        pass
                paths.append(options['repository_directory'] + '/' + name)
        finally:
            os.close(fd)
        object_format = workspace.run('git', 'rev-parse', '--show-object-format', cwd=root)
        expected_blobs = {}
        for source, name in names.items():
            data = files[source]
            blob = b'blob ' + str(len(data)).encode() + b'\0' + data
            expected_blobs[options['repository_directory'] + '/' + name] = hashlib.new(object_format, blob).hexdigest()
        workspace.run('git', 'add', '--', *paths, cwd=root)
        staged = set(filter(None, workspace.run('git', 'diff', '--cached', '--name-only', '-z', cwd=root).split('\0')))
        if staged - set(paths):
            raise ValueError('Other staged changes appeared during KNX delivery; checkout retained for review')
        try:
            return workspace.deliver(config, root, 'KNX checkpoint: ' + str(meta.get('comment') or meta['created'])[:200],
                                     expected_blobs=expected_blobs)
        except Exception as exc:
            raise ValueError('Git delivery failed; checkpoint and prepared checkout are retained. Inspect repository status before retrying.') from exc
