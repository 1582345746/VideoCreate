"""Hash-bound media references and private HTTPS transport records.

Transport links are deliberately outside generation plans. Replacing an expired
link does not replace the source bytes or create a remote generation task.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import math
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json, resolve_key
from .planning.project import within
from .runtime.state import state_lock
from .catalog.media_constraints import ROLES

MAX_BYTES = 512 * 1024 * 1024


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def inspect(path: Path, kind: str) -> dict:
    """Inspect real bytes; extension alone never establishes media type."""
    path = Path(path).resolve()
    if kind not in ROLES or not path.is_file():
        raise ConfigError('Choose an existing image, video or audio reference')
    size = path.stat().st_size
    if not 0 < size <= MAX_BYTES:
        raise ConfigError('Reference must be nonempty and at most 512 MiB')
    with path.open('rb') as stream:
        head = stream.read(64)
    mime, suffix = '', ''
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        mime, suffix = 'image/png', '.png'
    elif head.startswith(b'\xff\xd8\xff'):
        mime, suffix = 'image/jpeg', '.jpg'
    elif head.startswith(b'RIFF') and head[8:12] == b'WEBP':
        mime, suffix = 'image/webp', '.webp'
    elif b'ftyp' in head[4:32]:
        mime, suffix = 'video/mp4', '.mp4'
    elif head.startswith(b'RIFF') and head[8:12] == b'WAVE':
        mime, suffix = 'audio/wav', '.wav'
    elif head.startswith(b'ID3') or len(head) > 1 and head[0] == 255 and head[1] & 224 == 224:
        mime, suffix = 'audio/mpeg', '.mp3'
    if not mime.startswith(kind + '/'):
        raise ConfigError('Reference bytes do not match the selected media kind or supported format')
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ConfigError('FFprobe is required to inspect actual reference media')
    result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, timeout=60)
    try:
        data = json.loads(result.stdout)
        streams = data['streams']
        stream = next(s for s in streams if s.get('codec_type') == ('audio' if kind == 'audio' else 'video'))
        if result.returncode:
            raise ValueError()
        duration = None if kind == 'image' else float(data['format']['duration'])
        if duration is not None and (not math.isfinite(duration) or duration <= 0):
            raise ValueError()
        if kind == 'image' and stream.get('codec_name') not in {'png', 'mjpeg', 'webp'}:
            raise ValueError()
    except (KeyError, ValueError, StopIteration, TypeError):
        raise ConfigError('Reference media could not be decoded as the selected kind') from None
    return {'kind': kind, 'sha256': digest(path), 'bytes': size, 'mime_type': mime, 'suffix': suffix,
            'duration_seconds': duration, 'width': stream.get('width'), 'height': stream.get('height'),
            'sample_rate': int(stream['sample_rate']) if stream.get('sample_rate') else None,
            'channels': stream.get('channels')}


def register(root, source, *, kind, role):
    root, source = Path(root).resolve(), Path(source).resolve()
    if role not in ROLES.get(kind, set()):
        raise ConfigError('Reference role does not match media kind')
    # The copied bytes, rather than a mutable original path, become the source.
    folder = root / 'assets' / 'media-references'
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='register-', dir=folder) as temp:
        snapshot = Path(temp) / 'source'
        if not source.is_file() or source.stat().st_size > MAX_BYTES:
            raise ConfigError('Missing or oversized reference source')
        shutil.copyfile(source, snapshot)
        media = inspect(snapshot, kind)
        target = folder / (media['sha256'] + media['suffix'])
        with state_lock(root):
            if target.exists() and digest(target) != media['sha256']:
                raise ConfigError('Existing registered reference was modified; preserve and repair it explicitly')
            if not target.exists():
                snapshot.replace(target)
            atomic_json(target.with_suffix(target.suffix + '.json'), media)
    return {'path': target.relative_to(root).as_posix(), 'sha256': media['sha256'], 'kind': kind, 'role': role}


def prepare_references(root, references):
    result = []
    for ref in references:
        kind = ref.get('kind', 'image')
        if ref.get('role') not in ROLES.get(kind, set()):
            raise ConfigError('Reference role does not match media kind')
        media = inspect(within(Path(root), ref['path']), kind)
        if media['sha256'] != ref.get('sha256'):
            raise ConfigError('Reference source hash changed')
        if 'derivation' in ref:
            from .reference_slices import validate_derivation
            validate_derivation(root, ref, media)
        result.append({**ref, **media})
    return result


def selection_request(root, bundle, job):
    """Serializable, URL-free constraints for selecting a job's actual inputs."""
    refs = job.get('references', [])
    result = {'seconds': job['seconds'], 'resolution': bundle['brief']['resolution'],
              'aspect_ratio': bundle['brief']['aspect_ratio']}
    shots = [s for s in bundle['director']['shots'] if s['id'] in job['shot_ids']]
    result['generate_audio'] = any(s.get('audio', {}).get('mode', 'ambience') in
                                   {'native-dialogue', 'offscreen', 'ambience'} for s in shots)
    if any('kind' in ref for ref in refs):
        if any('kind' not in ref for ref in refs):
            raise ConfigError('Explicitly type every reference before using a media URL adapter')
        result['media_references'] = prepare_references(root, refs)
    elif refs:
        primary = next((ref for ref in refs if ref['role'] == 'opening-frame'), None)
        result.update(primary_reference=primary['path'] if primary else None,
            reference_images=[ref['path'] for ref in refs if ref['role'] != 'opening-frame'])
    return result


