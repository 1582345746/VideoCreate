"""Version four's user-managed catalog; declarations never grant wire capabilities."""
from .schema import BOOL, POS, STR, STRING_LIST, enum, obj


def extend(schema):
    p = schema['properties']
    metadata = {
        'notes': STR, 'tags': STRING_LIST, 'favorite': BOOL,
        'sort_order': {'type': 'integer'}, 'documentation_url': STR,
        'archived': BOOL,
    }
    source = obj({'kind': enum('user', 'screenshot', 'documentation', 'catalog', 'observed'),
                  'url': STR, 'observed_at': STR, 'effective_at': STR, 'notes': STR}, ('kind',))
    for group in ('models', 'upstreams', 'bindings'):
        p[group]['additionalProperties']['properties'].update(metadata)
    up = p['upstreams']['additionalProperties']['properties']
    up.update({'account_id': STR, 'credential_version': STR, 'capacity_group': STR})
    binding = p['bindings']['additionalProperties']
    b = binding['properties']
    b['display_name'] = STR
    b['adapter']['enum'].append('unconfigured')
    b['operations']['minItems'] = 0
    nullable_count = {'type': ['integer', 'null'], 'minimum': 0}
    nullable_positive = {'type': ['number', 'null'], 'exclusiveMinimum': 0}
    b['declared_capabilities'] = obj({
        'summary': STR, 'source': source,
        'references': obj({name: nullable_count for name in ('images', 'videos', 'audios', 'combined_total')}),
        'duration': obj({k: nullable_positive for k in ('minimum', 'maximum', 'step')}),
        'resolutions': STRING_LIST,
        'aspect_ratios': obj({'raw': STR, 'allowed': {'type': ['array', 'null'], 'items': STR}}),
        'prompt': obj({'limit': POS, 'unit': enum('characters', 'bytes', 'tokens', 'unknown'),
                       'counting_rule': enum('unicode-codepoints', 'utf16-code-units', 'utf8-bytes', 'unknown')}),
        'human_reference_note': STR, 'audio_note': STR,
    })
    b['listed_pricing'] = obj({
        'amount': {'type': ['number', 'null'], 'minimum': 0}, 'currency': {'type': ['string', 'null']},
        'display_symbol': STR, 'unit': enum('request', 'second', 'image', 'unknown'),
        'account_group': STR, 'billing_event': STR, 'refund_policy': STR,
        'source': source, 'notes': STR,
    }, ('unit',))
    caps = b['capability_overrides']['properties']
    caps['prompt_limit'] = obj({'maximum': POS,
        'counting_rule': enum('unicode-codepoints', 'utf16-code-units', 'utf8-bytes')},
        ('maximum', 'counting_rule'))
    b['pricing']['properties'].update({
        'status': enum('confirmed', 'unverified'), 'version': STR, 'effective_at': STR,
        'valid_until': STR, 'account_group': STR, 'billing_event': STR,
        'minimum_seconds': {'type': 'number', 'minimum': 0},
        'round_seconds': {'type': 'number', 'exclusiveMinimum': 0},
        'source': source,
        'tiers': {'type': 'array', 'minItems': 1, 'items': obj({
            'when': obj({'operation': STR, 'resolution': STR, 'aspect_ratio': STR,
                'minimum_seconds': {'type': 'number', 'minimum': 0},
                'maximum_seconds': {'type': 'number', 'minimum': 0}}),
            'per_request': {'type': 'number', 'minimum': 0},
            'per_second': {'type': 'number', 'minimum': 0}}, ('when',))},
    })
    selection = obj({'when_unspecified': enum('ask', 'use-default'),
                     'remember_scope': enum('project', 'once')}, ('when_unspecified',))
    p['selection'] = obj({'image': selection, 'video': selection})
    p['revision'] = {'type': 'integer', 'minimum': 0}
    p['updated_at'] = STR
    p['local_media_server'] = obj({'port': {'type': 'integer', 'minimum': 1024, 'maximum': 65535},
        'public_base_url': STR, 'max_link_seconds': {'type': 'integer', 'minimum': 60, 'maximum': 2592000}},
        ('port', 'public_base_url'))
    return schema


def semantic_errors(config):
    errors = []
    if config.get('local_media_server', {}).get('public_base_url'):
        from ..media_references import public_url
        from .storage import ConfigError
        try:
            parsed = public_url(config['local_media_server']['public_base_url'])
            if parsed.query or parsed.path not in {'', '/'}:
                errors.append('$.local_media_server.public_base_url: use an HTTPS origin without path/query')
        except ConfigError as error:
            errors.append('$.local_media_server.public_base_url: ' + str(error))
    for bid, binding in config['bindings'].items():
        path = '$.bindings.' + bid
        if binding.get('enabled') and (binding['adapter'] == 'unconfigured' or
                binding.get('setup_status') == 'draft' or not binding['operations'] or binding.get('archived')):
            errors.append(path + ': draft/archived/unconfigured binding cannot be enabled')
        upstream = config['upstreams'].get(binding['upstream'], {})
        model = config['models'].get(binding['model'], {})
        if binding.get('enabled') and (upstream.get('archived') or model.get('archived')):
            errors.append(path + ': upstream/model is archived')
        declared = binding.get('declared_capabilities', {}).get('duration', {})
        if declared.get('minimum') and declared.get('maximum') and declared['minimum'] > declared['maximum']:
            errors.append(path + '.declared_capabilities.duration: minimum exceeds maximum')
        pricing = binding.get('pricing', {})
        if pricing and not any(k in pricing for k in ('per_request', 'per_second', 'tiers')):
            errors.append(path + '.pricing: specify a rate; record unconfirmed prices in listed_pricing')
        for tier in pricing.get('tiers', []):
            if not any(k in tier for k in ('per_request', 'per_second')):
                errors.append(path + '.pricing.tiers: each tier needs a rate')
            when = tier['when']
            if when.get('minimum_seconds', 0) > when.get('maximum_seconds', float('inf')):
                errors.append(path + '.pricing.tiers: inverted duration range')
    return errors
