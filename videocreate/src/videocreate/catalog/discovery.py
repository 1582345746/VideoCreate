"""Read-only provider discovery. Returned names are drafts, never capability proof."""
from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request

from ..config.storage import ConfigError, parse_json, resolve_key
from ..config.management import add_binding, migrate


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
    from . import observations
    url = observations.url(observations.identity(config,upstream_id))
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
        data = parse_json(raw.decode('utf-8-sig'))
        rows = data['data']
        if not isinstance(rows, list):
            raise ValueError()
        if any(not isinstance(row,dict) or 'id' not in row for row in rows):raise ValueError()
        ids = observations.ids([row['id'] for row in rows])
        if any(key in remote for remote in ids):raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ConfigError('Model catalog is not the supported data/id response format') from None
    result=observations.record(config,upstream_id,ids,store_root=store_root)
    return {**result,'network_requests':1}


def import_models(config, upstream_id, ids, *, kind='video', family='custom', observation=None):
    from . import observations
    ids=observations.ids(ids)
    if upstream_id not in config['upstreams']:raise ConfigError('Unknown upstream')
    if observation is not None:
        observations.checked(observation,observations.identity(config,upstream_id))
        if set(ids)-set(observation['ids']):raise ConfigError('Import selection contains models outside this catalog observation')
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
        if observation is not None:
            result['bindings'][identity]['declared_capabilities']={'source':{'kind':'catalog',
                'url':observation['url'],'observed_at':observation['observed_at'],
                'notes':'Catalog-only observation SHA256: '+observation['observation_hash']}}
        added.append(identity)
        existing.add(remote)
    return result, added
