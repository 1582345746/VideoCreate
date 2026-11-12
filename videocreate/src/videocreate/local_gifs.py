"""Project-owned local GIF derivations, independent of provider jobs and budgets."""
from __future__ import annotations

import copy
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json
from .local_sources import digest, _probe_video
from .media.gif import export_frames_to_gif, export_video_to_gif, probe_image
from .planning.project import content_hash, load_project, validate_plan, within
from .runtime.state import read_state, state_lock


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,47}', value) or value == 'final':
        raise ConfigError('Local GIF ID needs 1–48 ASCII letters/digits/._-; final is reserved')


def _parameters(recipe):
    sources = recipe['sources']
    kind = recipe['kind']
    if not sources or len(sources) > 1800:
        raise ConfigError('Local GIF needs 1–1800 source snapshots')
    if kind == 'video-to-gif':
        if len(sources) != 1 or sources[0]['kind'] != 'video':
            raise ConfigError('Video GIF needs exactly one video source')
    elif kind == 'frames-to-gif':
        if any(s['kind'] != 'image' for s in sources):
            raise ConfigError('Frame GIF needs ordered static image sources')
    else:
        raise ConfigError('Unknown local GIF conversion kind')
    for key, low, high in (('fps', 1, 60), ('width', 64, 2048), ('loop', -1, 65535)):
        value = recipe[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError('Invalid local GIF parameter: ' + key)
    for key in ('start', 'duration'):
        value = recipe[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ConfigError('Local GIF interval must be finite')
    if not 0 <= recipe['start'] <= 86400 or not .1 <= recipe['duration'] <= 30:
        raise ConfigError('Local GIF interval must be positive and at most 30 seconds')
    if kind == 'frames-to-gif' and (recipe['start'] != 0 or abs(recipe['duration'] - len(sources)/recipe['fps']) > 1e-9):
        raise ConfigError('Frame GIF duration is determined by frame count and fps; start must be zero')
    for source in sources:
        if not re.fullmatch(r'[0-9a-f]{64}', source['sha256']):
            raise ConfigError('Local GIF source needs an exact SHA-256')


def sources(root, recipe):
    _parameters(recipe)
    paths = []
    for source in recipe['sources']:
        path = within(root, source['path'])
        if digest(path) != source['sha256']:
            raise ConfigError('Local GIF source snapshot changed; restore it or import a new GIF ID')
        paths.append(path)
    return paths


def validate(bundle, root=None):
    errors, ids = [], {j['id'] for j in bundle['generation-plan'].get('image_jobs', [])}
    entries = bundle['generation-plan'].get('local_gifs', [])
    if entries and bundle['brief'].get('workflow_profile') not in {'gif-only', 'gif-local'}:
        errors.append('Local GIF derivations require an explicit gif-only or gif-local workflow')
    if bundle['brief'].get('workflow_profile') == 'gif-local' and bundle['generation-plan'].get('image_jobs'):
        errors.append('Local GIF workflow must not contain provider image jobs')
    for item in entries:
        try:
            _identity(item['id'])
            if item['id'] in ids:
                raise ConfigError('Local GIF IDs must be unique and must not shadow image job IDs')
            ids.add(item['id'])
            _parameters(item['recipe'])
            if root:
                sources(Path(root).resolve(), item['recipe'])
        except (ConfigError, OSError, ValueError) as exc:
            errors.append(str(exc))
    return errors


def _decode(path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ConfigError('FFmpeg is required for local GIF conversion')
    try:
        result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
                                 '-f', 'null', '-'], capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise ConfigError('Local media decode timed out; no plan was changed') from None
    if result.returncode:
        raise ConfigError('Local media did not fully decode; no plan was changed')


def _frame_shape(path):
    executable=shutil.which('ffprobe')
    if not executable:
        raise ConfigError('FFprobe is required to verify static source frames')
    try:
        result=subprocess.run([executable,'-v','error','-select_streams','v:0','-count_frames',
            '-show_entries','stream=width,height,nb_read_frames','-of','json',str(path)],
            capture_output=True,timeout=60,check=True)
        stream=json.loads(result.stdout)['streams'][0]
        if int(stream['nb_read_frames'])!=1:
            raise ValueError('Animated image')
        return stream['width'],stream['height']
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired,ValueError,KeyError,IndexError):
        raise ConfigError('Frame sources must decode to exactly one static image') from None


def _snapshot(root, source, kind):
    source = Path(source).resolve()
    suffixes = {'.mp4', '.mov', '.mkv', '.webm'} if kind == 'video' else {'.png', '.jpg', '.jpeg', '.webp'}
    if not source.is_file() or source.suffix.lower() not in suffixes:
        raise ConfigError('Use MP4/MOV/MKV/WebM video or static PNG/JPEG/WebP frames')
    if source.stat().st_size > 2*1024*1024*1024:
        raise ConfigError('Local GIF source exceeds 2 GB')
    folder = within(root, 'assets/local-gif-sources', exists=False)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='snapshot-', dir=folder) as temporary:
        staged = Path(temporary)/('source'+source.suffix.lower())
        shutil.copyfile(source, staged)
        sha = digest(staged)
        if digest(source) != sha:
            raise ConfigError('Source changed during snapshot; no plan was changed')
        if kind == 'image':
            if probe_image(staged)['animated']:
                raise ConfigError('Frame GIF sources must be static images')
            _frame_shape(staged)
        else:
            _probe_video(staged)
        _decode(staged)
        destination = folder/(sha+source.suffix.lower())
        if destination.exists():
            if digest(destination) != sha:
                raise ConfigError('Existing local GIF snapshot was modified; preserve and repair it')
        else:
            staged.replace(destination)
    return {'path': destination.relative_to(root).as_posix(), 'sha256': sha, 'kind': kind}


