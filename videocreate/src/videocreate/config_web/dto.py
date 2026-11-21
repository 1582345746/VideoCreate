"""Browser projections: never return config, auth, environment or secret references."""
import math
from urllib.parse import urlsplit, urlunsplit

from ..catalog.presentation import pricing_text


def cleaner(config):
    # Saved inline legacy keys may also have been pasted into labels/notes.
    # Do not decrypt external stores merely to prepare a catalog view.
    secrets = [u.get('auth', {}).get(key) for u in config.get('upstreams', {}).values()
               if isinstance(u, dict) for key in ('api_key', 'env', 'secret_ref')]
    secrets = sorted((s for s in secrets if isinstance(s, str) and s), key=len, reverse=True)

    def clean(value):
        text = str(value) if value is not None else ''
        for secret in secrets:
            text = text.replace(secret, '[已隐藏]')
        return text[:16000]
    return clean


def safe_url(value, clean):
    try:
        url = urlsplit(value)
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
            return '[地址需检查]'
        host = '[' + url.hostname + ']' if ':' in url.hostname else url.hostname
        if url.port:
            host += ':' + str(url.port)
        # Queries/fragments are not part of a valid provider base URL.
        return clean(urlunsplit((url.scheme, host, url.path, '', '')))
    except (TypeError, ValueError):
        return '[地址需检查]'


def project(value, schema, clean):
    """Project known schema properties only; no passthrough dictionaries."""
    if isinstance(value, dict):
        props = schema.get('properties', {})
        return {key: project(item, props[key], clean) for key, item in value.items() if key in props}
    if isinstance(value, list):
        return [project(item, schema.get('items', {}), clean) for item in value[:1000]]
    if isinstance(value, str):
        return clean(value)
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    return None


def setup_gaps(binding, kind):
    """Explain saved contract gaps without filling in adapter defaults or claims.

    This is guidance for Codex, not a replacement for routing/request preflight.
    Existing configured bindings do not acquire new readiness requirements.
    """
    gaps = []
    pending = binding.get('setup_status') == 'draft' or binding['adapter'] == 'unconfigured'
    caps = binding.get('capability_overrides', {})
    if pending:
        if binding['adapter'] == 'unconfigured':
            gaps.append({'code': 'protocol', 'message': '尚未确认请求与结果读取协议及其文档来源。'})
        if not binding['operations']:
            gaps.append({'code': 'operations', 'message': '尚未确认此精确型号支持哪些操作。'})
        fields = (('duration', '视频时长范围与步长'), ('resolutions', '视频分辨率'),
                  ('aspect_ratios', '视频画幅')) if kind == 'video' else (
                  ('image_sizes', '图片尺寸'), ('output_formats', '图片输出格式'))
        for field, label in fields:
            if not caps.get(field):
                gaps.append({'code': field, 'message': '尚未记录明确的' + label + '约束。'})
    limits = caps.get('media_reference_limits') or {}
    if (binding['adapter'] in {'xingapi-video-v2', 'newapi-json-v2'}
            and set(binding['operations']) & {'reference-to-video', 'image-to-video'}
            and (not limits.get('maximum_total_count') or not limits.get('allowed_combinations'))):
        gaps.append({'code': 'reference_limits',
                     'message': '尚未确认参考素材的数量、类型、角色、大小、时长限制及允许的组合。'})
    if pending and not gaps:
        gaps.append({'code': 'review',
                     'message': '参数已填写，仍保留为草稿；请让 Codex 核对当前上游、精确型号、操作和合同来源后再启用。'})
    return gaps


def catalog(config):
    from ..config.schema import configuration_schema
    clean = cleaner(config)
    schema = configuration_schema()['properties']['bindings']['additionalProperties']['properties']
    upstreams, bindings = [], []
    for identity, upstream in config['upstreams'].items():
        auth = upstream.get('auth', {})
        source = ('encrypted' if 'secret_ref' in auth else 'environment' if 'env' in auth
                  else 'legacy-inline' if 'api_key' in auth else 'missing')
        upstreams.append({'id': clean(identity), 'name': clean(upstream.get('display_name') or identity),
                          'url': safe_url(upstream.get('base_url', ''), clean),
                          'notes': clean(upstream.get('notes', '')), 'archived': bool(upstream.get('archived')),
                          'credential_present': any(bool(auth.get(k)) for k in ('api_key', 'env', 'secret_ref')),
                          'credential_source': source,
                          'binding_count': sum(b['upstream'] == identity for b in config['bindings'].values())})
    for identity, binding in config['bindings'].items():
        model = config['models'][binding['model']]
        upstream = config['upstreams'][binding['upstream']]
        archived = bool(binding.get('archived') or model.get('archived') or upstream.get('archived'))
        draft = binding.get('setup_status') == 'draft' or binding['adapter'] == 'unconfigured'
        eligible = (not archived and not draft and binding['enabled'] and bool(binding['operations'])
                    and identity in config['routes'].get(binding['model'], {}).get('candidates', []))
        detail = {key: project(binding[key], schema[key], clean) for key in
                  ('declared_capabilities', 'capability_overrides', 'pricing', 'listed_pricing', 'adapter_options') if key in binding}
        bindings.append({'id': clean(identity), 'upstream_id': clean(binding['upstream']),
                         'upstream_name': clean(upstream.get('display_name') or binding['upstream']),
                         'model_id': clean(binding['model']),
                         'name': clean(binding.get('display_name') or model.get('display_name') or binding['remote_model']),
                         'remote_model': clean(binding['remote_model']), 'family': clean(model['family']),
                         'kind': model['kind'], 'adapter': binding['adapter'],
                         'operations': list(binding['operations']), 'enabled': binding['enabled'],
                         'archived': archived, 'draft': draft, 'favorite': bool(binding.get('favorite')),
                         'default_eligible': bool(eligible),
                         'setup_gaps': setup_gaps(binding, model['kind']),
                         'sort_order': binding.get('sort_order', 0), 'notes': clean(binding.get('notes', '')),
                         'documentation_url': safe_url(binding['documentation_url'], clean) if binding.get('documentation_url') else '',
                         'setup_status': clean(binding.get('setup_status', 'configured')),
                         'tags': [clean(t) for t in binding.get('tags', [])],
                         'price_text': clean(pricing_text(detail.get('pricing'), detail.get('listed_pricing'))),
                         'state': 'archived' if archived else 'draft' if draft else 'enabled' if binding['enabled'] else 'disabled',
                         'evidence_status': 'not-evaluated', **detail})
    bindings.sort(key=lambda b: (not b['favorite'], b['sort_order'], b['upstream_id'], b['id']))
    return {'upstreams': upstreams, 'bindings': bindings}
