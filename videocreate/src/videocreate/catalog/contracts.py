"""Explicit, opt-in recipes from supplied documents. Names never select adapters."""
from copy import deepcopy

from ..config.management import add_binding, fingerprint, migrate
from ..config.storage import ConfigError

XING_V = {
    'id': 'xingapi-seedance-v-text-20261030',
    'revision': '1', 'title': '星光 Seedance2.5-V 文生视频',
    'source': 'references/xingapi-contract.md · 用户提供文档 2026-10-30',
    'base_urls': ['https://xingapi.top/v1'],
    'remote_model': 'seedance2.5-V', 'adapter': 'xingapi-video-v1',
    'operations': ['text-to-video'],
    'capability_overrides': {'duration': {'minimum': 5, 'maximum': 30, 'step': 1},
        'resolutions': ['720p'], 'aspect_ratios': ['9:16'], 'max_reference_images': 0,
        'max_additional_reference_images': 0, 'audio_control': 'model-default'},
    'scope': '仅明确的文生视频合同；参考素材、声音开关和其他型号需单独整理。无生成、计费或质量验收。'
}
RECIPES = {XING_V['id']: XING_V}


def available(config, upstream):
    item = config['upstreams'].get(upstream, {})
    if item.get('archived'):
        return []
    return [{k: deepcopy(recipe[k]) for k in ('id', 'revision', 'title', 'source', 'remote_model', 'scope')}
            for recipe in RECIPES.values() if item.get('base_url', '').rstrip('/') in recipe['base_urls']]


def apply(config, upstream, contract, revision):
    recipe = RECIPES.get(contract)
    if not recipe or revision != recipe['revision'] or not any(r['id'] == contract for r in available(config, upstream)):
        raise ConfigError('Contract source/version or explicit upstream address does not match')
    value = migrate(config)
    matches = [(bid, b) for bid, b in value['bindings'].items()
               if b['upstream'] == upstream and b['remote_model'] == recipe['remote_model']]
    if len(matches) > 1:
        raise ConfigError('Multiple bindings use this exact remote ID; choose one explicitly through Codex')
    bid = matches[0][0] if matches else 'documented-' + fingerprint([upstream, contract])[:24]
    if matches and matches[0][1]['adapter'] != 'unconfigured':
        raise ConfigError('This binding already has a configured protocol; edit explicitly instead of replacing it')
    if not matches:
        value = add_binding(value, identity=bid, upstream=upstream, model=bid,
                            remote_model=recipe['remote_model'], family='seedance', kind='video')
    item = value['bindings'][bid]
    item.update(adapter=recipe['adapter'], operations=deepcopy(recipe['operations']), enabled=True,
                setup_status='documented-text-only-no-generation-test',
                capability_overrides=deepcopy(recipe['capability_overrides']),
                documentation_url='https://xingapi.top',
                adapter_options={})
    # Existing model names, notes, declaration sources and prices stay independent.
    return value, bid
