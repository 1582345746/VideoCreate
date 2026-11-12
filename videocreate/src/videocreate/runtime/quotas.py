"""Host-local admission and request windows, derived from authoritative v3 jobs.

The registry remembers project locations and last observable active attempts,
never a second editable task status. Missing/unreadable projects retain holds.
"""
from __future__ import annotations

import contextlib
import copy
import math
import time
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json
from .state import read_state, state_lock

RATE_FIELDS = {'create': 'create_rpm', 'poll': 'poll_rpm', 'download': 'download_rpm'}
TERMINAL = {'completed', 'complete', 'succeeded', 'success', 'done', 'finished',
            'failed', 'failure', 'error', 'cancelled', 'canceled', 'expired', 'rejected', 'output_invalid'}


class QuotaExceeded(ConfigError):
    def __init__(self, resource, retry_after_seconds=None):
        self.resource, self.retry_after_seconds = resource, retry_after_seconds
        delay = f'; retry after at least {retry_after_seconds:.1f}s' if retry_after_seconds is not None else ''
        super().__init__('Local shared-account quota reached: ' + resource + delay +
                         '; keep existing task IDs. No request was sent by this admission check')


def members(config, upstream_id):
    """Transitive account/group aliases share the most restrictive policy."""
    if upstream_id not in config['upstreams']:
        raise ConfigError('Quota upstream is missing; restore the original instance')
    found = {upstream_id}
    while True:
        accounts = {config['upstreams'][uid].get('account_id') or uid for uid in found}
        groups = {config['upstreams'][uid].get('capacity_group') for uid in found} - {None, ''}
        added = {uid for uid, item in config['upstreams'].items()
                 if (item.get('account_id') or uid) in accounts or item.get('capacity_group') in groups}
        if added <= found:
            return sorted(found)
        found |= added


def policy(config, upstream_id):
    identities = members(config, upstream_id)
    limits = {}
    for name in ('max_remote_inflight', *RATE_FIELDS.values()):
        values = [config['upstreams'][uid].get('quotas', {}).get(name) for uid in identities]
        values = [v for v in values if v is not None]
        if values:
            limits[name] = min(values)
    return identities, limits


def _folder(store_root):
    return Path(store_root) / 'runtime' / 'quotas'


def _load(store_root):
    path = _folder(store_root) / 'registry.json'
    value = load_json(path) if path.exists() else {'schema_version': 1, 'projects': [], 'active': [], 'events': []}
    if (value.get('schema_version') != 1 or
            any(not isinstance(value.get(k), list) for k in ('projects', 'active', 'events')) or
            any(not isinstance(p, str) for p in value['projects']) or
            any(not isinstance(r, dict) or not all(isinstance(r.get(k), str) for k in
                ('project', 'job_id', 'attempt_id', 'upstream_id')) for r in value['active'])):
        raise ConfigError('Quota registry is invalid; preserve it and repair before submitting')
    index = Path(store_root) / 'runtime' / 'projects.json'
    if index.is_file():
        paths = load_json(index).get('paths')
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise ConfigError('Project index is invalid; repair before quota admission')
        value['projects'] = list(dict.fromkeys([*value['projects'], *paths]))
    return value


def _save(store_root, value):
    atomic_json(_folder(store_root) / 'registry.json', value)


def watch(store_root, project):
    project = str(Path(project).resolve())
    with state_lock(_folder(store_root)):
        value = _load(store_root)
        if project not in value['projects']:
            value['projects'].append(project)
            _save(store_root, value)


def _active(value):
    active, unavailable = [], []
    for project in value['projects']:
        try:
            path = Path(project) / 'state.json'
            if not path.is_file():
                raise OSError('Project state is unavailable')
            state = read_state(Path(project))
            for jid, current in state['jobs'].items():
                for record in [*current.get('history', []), current]:
                    if (record.get('status') in TERMINAL or record.get('provider_completed_at') or
                            record.get('submission_sent') is False):
                        continue
                    snap = record.get('binding_snapshot', {})
                    if not record.get('attempt_id') or not snap.get('upstream_id'):
                        continue
                    active.append({'project': project, 'job_id': jid, 'attempt_id': record['attempt_id'],
                        'upstream_id': snap['upstream_id'],
                        'account_id': snap.get('identity', {}).get('account_id') or snap['upstream_id'],
                        'task_id': record.get('task_id', ''), 'status': record.get('status', 'unknown'),
                        'source_available': True})
        except (ConfigError, OSError, ValueError, TypeError, KeyError):
            unavailable.append(project)
            active.extend({**item, 'source_available': False} for item in value['active'] if item['project'] == project)
    # Deduplicate a cached/history record without shortening unknown holds.
    return list({(r['project'], r['attempt_id']): r for r in active}.values()), unavailable


