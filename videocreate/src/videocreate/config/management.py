"""Transactional, UI-independent catalog editing. No generation or network calls."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .schema import configuration_schema, validate_config
from .storage import ConfigError, atomic_json, load_json, redact_config
from ..runtime.state import state_lock


def stamp():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load(path):
    path = Path(path).resolve()
    value = load_json(path)
    errors = validate_config(value)
    return {'path': str(path), 'config': value, 'token': fingerprint(value),
            'revision': value.get('revision', 0), 'errors': errors, 'editable': not errors}


def migrate(value, *, ask=True):
    errors = validate_config(value)
    if errors:
        raise ConfigError('; '.join(errors))
    result = copy.deepcopy(value)
    result['schema_version'] = 4
    result.setdefault('revision', 0)
    for kind in ('image', 'video'):
        result.setdefault('selection', {}).setdefault(kind, {
            'when_unspecified': 'ask' if ask else 'use-default', 'remember_scope': 'project'})
    for uid, upstream in result['upstreams'].items():
        upstream.setdefault('account_id', uid)
        upstream.setdefault('credential_version', '1')
    errors = validate_config(result)
    if errors:
        raise ConfigError('; '.join(errors))
    return result


def changed_paths(before, after, prefix='$'):
    """Names only: diagnostics must not contain credential values or free text."""
    if isinstance(before, dict) and isinstance(after, dict):
        rows = []
        for key in sorted(set(before) | set(after)):
            if key not in before or key not in after:
                rows.append(prefix + '.' + key)
            else:
                rows.extend(changed_paths(before[key], after[key], prefix + '.' + key))
        return rows
    return [] if before == after else [prefix]


def _protect_recovery(before, after):
    for uid, previous in before.get('upstreams', {}).items():
        current = after.get('upstreams', {}).get(uid)
        if current is None:
            raise ConfigError('Archive an upstream instead of deleting it; old tasks may still need its credentials')
        for key in ('base_url', 'account_id'):
            a = previous.get(key, uid if key == 'account_id' else '')
            b = current.get(key, uid if key == 'account_id' else '')
            if key == 'base_url':
                a, b = a.rstrip('/'), b.rstrip('/')
            if a != b:
                raise ConfigError('A different address/account needs a new upstream ID; preserve the old instance for recovery')


def save(path, value, *, expected_token, reason='configuration edit', on_prepared=None):
    path = Path(path).resolve()
    if not expected_token:
        raise ConfigError('Saving requires the token returned by config management load')
    errors = validate_config(value)
    if errors:
        raise ConfigError('; '.join(errors))
    with state_lock(path.parent / 'config-lock'):
        current = load_json(path)
        if fingerprint(current) != expected_token:
            raise ConfigError('Configuration changed in another editor; reload and merge before saving')
        if current.get('schema_version') not in {3, 4}:
            raise ConfigError('Newer configuration is read-only')
        _protect_recovery(current, value)
        result = copy.deepcopy(value)
        if result.get('schema_version') != 4:
            raise ConfigError('Management writes require version 4; preview the migration first')
        if not changed_paths(current, result):
            return {'ok': True, 'changed': False, 'token': expected_token, 'paid_creates': 0}
        result['revision'] = current.get('revision', 0) + 1
        result['updated_at'] = stamp()
        # Optional callers can durably record this exact proposed hash before
        # replacement, allowing a lost response to be reconciled without replay.
        # Failure here must leave the authoritative configuration untouched.
        if on_prepared is not None:
            on_prepared(fingerprint(result))
        backup = path.parent / 'backups' / (path.stem + '-' + expected_token + '.json')
        if not backup.exists():
            atomic_json(backup, current)
        atomic_json(path, result)
        # The configuration is authoritative; a failed audit write cannot undo a committed save.
        audit = {'revision': result['revision'], 'at': result['updated_at'], 'reason': reason,
                 'before': expected_token, 'after': fingerprint(result), 'paths': changed_paths(current, result)}
        warning = None
        try:
            atomic_json(path.parent / 'config-history' / (str(result['revision']) + '-' + audit['after'] + '.json'), audit)
        except OSError:
            warning = 'Configuration saved; history record could not be written. Backup retained.'
        return {'ok': True, 'changed': True, 'path': str(path), 'revision': result['revision'],
                'token': audit['after'], 'backup': str(backup), 'changed_paths': audit['paths'],
                'warning': warning, 'paid_creates': 0}


def migration(path, *, apply=False, ask=True):
    record = load(path)
    result = migrate(record['config'], ask=ask)
    if not apply:
        return {'ok': True, 'applied': False, 'from_version': record['config']['schema_version'],
                'to_version': 4, 'changed_paths': changed_paths(record['config'], result), 'paid_creates': 0}
    saved = save(path, result, expected_token=record['token'], reason='configuration v4 migration')
    atomic_json(Path(path).parent / 'videocreate.config.schema.json', configuration_schema())
    return {**saved, 'applied': True}


def restore(path, backup, *, expected_token):
    """Restore settings while retaining identities needed by post-backup tasks."""
    record = load(path)
    if record['token'] != expected_token:
        raise ConfigError('Configuration changed; reload before restoring')
    old = restore_candidate(record['config'], load_json(Path(backup)))
    return save(path, old, expected_token=expected_token, reason='restore configuration; retain later identities')


def restore_candidate(current, previous):
    """Build a restore without erasing identities referenced by later tasks."""
    old = migrate(previous, ask=True)
    for group in ('upstreams', 'models', 'bindings', 'routes'):
        for key, value in current[group].items():
            if key not in old[group]:
                kept = copy.deepcopy(value)
                if group in {'upstreams', 'models', 'bindings'}:
                    kept['archived'] = True
                if group == 'bindings':
                    kept['enabled'] = False
                old[group][key] = kept
    return old


def upsert(value, group, identity, item):
    if group not in {'models', 'upstreams', 'bindings', 'routes'}:
        raise ConfigError('Unsupported catalog group')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', identity):
        raise ConfigError('Use a stable ASCII ID with letters, numbers, dots, underscores or hyphens')
    result = migrate(value)
    result[group][identity] = copy.deepcopy(item)
    return result


def archive(value, group, identity, archived=True):
    if group not in {'upstreams', 'models', 'bindings'} or identity not in value.get(group, {}):
        raise ConfigError('Unknown catalog entry')
    result = migrate(value)
    result[group][identity]['archived'] = archived
    if archived:
        for bid, binding in result['bindings'].items():
            if ((group == 'bindings' and bid == identity) or
                    (group == 'upstreams' and binding['upstream'] == identity) or
                    (group == 'models' and binding['model'] == identity)):
                binding['enabled'] = False
    return result


def add_binding(value, *, identity, upstream, model, remote_model, family, kind='video',
                display_name='', adapter='unconfigured', notes=''):
    result = migrate(value)
    if upstream not in result['upstreams']:
        raise ConfigError('Add the upstream before its model binding')
    if identity in result['bindings']:
        raise ConfigError('Binding ID already exists; edit the existing record explicitly')
    if model in result['models'] and result['models'][model]['kind'] != kind:
        raise ConfigError('Model identity already has a different media kind')
    result['models'].setdefault(model, {'kind': kind, 'family': family, 'display_name': display_name or model})
    result['bindings'][identity] = {'enabled': False, 'setup_status': 'draft', 'model': model,
        'upstream': upstream, 'remote_model': remote_model, 'adapter': adapter, 'operations': [],
        'display_name': display_name or remote_model, 'notes': notes}
    route = result['routes'].setdefault(model, {'policy': 'fixed', 'preferred_binding': identity, 'candidates': []})
    if identity not in route['candidates']:
        route['candidates'].append(identity)
    errors = validate_config(result)
    if errors:
        raise ConfigError('; '.join(errors))
    return result


def catalog(value, *, upstream=None, kind=None):
    rows = []
    for bid, b in value['bindings'].items():
        m, u = value['models'][b['model']], value['upstreams'][b['upstream']]
        if upstream and b['upstream'] != upstream or kind and m['kind'] != kind:
            continue
        rows.append({'id': bid, 'display_name': b.get('display_name', m.get('display_name', b['remote_model'])),
            'upstream_id': b['upstream'], 'upstream_name': u.get('display_name', b['upstream']),
            'model': b['model'], 'family': m['family'], 'kind': m['kind'], 'remote_model': b['remote_model'],
            'adapter': b['adapter'], 'operations': b['operations'], 'enabled': b['enabled'],
            'archived': bool(b.get('archived') or u.get('archived') or m.get('archived')),
            'favorite': b.get('favorite', False), 'sort_order': b.get('sort_order', 0),
            'notes': b.get('notes', ''), 'tags': b.get('tags', []),
            'declared_capabilities': b.get('declared_capabilities', {}),
            'capability_overrides': b.get('capability_overrides', {}),
            'pricing': b.get('pricing'), 'listed_pricing': b.get('listed_pricing'),
            'setup_status': b.get('setup_status', 'configured')})
    return sorted(rows, key=lambda r: (not r['favorite'], r['sort_order'], r['upstream_id'], r['id']))
