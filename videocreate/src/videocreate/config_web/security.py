"""Loopback browser sessions with same-origin CSRF and bounded request bodies."""
import asyncio
import secrets
import time
from http.cookies import CookieError, SimpleCookie

from starlette.responses import JSONResponse

COOKIE = 'vc_config_session'
MAX_BODY = 256 * 1024
TTL = 60 * 60


class Sessions:
    def __init__(self):
        self.values = {}

    def issue(self):
        now = time.monotonic()
        self.values = {key: value for key, value in self.values.items() if value[0] > now}
        if len(self.values) >= 64:
            self.values.pop(next(iter(self.values)))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.values[token] = (now + TTL, csrf)
        return token

    def read(self, headers):
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get('cookie', ''))
            token = cookie[COOKIE].value
        except (KeyError, ValueError, CookieError):
            return None
        value = self.values.get(token)
        if value and value[0] > time.monotonic():
            return value[1]
        return None


class Boundary:
    def __init__(self, app, *, origin, sessions, config_id):
        self.app, self.origin, self.sessions = app, origin, sessions
        self.config_id = config_id
        self.host = origin.split('://', 1)[1]

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope['headers']}
        path, method = scope['path'], scope['method']

        async def reject(status, code, message):
            response = JSONResponse({'error': {'code': code, 'message': message, 'field': None,
                                               'reload_required': status == 401 or code == 'config_changed'}}, status_code=status,
                                    headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
            await response(scope, receive, send)

        if headers.get('host') != self.host:
            return await reject(403, 'invalid_host', '请使用启动器提供的本机地址。')
        client = scope.get('client')
        if client and client[0] not in {'127.0.0.1', '::1', 'testclient'}:
            return await reject(403, 'loopback_required', '配置服务只接受本机连接。')
        if headers.get('origin') not in {None, self.origin} or headers.get('sec-fetch-site') == 'cross-site':
            return await reject(403, 'invalid_origin', '此请求不属于当前配置页面。')
        if method not in {'GET', 'HEAD', 'POST'}:
            return await reject(405, 'method_not_allowed', '此操作不受支持。')
        api = path.startswith('/api/')
        if api:
            csrf = self.sessions.read(headers)
            if not csrf or headers.get('x-vc-client') != '1':
                return await reject(401, 'session_required', '配置会话已失效，请重新打开页面。')
            scope['vc.csrf'] = csrf
            # Optional for existing explicit API clients. The Web always binds
            # requests after session bootstrap; a reused port cannot retarget it.
            if headers.get('x-vc-config') not in {None, self.config_id}:
                return await reject(409, 'config_changed', '当前端口已打开另一份配置，请重新打开页面后核对配置位置；原输入和记录保留。')
            if method not in {'GET', 'HEAD'}:
                if headers.get('origin') != self.origin or not secrets.compare_digest(headers.get('x-vc-csrf', ''), csrf):
                    return await reject(403, 'csrf_required', '请刷新页面后重试。')
                if headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                    return await reject(415, 'json_required', '请求必须使用 JSON。')
        chunks, size = [], 0
        if method == 'POST':
            deadline = time.monotonic() + 15
            while True:
                try:
                    packet = await asyncio.wait_for(receive(), timeout=max(.01, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    return await reject(408, 'request_timeout', '提交超时，请重新核对后再保存。')
                if packet['type'] == 'http.disconnect':
                    return
                size += len(packet.get('body', b''))
                if size > MAX_BODY:
                    return await reject(413, 'body_too_large', '提交内容过大，请缩减后重试。')
                chunks.append(packet.get('body', b''))
                if not packet.get('more_body'):
                    break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if method == 'POST' and not delivered:
                delivered = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()

        async def secured_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message.get('headers', [])) + [
                    (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                    (b'referrer-policy', b'no-referrer'), (b'x-frame-options', b'DENY'),
                    (b'permissions-policy', b'camera=(), microphone=(), geolocation=()'),
                    (b'content-security-policy', b"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
            await send(message)
        await self.app(scope, bounded_receive, secured_send)
