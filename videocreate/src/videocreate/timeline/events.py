"""Project authored action or beat intervals through the actual edit decisions."""
import json
import shutil
import subprocess
from pathlib import Path

from ..config.storage import ConfigError, load_json
from ..media_references import digest
from ..planning.project import content_hash, within
from ..runtime.candidates import selected
from ..runtime.state import read_state
from .model import mapping, number, source_to_timeline


def _clock(root, record, kind):
    if (not isinstance(record, dict) or set(record) != {'path', 'sha256'}
            or not isinstance(record['path'], str)):
        raise ConfigError('Each reference clock needs a project path and SHA-256')
    path = within(root, record['path'])
    if digest(path) != record['sha256']:
        raise ConfigError('Event reference bytes changed: ' + record['path'])
    executable = shutil.which('ffprobe')
    if not executable:
        raise ConfigError('FFprobe is required to read event reference clocks')
    args = [executable, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]
    try:
        output = subprocess.run(args, check=True, capture_output=True, timeout=60)
        media = json.loads(output.stdout)
        stream = next(s for s in media['streams'] if s['codec_type'] == kind
                      and not s.get('disposition', {}).get('attached_pic'))
        # A container may include a longer soundtrack or picture stream.
        duration = stream.get('duration')
        if duration in (None, 'N/A') and len(media['streams']) == 1:
            duration = media['format']['duration']
        duration = float(duration)
        if not number(duration) or duration <= 0:
            raise ValueError
    except (KeyError, StopIteration, TypeError, ValueError, subprocess.SubprocessError):
        raise ConfigError('Cannot measure the ' + kind + ' reference interval: ' + record['path']) from None
    return {**record, 'duration_seconds': duration}


def _window(event, name, duration):
    interval = event.get(name)
    if (not isinstance(interval, list) or len(interval) != 2 or not all(number(v) for v in interval)
            or not 0 <= interval[0] < interval[1] <= duration):
        raise ConfigError(event['id'] + ': invalid ' + name + ' interval')
    return interval


def _project_window(retained, target, reference):
    """Linearly interpolate only inside one explicitly authored event."""
    scale = (reference[1] - reference[0]) / (target[1] - target[0])
    return [reference[0] + (point - target[0]) * scale for point in retained]


def _audio_alignment(row, track, duration, tolerance):
    if track.get('loop') and track['source_out'] > duration:
        return {'track_id': track['id'], 'status': 'loop-needs-playback'}
    left, right = row['audio']
    if left < track['source_in'] or right > track['source_out']:
        return {'track_id': track['id'], 'status': 'outside-retained-audio-window'}
    final = [track['timeline_start'] + (t - track['source_in']) for t in (left, right)]
    offsets = [t - a for t, a in zip(row['timeline'], final)]
    fits = all(abs(delta) <= tolerance + 1e-9 for delta in offsets)
    return {'track_id': track['id'], 'timeline': final, 'picture_minus_audio_seconds': offsets,
            'status': 'within-planned-tolerance' if fits else 'outside-planned-tolerance'}


def _occurrences(segments, target, source, audio, tolerance, track, audio_duration):
    rows = []
    for segment in segments:
        kept = [max(target[0], segment['source_in']), min(target[1], segment['source_out'])]
        if kept[0] >= kept[1]:
            continue
        row = {'segment_id': segment['id'], 'clip_id': segment['clip_id'], 'target': kept,
               'source': _project_window(kept, target, source),
               'timeline': [source_to_timeline(segment, t) for t in kept],
               'rate': segment.get('rate', 1), 'cut_reason': segment['cut_reason'],
               'partially_retained': kept != target}
        if audio is not None:
            row['audio'] = _project_window(kept, target, audio)
            if track:
                row['audio_alignment'] = _audio_alignment(row, track, audio_duration, tolerance)
        playback_seconds = row['timeline'][1] - row['timeline'][0]
        row['duration_delta_seconds'] = {key: playback_seconds - (row[key][1] - row[key][0])
                                         for key in ('source', 'audio') if key in row}
        row['within_duration_tolerance'] = all(abs(delta) <= tolerance + 1e-9
                                              for delta in row['duration_delta_seconds'].values())
        rows.append(row)
    return rows


