"""Version-bound, offline production policies; never execute tasks or approve media."""
import copy
from pathlib import Path

from . import production
from .config.management import stamp
from .config.storage import ConfigError, atomic_json
from .planning.project import content_hash, load_project
from .runtime.state import read_state, state_lock

MODES = {'assisted', 'auto-within-authorization'}


def _snapshot(root):
    root = Path(root).resolve()
    bundle, state, record = load_project(root), read_state(root), production._record(root)
    current = production.status(root, _policy_record=record)
    if (bundle != load_project(root) or state != read_state(root) or record != production._record(root)):
        raise ConfigError('Project changed while reading its production policy; reload')
    token = content_hash({'root': str(root), 'plan': bundle, 'state': state, 'record': record, 'status': current})
    return root, bundle, state, record, current, token


def _view(current):
    automatic = current['policy'] == 'auto-within-authorization'
    required = current['required_authoring_stages']
    stages = []
    for row in current['stages']:
        authoring = row['id'] in production.AUTHORING
        gate = (not automatic or row['id'] in required) if authoring else True
        progression = ('not-applicable' if row['status'] == 'skipped' else
            'checked-current-version' if authoring and row['status'] == 'complete' else
            'review-required' if authoring and gate else 'automatic-without-approval' if authoring else 'existing-runtime-and-review')
        stages.append({**row, 'authoring': authoring, 'review_required': gate and row['status'] != 'skipped',
            'progression': progression})
    return {'policy': current['policy'], 'required_authoring_stages': required, 'stages': stages,
        'next': current['next'], 'plan_valid': current['ok'], 'errors': current['errors'],
        'jobs': current['jobs'], 'budget': current['budget'], 'review': current['review']}


def describe(root):
    root, bundle, state, record, current, token = _snapshot(root)
    return {'ok': True, 'project': str(root), 'title': current['title'], 'branch': current['branch'],
        'source_token': token, 'record_version': record['schema_version'], **_view(current), 'paid_creates': 0,
        'note': 'Policy guides continuation. Bypassed authoring remains unchecked; existing spending, task recovery and media review rules still apply.'}


def _options(mode, required_stages, reason):
    if not isinstance(mode, str) or mode not in MODES or not isinstance(reason, str) or not reason.strip():
        raise ConfigError('Choose assisted/auto-within-authorization and record the user instruction')
    if (not isinstance(required_stages, list) or any(not isinstance(s, str) or s not in production.AUTHORING for s in required_stages)
            or len(set(required_stages)) != len(required_stages)):
        raise ConfigError('Required reviews must be distinct authoring stages; media/runtime stages cannot be waived')
    return [s for s in production.AUTHORING if s in required_stages], reason.strip()


def _preview(root, *, mode, required_stages, reason, source_token):
    required, reason = _options(mode, required_stages, reason)
    root, bundle, state, record, current, actual_token = _snapshot(root)
    if not source_token or actual_token != source_token:
        raise ConfigError('Production policy source changed; reload before previewing or saving')
    proposed = copy.deepcopy(record)
    proposed.update(schema_version=2, policy=mode, required_authoring_stages=required)
    after = production.status(root, _policy_record=proposed)
    changed = (record.get('policy', 'assisted') != mode or record.get('required_authoring_stages', []) != required)
    result = {'ok': True, 'source_token': source_token, 'before': _view(current), 'after': _view(after),
        'changed': changed, 'reason': reason, 'paid_creates': 0,
        'note': 'Saving changes only production policy/history. No checkpoints, model requests, media approvals or spending authorization are created.'}
    result['preview_token'] = content_hash({'root': str(root), 'source': source_token, 'mode': mode,
        'required': required, 'reason': reason, 'after': result['after']})
    return result, proposed


def preview(root, **options):
    return _preview(root, **options)[0]


def save(root, *, preview_token, **options):
    root = Path(root).resolve()
    with state_lock(root):
        result, proposed = _preview(root, **options)
        if not preview_token or result['preview_token'] != preview_token:
            raise ConfigError('Production policy preview changed; preview the current options before saving')
        if result['changed']:
            proposed['history'].append({'policy': proposed['policy'],
                'required_authoring_stages': proposed['required_authoring_stages'], 'reason': result['reason'], 'at': stamp()})
            atomic_json(root / 'production' / 'stages.json', proposed)
    return {'ok': True, 'policy': proposed['policy'], 'required_authoring_stages': proposed['required_authoring_stages'],
        'changed': result['changed'], 'next': result['after']['next'], 'paid_creates': 0, 'note': result['note']}


def inspect_stage(root, stage, *, source_token):
    root, bundle, state, record, current, token = _snapshot(root)
    if token != source_token:
        raise ConfigError('Production policy source changed; reload before inspecting this stage')
    if stage not in production.AUTHORING:
        raise ConfigError('Only authoring stages use plan checkpoints; inspect media through its review page')
    row = next(s for s in current['stages'] if s['id'] == stage)
    if row['status'] == 'skipped':
        raise ConfigError('This stage is not applicable to the current plan')
    from .production_continue import authoring_step
    return authoring_step({'ok': True, 'project': str(root), 'stage': stage, 'name': row['name'],
        'policy': current['policy'], 'paid_creates': 0, 'executable': False}, bundle, root, stage, row)
