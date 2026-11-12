"""Opt-in public catalog declarations. Never infer a wire adapter from marketing."""
from copy import deepcopy

from ..config.management import migrate, add_binding
from ..config.storage import ConfigError


def xingapi_drafts(config, *, upstream_id='xingapi-main', auth=None):
    value = migrate(config)
    if upstream_id not in value['upstreams']:
        value['upstreams'][upstream_id] = {'display_name': '星光 API', 'base_url': 'https://xingapi.top/v1',
            'account_id': upstream_id, 'credential_version': 'v1',
            'auth': auth or {'type': 'bearer', 'env': 'XINGAPI_API_KEY'},
            'max_concurrent_submissions': 1, 'request_timeout_seconds': 120,
            'notes': '模型目录已确认；生成、上传与计费合同需要独立核实。'}
    elif value['upstreams'][upstream_id]['base_url'].rstrip('/') != 'https://xingapi.top/v1':
        raise ConfigError('That upstream ID belongs to a different address')
    source = {'kind': 'screenshot', 'url': 'https://xingapi.top', 'observed_at': '2026-11-12',
        'notes': 'User-provided model square screenshot; API /models separately confirmed exact ID casing.'}
    rows = [
        ('seedance-933', 'Seedance-933', 2.79, 'request', (9,0,3), (4,15),
         '可近音参考；720P；原生过真人；15000 字符上限；按条收费；页面称耗时 4–10 分钟。'),
        ('seedance2.0-933-C', 'Seedance2.0-933-C', 2.89, 'request', (9,3,3), (4,15),
         'C 通道；参考 9 图片、3 视频、3 音频；720P；过真人；4–15 秒；按条收费。'),
        ('seedance2.0-933-Q', 'Seedance2.0-933-Q', 1.35, 'request', (9,3,3), (5,15),
         'Q 通道；参考 9 图片、3 视频、3 音频；720P；原生过真人；5–15 秒；9:16；参考音频和视频 3 秒以上；提示词大于 10 字。'),
        ('seedance2.5-s', 'Seedance2.5-S', .299, 'second', (30,10,10), (4,30),
         'S 通道；参考 30 图片、10 视频、10 音频；720P；原生过真人；4–30 秒；全比例；按秒计费。'),
        ('seedance2.5-V', 'Seedance2.5-V', 4.9, 'request', (30,10,10), (5,30),
         'V 通道；参考 30 图片、10 视频、10 音频；720P；原生过真人；5–30 秒；全比例；15000 字符上限；按条收费；页面称不主动封号。'),
        ('wan3.0-prime-720P', 'Wan3.0-Prime-720P', .22, 'second', (10,5,None), None,
         '参考 10 图片、5 视频；页面写有音频和 720P，音频数量未注明；按秒收费。')]
    added = []
    for remote, display, amount, unit, references, duration, notes in rows:
        if any(b['upstream'] == upstream_id and b['remote_model'] == remote for b in value['bindings'].values()):
            continue
        identity = upstream_id + '-' + remote.lower()
        value = add_binding(value, identity=identity, upstream=upstream_id, model=identity,
            remote_model=remote, family='wan' if remote.startswith('wan') else 'seedance', display_name=display, notes=notes)
        item = value['bindings'][identity]
        item['listed_pricing'] = {'amount': amount, 'display_symbol': '$', 'currency': None, 'unit': unit,
            'account_group': 'SVIP-视频', 'billing_event': 'unknown', 'source': deepcopy(source),
            'notes': '页面标价；币种、账户结算价格、失败收费及退款未核实。'}
        declared = {'source': deepcopy(source), 'summary': notes, 'resolutions': ['720p'],
            'references': dict(zip(('images','videos','audios'), references))}
        if duration:
            declared['duration'] = {'minimum': duration[0], 'maximum': duration[1], 'step': None}
        if remote in {'seedance-933','seedance2.5-V'}:
            declared['prompt'] = {'limit':15000, 'unit':'characters', 'counting_rule':'unknown'}
        if remote in {'seedance2.5-V','seedance2.5-s'}:
            declared['aspect_ratios'] = {'raw':'全比例', 'allowed':None}
        item['declared_capabilities'] = declared
        added.append(identity)
    return value, added