def _target_clock(root, bundle, job_id, *, planned=False):
    generation = bundle['generation-plan']
    local = next((s for s in generation.get('local_sources', []) if s['id'] == job_id), None)
    job = next((j for j in generation['jobs'] if j['id'] == job_id), None)
    if local and local.get('kind', 'video') != 'image':
        media = _clock(root, {k: local[k] for k in ('path', 'sha256')}, 'video')
        return {**media, 'basis': 'registered-local-video'}
    if not job:
        raise ConfigError('Choose an existing video generation job or registered video source')
    current = {} if planned else selected(read_state(root)['jobs'].get(job_id, {}))
    if current.get('status') == 'completed':
        artifact = current.get('artifact', {})
        media = _clock(root, {k: artifact.get(k) for k in ('path', 'sha256')}, 'video')
        return {**media, 'basis': 'selected-candidate'}
    return {'duration_seconds': job['seconds'], 'basis': 'planned-job'}


def attached_event_map(root, bundle, job):
    pointer = job['event_map']
    if (not isinstance(pointer, dict) or set(pointer) != {'path', 'sha256'}
            or not isinstance(pointer['path'], str) or not isinstance(pointer['sha256'], str)):
        raise ConfigError('Attach the event map with its project path and SHA-256')
    path = within(root, pointer['path'])
    if digest(path) != pointer['sha256']:
        raise ConfigError('Job event map bytes changed: ' + job['id'])
    spec = load_json(path)
    if not isinstance(spec, dict) or spec.get('target_job') != job['id']:
        raise ConfigError('The event map must target its own video job: ' + job['id'])
    return event_map(root, bundle, spec, planned=True)


def _source_profile(root, spec, source):
    pointer = spec.get('source_profile')
    if (not isinstance(pointer, dict) or set(pointer) != {'path', 'sha256'}
            or not isinstance(pointer['path'], str) or not isinstance(pointer['sha256'], str)):
        raise ConfigError('Event map version 2 requires a source profile path and SHA-256')
    path = within(root, pointer['path'])
    if digest(path) != pointer['sha256']:
        raise ConfigError('Source event profile bytes changed')
    from ..references import validate_profile
    errors = validate_profile(path)
    if errors:
        raise ConfigError('; '.join(errors))
    profile = load_json(path)
    if profile['schema_version'] != 2 or profile['source']['sha256'] != source['sha256']:
        raise ConfigError('Choose the event profile for the same original source video')
    return {**profile, 'evidence':[{**item,'path':(path.parent/item['path']).resolve().relative_to(Path(root).resolve()).as_posix()}
                                    for item in profile.get('evidence', [])]}


def _source_coverage(profile, events, changes):
    from ..production_metrics import union_seconds
    source_events = {e['id']: e for e in profile['events']}
    if (not isinstance(changes, dict) or set(changes) - source_events.keys()
            or any(not isinstance(note, str) or not note.strip() for note in changes.values())):
        raise ConfigError('Explain source event changes using known event IDs and nonempty reasons')
    rows = []
    missing = []
    for eid, event in source_events.items():
        retained = [row['source'] for target in events if target.get('source_event_id') == eid
                    for row in target['occurrences']]
        seconds = union_seconds(retained)
        complete = seconds >= event['end'] - event['start'] - 1e-9
        if event.get('must_preserve') and not complete and eid not in changes:
            missing.append(eid)
        rows.append({'source_event_id': eid, 'must_preserve': event.get('must_preserve', False),
                     'retained_source_seconds': seconds, 'fully_retained': complete,
                     **({'change_reason': changes[eid]} if eid in changes else {})})
    issues = ['Required source events need retained coverage or an explicit change reason: ' + ', '.join(missing)] if missing else []
    return rows, issues


