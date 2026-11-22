"""Hash-bound, event-level comparison of a motion source and a candidate."""
import json
import math
import os
import re
from pathlib import Path
from urllib.parse import quote

from ..asset_library import digest, project_media_revision
from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash, within
from ..runtime.state import state_lock
from ..timeline.render import probe


def _interval(value, duration):
    return (isinstance(value, list) and len(value) == 2
            and all(type(t) in (int, float) and math.isfinite(t) for t in value)
            and 0 <= value[0] < value[1] <= duration)


def _visual_references(root, bundle, asset_ids):
    if not isinstance(asset_ids, list) or not all(isinstance(a, str) for a in asset_ids):
        raise ConfigError('Comparison asset_ids must be project asset identifiers')
    cards = {a['id']: a for a in bundle['director']['assets']}
    references = []
    for aid in dict.fromkeys(asset_ids):
        card = cards.get(aid)
        if not card or card['kind'] == 'voice' or not card.get('references'):
            raise ConfigError('Comparison requires an existing visual card with reference media')
        for name in card['references']:
            sha = digest(within(root, name))
            references.append({'asset_id': aid, 'path': name, 'sha256': sha,
                               'revision': project_media_revision(root, name, sha)})
    return references


def _final_comparison(root, bundle, spec, output_name):
    from ..timeline.events import event_map
    from .receipts import contracts
    timing = event_map(root, bundle, spec)
    final = contracts(root, bundle, output_name=output_name).get('final')
    if not final:
        raise ConfigError('Render the current final edit before comparing mapped events')
    delivery = final.get('audio_delivery')
    if delivery:
        timing['audio_delivery'] = delivery
        if 'audio_track_id' in spec:
            timing['reference_track_in_export'] = spec['audio_track_id'] in delivery['track_ids']
    events = []
    for index, event in enumerate(timing['events'], 1):
        for use, row in enumerate(event['occurrences'], 1):
            if not _interval(row['timeline'], final['duration'] + 1e-9):
                raise ConfigError('Mapped event extends beyond the current rendered edit: ' + event['id'])
            events.append({'id': f'event-{index}-use-{use}', 'label': event['id'] + ' · ' + row['segment_id'],
                           'source': row['source'], 'candidate': row['timeline'], 'target': row['target'],
                           **({'source_event_id': event['source_event_id']} if 'source_event_id' in event else {}),
                           'segment_id': row['segment_id'], 'reason': event['reason'], 'rate': row['rate'],
                           **{k: row[k] for k in ('audio', 'audio_alignment') if k in row}})
    if not events:
        raise ConfigError('The current edit retains no mapped events from this target')
    generation = bundle['generation-plan']
    target = next(s for s in [*generation['jobs'], *generation.get('local_sources', [])]
                  if s['id'] == timing['target_job'])
    cards = {a['id']: a for a in bundle['director']['assets']}
    selected = [aid for shot in bundle['director']['shots'] if shot['id'] in target['shot_ids']
                for aid in shot.get('asset_ids', [])]
    if set(selected) - cards.keys():
        raise ConfigError('The mapped target uses an unknown visual card')
    asset_ids = [aid for aid in selected if cards[aid]['kind'] != 'voice' and cards[aid].get('references')]
    references = _visual_references(root, bundle, asset_ids)
    source = timing['source']
    return {'schema_version': 1, 'source': {**source, 'media': probe(within(root, source['path']))},
            'candidate': {'path': final['path'], 'sha256': final['sha256'], 'media': probe(within(root, final['path']))},
            'review_scope': {'asset_id': 'final', 'contract_hash': final['contract_hash']},
            'visual_references': references, 'events': events, 'timing': timing,
            **({'source_events':timing['source_profile']['events'],
                'source_participants':timing['source_profile']['participants'],
                'source_event_coverage':timing['source_profile']['event_coverage'],
                'source_event_issues':timing['source_event_issues']}
               if timing.get('source_profile') else {})}


