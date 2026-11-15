"""Pinned editor adapter: admin lifecycle API and finite assistant mutations."""
import asyncio
import hmac
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tempfile
import threading
import uuid

from .knx import CAPABILITIES, authorize, normalize_policy, validate
from .knx_projects import Projects, ROOT, MAX_PROJECT, atomic_json
from .policy import Rejected


class Runtime:
    def __init__(self, root=ROOT):
        self.root = root
        self.ctx = None
        self.projects = None
        self.tools = {}
        self.audit = logging.getLogger('butler.knx.editor')

    def attach(self, ctx, monitor=True):
        if self.ctx is not None and self.ctx.api.project is ctx.api.project:
            return
        # MainThreadExecutor does not support recursive dispatch. Our finite
        # project functions run inside one locked UI task, including authorization.
        run_on_ui = ctx.run_on_ui
        ctx.run_on_ui = lambda fn, **kw: fn() if threading.current_thread() is threading.main_thread() else run_on_ui(fn, **kw)
        from editor_gui.plugins.mcp.tools import project
        class Registry:
            def tool(_self, fn, **kwargs):
                self.tools[fn.__name__] = fn
                return fn
        project.register(Registry(), ctx)
        self.ctx = ctx
        self.projects = Projects(ctx, self.root)
        self.audit = logging.getLogger('butler.knx.editor.' + hashlib.sha256(str(self.root).encode()).hexdigest()[:12])
        if not self.audit.handlers:
            self.audit.addHandler(RotatingFileHandler(self.root / 'admin-audit.log', maxBytes=1048576, backupCount=2))
        self.audit.setLevel(logging.INFO)
        self.audit.propagate = False
        def closing():
            if self.projects.active():
                try:
                    self.projects.checkpoint('Project closing', 'editor', force=False)
                except Exception:
                    self.audit.error('KNX closing checkpoint failed')
        ctx.run_locked(lambda: ctx.api.project.subscribe('closing', closing))
        if ctx.project_plugin is not None:
            self.guard_program_queue(ctx.project_plugin._program_queue)
        monitor_enabled = monitor
        def monitor():
            while True:
                try:
                    def tick():
                        self.projects.remember()
                        if self.projects.active():
                            self.projects.checkpoint('Automatic editor checkpoint', 'editor', force=False)
                    ctx.run_locked(tick, timeout=300)
                except Exception:
                    self.audit.error('KNX automatic checkpoint unavailable; inspect project status')
                threading.Event().wait(30)
        if monitor_enabled:
            threading.Thread(target=monitor, name='butler-checkpoints', daemon=True).start()

    def guard_program_queue(self, queue):
        start = queue._start
        def guarded(item):
            if item.scope is not None and not item.test:
                try:
                    self.ctx.run_locked(lambda: self.projects.checkpoint(
                        'Before programming device ' + str(item.node_id), 'programming', force=False), timeout=600)
                except Exception:
                    from concurrent.futures import Future
                    failed = Future()
                    failed.set_exception(ValueError('Programming blocked: project checkpoint/export failed'))
                    return failed
            return start(item)
        queue._start = guarded

    def policy(self):
        path = self.root / 'permissions.json'
        if not path.exists():
            return {'grants': []}
        return normalize_policy(json.loads(path.read_text()))

    def policy_version(self):
        return hashlib.sha256(json.dumps(self.policy(), sort_keys=True).encode()).hexdigest()

    def execute(self, action, body, actor=''):
        if not self.ctx:
            raise ValueError('Editor services are starting; retry shortly')
        def work():
            projects = self.projects
            if action == 'status':
                return {**projects.status(), 'policy': self.policy(), 'policy_version': self.policy_version()}
            if action == 'policy':
                if set(body) != {'grants', 'version'} or body['version'] != self.policy_version():
                    raise ValueError('KNX permissions changed. Refresh before saving.')
                policy = normalize_policy({'grants': body['grants']})
                atomic_json(self.root / 'permissions.json', policy)
                self.audit.info('KNX permissions updated by admin %s', actor)
                return {'policy': policy}
            if action == 'checkpoint':
                if set(body) != {'comment'} or not isinstance(body['comment'], str) or len(body['comment']) > 500:
                    raise ValueError('Expected a comment of at most 500 characters')
                return projects.checkpoint(body['comment'], 'admin', actor)
            if action == 'restore':
                if set(body) != {'id', 'state'}:
                    raise ValueError('Expected checkpoint id and current project state')
                result = projects.restore(body['id'], body['state'], actor)
                self.audit.info('KNX restore %s by admin %s', body['id'], actor)
                return result
            if action == 'assistant':
                if set(body) != {'tool', 'arguments'}:
                    raise Rejected('Invalid KNX request')
                name, args = body['tool'], body['arguments']
                validate(name, args)
                if name not in CAPABILITIES:
                    raise Rejected('Not an assistant project mutation')
                active = projects.active()
                if not active:
                    raise Rejected('Open a project first')
                authorize(self.policy(), name, args, active['guid'])
                # Refuse mutations without a complete recovery point. All checks
                # and the actual mutation share this UI task and its project lock.
                projects.checkpoint('Before ' + name, 'assistant', force=False)
                result = self.tools[name](**args)
                self.audit.info('KNX assistant mutation %s project %s', name, active['guid'])
                try:
                    projects.checkpoint(name, 'assistant')
                except Exception:
                    return {'result': result, 'checkpoint_error': projects.error,
                            'changed': True}
                return {'result': result}
            raise ValueError('Unknown KNX action')
        return self.ctx.run_locked(work, timeout=600)

    def import_source(self, source, actor=''):
        if not self.ctx:
            raise ValueError('Editor services are starting; retry shortly')
        destination = self.root / 'projects' / ('repository-' + uuid.uuid4().hex + '.xknx')
        def work():
            if self.projects.active():
                self.projects.checkpoint('Before repository import', 'admin', actor, force=False)
            # Upstream validates and stages before installing the new native file.
            # A new destination preserves every existing manually imported project.
            self.ctx.api.project.import_knxproj(source, destination)
            self.ctx.api.project.prepare_views()
            self.projects.remember()
            try:
                checkpoint = self.projects.checkpoint('Imported repository project', 'admin', actor)
                return {'imported': destination.name, 'checkpoint': checkpoint}
            except Exception:
                return {'imported': destination.name, 'checkpoint_error': self.projects.error}
        return self.ctx.run_locked(work, timeout=600)


