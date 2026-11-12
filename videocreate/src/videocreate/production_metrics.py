"""Read-only production measures, with explicit samples and unknowns."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from .asset_library import digest
from .config.storage import ConfigError
from .planning.project import load_project, within
from .runtime.candidates import records, selected
from .runtime.state import read_state
from .timeline.model import number, validate_timeline


def union_seconds(windows):
    total, cursor = 0.0, -1.0
    for start, end in sorted(windows):
        total += max(0, end - max(cursor, start))
        cursor = max(cursor, end)
    return total


def report(root, *, output_name='preview.mp4'):
    root = Path(root).resolve()
    bundle, state = load_project(root), read_state(root)
    errors = validate_timeline(bundle['timeline'])
    if errors:
        raise ConfigError('; '.join(errors))
    hashes, warnings = {}, []

    def artifact_valid(artifact):
        try:
            path = within(root, artifact['path'])
            if path not in hashes:
                hashes[path] = digest(path)
            return hashes[path] == artifact.get('sha256')
        except (ConfigError, KeyError, OSError):
            return False

    attempts = []
    for jid, current in state['jobs'].items():
        seen = set()
        for index, attempt in enumerate(records(current)):
            if not attempt:
                continue
            identity = attempt.get('attempt_id', 'legacy-index-' + str(index))
            if identity in seen:
                continue
            seen.add(identity)
            attempts.append({'job_id': jid, **attempt})
    videos = [a for a in attempts if a.get('kind', 'video') == 'video']
    completed = [a for a in videos if a.get('status') == 'completed']
    known_durations, missing_durations, invalid_artifacts = [], 0, 0
    for attempt in completed:
        artifact = attempt.get('artifact', {})
        if not artifact_valid(artifact):
            invalid_artifacts += 1
            continue
        duration = artifact.get('media', {}).get('duration')
        if number(duration) and duration > 0:
            known_durations.append(duration)
        else:
            missing_durations += 1

    try:
        from .review.receipts import summary
        review = summary(root, bundle, output_name=output_name)
        review_available = True
    except (ConfigError, OSError, ValueError) as exc:
        review = {'status': 'unavailable', 'assets': {}, 'valid_receipts': 0}
        review_available = False
        warnings.append('Current review could not be validated: ' + str(exc))

    clips = {c['id']: c for c in bundle['timeline']['clips']}
    planned_jobs = {j['id'] for j in bundle['generation-plan']['jobs']}
    windows, usable_windows = defaultdict(list), defaultdict(list)
    planned_playback = available_playback = usable_playback = 0.0
    retained_jobs, available_jobs, reviewed_jobs, rejected_jobs = set(), set(), set(), set()
    unavailable_segments, unmatched_segments = [], []
    for segment in bundle['timeline']['segments']:
        start, end = segment['source_in'], segment['source_out']
        seconds = (end - start) / segment.get('rate', 1)
        planned_playback += seconds
        clip = clips[segment['clip_id']]
        jid = clip['job_id']
        retained_jobs.add(jid)
        try:
            candidate = selected(state['jobs'].get(jid, {}))
        except ConfigError as exc:
            warnings.append(jid + ': ' + str(exc))
            candidate = {}
        artifact = candidate.get('artifact', {})
        duration = artifact.get('media', {}).get('duration')
        same_candidate = candidate.get('status') == 'completed' and artifact_valid(artifact)
        if clip.get('path'):
            try:
                same_candidate = same_candidate and within(root, clip['path']) == within(root, artifact['path'])
            except (ConfigError, KeyError):
                same_candidate = False
        if not same_candidate:
            unavailable_segments.append(segment['id'])
            if clip.get('path'):
                unmatched_segments.append(segment['id'])
            continue
        if not number(duration) or duration <= 0 or end > duration + .001:
            unavailable_segments.append(segment['id'])
            continue
        available_playback += seconds
        available_jobs.add(jid)
        # Count reused intervals once in source seconds, each occurrence in playback seconds.
        key = artifact['sha256']
        windows[key].append((start, end))
        layers = review['assets'].get(jid, {}) if jid in planned_jobs else {}
        if 'fail' in layers.values():
            rejected_jobs.add(jid)
        if layers and all(v in {'pass', 'not_applicable'} for v in layers.values()):
            usable_playback += seconds
            usable_windows[key].append((start, end))
            reviewed_jobs.add(jid)

    ledger = state.get('ledger', [])
    counts = Counter(item['job_id'] for item in ledger if item['kind'] == 'video')
    retried_jobs = sum(n > 1 for n in counts.values())
    costs = {}
    for currency in sorted({i.get('currency', 'unknown') for i in ledger}):
        rows = [i for i in ledger if i.get('currency', 'unknown') == currency]
        actual_known = [i['actual'] for i in rows if i.get('actual') is not None]
        estimated_known = [i['estimated'] for i in rows if i.get('estimated') is not None]
        actual_total = sum((Decimal(str(v)) for v in actual_known), Decimal(0))
        all_actual = len(actual_known) == len(rows) and currency != 'unknown'
        costs[currency] = {'attempts': len(rows), 'actual_known_total': float(actual_total),
            'actual_unknown_attempts': len(rows) - len(actual_known),
            'estimated_known_total': float(sum((Decimal(str(v)) for v in estimated_known), Decimal(0))),
            'estimated_unknown_attempts': len(rows) - len(estimated_known),
            'project_actual_cost_per_reviewed_source_job': float(actual_total / len(reviewed_jobs))
                if all_actual and review_available and reviewed_jobs else None,
            'project_actual_cost_per_reviewed_playback_second': float(actual_total / Decimal(str(usable_playback)))
                if all_actual and review_available and usable_playback > 0 else None}

    return {'ok': True, 'project': str(root), 'paid_creates': 0,
        'sample': {'scope': 'this project only; all saved attempts, current selected candidates and retained windows',
            'create_attempts': len(ledger), 'recorded_video_attempts': len(videos), 'completed_video_attempts': len(completed),
            'retained_jobs': len(retained_jobs), 'available_selected_jobs': len(available_jobs),
            'reviewed_source_jobs': len(reviewed_jobs) if review_available else None,
            'rejected_source_jobs': len(rejected_jobs) if review_available else None,
            'unverified_source_jobs': len(available_jobs - reviewed_jobs - rejected_jobs) if review_available else None,
            'valid_review_receipts': review['valid_receipts']},
        'seconds': {'generated_known': sum(known_durations), 'completed_duration_unknown': missing_durations,
            'completed_artifact_missing_or_changed': invalid_artifacts, 'retained_planned_playback': planned_playback,
            'retained_available_playback': available_playback, 'retained_unique_source': sum(union_seconds(w) for w in windows.values()),
            'reviewed_usable_playback': usable_playback if review_available else None,
            'reviewed_unique_source': sum(union_seconds(w) for w in usable_windows.values()) if review_available else None},
        'rates': {'reviewed_source_jobs_over_available_selected_jobs': len(reviewed_jobs) / len(available_jobs)
                    if review_available and available_jobs else None,
            'retried_jobs_over_submitted_video_jobs': retried_jobs / len(counts) if counts else None,
            'retry_attempts': sum(n - 1 for n in counts.values()), 'retried_jobs': retried_jobs},
        'costs_by_currency': costs, 'delivery_status': review['status'], 'warnings': warnings,
        'unavailable_segments': unavailable_segments, 'explicit_clip_segments_not_matched_to_candidate': unmatched_segments,
        'notes': ['Generated seconds count hash-valid completed candidates with measured durations, including unselected candidates.',
            'Reviewed usable seconds mean source-layer approval for retained windows, not final edit/story acceptance.',
            'Unit costs include every ledger attempt in this project, including images and retries; currencies are separate components, never converted.',
            'Unknown billing or review data stays null; these samples do not establish a model ranking.',
            'Imported/overridden clip paths without a matching generated candidate are outside the source-job quality sample.']}