def _refresh(value, now):
    value['active'], unavailable = _active(value)
    events = value['events']
    if any(not isinstance(e, dict) or isinstance(e.get('at'), bool) or
           not isinstance(e.get('at'), (int, float)) or not math.isfinite(e['at']) or
           e.get('kind') not in RATE_FIELDS or not isinstance(e.get('upstream_id'), str) for e in events):
        raise ConfigError('Quota request history is invalid; preserve it before repair')
    # Wall-clock rollback retains future events, so restarting cannot reset RPM.
    value['events'] = [e for e in events if e['at'] > now - 60]
    return unavailable


def _in_scope(item, config, identities):
    return (item['upstream_id'] in identities or item.get('account_id') in
            {config['upstreams'][uid].get('account_id') or uid for uid in identities})


def _rate(value, config, identities, limits, kind, now):
    maximum = limits.get(RATE_FIELDS[kind])
    events = [e for e in value['events'] if e['kind'] == kind and _in_scope(e, config, identities)]
    if maximum is not None and len(events) >= maximum:
        raise QuotaExceeded(kind + '_rpm', max(0, sorted(e['at'] for e in events)[-maximum] + 60 - now))


def _event(value, config, upstream_id, kind, now):
    value['events'].append({'upstream_id': upstream_id,
        'account_id': config['upstreams'][upstream_id].get('account_id') or upstream_id, 'kind': kind, 'at': now})


@contextlib.contextmanager
def admission(store_root, config, upstream_id):
    """Use inside the project lock, through durable intent, never over networking.

    watch() must run before the project lock. All processes then see a committed
    intent even if the creator dies immediately after its state write.
    """
    identities, limits = policy(config, upstream_id)
    with state_lock(_folder(store_root)):
        value, now = _load(store_root), time.time()
        _refresh(value, now)
        _save(store_root, value)  # Preserve observed holds even when admission fails.
        maximum = limits.get('max_remote_inflight')
        count = sum(_in_scope(item, config, identities) for item in value['active'])
        if maximum is not None and count >= maximum:
            raise QuotaExceeded('max_remote_inflight')
        _rate(value, config, identities, limits, 'create', now)
        # Count an admission conservatively even if a later local budget/write
        # fails. It expires after 60s; it never implies an actual paid request.
        _event(value, config, upstream_id, 'create', now)
        _save(store_root, value)
        yield
        _refresh(value, time.time())
        _save(store_root, value)


def request(store_root, config, upstream_id, kind):
    identities, limits = policy(config, upstream_id)
    with state_lock(_folder(store_root)):
        value, now = _load(store_root), time.time()
        _refresh(value, now)
        _rate(value, config, identities, limits, kind, now)
        _event(value, config, upstream_id, kind, now)
        _save(store_root, value)


@contextlib.contextmanager
def network_scope(store_root, config, upstream_id, kind):
    import vc_common
    with vc_common.request_policy(lambda method, url: request(store_root, config, upstream_id, kind)):
        yield


def status(store_root, config, upstream_id):
    identities, limits = policy(config, upstream_id)
    with state_lock(_folder(store_root)):
        value, now = _load(store_root), time.time()
        unavailable = _refresh(value, now)
        _save(store_root, value)
    active = [r for r in value['active'] if _in_scope(r, config, identities)]
    rates = {}
    for kind in RATE_FIELDS:
        events = [e for e in value['events'] if e['kind'] == kind and _in_scope(e, config, identities)]
        maximum = limits.get(RATE_FIELDS[kind])
        rates[kind] = {'used': len(events), 'limit': maximum,
            'retry_after_seconds': max(0, sorted(e['at'] for e in events)[-maximum] + 60 - now)
                if maximum and len(events) >= maximum else 0}
    return {'ok': True, 'scope': 'host-local-v3', 'upstreams': identities, 'limits': limits,
        'remote_inflight': len(active), 'active': copy.deepcopy(active), 'rates': rates,
        'unavailable_projects': unavailable, 'tracked_projects': len(value['projects']),
        'network_requests': 0, 'paid_creates': 0,
        'note': 'Known local projects only; external clients and other machines are not counted. '
                'Create admission counts are conservative, not billing receipts. Unknown tasks have no automatic expiry.'}
