"""Immutable, local asset revisions. Importing copies bytes, never live pointers."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json
from .planning.project import content_hash, load_project, within
from .runtime.state import state_lock

KINDS = ('character', 'scene', 'prop', 'voice')
DESCRIPTOR_FIELDS = {'kind', 'description', 'identity_origin', 'invariants', 'visual_design', 'physical_design'}


def identifier(value):
    # Canonical lowercase IDs avoid two distinct revisions colliding on Windows.
    if (not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', value)
            or value in {'con', 'prn', 'aux', 'nul'} or re.fullmatch(r'(com|lpt)[0-9]', value)):
        raise ConfigError('Library ID must use lowercase letters, digits, _ or -; reserved filenames are not allowed')
    return value


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def library_root(store_root):
    return Path(store_root).resolve() / 'asset-library'


def _revision_path(store_root, asset_id, version):
    identifier(asset_id)
    if not isinstance(version, str) or not re.fullmatch(r'[0-9a-f]{64}', version):
        raise ConfigError('Choose an exact library revision from library list')
    root = library_root(store_root)
    return within(root, f'items/{asset_id}/{version}/manifest.json', exists=False)


def _validate_payload(payload):
    if (not isinstance(payload, dict) or set(payload) != {'title', 'tags', 'notes', 'descriptor', 'media'}
            or not isinstance(payload['title'], str) or not payload['title'].strip()
            or not isinstance(payload['notes'], str)
            or not isinstance(payload['tags'], list)
            or not all(isinstance(t, str) and t.strip() for t in payload['tags'])):
        raise ConfigError('Invalid library card title, tags or notes')
    card = payload['descriptor']
    if (not isinstance(card, dict) or set(card) - DESCRIPTOR_FIELDS or card.get('kind') not in KINDS
            or not isinstance(card.get('description'), str) or not card['description'].strip()
            or 'identity_origin' in card and not isinstance(card['identity_origin'], str)
            or not isinstance(card.get('invariants', []), list)
            or not all(isinstance(i, str) for i in card.get('invariants', []))):
        raise ConfigError('Invalid library asset description')
    from .planning.schema import VISUAL_DESIGN_FIELDS, PHYSICAL_DESIGN_FIELDS
    for field,keys in (('visual_design',VISUAL_DESIGN_FIELDS),('physical_design',PHYSICAL_DESIGN_FIELDS)):
        if field in card and (not isinstance(card[field],dict) or set(card[field])-set(keys)
                or any(not isinstance(value,str) for value in card[field].values())):
            raise ConfigError('Invalid library asset design')
    if not isinstance(payload['media'], list):
        raise ConfigError('Library media must be an array')
    for media in payload['media']:
        if (not isinstance(media, dict) or set(media) != {'file', 'sha256', 'bytes', 'inspection'}
                or not isinstance(media['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', media['sha256'])
                or not isinstance(media['file'], str)
                or not re.fullmatch(r'media/[0-9a-f]{64}\.(png|jpe?g|webp|gif|wav|mp3|m4a|flac|ogg)', media['file'])
                or Path(media['file']).stem != media['sha256']
                or type(media['bytes']) is not int or media['bytes'] <= 0
                or not isinstance(media['inspection'], dict)):
            raise ConfigError('Invalid library media entry')
        suffix = Path(media['file']).suffix
        if (card['kind'] == 'voice') != (suffix in {'.wav', '.mp3', '.m4a', '.flac', '.ogg'}):
            raise ConfigError('Voice cards use audio; visual cards use image references')


def _load(path, *, verify_media=True):
    manifest = load_json(path)
    if (set(manifest) != {'schema_version', 'library_id', 'version', 'payload', 'content_status'}
            or manifest['schema_version'] != 1 or manifest['content_status'] != 'unverified'
            or manifest['version'] != path.parent.name or manifest['library_id'] != path.parent.parent.name):
        raise ConfigError('Invalid library revision manifest')
    identifier(manifest['library_id'])
    _validate_payload(manifest['payload'])
    if content_hash(manifest['payload']) != manifest['version']:
        raise ConfigError('Library card changed after versioning')
    if verify_media:
        for item in manifest['payload']['media']:
            media = within(path.parent, item['file'])
            if media.stat().st_size != item['bytes'] or digest(media) != item['sha256']:
                raise ConfigError('Library media changed after versioning')
    return manifest


def inspect_reference(path, kind):
    if kind != 'voice':
        from .media.gif import probe_image
        return probe_image(path)
    if path.suffix.lower() not in {'.wav', '.mp3', '.m4a', '.flac', '.ogg'}:
        raise ConfigError('Voice reference must be WAV, MP3, M4A, FLAC or OGG')
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ConfigError('FFprobe is required to inspect a voice reference')
    try:
        result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                                capture_output=True, timeout=30)
        value = json.loads(result.stdout) if result.returncode == 0 else {}
        stream = next((s for s in value.get('streams', []) if s.get('codec_type') == 'audio'), None)
        duration = float(value.get('format', {}).get('duration', 0))
        if not stream or not math.isfinite(duration) or duration <= 0:
            raise ValueError()
    except (ValueError, subprocess.TimeoutExpired):
        raise ConfigError('Voice reference has no readable positive-duration audio stream') from None
    return {'kind': 'audio', 'duration': duration, 'codec': stream.get('codec_name'),
            'sample_rate': stream.get('sample_rate'), 'channels': stream.get('channels'),
            'content': 'unverified; no listening or speaker identity approval'}


def _copy_verified(source, target, expected):
    """Copy to a private temporary file, validate it, then install under caller's lock."""
    if target.exists():
        if not target.is_file() or digest(target) != expected:
            raise ConfigError('Existing snapshot bytes changed; preserve it and investigate before reuse')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if digest(temporary) != expected:
            raise ConfigError('Source reference changed while copying; retry from a stable source')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(root, store_root, asset_id, library_id, *, title=None, tags=None, notes=''):
    root = Path(root).resolve()
    identifier(library_id)
    bundle = load_project(root)
    asset = next((a for a in bundle['director']['assets'] if a['id'] == asset_id), None)
    if not asset:
        raise ConfigError('Choose an existing director asset')
    sources, media = [], []
    for ref in dict.fromkeys(asset.get('references', [])):
        source = within(root, ref)
        sha = digest(source)
        inspection = inspect_reference(source, asset['kind'])
        if digest(source) != sha:
            raise ConfigError('Source reference changed during inspection')
        entry = {'file': 'media/' + sha + source.suffix.lower(), 'sha256': sha,
                 'bytes': source.stat().st_size, 'inspection': inspection}
        if entry not in media:
            media.append(entry)
            sources.append(source)
    payload = {'title': title if title is not None else asset_id, 'tags': tags or [], 'notes': notes,
               'descriptor': {k: copy.deepcopy(v) for k, v in asset.items() if k in DESCRIPTOR_FIELDS}, 'media': media}
    _validate_payload(payload)
    version = content_hash(payload)
    path = _revision_path(store_root, library_id, version)
    manifest = {'schema_version': 1, 'library_id': library_id, 'version': version,
                'payload': payload, 'content_status': 'unverified'}
    with state_lock(library_root(store_root)):
        if path.exists():
            _load(path)
        else:
            for source, entry in zip(sources, media):
                _copy_verified(source, within(path.parent, entry['file'], exists=False), entry['sha256'])
            atomic_json(path, manifest)  # Commit marker is written only after all bytes are installed.
    return {'ok': True, 'library_id': library_id, 'version': version, 'manifest': str(path),
            'media_count': len(media), 'content_status': 'unverified', 'paid_creates': 0}


