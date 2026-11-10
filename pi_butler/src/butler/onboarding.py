"""Pi-owned setup checks, project registration and editable house knowledge."""
import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone

from aiohttp import ClientSession, ClientTimeout, web
from . import workspace

MEMORY = Path('/data/pi/house-memory.md')
INITIAL_MEMORY = '''# House notes

## User-provided facts and preferences

## Agent observations

Observations should include a date, source and uncertainty. Move them to confirmed
knowledge only after user confirmation. Do not store credentials here.
'''
MAX_MEMORY = 65536


@contextlib.contextmanager
def memory_lock(path):
    lock = path.parent / '.house-memory.lock'
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def memory_snapshot(path=MEMORY):
    if path.is_symlink():
        raise ValueError('House notes must not be a symlink')
    if path.exists():
        with path.open('rb') as stream:
            raw = stream.read(MAX_MEMORY + 1)
    else:
        raw = INITIAL_MEMORY.encode()
    if len(raw) > MAX_MEMORY:
        raise ValueError('House notes exceed 64 KiB; shorten the file in the terminal')
    return {'text': raw.decode('utf-8'), 'version': hashlib.sha256(raw).hexdigest()}


def save_memory(text, version, path=MEMORY):
    if not isinstance(text, str) or not isinstance(version, str) or len(text.encode()) > MAX_MEMORY:
        raise ValueError('House notes must be text of at most 64 KiB with a version')
    with memory_lock(path):
        if memory_snapshot(path)['version'] != version:
            raise FileExistsError('House notes changed elsewhere. Reload before saving; copy your edits first.')
        fd, temporary = tempfile.mkstemp(prefix='.house-memory-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return memory_snapshot(path)


async def read_bounded(reply, limit):
    raw = bytearray()
    async for chunk in reply.content.iter_chunked(65536):
        raw.extend(chunk)
        if len(raw) > limit:
            raise ValueError('Response too large')
    return bytes(raw)


async def pi_request(client, method, path, **kwargs):
    async with client.request(method, 'http://127.0.0.1:8504' + path, allow_redirects=False, **kwargs) as reply:
        if reply.status != 200:
            raise ValueError('Pi Web is not ready')
        raw = await read_bounded(reply, 2097152)
        return json.loads(raw)


async def register_projects(client, repository_state, root=workspace.ROOT):
    """Use the live API, preserving IDs and names; retry startup/clone races later."""
    projects = await pi_request(client, 'GET', '/api/projects')
    if not isinstance(projects, list):
        raise ValueError('Unexpected Pi Web project list')
    wanted = [('scratch', 'Home Assistant')]
    if repository_state == 'ready':
        wanted.append(('repository', 'HA configuration'))
    result = {}
    for directory, name in wanted:
        path = str((root / directory).resolve())
        existing = next((p for p in projects if isinstance(p, dict) and p.get('path') == path), None)
        if existing is None:
            existing = await pi_request(client, 'POST', '/api/projects', json={'path': path, 'name': name})
            if not isinstance(existing, dict) or existing.get('path') != path or not existing.get('id'):
                raise ValueError('Could not verify project registration')
            projects.append(existing)
        result['repository_project' if directory == 'repository' else directory] = {'state': 'ready', 'help': f'{existing.get("name", name)} is registered in Pi Web.'}
    return result


def command_check(command, cwd=None):
    # Never expose output: Git/model configuration can contain credentials.
    try:
        result = subprocess.run(command, cwd=cwd, env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never'),
                                capture_output=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def model_check():
    try:
        result = subprocess.run(['node', '/opt/runtime/butler/model-status.mjs'], capture_output=True, text=True, timeout=15)
        value = json.loads(result.stdout)
        if value.get('state') in ('ready', 'pending', 'unknown'):
            return value
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return {'state': 'unknown', 'help': 'Model check unavailable. Inspect Pi Web settings/login.'}


class Onboarding:
    def __init__(self):
        self.checks = {}
        self.git_checked = 0
        self.git_result = None
        self.git_revision = None

    async def refresh(self, client):
        try:
            repository = json.loads(workspace.STATUS.read_text())
        except (OSError, ValueError):
            repository = {'state': 'pending', 'help': 'Repository setup is starting. Retry butler-workspace setup in the terminal if needed.'}
        checks = {'repository': repository}
        try:
            checks.update(await register_projects(client, repository['state']))
        except Exception:
            checks['scratch'] = {'state': 'pending', 'help': 'Waiting for Pi Web. Project registration retries automatically.'}
            if repository['state'] == 'ready':
                checks['repository_project'] = {'state': 'pending', 'help': 'Repository cloned; Pi Web registration will retry.'}
        if repository['state'] == 'not_configured':
            optional = {'state': 'optional', 'help': 'Optional for HA investigations. Configure a repository in the HA app options when needed.'}
            checks['repository_project'] = optional
            checks['git'] = optional
        elif repository['state'] == 'ready':
            # Verify remote read access, not just presence of credential files.
            # Cache for five minutes and invalidate when setup is retried.
            try:
                revision = workspace.STATUS.stat().st_mtime_ns
            except OSError:
                revision = None
            now = asyncio.get_running_loop().time()
            if now - self.git_checked >= 300 or self.git_result is None or revision != self.git_revision:
                self.git_result = await asyncio.to_thread(command_check,
                    ['git', 'ls-remote', '--exit-code', 'origin', 'HEAD'], workspace.ROOT / 'repository')
                self.git_checked, self.git_revision = now, revision
            checks['git'] = {'state': 'ready' if self.git_result else 'pending', 'help':
                'Remote read access verified; push and PR permissions are checked when delivering.' if self.git_result else
                'Remote access failed. Check terminal Git authentication/network, then run butler-workspace setup.'}
        else:
            checks['git'] = {'state': 'pending', 'help': 'Complete repository setup and terminal Git authentication first.'}
            checks['repository_project'] = {'state': 'pending', 'help': 'Registered automatically after repository setup succeeds.'}
        checks['model'] = await asyncio.to_thread(model_check)
        self.checks = {'checks': checks, 'checked_at': datetime.now(timezone.utc).isoformat()}

    async def loop(self, client):
        while True:
            try:
                await self.refresh(client)
            except Exception:
                # A failed check must not shut down the coding workspace.
                self.checks = {'checks': {}, 'error': 'Setup checks could not finish; retry shortly.'}
            await asyncio.sleep(30)


def create_app(onboarding, memory_path=MEMORY):
    app = web.Application(client_max_size=MAX_MEMORY * 8)

    async def status(request):
        return web.json_response(onboarding.checks, headers={'Cache-Control': 'no-store'})

    async def memory(request):
        try:
            if request.method == 'POST':
                if request.content_type != 'application/json' or request.headers.get('X-Butler-Settings') != '1':
                    raise web.HTTPForbidden(text='Settings request required')
                body = await request.json()
                if not isinstance(body, dict) or set(body) != {'text', 'version'}:
                    raise ValueError('Expected text and version')
                result = save_memory(body['text'], body['version'], memory_path)
            else:
                result = memory_snapshot(memory_path)
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except FileExistsError as error:
            return web.json_response({'error': str(error)}, status=409)
        except (ValueError, OSError) as error:
            return web.json_response({'error': str(error)}, status=400)

    app.router.add_get('/status', status)
    app.router.add_get('/memory', memory)
    app.router.add_post('/memory', memory)
    return app


async def main():
    if os.getuid() != 1000:
        raise RuntimeError('Onboarding must run as pi')
    if not MEMORY.exists():
        save_memory(INITIAL_MEMORY, memory_snapshot()['version'])
    onboarding = Onboarding()
    runner = web.AppRunner(create_app(onboarding), access_log=None)
    await runner.setup()
    socket = Path('/run/butler/workspace/ui.sock')
    socket.unlink(missing_ok=True)
    await web.UnixSite(runner, str(socket)).start()
    # Parent has setgid ingress: inherited socket group allows ingress to connect,
    # without adding pi to the privileged ingress group.
    socket.chmod(0o660)
    try:
        async with ClientSession(timeout=ClientTimeout(total=20), trust_env=False) as client:
            await onboarding.loop(client)
    finally:
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