def comparison(root, bundle, spec, *, mapped=False, output_name='preview.mp4'):
    if mapped:
        return _final_comparison(root, bundle, spec, output_name)
    if not isinstance(spec, dict) or spec.get('schema_version') != 1:
        raise ConfigError('Use event comparison schema version 1')
    result = {'schema_version': 1}
    for key in ('source', 'candidate'):
        item = spec.get(key)
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ConfigError('Comparison needs a project-local path and SHA-256 for ' + key)
        path = within(root, item['path'])
        if digest(path) != item.get('sha256'):
            raise ConfigError('Comparison bytes changed for ' + key)
        result[key] = {'path': path.relative_to(root).as_posix(), 'sha256': item['sha256'], 'media': probe(path)}
    if 'review_asset_id' in spec:
        from .receipts import contracts
        aid = spec['review_asset_id']
        if not isinstance(aid, str) or not aid:
            raise ConfigError('Choose an existing review asset ID for this candidate')
        candidate = result['candidate']
        final = aid == 'final'
        output_name = Path(candidate['path']).name if final else 'preview.mp4'
        scope = contracts(root, bundle, output_name=output_name, include_final=final)
        asset = scope.get(aid)
        if not asset or asset['sha256'] != candidate['sha256']:
            raise ConfigError('The selected review asset must match the candidate bytes')
        result['review_scope'] = {'asset_id': aid, 'contract_hash': asset['contract_hash']}
    result['visual_references'] = _visual_references(root, bundle, spec.get('asset_ids', []))
    events = spec.get('events')
    if not isinstance(events, list) or not events:
        raise ConfigError('Comparison requires at least one event')
    seen = set()
    for event in events:
        if not isinstance(event, dict) or set(event) != {'id', 'label', 'source', 'candidate'}:
            raise ConfigError('Each event requires an ID, label, source interval and candidate interval')
        eid = event['id']
        if (not isinstance(eid, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', eid)
                or eid in seen or not isinstance(event['label'], str) or not event['label'].strip()):
            raise ConfigError('Event IDs must be unique and labels must be nonempty')
        seen.add(eid)
        for key in ('source', 'candidate'):
            if not _interval(event[key], result[key]['media']['duration']):
                raise ConfigError(eid + ': invalid ' + key + ' interval in media seconds')
    result['events'] = events
    return result


def export_comparison(root, bundle, spec, *, mapped=False, output_name='preview.mp4'):
    from ..cli import skill_root
    result = comparison(root, bundle, spec, mapped=mapped, output_name=output_name)
    fingerprint = content_hash(result)
    folder = within(root, 'reviews/comparisons/' + fingerprint, exists=False)
    folder.mkdir(parents=True, exist_ok=True)
    media = [result['source'], result['candidate'], *result['visual_references']]
    reference_audio = result.get('timing', {}).get('audio')
    if reference_audio:
        media.append(reference_audio)
    source_profile = result.get('timing', {}).get('source_profile', {})
    media.extend(source_profile.get('evidence', []))
    urls = {item['path']: quote(os.path.relpath(within(root, item['path']), folder).replace(os.sep, '/'), safe='/')
            for item in media}
    payload = {'comparison_hash': fingerprint, 'comparison': result, 'urls': urls}
    page = (skill_root() / 'assets' / 'event-comparison.html').read_text(encoding='utf-8')
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    html_path = folder/'index.html'
    with state_lock(root):
        record_path = folder/'comparison.json'
        if record_path.exists():
            if load_json(record_path) != result:
                raise ConfigError('Existing event comparison changed; keep each review immutable')
        else:
            atomic_json(record_path,result)
        if not html_path.exists():
            html_path.write_text(page.replace('__COMPARISON_DATA__', data), encoding='utf-8')
    return {'ok': True, 'page': str(html_path), 'comparison_hash': fingerprint,
            'candidate_has_audio_stream': result['candidate']['media']['has_audio'],
            'events': len(result['events']), 'paid_creates': 0}


def record_observations(root, bundle, spec, receipt, *, mapped=False, output_name='preview.mp4'):
    result = comparison(root, bundle, spec, mapped=mapped, output_name=output_name)
    fingerprint = content_hash(result)
    if (not isinstance(receipt, dict) or set(receipt) != {'schema_version', 'comparison_hash', 'reviewer', 'observations'}
            or receipt['schema_version'] != 1 or receipt['comparison_hash'] != fingerprint):
        raise ConfigError('Observations require the current comparison, media hashes and event map')
    if not isinstance(receipt['reviewer'], str) or not receipt['reviewer'].strip():
        raise ConfigError('Record who made these observations')
    rows = receipt['observations']
    if not isinstance(rows, dict) or set(rows) != {e['id'] for e in result['events']}:
        raise ConfigError('Include every event, keeping unobserved events unverified')
    for item in rows.values():
        if (not isinstance(item, dict) or set(item) != {'status', 'note'}
                or item['status'] not in ('unverified', 'pass', 'fail')
                or not isinstance(item['note'], str) or (item['status'] != 'unverified' and not item['note'].strip())):
            raise ConfigError('Each observed event needs a status and a concrete observation')
    folder = within(root, 'reviews/comparisons/' + fingerprint, exists=False)
    target = folder / ('observations-' + content_hash(receipt) + '.json')
    with state_lock(root):
        atomic_json(folder / 'comparison.json', result)
        if target.exists() and load_json(target) != receipt:
            raise ConfigError('Existing comparison observations changed')
        if not target.exists():
            atomic_json(target, receipt)
    return {'ok': True, 'observations': str(target), 'scope': 'event-observations-only', 'paid_creates': 0}


def event_history(root, current_assets):
    """Expose saved event evidence in review status and the delivery manifest."""
    reports = []
    folder = within(root, 'reviews/comparisons', exists=False)
    for path in sorted(folder.glob('*/observations-*.json')):
        path = within(root, path.relative_to(root).as_posix())
        receipt = load_json(path)
        saved = load_json(within(root, (path.parent / 'comparison.json').relative_to(root).as_posix()))
        if (content_hash(saved) != path.parent.name or receipt.get('comparison_hash') != path.parent.name
                or path.stem != 'observations-' + content_hash(receipt)):
            raise ConfigError('Saved event observations changed: ' + path.name)
        candidate = saved['candidate']
        matching = [aid for aid, asset in current_assets.items() if asset['sha256'] == candidate['sha256']]
        events = [{**event, **receipt['observations'][event['id']]} for event in saved['events']]
        scope = saved.get('review_scope')
        if scope and scope['asset_id'] in matching:
            asset = current_assets[scope['asset_id']]
            if asset['contract_hash'] == scope['contract_hash']:
                for event in events:
                    if event['status'] == 'fail':
                        event['retained_defect'] = _retained_defect(event['candidate'], asset['windows'])
        provenance = {}
        timing = saved.get('timing', {})
        if timing.get('source_profile'):
            provenance = {key: timing[key] for key in ('source_profile', 'source_event_coverage', 'source_event_issues')}
        reports.append({'receipt': path.relative_to(root).as_posix(), 'candidate': candidate['path'],
                        'candidate_sha256': candidate['sha256'], 'matching_current_assets': matching,
                        **({'review_scope': scope} if scope else {}),
                        'reviewer': receipt['reviewer'], 'events': events, **provenance})
    return reports


def _retained_defect(interval, windows):
    """A partially retained observation needs a new look at the remaining frames."""
    start, end = interval
    covered_to = start
    for left, right in sorted(windows):
        if right <= start or left >= end:
            continue
        if left > covered_to:
            return 'partial'
        covered_to = max(covered_to, right)
        if covered_to >= end:
            return 'full'
    return 'partial' if covered_to > start else 'trimmed'
