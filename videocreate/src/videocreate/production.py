"""Derived production progress. Jobs and reviews remain the authoritative records."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from .config.management import stamp
from .config.storage import ConfigError, atomic_json, load_json
from .planning.project import content_hash, load_project, validate_plan, within
from .runtime.state import read_state, state_lock

AUTHORING = ('theme', 'outline', 'script', 'characters', 'storyboard', 'references')
NAMES = dict(zip(AUTHORING + ('generation', 'editing', 'review', 'delivery'),
    ('主题与规格', '故事大纲', '剧本与对白', '角色与场景', '分镜', '参考素材', '生成素材', '剪辑与声音', '实际审片', '交付')))


def script_projection(bundle):
    """Director is the source; the readable/script exchange is a projection, not a second script."""
    return {'schema_version': 1, 'source': bundle['project'].get('files', {}).get('director', 'director.json'),
        'source_hash': content_hash(bundle['director']), 'title': bundle['project']['title'],
        'logline': bundle['story'].get('logline', ''),
        'scenes': copy.deepcopy(bundle['director']['scenes']),
        'characters': copy.deepcopy(bundle['director']['assets']),
        'shots': copy.deepcopy(bundle['director']['shots'])}


def script_export(root):
    root = Path(root).resolve()
    bundle = load_project(root)
    value = script_projection(bundle)
    target = root / 'production' / 'script.json'
    atomic_json(target, value)
    lines = ['# ' + value['title'], '', value['logline'], '',
        '来源：director 层。此阅读稿为单向导出；结构化 script.json 可经版本检查导入。', '']
    for shot in value['shots']:
        lines.extend(['## ' + shot['id'] + ' · ' + shot['scene_id'], '',
            shot.get('information_goal', ''), '', '画面：' + shot.get('opening_frame', ''),
            '动作：' + '；'.join(a['description'] for a in shot['actions']),
            '情绪与表演：' + '；'.join(shot.get('performance', {}).values())])
        lines.extend(f"{line['speaker']}：{line['text']}" for line in shot.get('audio', {}).get('lines', []))
        lines.extend(['转场：' + shot.get('cut_motivation', ''), ''])
    text = target.with_suffix('.md')
    text.write_text('\n'.join(lines), encoding='utf-8')
    return {'ok': True, 'script': str(target), 'reading_copy': str(text), 'source_hash': value['source_hash'], 'paid_creates': 0}


def import_script(root, value):
    root = Path(root).resolve()
    with state_lock(root):
        bundle = load_project(root)
        if value.get('schema_version') != 1 or value.get('source_hash') != content_hash(bundle['director']):
            raise ConfigError('Script source changed; export the current version before importing edits')
        if set(value) - {'schema_version', 'source', 'source_hash', 'title', 'logline', 'scenes', 'characters', 'shots'}:
            raise ConfigError('Unknown script exchange fields')
        if value.get('title') != bundle['project']['title'] or value.get('logline') != bundle['story'].get('logline', ''):
            raise ConfigError('Edit title/logline in project/story; this import only edits the director layer')
        changed = copy.deepcopy(bundle)
        changed['director'] = {'assets': value.get('characters'), 'scenes': value.get('scenes'), 'shots': value.get('shots')}
        check = validate_plan(changed, root)
        if not check['ok']:
            raise ConfigError('; '.join(check['errors']))
        report = impact(root, candidate=changed)
        backup = root / 'production' / 'backups' / (content_hash(bundle['director']) + '.director.json')
        atomic_json(backup, bundle['director'])
        target = within(root, bundle['project'].get('files', {}).get('director', 'director.json'))
        atomic_json(target, changed['director'])
    return {'ok': True, 'backup': str(backup), 'impact': report, 'paid_creates': 0}


def impact(root, candidate=None):
    from .runtime.jobs import current_inputs
    root = Path(root).resolve()
    bundle, state = candidate or load_project(root), read_state(root)
    changed, unchanged, pending = [], [], []
    for job in bundle['generation-plan']['jobs']:
        prior = state['jobs'].get(job['id'])
        if not prior:
            pending.append(job['id'])
            continue
        try:
            same = current_inputs(root, bundle, job, prior) == prior.get('input_hash')
        except (ConfigError, OSError, ValueError):
            same = False
        (unchanged if same else changed).append(job['id'])
    dependents = set()
    while True:
        found = {j['id'] for j in bundle['generation-plan']['jobs']
                 if set(j.get('depends_on', [])) & (set(changed) | dependents)}
        if found <= dependents:
            break
        dependents |= found
    return {'ok': True, 'changed_job_inputs': changed, 'dependent_jobs_to_check': sorted(dependents - set(changed)),
        'reusable_inputs': unchanged, 'not_submitted': pending,
        'note': 'No task was changed. Changed jobs require explicit replan; unchanged inputs do not recreate video.', 'paid_creates': 0}


def _record(root):
    path = root / 'production' / 'stages.json'
    value = load_json(path) if path.exists() else {'schema_version': 1, 'policy': 'assisted', 'decisions': {}, 'history': []}
    if value.get('schema_version') != 1:
        raise ConfigError('Unsupported production stage record')
    return value


def _authoring_inputs(bundle, root):
    refs = [r for job in bundle['generation-plan']['jobs'] for r in job.get('references', [])]
    observed = []
    for ref in refs:
        path = within(root, ref['path'], exists=False)
        observed.append({**ref, 'actual_hash': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None})
    return {'theme': {'brief': bundle['brief'], 'title': bundle['project']['title']},
        'outline': bundle['story'], 'script': script_projection(bundle),
        'characters': bundle['director']['assets'], 'storyboard': bundle['director']['shots'], 'references': observed}


def status(root, *, output_name='preview.mp4'):
    root = Path(root).resolve()
    bundle, state, record = load_project(root), read_state(root), _record(root)
    check = validate_plan(bundle, root)
    inputs = _authoring_inputs(bundle, root)
    stages = []
    for stage in AUTHORING:
        value = inputs[stage]
        decision = record['decisions'].get(stage, {})
        unused = stage in {'characters', 'references'} and not value
        if stage == 'outline' and bundle['brief']['intent'] == 'single-shot' and not bundle['story']['beats']:
            unused = True
        matches = decision.get('input_hash') == content_hash(value)
        state_name = 'skipped' if unused else 'complete' if matches and decision.get('decision') == 'accept' else 'stale' if decision else 'ready'
        stages.append({'id': stage, 'name': NAMES[stage], 'status': state_name,
            'input_hash': content_hash(value), 'reason': 'Not used by this plan' if unused else decision.get('reason', ''),
            'approval_scope': 'authoring-only; not media quality'})
    planned = {j['id']: j for j in bundle['generation-plan']['jobs']}
    task_rows = []
    for jid in dict.fromkeys([*planned, *state['jobs']]):
        rec = state['jobs'].get(jid, {})
        snapshot = rec.get('binding_snapshot', {})
        task_rows.append({'job_id': jid, 'kind': rec.get('kind', 'video'), 'status': rec.get('status', 'not-submitted'),
            'task_id': rec.get('task_id'), 'binding': snapshot.get('binding_id'),
            'model': snapshot.get('model'), 'upstream': snapshot.get('upstream_id'),
            'candidate_count': len(rec.get('history', [])) + bool(rec),
            'content_status': rec.get('content_status', 'unverified')})
    affected = impact(root)
    active = [r for r in task_rows if r['job_id'] in planned]
    ambiguous = [r['job_id'] for r in active if r['status'] in {'submitting', 'submission_unknown'}]
    complete = bool(active) and all(r['status'] == 'completed' for r in active)
    generation = 'skipped' if not planned else 'blocked' if ambiguous else 'stale' if affected['changed_job_inputs'] else 'complete' if complete else 'pending'
    stages.append({'id': 'generation', 'name': NAMES['generation'], 'status': generation, 'blocked_by': ambiguous})
    try:
        from .review.receipts import summary
        review = summary(root, bundle, output_name=output_name)
        review_error = ''
    except (ConfigError, OSError, ValueError) as exc:
        review, review_error = {'status': 'review_pending', 'assets': {}}, str(exc)
    final = 'final' in review['assets']
    stages.extend([
        {'id': 'editing', 'name': NAMES['editing'], 'status': 'stale' if review_error else 'complete' if final else 'pending', 'reason': review_error},
        {'id': 'review', 'name': NAMES['review'], 'status': 'complete' if review['status'] == 'accepted_delivery' else 'blocked' if review['status'] == 'rejected' else 'pending', 'reason': review['status']},
        {'id': 'delivery', 'name': NAMES['delivery'], 'status': 'ready' if review['status'] == 'accepted_delivery' else 'pending'}])
    next_step = next((s for s in stages if s['status'] not in {'complete', 'skipped'}), None)
    if ambiguous:
        next_step = {'id': 'reconcile', 'name': '核对原提交；不重复创建', 'jobs': ambiguous}
    elif not check['ok']:
        next_step = {'id': 'repair-plan', 'name': '修复计划结构', 'errors': check['errors']}
    elif record.get('policy') == 'auto-within-authorization':
        next_step = next((s for s in stages if s['id'] not in AUTHORING and s['status'] not in {'complete', 'skipped'}), None)
    from .runtime.budget import summary as budget_summary
    return {'ok': check['ok'], 'project': str(root), 'title': bundle['project']['title'],
        'branch': 'animation' if 'animation' in bundle else bundle['brief'].get('workflow_profile', bundle['brief']['intent']),
        'policy': record.get('policy', 'assisted'), 'stages': stages, 'next': next_step,
        'jobs': task_rows, 'impact': affected, 'budget': budget_summary(state),
        'review': review, 'errors': check['errors'], 'warnings': check['warnings'], 'paid_creates': 0}


def checkpoint(root, stage, *, reason, expected_hash):
    root = Path(root).resolve()
    if stage not in AUTHORING or not reason.strip():
        raise ConfigError('Checkpoint requires an authoring stage and review reason; media approval uses review receipts')
    with state_lock(root):
        bundle = load_project(root)
        actual = content_hash(_authoring_inputs(bundle, root)[stage])
        if actual != expected_hash:
            raise ConfigError('Stage content changed; review the current version')
        record = _record(root)
        decision = {'decision': 'accept', 'input_hash': actual, 'reason': reason, 'at': stamp()}
        record['history'].append({'stage': stage, **decision})
        record['decisions'][stage] = decision
        atomic_json(root / 'production' / 'stages.json', record)
    return {'ok': True, 'stage': stage, **decision, 'paid_creates': 0}


def policy(root, mode, reason):
    root = Path(root).resolve()
    load_project(root)
    if mode not in {'assisted', 'auto-within-authorization'} or not reason.strip():
        raise ConfigError('Choose assisted/auto-within-authorization and record the user instruction')
    with state_lock(root):
        record = _record(root)
        record['policy'] = mode
        record['history'].append({'policy': mode, 'reason': reason, 'at': stamp()})
        atomic_json(root / 'production' / 'stages.json', record)
    return {'ok': True, 'policy': mode, 'paid_creates': 0,
        'note': 'Policy guides next steps; it does not create tasks, grant spending authorization or approve media.'}


def project_index(store_root, project=None):
    store_root = Path(store_root)
    path = store_root / 'runtime' / 'projects.json'
    with state_lock(store_root / 'project-index-lock'):
        index = load_json(path) if path.exists() else {'schema_version': 1, 'paths': []}
        if project:
            project = Path(project).resolve()
            load_project(project)
            if str(project) not in index['paths']:
                index['paths'].append(str(project))
                atomic_json(path, index)
    rows = []
    for item in index['paths']:
        try:
            current = status(Path(item))
            rows.append({k: current[k] for k in ('project', 'title', 'next', 'budget', 'review')})
        except (ConfigError, OSError, ValueError) as exc:
            rows.append({'project': item, 'unavailable': str(exc)})
    return {'ok': True, 'projects': rows, 'source': 'live-project-files', 'paid_creates': 0}


def delivery(root, *, output_name='preview.mp4'):
    root = Path(root).resolve()
    current = status(root, output_name=output_name)
    if not current['ok']:
        raise ConfigError('Repair plan validation errors before exporting delivery')
    if Path(output_name).name != output_name or not output_name.endswith('.mp4'):
        raise ConfigError('Delivery output must be a plain MP4 filename')
    script = script_export(root)
    target = within(root, 'deliverables/' + output_name)
    manifest = load_json(target.with_suffix('.manifest.json'))
    result = {'schema_version': 1, 'status': current['review']['status'],
        'video': {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()},
        'script': script, 'subtitles': str(target.with_suffix('.srt')) if target.with_suffix('.srt').exists() else None,
        'mapping': manifest.get('mapping'), 'source_hashes': manifest.get('source_hashes'),
        'jobs': current['jobs'], 'budget': current['budget'], 'review': current['review'],
        'unverified': [s for s in current['stages'] if s['id'] in {'editing', 'review'} and s['status'] != 'complete'],
        'paid_creates': 0}
    path = root / 'deliverables' / (target.stem + '.delivery.json')
    atomic_json(path, result)
    return {'ok': True, 'manifest': str(path), **result}