def _convert(root, identity, recipe, previous=None):
    paths = sources(root, recipe)
    if recipe['kind'] == 'video-to-gif':
        actual = _probe_video(paths[0])
        if recipe['start'] + recipe['duration'] > actual['duration'] + .001:
            raise ConfigError('GIF interval extends beyond the actual source video')
    else:
        if len({_frame_shape(path) for path in paths})!=1:
            raise ConfigError('Ordered GIF frames must have matching actual dimensions')
    output_id = 'local-gif-'+uuid.uuid4().hex
    options = {key: recipe[key] for key in ('fps', 'width', 'loop')}
    if recipe['kind'] == 'video-to-gif':
        result = export_video_to_gif(root, source=paths[0], job_id=output_id,
            start=recipe['start'], duration=recipe['duration'], **options)
    else:
        result = export_frames_to_gif(root, frames=paths, job_id=output_id, **options)
    artifact = result['artifact']
    path = within(root, artifact['path'])
    if not artifact['animated']:
        raise ConfigError('Conversion produced only one frame; use a longer interval or more frames')
    _decode(path)
    # Recheck all inputs after encoding so source edits cannot certify another recipe.
    sources(root, recipe)
    manifest = {'schema_version': 1, 'kind': 'local-gif-derivation', 'gif_id': identity,
        'recipe': recipe, 'recipe_hash': content_hash(recipe), 'artifact': artifact,
        'created_at': time.time_ns(), 'previous_derivation': previous,
        'status': 'review_pending', 'paid_creates': 0}
    target = path.with_suffix('.gif.json')
    atomic_json(target, manifest)
    return {'id': identity, 'recipe': recipe,
        'derivation': {'path': target.relative_to(root).as_posix(), 'sha256': digest(target)}}


def build(root, *, gif_id, source=None, frames=None, start=0, duration=3, fps=15, width=480, loop=0, rebuild=False):
    root = Path(root).resolve()
    _identity(gif_id)
    bundle = load_project(root)
    if bundle['brief'].get('workflow_profile') not in {'gif-only', 'gif-local'}:
        raise ConfigError('Local GIF conversion requires a gif-only or gif-local project')
    target = within(root, bundle['project'].get('files', {}).get('generation-plan', 'generation-plan.json'))
    original = target.read_bytes()
    entries = bundle['generation-plan'].get('local_gifs', [])
    prior = next((v for v in entries if v['id'] == gif_id), None)
    if rebuild:
        if not prior or source is not None or frames is not None:
            raise ConfigError('Rebuild selects one registered --gif; it reads its saved source snapshots')
        recipe = copy.deepcopy(prior['recipe'])
    else:
        if prior or any(j['id'] == gif_id for j in bundle['generation-plan'].get('image_jobs', [])):
            raise ConfigError('GIF ID already exists; use a new ID or explicitly gif-rebuild')
        if (source is None) == (frames is None):
            raise ConfigError('Choose exactly one video source or an ordered frame list')
        if frames is not None and (not frames or len(frames) > 1800):
            raise ConfigError('Supply 1–1800 ordered frames')
        recipe = {'kind': 'video-to-gif' if source is not None else 'frames-to-gif',
            'sources': [_snapshot(root, source, 'video')] if source is not None else [_snapshot(root, p, 'image') for p in frames],
            'start': start if source is not None else 0,
            'duration': duration if source is not None else len(frames)/fps if fps else 0,
            'fps': fps, 'width': width, 'loop': loop}
    if gif_id in read_state(root)['jobs']:
        raise ConfigError('Local GIF ID conflicts with a saved provider task')
    item = _convert(root, gif_id, recipe, prior['derivation'] if prior else None)
    with state_lock(root):
        current = load_project(root)
        current_target=within(root,current['project'].get('files',{}).get('generation-plan','generation-plan.json'))
        if (current_target!=target or target.read_bytes() != original
                or current['brief'].get('workflow_profile') != bundle['brief'].get('workflow_profile')):
            raise ConfigError('Project changed during conversion; output is preserved but was not registered: '+item['derivation']['path'])
        if gif_id in read_state(root)['jobs']:
            raise ConfigError('Local GIF ID now conflicts with a saved provider task; output was not registered')
        candidate = copy.deepcopy(current)
        candidate['generation-plan']['local_gifs'] = [item if v['id'] == gif_id else v for v in entries] if prior else [*entries, item]
        check = validate_plan(candidate, root)
        if not check['ok']:
            raise ConfigError('; '.join(check['errors']))
        backup = root/'production/backups'/('gif-'+content_hash(bundle['generation-plan'])+'.json')
        atomic_json(backup, bundle['generation-plan'])
        atomic_json(target, candidate['generation-plan'])
    return {'ok': True, 'gif': item, 'backup': str(backup), 'status': 'review_pending',
        'source_unchanged': True, 'full_decode_verified': True, 'paid_creates': 0}


