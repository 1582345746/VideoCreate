"""Stable numbered choices shared by conversation, CLI and local manager."""
from __future__ import annotations

import copy
import uuid
from pathlib import Path

from .catalog.bindings import configured_binding, validate_request
from .config.management import catalog, fingerprint, stamp
from .config.storage import ConfigError, atomic_json, load_json, resolve_key
from .runtime.state import state_lock


class SelectionRequired(ConfigError):
    def __init__(self, payload):
        super().__init__('Choose an upstream/model before generation; no create was sent')
        self.payload = payload


def policy(config, kind):
    return config.get('selection', {}).get(kind, {}).get('when_unspecified', 'use-default')


def candidates(config, *, kind, store_root, model=None, upstream=None, binding=None,
               operation=None, request=None):
    operation = operation or ('text-to-video' if kind == 'video' else 'text-to-image')
    rows = []
    for row in catalog(config, upstream=upstream, kind=kind):
        if model and row['model'] != model or binding and row['id'] != binding:
            continue
        b = config['bindings'][row['id']]
        errors = []
        if not row['enabled'] or row['archived'] or row['setup_status'] == 'draft' or row['adapter'] == 'unconfigured':
            errors.append('disabled, archived or protocol not configured')
        if operation not in row['operations']:
            errors.append('operation not supported')
        if row['id'] not in config['routes'].get(row['model'], {}).get('candidates', []):
            errors.append('not registered in this model route')
        try:
            available = bool(resolve_key(config['upstreams'][row['upstream_id']]['auth'], store_root=store_root))
        except ConfigError:
            available = False
        if not available:
            errors.append('credential unavailable')
        if not errors and request:
            report = validate_request(configured_binding(config, row['id']), {'operation': operation, **request})
            errors.extend(report['errors'])
        rows.append({**row, 'eligible': not errors, 'reasons': errors, 'credential_available': available})
    return rows


def menu(root, config, *, kind, store_root, model=None, upstream=None, operation=None, request=None):
    root = Path(root).resolve()
    if not (root / 'project.json').is_file():
        raise ConfigError('A project is required for a numbered selection')
    rows = candidates(config, kind=kind, store_root=store_root, model=model, upstream=upstream,
                      operation=operation, request=request)
    eligible = [row for row in rows if row['eligible']]
    choices = [{**row, 'number': i + 1} for i, row in enumerate(eligible)]
    packet = {'schema_version': 1, 'selection_id': uuid.uuid4().hex, 'created_at': stamp(),
        'project_root': str(root), 'config_token': fingerprint(config), 'config_revision': config.get('revision', 0),
        'kind': kind, 'model_filter': model, 'upstream_filter': upstream,
        'operation': operation or ('text-to-video' if kind == 'video' else 'text-to-image'),
        'request': request or {}, 'choices': choices, 'excluded': [r for r in rows if not r['eligible']]}
    packet['packet_hash'] = fingerprint(packet)
    atomic_json(root / 'selections' / (packet['selection_id'] + '.json'), packet)
    return {'ok': False, 'status': 'selection_required', **packet, 'paid_creates': 0}


def choose(root, config, *, selection_id, number, store_root, scope='project'):
    import re
    if not re.fullmatch(r'[0-9a-f]{32}', selection_id) or type(number) is not int or number < 1:
        raise ConfigError('Invalid selection ID or number')
    if scope not in {'project', 'once'}:
        raise ConfigError('Selection scope must be project or once')
    root = Path(root).resolve()
    with state_lock(root):
        path = root / 'selections' / (selection_id + '.json')
        packet = load_json(path)
        expected = packet.pop('packet_hash', None)
        if fingerprint(packet) != expected or packet.get('project_root') != str(root):
            raise ConfigError('Selection packet was changed or belongs to another project')
        if fingerprint(config) != packet['config_token']:
            raise ConfigError('Configuration changed since this list; request a new selection list')
        row = next((r for r in packet['choices'] if r['number'] == number), None)
        if not row:
            raise ConfigError('That number was not in this selection list')
        fresh = candidates(config, kind=packet['kind'], store_root=store_root, binding=row['id'],
            operation=packet['operation'], request=packet['request'])
        if not fresh or not fresh[0]['eligible']:
            raise ConfigError('Selected binding is no longer eligible; refresh the list')
        choice = {'binding_id': row['id'], 'model': row['model'], 'selection_id': selection_id,
                  'config_token': packet['config_token'], 'selected_at': stamp(), 'source': 'explicit-number'}
        record_path = root / 'route-selection.json'
        record = load_json(record_path) if record_path.exists() else {'schema_version': 1, 'choices': {}, 'history': []}
        prior = record['choices'].get(packet['kind'])
        if scope == 'project':
            if prior:
                record['history'].append({'kind': packet['kind'], **prior})
            record['choices'][packet['kind']] = choice
            atomic_json(record_path, record)
    return {'ok': True, 'scope': scope, 'kind': packet['kind'], **choice, 'paid_creates': 0,
            'note': 'Only future new tasks use this choice. Existing tasks retain their saved route.'}