def public_url(url, *, resolve=False):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (ValueError, TypeError):
        raise ConfigError('Invalid HTTPS media URL') from None
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in url)):
        raise ConfigError('Media URL must be HTTPS without login credentials, whitespace or fragment')
    host = parsed.hostname
    if host.lower() == 'localhost' or host.lower().endswith(('.localhost', '.local')):
        raise ConfigError('Media URL must be publicly reachable')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ConfigError('Media URL must not use a private or reserved address')
    if resolve:
        try:
            addresses = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
        except OSError:
            raise ConfigError('Media URL hostname could not be resolved') from None
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ConfigError('Media URL resolves to a private or reserved address')
    return parsed


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_url(url, media, *, timeout=30, deadline_seconds=300):
    """GET without cookies/auth, checking redirects, type, length and full hash."""
    opener = urllib.request.build_opener(NoRedirect())
    current, started = url, time.monotonic()
    try:
        for hop in range(6):
            public_url(current, resolve=True)
            request = urllib.request.Request(current, headers={'Accept-Encoding': 'identity',
                'User-Agent': 'VideoCreate/reference-check'}, method='GET')
            try:
                response = opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                if error.code in {301, 302, 303, 307, 308}:
                    location = error.headers.get('Location')
                    error.close()
                    if not location:
                        raise ConfigError('Media redirect has no location')
                    current = urllib.parse.urljoin(current, location)
                    continue
                status = error.code
                error.close()
                raise ConfigError('Media link GET failed with HTTP ' + str(status)) from None
            with response:
                if response.status != 200:
                    raise ConfigError('Media URL must return a complete HTTP 200 file')
                mime = response.headers.get('Content-Type', '').split(';')[0].lower().strip()
                accepted = {media['mime_type'], 'application/octet-stream'}
                if media['mime_type'] == 'audio/wav':
                    accepted.add('audio/x-wav')
                if mime not in accepted:
                    raise ConfigError('Media URL returned a page or a different media type')
                value, size = hashlib.sha256(), 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > media['bytes'] or time.monotonic() - started > deadline_seconds:
                        raise ConfigError('Media link check exceeded the expected size or local time limit')
                    value.update(chunk)
                if size != media['bytes'] or value.hexdigest() != media['sha256']:
                    raise ConfigError('Media URL bytes differ from the registered local reference')
                return {'verified_at': time.time(), 'sha256': value.hexdigest(), 'bytes': size,
                    'mime_type': mime, 'redirects': hop, 'method': 'unauthenticated-full-GET-sha256'}
        raise ConfigError('Media link has too many redirects')
    except ConfigError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as error:
        # Network exceptions can contain secret signatures or capability URLs.
        raise ConfigError('Media link check failed: ' + type(error).__name__) from None


