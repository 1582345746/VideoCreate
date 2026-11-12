"""Explicit read-only pricing discovery; catalog claims never enable a model."""
import hashlib
import json
import math
import urllib.request
import urllib.error
from pathlib import Path

from .discovery import NoRedirect
from ..config.management import stamp
from ..config.storage import ConfigError, atomic_json, parse_json, resolve_key


def normalize(body):
    if not isinstance(body.get('data'), list):
        raise ConfigError('Pricing response must contain a data array')
    rows, ids = [], set()
    for raw in body['data']:
        if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id'].strip():
            raise ConfigError('Pricing rows require exact model IDs')
        if raw['id'] in ids:
            raise ConfigError('Pricing has duplicate model IDs; do not choose an arbitrary price')
        ids.add(raw['id'])
        pricing = raw.get('pricing', {})
        if not isinstance(pricing, dict):
            raise ConfigError('Pricing details must be an object')
        tiers = pricing.get('tiers', [])
        unit = raw.get('video_billing_unit')
        currency = body.get('currency')
        quote = None
        if (raw.get('pricing_configured') is True and raw.get('billing_mode') == 'video'
                and currency == 'USD' and unit in {'request', 'second'}
                and pricing.get('unit') == {'request': 'usd_per_video', 'second': 'usd_per_second'}[unit]
                and isinstance(tiers, list) and len(tiers) == 1 and isinstance(tiers[0], dict)):
            tier = tiers[0]
            amount = tier.get('per_request_price')
            if (type(amount) in {int, float} and math.isfinite(amount) and amount >= 0
                    and tier.get('min_tokens') == 0 and tier.get('max_tokens') is None
                    and isinstance(tier.get('tier_label'), str)
                    and tier['tier_label'].lower() in {'480p', '720p', '1080p'}):
                quote = {'currency': currency, 'unit': unit, 'amount': amount,
                         'resolution': tier['tier_label'].lower(), 'actual_payment': 'unknown'}
        rows.append({'remote_model': raw['id'], 'kind': raw.get('billing_mode'),
            'description': raw.get('description') if isinstance(raw.get('description'), str) else '',
            'quote': quote, 'raw_pricing': pricing,
            'note': 'Read-only account quote. No executable limits, budget price or actual payment was changed.'})
    return rows


def discover(config, upstream_id, *, store_root):
    upstream = config['upstreams'].get(upstream_id)
    if not upstream:
        raise ConfigError('Unknown upstream')
    key = resolve_key(upstream['auth'], store_root=store_root)
    if not key:
        raise ConfigError('Upstream credential is unavailable')
    base = upstream['base_url'].rstrip('/')
    url = base + ('/pricing' if base.endswith('/v1') else '/v1/pricing')
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise ConfigError('Pricing catalog returned HTTP ' + str(exc.code) + '; no generation was attempted') from None
    except (OSError, ValueError):
        raise ConfigError('Pricing catalog could not be read; no generation was attempted') from None
    if len(raw) > 4 * 1024 * 1024:
        raise ConfigError('Pricing response exceeds the local size limit')
    try:
        body = parse_json(raw.decode('utf-8-sig'))
    except UnicodeError:
        raise ConfigError('Pricing response is not UTF-8') from None
    rows = normalize(body)
    for row in rows:
        row['local_bindings'] = [bid for bid, b in config['bindings'].items()
                                 if b['upstream'] == upstream_id and b['remote_model'] == row['remote_model']]
        row['description_changed'] = any(config['bindings'][bid].get('declared_capabilities', {}).get('summary')
                                        != row['description'] for bid in row['local_bindings'])
    result = {'upstream': upstream_id, 'url': url, 'observed_at': stamp(), 'currency': body.get('currency'),
              'models': rows, 'paid_creates': 0, 'config_changed': False}
    # Defensive redaction even if an upstream unexpectedly reflects credentials.
    text = json.dumps(result, ensure_ascii=False).replace(key, '[REDACTED]')
    result = json.loads(text)
    path = Path(store_root) / 'runtime/pricing' / (hashlib.sha256(text.encode()).hexdigest() + '.json')
    atomic_json(path, result)
    return {'ok': True, **result, 'evidence': str(path)}