def event_map(root, bundle, spec, *, planned=False):
    fields = {'schema_version', 'source', 'audio', 'audio_track_id', 'target_job', 'tolerance_seconds', 'events'}
    version = spec.get('schema_version') if isinstance(spec, dict) else None
    if version == 2:
        fields.update({'source_profile', 'source_event_changes'})
    if (not isinstance(spec, dict) or set(spec) - fields or type(version) is not int
            or version not in {1, 2} or not isinstance(spec.get('events'), list) or not spec['events']):
        raise ConfigError('Use event map schema version 1 or 2 with a nonempty events array')
    tolerance = spec.get('tolerance_seconds')
    if not number(tolerance) or tolerance < 0:
        raise ConfigError('Specify a finite nonnegative timing tolerance in seconds')
    job_id = spec.get('target_job')
    if not isinstance(job_id, str) or not job_id:
        raise ConfigError('Specify the target video job or local source ID')
    target_clock = _target_clock(root, bundle, job_id, planned=planned)
    timeline = bundle['timeline']
    clip_ids = set()
    replaced_clips = []
    for clip in timeline['clips']:
        if clip.get('job_id') != job_id:
            continue
        if clip.get('path') and digest(within(root, clip['path'])) != target_clock.get('sha256'):
            replaced_clips.append(clip['id'])
        else:
            clip_ids.add(clip['id'])
    edit = mapping(timeline)
    segments = [s for s in edit['segments'] if s['clip_id'] in clip_ids]
    source = _clock(root, spec.get('source'), 'video')
    profile = _source_profile(root, spec, source) if version == 2 else None
    source_events = {e['id']: e for e in profile['events']} if profile else {}
    audio = _clock(root, spec['audio'], 'audio') if 'audio' in spec else None
    track = None
    if 'audio_track_id' in spec:
        track = next((t for t in edit['audio_tracks'] if t['id'] == spec['audio_track_id']), None)
        if not track or not audio:
            raise ConfigError('Choose the existing audio track and reference audio for the alignment check')
        if track.get('clip_id'):
            clip = next(c for c in timeline['clips'] if c['id'] == track['clip_id'])
            path = clip.get('path') or _target_clock(root, bundle, clip['job_id']).get('path')
        else:
            path = track['path']
        if not path or digest(within(root, path)) != audio['sha256']:
            raise ConfigError('The selected audio track must use the reference audio bytes')
    events = []
    ids = set()
    for event in spec['events']:
        allowed = {'id', 'reason', 'source', 'audio', 'target'}
        if version == 2:
            allowed.add('source_event_id')
        if (not isinstance(event, dict) or set(event) - allowed
                or not isinstance(event.get('id'), str) or not event['id'].strip() or event['id'] in ids
                or not isinstance(event.get('reason'), str) or not event['reason'].strip()):
            raise ConfigError('Each event needs a unique ID and its timing or edit reason')
        ids.add(event['id'])
        if ('audio' in event) and not audio:
            raise ConfigError(event['id'] + ': supply the reference audio file for this interval')
        if 'source_event_id' in event:
            eid = event['source_event_id']
            if not isinstance(eid, str) or eid not in source_events:
                raise ConfigError(event['id'] + ': unknown source event')
            original = source_events[eid]
            event = {**event, 'source': event.get('source', [original['start'], original['end']])}
            source_window = _window(event, 'source', source['duration_seconds'])
            if not original['start'] <= source_window[0] < source_window[1] <= original['end']:
                raise ConfigError(event['id'] + ': mapped interval lies outside the original source event')
        source_window = _window(event, 'source', source['duration_seconds'])
        target = _window(event, 'target', target_clock['duration_seconds'])
        audio_window = _window(event, 'audio', audio['duration_seconds']) if 'audio' in event else None
        occurrences = _occurrences(segments, target, source_window, audio_window, tolerance, track,
                                   audio['duration_seconds'] if audio else None)
        events.append({**event, 'occurrences': occurrences,
                       'edit_status': 'used' if occurrences else 'omitted',
                       'sync_verification': 'requires-playback' if occurrences else 'not-in-final-edit'})
    evidence = {}
    if profile:
        retained, issues = _source_coverage(profile, events, spec.get('source_event_changes', {}))
        evidence = {'source_profile': {**spec['source_profile'], 'profile_hash': profile['profile_hash'],
                    'participants': profile['participants'], 'events': profile['events'],
                    'evidence': profile.get('evidence', []), 'event_coverage': profile['event_coverage']},
                    'source_event_coverage': retained, 'source_event_issues': issues}
    return {'schema_version': version, 'source': source, 'audio': audio, 'target_job': job_id, **evidence,
            'target_clock': target_clock, 'unmatched_path_clips': replaced_clips,
            'tolerance_seconds': tolerance, 'events': events,
            'timeline_fps': edit['fps'], 'timeline_seconds': edit['duration'],
            'timeline_sha256': content_hash(timeline), 'spec_sha256': content_hash(spec),
            'verification': 'authored-timing', 'paid_creates': 0}
