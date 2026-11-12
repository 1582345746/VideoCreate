"""A loopback-only, read-only file service for an existing HTTPS tunnel.

Only explicitly published immutable snapshots are served. There is no directory
listing, upload endpoint, arbitrary path endpoint or remotely callable admin API.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json
from .media_references import MAX_BYTES, digest, inspect, public_url
from .runtime.state import state_lock


def settings(config):
    value = {'port': 8765, 'public_base_url': '', 'max_link_seconds': 604800}
    value.update(config.get('local_media_server', {}))
    return value


def publish(store_root, source, *, kind, public_base_url, lifetime_seconds=14400, maximum_seconds=604800):
    parsed = public_url(public_base_url)
    if parsed.query or parsed.fragment:
        raise ConfigError('Public media base URL must not contain a query or fragment')
    if (isinstance(lifetime_seconds, bool) or not isinstance(lifetime_seconds, (float, int))
            or not math.isfinite(lifetime_seconds) or not 60 <= lifetime_seconds <= maximum_seconds):
        raise ConfigError('Media link lifetime must be between 60 seconds and the configured maximum')
    source = Path(source).resolve()
    root = Path(store_root) / 'local-media'
    cache = root / 'objects'
    cache.mkdir(parents=True, exist_ok=True)
    if not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise ConfigError('Missing or oversized local media')
    with tempfile.TemporaryDirectory(prefix='publish-', dir=cache) as temp:
        snapshot = Path(temp) / 'source'
        shutil.copyfile(source, snapshot)
        media = inspect(snapshot, kind)
        name = media['sha256'] + media['suffix']
        destination = cache / name
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        with state_lock(root):
            if destination.exists() and digest(destination) != media['sha256']:
                raise ConfigError('Published snapshot was modified; refusing to overwrite it')
            if not destination.exists():
                snapshot.replace(destination)
            path = root / 'published.json'
            registry = load_json(path) if path.exists() else {'schema_version': 1, 'items': {}}
            registry['items'][token_hash] = {'file': name, 'media': media, 'created_at': now,
                'expires_at': now + lifetime_seconds, 'revoked': False}
            atomic_json(path, registry)
    return {'publication_id': token_hash, 'url': public_base_url.rstrip('/') + '/m/' + token + '/reference' + media['suffix'],
            'expires_at': now + lifetime_seconds, 'media': media, 'network_requests': 0, 'paid_creates': 0}


def revoke(store_root, publication_id):
    root = Path(store_root) / 'local-media'
    with state_lock(root):
        path = root / 'published.json'
        registry = load_json(path) if path.exists() else {'schema_version': 1, 'items': {}}
        if publication_id not in registry['items']:
            raise ConfigError('Unknown publication ID')
        registry['items'][publication_id]['revoked'] = True
        atomic_json(path, registry)
    return {'ok': True, 'publication_id': publication_id, 'revoked': True}


def published(store_root):
    path = Path(store_root) / 'local-media/published.json'
    registry = load_json(path) if path.exists() else {'items': {}}
    return [{'publication_id': key, 'kind': item['media']['kind'], 'sha256': item['media']['sha256'],
             'bytes': item['media']['bytes'], 'expires_at': item['expires_at'], 'revoked': item['revoked'],
             'expired': item['expires_at'] <= time.time()} for key, item in registry['items'].items()]


def byte_range(value, size):
    if not value:
        return 0, size - 1, False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not any(match.groups()):
        raise ValueError('Unsupported range')
    left, right = match.groups()
    if not left:
        count = int(right)
        if count <= 0:
            raise ValueError('Empty suffix')
        return max(0, size - count), size - 1, True
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start >= size or end < start:
        raise ValueError('Unsatisfiable range')
    return start, end, True


class MediaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, store_root, port=8765):
        self.root = Path(store_root).resolve() / 'local-media'
        self.slots = threading.BoundedSemaphore(12)
        self.hash_cache = {}
        self.cache_lock = threading.Lock()
        self.connections = threading.BoundedSemaphore(16)
        self.instance_id = secrets.token_hex(16)
        super().__init__(('127.0.0.1', port), MediaHandler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

    def handle_error(self, request, client_address):
        # Do not log signed/capability URLs or socket headers.
        pass


class MediaHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'VideoCreateMedia'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *args):
        pass

    def end_empty(self, code, *, content_range=None):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        if self.path == '/health' and code == 204:
            self.send_header('X-VideoCreate-Instance', self.server.instance_id)
        if content_range:
            self.send_header('Content-Range', content_range)
        self.end_headers()

    def do_HEAD(self):
        self.serve_media(head=True)

    def do_GET(self):
        self.serve_media(head=False)

    def do_POST(self):
        self.close_connection = True
        self.end_empty(405)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST

    def serve_media(self, *, head):
        if self.path == '/health':
            self.end_empty(204)
            return
        # Reject percent-encoded traversal, query variants and unexpected names.
        match = re.fullmatch(r'/m/([A-Za-z0-9_-]{43})/reference\.(png|jpg|webp|mp4|mp3|wav)', self.path)
        if not match:
            self.end_empty(404)
            return
        if not self.server.slots.acquire(blocking=False):
            self.end_empty(503)
            return
        try:
            path = self.server.root / 'published.json'
            registry = load_json(path) if path.is_file() else {'items': {}}
            key = hashlib.sha256(match[1].encode()).hexdigest()
            item = registry['items'].get(key)
            if not item or item['revoked'] or item['expires_at'] <= time.time():
                self.end_empty(404)
                return
            media = item['media']
            if not re.fullmatch(r'[0-9a-f]{64}\.(png|jpg|webp|mp4|mp3|wav)', item['file']):
                self.end_empty(404)
                return
            if not item['file'].endswith('.' + match[2]):
                self.end_empty(404)
                return
            target = self.server.root / 'objects' / item['file']
            if target.is_symlink() or not target.is_file():
                self.end_empty(404)
                return
            with target.open('rb') as stream:
                stat = os.fstat(stream.fileno())
                signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
                with self.server.cache_lock:
                    known = self.server.hash_cache.get(item['file'])
                if stat.st_size != media['bytes']:
                    self.end_empty(409)
                    return
                if known != signature:
                    value = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        value.update(chunk)
                    if value.hexdigest() != media['sha256']:
                        self.end_empty(409)
                        return
                    with self.server.cache_lock:
                        self.server.hash_cache[item['file']] = signature
                try:
                    start, end, partial = byte_range(self.headers.get('Range'), stat.st_size)
                except ValueError:
                    self.end_empty(416, content_range='bytes */' + str(stat.st_size))
                    return
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type', media['mime_type'])
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('ETag', '"sha256-' + media['sha256'] + '"')
                self.send_header('Cache-Control', 'private, no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Disposition', 'inline; filename="reference.' + match[2] + '"')
                if partial:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{stat.st_size}')
                self.end_headers()
                if not head:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        data = stream.read(min(65536, remaining))
                        if not data:
                            break
                        self.wfile.write(data)
                        remaining -= len(data)
        except (OSError, ConfigError, KeyError, TypeError):
            self.close_connection = True
        finally:
            self.server.slots.release()


def serve(store_root, *, port=8765):
    root = Path(store_root) / 'local-media'
    with state_lock(root / 'server-lock', timeout=.2):
        try:
            server = MediaHTTPServer(store_root, port)
        except OSError:
            raise ConfigError('Local media port is unavailable; choose a free port') from None
        record = {'status': 'serving', 'pid': os.getpid(), 'host': '127.0.0.1', 'port': server.server_port,
                  'instance_id': server.instance_id, 'started_at': time.time()}
        atomic_json(root / 'server.json', record)
        server.timeout = .25
        try:
            while True:
                stop_path = root / 'stop.json'
                if stop_path.exists() and load_json(stop_path).get('instance_id') == server.instance_id:
                    break
                server.handle_request()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            atomic_json(root / 'server.json', {**record, 'status': 'stopped', 'stopped_at': time.time()})


def status(store_root):
    path = Path(store_root) / 'local-media/server.json'
    record = load_json(path) if path.exists() else {}
    running = False
    if record.get('status') == 'serving':
        try:
            port = int(record['port'])
            if not 1024 <= port <= 65535:
                raise ValueError()
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    'http://127.0.0.1:' + str(port) + '/health', timeout=2) as response:
                running = response.status == 204 and response.headers.get('X-VideoCreate-Instance') == record.get('instance_id')
        except (OSError, ValueError):
            pass
    return {**record, 'running': running, 'status': 'serving' if running else 'stopped-or-unreachable'}


def stop(store_root):
    record = status(store_root)
    if not record['running']:
        return {'ok': True, 'stopped': False, 'reason': 'No matching local media service is reachable'}
    atomic_json(Path(store_root) / 'local-media/stop.json', {'instance_id': record['instance_id']})
    for _ in range(30):
        time.sleep(.1)
        if not status(store_root)['running']:
            return {'ok': True, 'stopped': True, 'pid': record['pid']}
    raise ConfigError('Stop was requested locally; service has not yet stopped')


def start(config_path):
    import subprocess
    import sys
    path = Path(config_path).resolve()
    from .cli import read_config
    options = settings(read_config(path))
    with state_lock(path.parent / 'local-media/start-lock'):
        current = status(path.parent)
        if current['running']:
            if current['port'] != options['port']:
                raise ConfigError('Service is running on the previous port; stop it before changing port')
            return {'ok': True, 'reused': True, **current}
        if getattr(sys, 'frozen', False):
            args = [sys.executable, '--media-server-run', '--config', str(path)]
        else:
            code = 'import sys; sys.path.insert(0,' + repr(str(Path(__file__).resolve().parents[1])) + '); from videocreate.cli import main; raise SystemExit(main())'
            args = [sys.executable, '-c', code, 'media-server', 'run', '--config', str(path)]
        creation = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **creation)
        threading.Thread(target=process.wait, daemon=True).start()
        for _ in range(60):
            if process.poll() is not None:
                raise ConfigError('Media service exited during startup; check the configured port')
            current = status(path.parent)
            if current['running'] and current.get('pid') == process.pid:
                return {'ok': True, 'reused': False, **current}
            time.sleep(.1)
        raise ConfigError('Service startup has not been confirmed; check media-server status before starting again')
