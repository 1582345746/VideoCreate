"""Thin local HTTP application; optional imports keep the CLI lightweight."""
import hashlib
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config.storage import ConfigError, parse_json
from .changes import Changes
from .errors import WebError
from .security import Boundary, COOKIE, Sessions, TTL
from .service import ConfigService


def config_identity(path):
    return hashlib.sha256(str(Path(path).resolve()).casefold().encode('utf-8')).hexdigest()


def create_app(path=None, *, port=8787, instance_id=None, read_only=True):
    service, sessions = ConfigService(path, read_only=read_only), Sessions()
    changes = Changes(service, read_only=read_only)
    from .checks import Checks
    checks = Checks(service)
    from .inspections import Inspections
    inspections = Inspections(service)
    from .drafts import Drafts
    drafts = Drafts(service)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service, app.state.sessions = service, sessions
    app.state.changes = changes
    app.state.identity = {'product': 'VideoCreateConfigWeb', 'version': __version__,
                          'config_id': config_identity(service.path),
                          'instance_id': instance_id or secrets.token_hex(24),
                          'mode': 'read-only' if read_only else 'editable'}
    app.add_middleware(Boundary, origin='http://127.0.0.1:' + str(port), sessions=sessions,
                       config_id=service.identity)

    @app.exception_handler(WebError)
    async def known_error(request, error):
        return JSONResponse(error.packet(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(WebError('invalid_request', '请求字段无效，请检查输入。').packet(), status_code=422)

    @app.exception_handler(ConfigError)
    async def core_error(request, error):
        return JSONResponse(WebError('configuration_error', '配置操作未完成，请重新读取并核对输入。').packet(), status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        # Exception strings, including validation input, may contain credentials.
        return JSONResponse(WebError('internal_error', '操作未完成，请重新载入并检查本机状态。', status=500).packet(), status_code=500)

    @app.get('/health')
    def health():
        return app.state.identity

    @app.get('/api/session')
    def session(request: Request):
        return {'csrf_token': request.scope['vc.csrf'], 'config_id': service.identity,
                'mode': 'read-only' if read_only else 'editable', 'expires_in': TTL}

    @app.get('/api/config/summary')
    def summary():
        return service.summary()

    @app.get('/api/catalog')
    def catalog():
        return service.catalog()

    @app.get('/api/defaults')
    def defaults():
        return service.defaults()

    @app.get('/api/backups')
    def backups():
        return changes.backups.inspect()

    async def body(request):
        try:
            return parse_json((await request.body()).decode('utf-8'))
        except (ConfigError, UnicodeError):
            raise WebError('invalid_json', '请求不是有效 JSON；请检查字段并重试。') from None

    @app.post('/api/changes/preview')
    async def preview(request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(changes.preview, await body(request), session=request.scope['vc.csrf'])

    @app.post('/api/changes/commit')
    async def commit(request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(changes.commit, await body(request), session=request.scope['vc.csrf'])

    @app.post('/api/changes/status')
    async def change_status(request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(changes.status, await body(request))

    @app.post('/api/catalog/observation')
    async def observation(request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(checks.read, await body(request))

    @app.post('/api/catalog/check')
    async def catalog_check(request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(checks.read, await body(request), refresh=True)

    for route, handler in [('evidence', inspections.evidence), ('catalog/filter', inspections.filter),
                            ('catalog/compare', inspections.compare)]:
        def endpoint(handler):
            async def run(request: Request):
                from starlette.concurrency import run_in_threadpool
                return await run_in_threadpool(handler, await body(request))
            return run
        app.add_api_route('/api/' + route, endpoint(handler), methods=['POST'])

    @app.post('/api/diagnostics/preview')
    async def diagnostics_preview(request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(inspections.diagnostic_preview, await body(request), session=request.scope['vc.csrf'])

    @app.post('/api/diagnostics/export')
    async def diagnostics_export(request: Request):
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(inspections.diagnostic_export, await body(request), session=request.scope['vc.csrf'])

    @app.get('/api/diagnostics/files/{token}')
    def diagnostics_file(token: str):
        target = inspections.exported(token)
        return FileResponse(target, media_type='application/json', filename=target.name)

    for action in ('save', 'load', 'discard', 'list'):
        def draft_endpoint(action):
            async def run(request: Request):
                from starlette.concurrency import run_in_threadpool
                return await run_in_threadpool(getattr(drafts, action), await body(request), session=request.scope['vc.csrf'])
            return run
        app.add_api_route('/api/drafts/' + action, draft_endpoint(action), methods=['POST'])

    static = Path(__file__).parent / 'static'

    @app.get('/')
    def index(request: Request):
        target = static / 'index.html'
        if not target.is_file():
            return JSONResponse({'error': {'code': 'static_missing', 'message': '请先构建配置页面资源。'}}, status_code=503)
        response = FileResponse(target, media_type='text/html')
        if not sessions.read(dict(request.headers)):
            response.set_cookie(COOKIE, sessions.issue(), max_age=TTL, httponly=True, samesite='strict', path='/')
        return response

    if (static / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')
    return app
