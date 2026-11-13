"""Explicit local video and static-image sources; no provider tasks."""
from __future__ import annotations

import copy
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config.storage import ConfigError, atomic_json
from .planning.project import content_hash, load_project, validate_plan, within
from .runtime.state import read_state, state_lock
from .timeline.render import probe


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def verify_source(root, source):
    path = within(Path(root).resolve(), source['path'])
    if digest(path) != source['sha256']:
        raise ConfigError('Registered local source bytes changed; restore the original or import a new source ID')
    if source['kind'] == 'image':
        from .still_images import inspect
        if inspect(path) != source['media']:
            raise ConfigError('Local image metadata differs from actual static media')
        return path
    if any(key not in source['media'] for key in ('width', 'height', 'has_audio', 'fps', 'duration')):
        raise ConfigError('Video source metadata requires dimensions, audio, duration and fps')
    actual = _probe_video(path)
    for key in ('width', 'height', 'has_audio', 'fps'):
        if actual[key] != source['media'][key]:
            raise ConfigError('Local source metadata differs from actual media: ' + key)
    if abs(actual['duration'] - source['media']['duration']) > .001:
        raise ConfigError('Local source duration differs from actual media')
    return path


def _probe_video(path):
    try:
        media = probe(path)
        if not math.isfinite(media['duration']) or media['duration'] <= 0:
            raise ValueError('Invalid video duration')
        return media
    except (subprocess.CalledProcessError, KeyError, ValueError):
        raise ConfigError('Local source could not be probed as a video; no plan was changed') from None


def _restore_bytes(path, raw):
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.rollback-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def import_clip(root, source, *, source_id, start=0, end=None, description='', preserve_audio=True, shot_id=None):
    return _import(root, source, source_id=source_id, start=start, end=end,
        description=description, preserve_audio=preserve_audio, shot_id=shot_id, kind='video')


def import_image(root, source, *, source_id, seconds=3, description='', shot_id=None):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise ConfigError('Static image hold seconds must be finite and positive')
    return _import(root, source, source_id=source_id, start=0, end=seconds,
        description=description, preserve_audio=False, shot_id=shot_id, kind='image')