def project_choice(root, kind):
    path = Path(root) / 'route-selection.json'
    if not path.exists():
        return None
    value = load_json(path)
    if value.get('schema_version') != 1:
        raise ConfigError('Unsupported project selection version')
    return value.get('choices', {}).get(kind)


def resolve(root, config, *, kind, store_root, model=None, binding=None, upstream=None, operation=None, request=None):
    """Return an explicit fixed pair, or None for an explicitly allowed legacy/default policy."""
    if binding:
        item = config['bindings'].get(binding)
        if not item or config['models'][item['model']]['kind'] != kind:
            raise ConfigError('Unknown binding or wrong media kind')
        if model and item['model'] != model or upstream and item['upstream'] != upstream:
            raise ConfigError('Explicit model/upstream conflicts with binding')
        return item['model'], binding
    saved = project_choice(root, kind)
    if saved and (not model or saved['model'] == model):
        item = config['bindings'].get(saved['binding_id'])
        if not item:
            raise ConfigError('Project selection no longer exists; select a new route')
        if not upstream or item['upstream'] == upstream:
            return saved['model'], saved['binding_id']
    if policy(config, kind) != 'ask' and not upstream and (not model or config.get('schema_version') == 3):
        return None
    rows = candidates(config, kind=kind, store_root=store_root, model=model, upstream=upstream,
                      operation=operation, request=request)
    eligible = [r for r in rows if r['eligible']]
    if (model or upstream) and len(eligible) == 1:
        return eligible[0]['model'], eligible[0]['id']
    raise SelectionRequired(menu(root, config, kind=kind, store_root=store_root, model=model,
                                 upstream=upstream, operation=operation, request=request))


def video_overrides(root, config, *, job_ids=None, model=None, upstream=None, binding=None, store_root, retry=None):
    """One-time user selection affects selected new attempts, never a live task or dependency."""
    from .planning.project import load_project
    from .runtime.state import read_state
    bundle = load_project(Path(root))
    state = read_state(Path(root))
    selected_ids = set(job_ids or [j['id'] for j in bundle['generation-plan']['jobs']])
    if selected_ids - {j['id'] for j in bundle['generation-plan']['jobs']}:
        raise ConfigError('Unknown job ID')
    selected = [j for j in bundle['generation-plan']['jobs'] if j['id'] in selected_ids]
    result = {}
    for job in selected:
        previous = state['jobs'].get(job['id'], {})
        if previous and not (retry in {'content', 'replan'} and job_ids and previous.get('status') in {'completed', 'failed', 'rejected'}):
            continue
        pair = resolve(root, config, kind='video', store_root=store_root, model=model, upstream=upstream,
            binding=binding, operation=job['operation'], request={'seconds': job['seconds'],
                'resolution': bundle['brief']['resolution'], 'aspect_ratio': bundle['brief']['aspect_ratio']})
        if pair:
            result[job['id']] = pair[1]
    return result


def switch_impact(root, *, job_ids=None):
    """Report scope without changing plans, defaults, state, or remote tasks."""
    from .planning.project import load_project
    from .runtime.state import read_state
    bundle, state = load_project(Path(root)), read_state(Path(root))
    ids = {j['id'] for j in bundle['generation-plan']['jobs']}
    if job_ids and set(job_ids) - ids:
        raise ConfigError('Unknown job ID')
    rows = []
    for job in bundle['generation-plan']['jobs']:
        rec = state['jobs'].get(job['id'], {})
        status = rec.get('status', 'not-submitted')
        rows.append({'job_id': job['id'], 'selected': not job_ids or job['id'] in job_ids,
            'status': status, 'original_binding': rec.get('binding_snapshot', {}).get('binding_id'),
            'can_switch_new_task': not rec,
            'requires_explicit_retry': status in {'completed', 'failed', 'rejected'},
            'task_id': rec.get('task_id')})
    return {'ok': True, 'jobs': rows, 'paid_creates': 0}