class EditorApi:
    def __init__(self, app, runtime, credentials):
        self.app, self.runtime, self.credentials = app, runtime, credentials

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        assistant = path == '/butler-assistant'
        if not assistant and not path.startswith('/butler-api/'):
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse, FileResponse
        headers = scope.get('headers', [])
        key = b'x-butler-mcp-token' if assistant else b'x-butler-knx-token'
        token = self.credentials['mcp_token' if assistant else 'web_token'].encode()
        values = [v for k, v in headers if k.lower() == key]
        if scope['type'] != 'http' or len(values) != 1 or not hmac.compare_digest(values[0], token):
            if scope['type'] == 'websocket':
                return await send({'type': 'websocket.close', 'code': 4403})
            return await JSONResponse({'error': 'Forbidden'}, status_code=403)(scope, receive, send)
        from starlette.requests import Request
        request = Request(scope, receive)
        action = 'assistant' if assistant else path.removeprefix('/butler-api/')
        try:
            method = 'GET' if action in ('status', 'download') else 'POST'
            if request.method != method:
                return await JSONResponse({'error': 'Method not allowed'}, status_code=405)(scope, receive, send)
            if action == 'download':
                ident, kind = request.query_params.get('id'), request.query_params.get('kind')
                if kind not in ('xknx', 'knxproj', 'json', 'zip'):
                    raise ValueError('Invalid checkpoint format')
                folder, meta = await asyncio.to_thread(self.runtime.ctx.run_locked,
                    lambda: self.runtime.projects.find(ident))
                name = 'checkpoint.' + kind if kind in ('json', 'zip') else 'project.' + kind
                response = FileResponse(folder / name, filename=name, headers={'Cache-Control': 'no-store'})
            elif action == 'import':
                # Stream directly into KNX-owned private staging. Never give the
                # privileged editor a path in the agent-writable repository.
                with tempfile.TemporaryDirectory(prefix='.import-', dir=self.runtime.root) as tmp:
                    source = Path(tmp) / 'source.knxproj'
                    size = 0
                    with source.open('wb') as stream:
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > MAX_PROJECT:
                                raise ValueError('Project exceeds 64 MiB')
                            stream.write(chunk)
                    result = await asyncio.to_thread(self.runtime.import_source, source, request.headers.get('x-butler-admin-id', ''))
                response = JSONResponse(result)
            else:
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 32768:
                        raise ValueError('KNX request too large')
                body = json.loads(raw) if raw else {}
                if not isinstance(body, dict):
                    raise ValueError('Expected an object')
                actor = request.headers.get('x-butler-admin-id', '')
                result = await asyncio.to_thread(self.runtime.execute, action, body, actor)
                response = JSONResponse(result)
        except (ValueError, Rejected) as exc:
            response = JSONResponse({'error': str(exc)}, status_code=400)
        except Exception:
            # Upstream errors can include project secrets and filesystem paths.
            self.runtime.audit.error('KNX action failed: %s', action)
            response = JSONResponse({'error': 'KNX operation failed. Existing projects/checkpoints are retained. Check the editor for import/password or export errors.'}, status_code=502)
        response.headers['Cache-Control'] = 'no-store'
        await response(scope, receive, send)