def _receipts(root, item, media):
    result = []
    for path in (root/'reviews/local-gifs').glob('*.json'):
        try:
            value = load_json(path)
        except (ConfigError, OSError, ValueError):
            continue
        if (value.get('schema_version') == 1 and value.get('gif_id') == item['id']
                and value.get('artifact_sha256') == media['sha256']
                and isinstance(value.get('reviewer_id'),str) and value['reviewer_id'].strip()
                and isinstance(value.get('observation'),str) and value['observation'].strip() and value.get('temporal_observation') is True
                and value.get('status') in {'pass', 'fail'}):
            result.append(value)
    if any(v['status'] == 'fail' for v in result):
        return 'rejected'
    if any(v.get('derivation') == item['derivation'] and v.get('recipe_hash') == content_hash(item['recipe']) for v in result):
        return 'reviewed'
    return 'unverified'


def rows(root, bundle):
    result = []
    for item in bundle['generation-plan'].get('local_gifs', []):
        row = {'gif_id': item['id'], 'kind': 'local-gif', 'status': 'stale', 'content_status': 'unverified',
            'recipe_hash': content_hash(item['recipe']), 'recipe': item['recipe'], 'derivation': item['derivation'], 'error': ''}
        try:
            _identity(item['id'])
            sources(root, item['recipe'])
            path = within(root, item['derivation']['path'])
            if digest(path) != item['derivation']['sha256']:
                raise ConfigError('Local GIF derivation manifest changed')
            manifest = load_json(path)
            if (manifest.get('schema_version') != 1 or manifest.get('kind') != 'local-gif-derivation'
                    or manifest.get('gif_id') != item['id'] or manifest.get('recipe') != item['recipe']
                    or manifest.get('recipe_hash') != row['recipe_hash']):
                raise ConfigError('Local GIF recipe changed; explicitly rebuild the selected GIF')
            artifact = manifest['artifact']
            media = probe_image(within(root, artifact['path']))
            if media['sha256'] != artifact['sha256'] or media['format'] != 'gif' or not media['animated']:
                raise ConfigError('Local GIF output changed or is not animated')
            row.update(status='completed', artifact=artifact, media=media, content_status=_receipts(root, item, media))
        except (ConfigError, KeyError, OSError, ValueError) as exc:
            row['error'] = str(exc)
        result.append(row)
    return result


def review(root, *, gif_id, status, reviewer_id, observation, temporal_observation=False):
    if status not in {'pass', 'fail'} or not reviewer_id.strip() or not observation.strip() or temporal_observation is not True:
        raise ConfigError('Local GIF review needs pass/fail, reviewer, observation and full playback --temporal-observation')
    root = Path(root).resolve()
    with state_lock(root):
        bundle = load_project(root)
        if bundle['brief'].get('workflow_profile') not in {'gif-only', 'gif-local'}:
            raise ConfigError('Local GIF review requires a GIF collection project')
        row = next((r for r in rows(root, bundle) if r['gif_id'] == gif_id), None)
        if not row or row['status'] != 'completed':
            raise ConfigError('Local GIF is missing or stale; restore it or explicitly rebuild before review')
        receipt = {'schema_version': 1, 'gif_id': gif_id, 'status': status, 'reviewer_id': reviewer_id,
            'observation': observation, 'temporal_observation': True, 'reviewed_at': time.time_ns(),
            'artifact_sha256': row['media']['sha256'], 'recipe_hash': row['recipe_hash'], 'derivation': row['derivation']}
        target = root/'reviews/local-gifs'/(uuid.uuid4().hex+'.json')
        atomic_json(target, receipt)
    return {'ok': True, 'gif_id': gif_id, 'status': 'rejected' if status == 'fail' or row['content_status'] == 'rejected' else 'reviewed',
        'receipt': target.relative_to(root).as_posix(), 'paid_creates': 0}