def describe(store_root, library_id, version):
    path = _revision_path(store_root, library_id, version)
    manifest = _load(path)
    return {'ok': True, **manifest, 'manifest': str(path), 'paid_creates': 0}


def catalog(store_root, *, kind=None, query=''):
    if kind is not None and kind not in KINDS:
        raise ConfigError('Unknown library asset kind')
    root, rows, unavailable = library_root(store_root), [], []
    for path in sorted(root.glob('items/*/*/manifest.json')):
        try:
            path = within(root, path.relative_to(root).as_posix())
            manifest = _load(path, verify_media=False)
            payload = manifest['payload']
            if kind and payload['descriptor']['kind'] != kind:
                continue
            if query.casefold() not in json.dumps(manifest, ensure_ascii=False).casefold():
                continue
            rows.append({'library_id': manifest['library_id'], 'version': manifest['version'],
                         'kind': payload['descriptor']['kind'], 'title': payload['title'], 'tags': payload['tags'],
                         'description': payload['descriptor']['description'], 'notes': payload['notes'],
                         'media_count': len(payload['media']), 'content_status': 'unverified',
                         'verification': 'card-only; describe/import verifies media hashes'})
        except (ConfigError, OSError) as exc:
            unavailable.append({'manifest': str(path), 'error': str(exc)})
    return {'ok': not unavailable, 'items': rows, 'unavailable': unavailable, 'paid_creates': 0}


