"""Read-only provider discovery. Returned names are drafts, never capability proof."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, resolve_key
from ..config.management import add_binding, migrate, stamp


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def models(config, upstream_id, *, store_root):
    upstream = config['upstreams'].get(upstream_id)
    if not upstream:
        raise ConfigError('Unknown upstream')
    key = resolve_key(upstream['auth'], store_root=store_root)
    if not key:
        raise ConfigError('Upstream credential is unavailable')
    base = upstream['base_url'].rstrip('/')
    url = base + ('/models' if base.endswith('/v1') else '/v1/models')
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=min(60, upstream.get('request_timeout_seconds', 30))) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise ConfigError('Model catalog returned HTTP ' + str(exc.code) + '; no generation was attempted') from None
    except (OSError, ValueError):
        raise ConfigError('Model catalog could not be read; no generation was attempted') from None
    if len(raw) > 4 * 1024 * 1024:
        raise ConfigError('Model catalog exceeds the local response size limit')
    try:
        data = json.loads(raw)
        rows = data['data']
        if not isinstance(rows, list):
            raise ValueError()
        ids = list(dict.fromkeys(row['id'] for row in rows if isinstance(row, dict) and
                                isinstance(row.get('id'), str) and row['id'].strip()))
    except (ValueError, KeyError, TypeError):
        raise ConfigError('Model catalog is not the supported data/id response format') from None
    result = {'upstream': upstream_id, 'url': url, 'observed_at': stamp(), 'ids': ids,
              'evidence_kind': 'catalog-only', 'paid_creates': 0}
    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    evidence = Path(store_root) / 'runtime' / 'catalogs' / (digest + '.json')
    atomic_json(evidence, result)
    return {'ok': True, **result, 'evidence': str(evidence)}


def import_models(config, upstream_id, ids, *, kind='video', family='custom'):
    result = migrate(config)
    existing = {b['remote_model'] for b in result['bindings'].values() if b['upstream'] == upstream_id}
    added = []
    for remote in ids:
        if not isinstance(remote, str) or not remote.strip() or remote in existing:
            continue
        # Channel-specific identity until equivalence to another supplier is established.
        slug = re.sub(r'[^a-z0-9_.-]', '-', remote.lower()).strip('-')[:60] or 'model'
        identity = upstream_id[:40] + '-' + slug + '-' + hashlib.sha256(remote.encode()).hexdigest()[:8]
        result = add_binding(result, identity=identity, upstream=upstream_id, model=identity,
            remote_model=remote, family=family, kind=kind, display_name=remote)
        added.append(identity)
        existing.add(remote)
    return result, added
