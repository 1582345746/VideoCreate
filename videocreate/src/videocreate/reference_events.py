"""Source events reuse reference observation methods and retain unverified intervals."""
import hashlib
from pathlib import Path

from .config.schema import BOOL, STR, STRING_LIST, _walk, enum, obj
from .config.storage import ConfigError
from .planning.project import _index
from .production_metrics import union_seconds

CATEGORIES = {
    'hook': 'action', 'action': 'action', 'expression': 'subject', 'interaction': 'action',
    'camera': 'camera', 'edit': 'edit', 'dialogue': 'audio', 'sound': 'audio',
    'reversal': 'action', 'subject': 'subject',
}


def validate(report, document, *, evidence_root=None):
    number = {'type': 'number', 'minimum': 0}
    schema = obj({
        'participants': {'type': 'array', 'items': obj({'id': STR, 'description': STR}, ('id', 'description'))},
        'evidence': {'type':'array','items':obj({'id':STR,'path':STR,'sha256':STR,
            'source_sha256':STR,'at_seconds':number},('id','path','sha256','source_sha256','at_seconds'))},
        'events': {'type': 'array', 'minItems': 1, 'items': obj({
            'id': STR, 'category': enum(*CATEGORIES), 'start': number, 'end': number,
            'notes': STR, 'participants': STRING_LIST, 'status': enum('unverified', 'observed', 'inferred'),
            'method': enum('frames', 'human-video', 'model-audio-video', 'human-listening', 'asr', 'ocr'),
            'frame_ids': STRING_LIST, 'evidence_ids': STRING_LIST, 'transcript': STR, 'must_preserve': BOOL,
        }, ('id', 'category', 'start', 'end', 'notes', 'participants', 'status'))},
    }, ('participants', 'events'))
    value = {key: document.get(key, [] if key == 'evidence' else None) for key in ('participants', 'evidence', 'events')}
    errors = []
    _walk(value, schema, '$source_events', errors)
    if errors:
        raise ConfigError('; '.join(errors))
    participants = _index(value['participants'], 'Source participants', errors)
    evidence = _index(value['evidence'], 'Source event evidence', errors)
    _index(value['events'], 'Source events', errors)
    if errors:
        raise ConfigError('; '.join(errors))
    if any(not p['description'].strip() for p in participants.values()):
        raise ConfigError('Give each source participant a description')
    reviewer = document.get('reviewer_id')
    if any(e['status'] != 'unverified' for e in value['events']) and (
            not isinstance(reviewer, str) or not reviewer.strip()):
        raise ConfigError('Observed or inferred source events require a reviewer_id')
    duration = report['media']['duration_seconds']
    frames = {f['id']: f for f in report['frames']}
    external_frames = {}
    frame_times = {identity:frame['at_seconds'] for identity,frame in frames.items()}
    for identity, item in evidence.items():
        if (not 0 <= item['at_seconds'] <= duration or item['source_sha256'] != report['source']['sha256']
                or not evidence_root):
            raise ConfigError(identity + ': source frame evidence must name the analyzed video and a valid time')
        folder = Path(evidence_root).resolve()
        path = (folder/item['path']).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ConfigError(identity + ': source frame evidence bytes or project path changed')
        frame_times[identity] = item['at_seconds']
        external_frames[identity] = {'id':identity,'at_seconds':item['at_seconds']}
    from .references import _validate_observations
    for event in value['events']:
        if not 0 <= event['start'] < event['end'] <= duration or not event['notes'].strip():
            raise ConfigError(event['id'] + ': give the event a valid source interval and description')
        if set(event['participants']) - participants.keys():
            raise ConfigError(event['id'] + ': unknown source participant')
        if len(set(event['participants'])) != len(event['participants']):
            raise ConfigError(event['id'] + ': source participants must be unique')
        if 'transcript' in event and event['category'] != 'dialogue':
            raise ConfigError(event['id'] + ': transcripts belong to dialogue events')
        cited = [*event.get('frame_ids', []), *event.get('evidence_ids', [])]
        for fid in cited:
            if fid not in frame_times or not event['start'] <= frame_times[fid] <= event['end']:
                raise ConfigError(event['id'] + ': frame evidence is outside the event interval')
        if event['status'] == 'observed':
            observation = {**event, 'category': CATEGORIES[event['category']]}
            observation['frame_ids'] = [*event.get('frame_ids', []), *event.get('evidence_ids', [])]
            _validate_observations({**report,'frames':[*report['frames'],*external_frames.values()]},
                                   {'reviewer_id': reviewer, 'observations': [observation]})
            if observation['category'] == 'audio' and not report['media']['has_audio']:
                raise ConfigError(event['id'] + ': this source has no audio stream to observe')
    return value


def _uncovered(windows, duration):
    cursor = 0
    gaps = []
    for start, end in sorted(windows):
        if start > cursor:
            gaps.append([cursor, start])
        cursor = max(cursor, end)
    if cursor < duration:
        gaps.append([cursor, duration])
    return gaps


def coverage(report, events):
    duration = report['media']['duration_seconds']
    result = {'source_seconds': duration, 'declared_event_seconds': union_seconds(
        [[e['start'], e['end']] for e in events])}
    for domain, categories, methods in (
            ('temporal', set(CATEGORIES) - {'dialogue', 'sound'}, {'human-video', 'model-audio-video'}),
            ('audio', {'dialogue', 'sound'}, {'human-listening', 'model-audio-video'})):
        windows = [[e['start'], e['end']] for e in events if e['status'] == 'observed'
                   and e['category'] in categories and e.get('method') in methods]
        result[domain] = {'observed_event_seconds': union_seconds(windows),
                          'unverified_intervals': _uncovered(windows, duration)}
    return result


def template(report):
    return {'reviewer_id': '', 'observations': [], 'participants': [],
            'events': [{'id': 'event-001', 'category': 'action', 'start': 0,
                        'end': report['media']['duration_seconds'], 'participants': [],
                        'notes': '待逐段登记原片事件。', 'status': 'unverified', 'must_preserve': False}]}