def _import(root, source, *, source_id, start, end, description, preserve_audio, shot_id, kind):
    root, source = Path(root).resolve(), Path(source).resolve()
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,47}', source_id):
        raise ConfigError('Local source ID needs 1–48 ASCII letters, digits, dots, underscores or hyphens')
    if source_id == 'final':
        raise ConfigError('Local source ID final is reserved for the final edit review')
    extensions = {'.png', '.jpg', '.jpeg', '.webp'} if kind == 'image' else {'.mp4', '.mov', '.mkv', '.webm'}
    if not source.is_file() or source.suffix.lower() not in extensions:
        raise ConfigError('Import requires an existing static PNG/JPEG/WebP' if kind == 'image' else 'Import requires an existing MP4/MOV/MKV/WebM video')
    if not isinstance(preserve_audio, bool):
        raise ConfigError('preserve_audio must be boolean')
    if not isinstance(description, str):
        raise ConfigError('Source description must be text')
    initial = load_project(root)
    if not import_allowed(initial):
        raise ConfigError('Local imports require edit-only (zero generation jobs) or mixed-video')
    if shot_id is not None and (not isinstance(shot_id,str) or not shot_id.strip()):
        raise ConfigError('An existing shot ID must be nonempty text')
    if shot_id is not None and initial['brief'].get('workflow_profile')!='mixed-video':
        raise ConfigError('Existing-shot mapping requires mixed-video')
    if shot_id is not None and description.strip():
        raise ConfigError('description applies to new shots; edit an existing shot in the director layer')
    # Validate real media before the project edit. Keep the original file intact.
    ffmpeg = shutil.which('ffmpeg')
    if kind == 'video' and not ffmpeg:
        raise ConfigError('FFmpeg is required for source decoding; no automatic download was attempted')
    folder = within(root, 'assets/local-sources', exists=False)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='import-', dir=folder) as temporary:
        staged = Path(temporary) / ('source' + source.suffix.lower())
        shutil.copyfile(source, staged)
        sha = digest(staged)
        if kind == 'image':
            from .still_images import inspect
            media = inspect(staged)
        else:
            media = _probe_video(staged)
        if digest(source) != sha:
            raise ConfigError('Source changed during import; no plan was changed')
        selected_end = media['duration'] if end is None else end
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in (start, selected_end)) or not 0 <= start < selected_end or
                kind == 'video' and selected_end > media['duration']):
            raise ConfigError('Retained interval must be finite and inside the actual source duration')
        if kind == 'video':
            decoded = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(staged),
                                      '-f', 'null', '-'], capture_output=True)
            if decoded.returncode:
                raise ConfigError('Local source did not fully decode; no plan was changed')
        destination = folder / (sha + source.suffix.lower())
        sid, cid, segment_id = shot_id or 'shot-' + source_id, 'clip-' + source_id, 'seg-' + source_id
        item = {'id':source_id,'kind':kind,'path':destination.relative_to(root).as_posix(),
                'sha256':sha,'shot_ids':[sid],'media':media}
        with state_lock(root):
            bundle = load_project(root)
            if not import_allowed(bundle):
                raise ConfigError('Local imports require edit-only (zero generation jobs) or mixed-video')
            if source_id in read_state(root)['jobs']:
                raise ConfigError('Local source ID conflicts with a saved task; use a different source ID')
            if any(s['id']==source_id for s in bundle['generation-plan'].get('local_sources', [])):
                raise ConfigError('Local source ID already exists; edit its retained timeline window instead of reimporting')
            if shot_id is not None:
                if bundle['brief'].get('workflow_profile')!='mixed-video':
                    raise ConfigError('Existing-shot mapping requires mixed-video')
                if sum(s['id']==sid for s in bundle['director']['shots'])!=1:
                    raise ConfigError('Existing-shot mapping needs one authored shot with that exact ID')
                if any(sid in j['shot_ids'] for j in bundle['generation-plan']['jobs']):
                    raise ConfigError('Existing shot is already covered by a generation job; no task was replaced')
                if any(sid in s['shot_ids'] for s in bundle['generation-plan'].get('local_sources',[])):
                    raise ConfigError('Existing shot already has a local source; no source was replaced')
                if any(s['shot_id']==sid for s in bundle['timeline']['segments']):
                    raise ConfigError('Existing shot already has a timeline segment; no edit was replaced')
            elif any(s['id']==sid for s in bundle['director']['shots']):
                raise ConfigError('Imported shot ID already exists; use --shot-id for an uncovered authored shot')
            if any(c['id']==cid for c in bundle['timeline']['clips']) or any(s['id']==segment_id for s in bundle['timeline']['segments']):
                raise ConfigError('Imported shot/clip ID already exists')
            if destination.exists():
                if digest(destination) != sha:
                    raise ConfigError('Existing content-addressed local source was modified; preserve and repair it')
            else:
                staged.replace(destination)
            candidate = copy.deepcopy(bundle)
            candidate['generation-plan'].setdefault('local_sources', []).append(item)
            if shot_id is None and not any(s['id']=='local-edit' for s in candidate['director']['scenes']):
                candidate['director']['scenes'].append({'id':'local-edit',
                    'map':'Existing footage; inspect actual geography before continuity approval',
                    'axis':'Existing camera axes; continuity must be checked in playback'})
            if shot_id is None:
                candidate['director']['shots'].append({'id':sid,'scene_id':'local-edit','role':'source',
                    'information_goal':description.strip() or ('Hold the static image ' if kind == 'image' else 'Retain the selected interval from local source ') + source_id,
                    'framing':'Existing source framing; inspect actual footage',
                    'actions':[{'kind':'hold','description':'Hold the static image; no generated motion' if kind == 'image' else 'Use existing footage within the chosen source interval; no new generation'}],
                    'planned_seconds':selected_end if kind == 'image' else media['duration'],'cut_motivation':'Cut at the selected source boundary',
                    'asset_ids':[],'audio':{'mode':'ambience' if preserve_audio and media['has_audio'] else 'mute'}})
            candidate['timeline']['clips'].append({'id':cid,'job_id':source_id,'path':item['path']})
            candidate['timeline']['segments'].append({'id':segment_id,'shot_id':sid,'clip_id':cid,
                'source_in':start,'source_out':selected_end,'rate':1,
                'source_audio':'retime' if preserve_audio and media['has_audio'] else 'mute',
                'cut_reason':'Hold the static image for the authored interval' if kind == 'image' else 'Retain the explicitly selected interval from imported footage'})
            checked = validate_plan(candidate, root)
            if not checked['ok']:
                raise ConfigError('; '.join(checked['errors']))
            layers = ('director', 'generation-plan', 'timeline')
            targets = {name:within(root, bundle['project'].get('files',{}).get(name,name+'.json')) for name in layers}
            originals = {name:path.read_bytes() for name,path in targets.items()}
            backup = root/'production/backups'/('import-'+content_hash({k:bundle[k] for k in layers})+'.json')
            atomic_json(backup, {k:bundle[k] for k in layers})
            try:
                for name in layers:
                    atomic_json(targets[name], candidate[name])
            except OSError:
                failed = []
                for name in layers:
                    try:
                        if targets[name].read_bytes() != originals[name]:
                            _restore_bytes(targets[name], originals[name])
                    except OSError:
                        failed.append(name)
                if failed:
                    raise ConfigError('Import save and rollback failed for '+', '.join(failed)+'; restore layers from '+str(backup)) from None
                raise
    return {'ok':True,'source':item,'segment_id':segment_id,'retained_seconds':selected_end-start,
        'source_unchanged':True,'full_decode_verified':True,'backup':str(backup),'paid_creates':0,
        'note':'Imported images/footage remain unreviewed. This creates no task, budget entry or model request.'}


def import_allowed(bundle):
    profile=bundle['brief'].get('workflow_profile')
    return profile=='mixed-video' or profile=='edit-only' and not bundle['generation-plan']['jobs']