def impact(root, asset_id):
    bundle = load_project(Path(root).resolve())
    asset = next((a for a in bundle['director']['assets'] if a['id'] == asset_id), None)
    if not asset:
        raise ConfigError('Unknown project asset')
    shots = {s['id'] for s in bundle['director']['shots'] if asset_id in s.get('asset_ids', [])
             or any(line.get('voice_asset_id') == asset_id for line in s.get('audio', {}).get('lines', []))}
    jobs = bundle['generation-plan']['jobs']
    direct = {j['id'] for j in jobs if shots & set(j['shot_ids'])
              or set(asset.get('references', [])) & {r['path'] for r in j.get('references', [])}}
    affected = set(direct)
    while True:
        more = {j['id'] for j in jobs if affected & set(j.get('depends_on', []))} - affected
        if not more:
            break
        affected |= more
    return {'ok': True, 'asset_id': asset_id, 'asset_hash': content_hash(asset), 'shots': sorted(shots),
            'jobs': sorted(direct), 'dependent_jobs': sorted(affected - direct), 'paid_creates': 0,
            'note': 'Impact preview only. Existing references, voice tracks, candidates and tasks are unchanged.'}


def import_asset(root, store_root, library_id, version, asset_id):
    root = Path(root).resolve()
    if not isinstance(asset_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', asset_id):
        raise ConfigError('Invalid project asset ID')
    # Hold the library lock while reading/copying; project snapshots no longer need the library afterwards.
    with state_lock(library_root(store_root)):
        source = _revision_path(store_root, library_id, version)
        manifest = _load(source)
        destination = within(root, f'assets/library/{library_id}/{version}/manifest.json', exists=False)
        asset = {'id': asset_id, **copy.deepcopy(manifest['payload']['descriptor']), 'references': [
            (destination.parent / m['file']).relative_to(root).as_posix() for m in manifest['payload']['media']]}
        with state_lock(root):
            bundle = load_project(root)
            existing = next((a for a in bundle['director']['assets'] if a['id'] == asset_id), None)
            if existing is not None and existing != asset:
                raise ConfigError('Project asset ID already exists; import under a new ID and inspect library impact before updating shots')
            if destination.exists() and load_json(destination) != manifest:
                raise ConfigError('Project library manifest changed; cannot overwrite an existing snapshot')
            for entry in manifest['payload']['media']:
                _copy_verified(within(source.parent, entry['file']),
                               within(destination.parent, entry['file'], exists=False), entry['sha256'])
            if not destination.exists():
                atomic_json(destination, manifest)
            if existing is None:
                bundle['director']['assets'].append(asset)
                atomic_json(within(root, bundle['project'].get('files', {}).get('director', 'director.json')), bundle['director'])
    return {'ok': True, 'asset_id': asset_id, 'library_id': library_id, 'version': version,
            'snapshot': str(destination), 'asset': asset, 'reused': existing is not None,
            'content_status': 'unverified', 'paid_creates': 0,
            'note': 'Copied snapshot only. Add explicit shot/reference/voice mappings before generation; no approval was inherited.'}