def transport_id(upstream_id, account_id, sha256):
    return hashlib.sha256(json.dumps([upstream_id, account_id, sha256], separators=(',', ':')).encode()).hexdigest()


def _registry(root):
    path = Path(root) / 'references' / 'transports.json'
    return path, load_json(path) if path.exists() else {'schema_version': 1, 'links': {}}


def bind_url(root, reference, *, upstream_id, account_id, store_root, url=None, url_env=None,
             expires_at=None, permanent=False):
    if bool(url) == bool(url_env):
        raise ConfigError('Choose URL input or an environment variable')
    if permanent == (expires_at is not None):
        raise ConfigError('Declare either permanent availability or an expiry time')
    if expires_at is not None and (not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool)
            or not math.isfinite(expires_at) or expires_at <= time.time()):
        raise ConfigError('Reference URL expiry must be a future timestamp')
    media = prepare_references(root, [reference])[0]
    value = url if url is not None else os.environ.get(url_env, '')
    public_url(value)
    # Verify before storing a new reference or replacing a working transport.
    evidence = verify_url(value, media)
    key = transport_id(upstream_id, account_id, media['sha256'])
    if url_env:
        auth = {'env': url_env}
    else:
        from .config.secrets import store_credential
        project_key = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
        auth = store_credential(Path(store_root), 'media-' + project_key + '-' + key[:24], value,
                                version=hashlib.sha256(value.encode()).hexdigest()[:32])
        auth.pop('type', None)
    record = {'upstream_id': upstream_id, 'account_id': account_id, 'source_sha256': media['sha256'],
        'kind': media['kind'], 'url_auth': auth, 'url_sha256': hashlib.sha256(value.encode()).hexdigest(),
        'expires_at': expires_at, 'availability': 'user-declared-permanent' if permanent else 'user-declared-expiry',
        'verification': evidence, 'updated_at': time.time()}
    with state_lock(Path(root)):
        path, registry = _registry(root)
        prior = registry['links'].get(key)
        if prior and prior != record:
            atomic_json(path.parent / 'history' / (key + '-' + str(time.time_ns()) + '.json'), prior)
        registry['links'][key] = record
        atomic_json(path, registry)
    return {'transport_id': key, **{k: v for k, v in record.items() if k != 'url_auth'}, 'paid_creates': 0}


def resolve_transports(root, references, *, upstream_id, account_id, store_root,
                       minimum_validity=7200, verify=True):
    _, registry = _registry(root)
    result = []
    for media in prepare_references(root, references):
        key = transport_id(upstream_id, account_id, media['sha256'])
        record = registry['links'].get(key)
        if not record or record.get('kind') != media['kind']:
            raise ConfigError('Reference has no HTTPS link for this upstream/account; use media-ref link')
        expiry = record.get('expires_at')
        if expiry is not None and expiry - time.time() < minimum_validity:
            raise ConfigError('Reference link expires too soon; refresh the link without recreating known tasks')
        url = resolve_key(record['url_auth'], store_root=Path(store_root))
        if hashlib.sha256(url.encode()).hexdigest() != record['url_sha256']:
            raise ConfigError('Reference URL changed; link and verify the new value explicitly')
        public_url(url)
        if verify:
            evidence = verify_url(url, media)
        else:
            evidence = record['verification']
        result.append({**media, 'url': url,
                       'expires_at': expiry, 'verification': evidence})
    return result


def list_links(root):
    _, registry = _registry(root)
    return {'links': [{k: v for k, v in {'id': key, **record}.items() if k != 'url_auth'}
                      for key, record in registry['links'].items()], 'paid_creates': 0}
