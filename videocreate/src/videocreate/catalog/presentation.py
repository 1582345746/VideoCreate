"""Readable catalog and comparisons shared by the manager and CLI; no IO writes."""
from __future__ import annotations

import copy
import math

from ..config.management import catalog
from ..config.storage import ConfigError
from ..runtime.budget import estimate
from .bindings import configured_binding, validate_request

OPERATIONS = {'text-to-video': '文生视频', 'image-to-video': '图生视频',
    'reference-to-video': '多媒体参考视频', 'text-to-image': '文生图', 'image-edit': '图片编辑'}
KINDS = {'video': '视频', 'image': '图片'}
STAGES = {'catalog':'目录', 'contract':'合同', 'smoke':'生成小样', 'quality':'内容质量'}


def number(value):
    return format(value, '.12g') if isinstance(value, (int, float)) else str(value)


def rates(value):
    parts = [number(value[key]) + '/' + unit for key, unit in [('per_request','次'),('per_second','秒')]
             if key in value]
    return ' + '.join(parts) or '未设置费率'


def conditions(value):
    parts = [OPERATIONS.get(value['operation'], value['operation'])] if value.get('operation') else []
    for key in ('resolution', 'aspect_ratio'):
        if key in value:
            parts.append(value[key])
    if 'minimum_seconds' in value or 'maximum_seconds' in value:
        parts.append(number(value.get('minimum_seconds', 0)) + '–' +
                     number(value['maximum_seconds']) + ' 秒' if 'maximum_seconds' in value else
                     '至少 ' + number(value['minimum_seconds']) + ' 秒')
    return ' · '.join(parts) or '所有参数'


def pricing_text(pricing=None, listed=None):
    """Show actual tier rates, currencies and units without inventing a quote."""
    if pricing:
        currency = pricing.get('currency') or '币种未知'
        if pricing.get('tiers'):
            text = '\n'.join(currency + ' ' + rates(tier) + '（' + conditions(tier['when']) + '）'
                             for tier in pricing['tiers'])
        else:
            text = currency + ' ' + rates(pricing)
        if pricing.get('minimum_seconds'):
            text += '\n最低计费 ' + number(pricing['minimum_seconds']) + ' 秒'
        if pricing.get('round_seconds'):
            text += '\n按 ' + number(pricing['round_seconds']) + ' 秒向上取整'
        if pricing.get('effective_at'):
            text += '\n生效 ' + pricing['effective_at']
        if pricing.get('valid_until'):
            text += '\n有效至 ' + pricing['valid_until']
        if pricing.get('status') == 'unverified':
            text += '\n待核实；不能用于硬预算'
        return text
    if listed:
        currency = listed.get('currency') or ('币种未知 ' + listed.get('display_symbol', '')).strip()
        unit = {'request':'次','second':'秒','image':'张'}.get(listed.get('unit'), '单位未知')
        amount = '?' if listed.get('amount') is None else number(listed['amount'])
        return currency + ' ' + amount + '/' + unit + '（展示价，未用于预算）'
    return '未录入'


def state_text(row):
    if row['archived']:
        return '已归档'
    if row['adapter'] == 'unconfigured' or row['setup_status'] == 'draft':
        return '待接入'
    return '已启用' if row['enabled'] else '已禁用'


def rows(config, *, upstream=None, kind=None, family=None, query='', favorites=False, order='configured'):
    if order not in {'configured','name','upstream','family'}:
        raise ConfigError('Catalog sort must be configured, name, upstream or family')
    terms = query.casefold().split()
    result = []
    for row in catalog(config, upstream=upstream, kind=kind):
        if family and row['family'] != family or favorites and not row['favorite']:
            continue
        haystack = ' '.join(str(row[k]) for k in ('id','display_name','remote_model','family','notes',
                                                 'upstream_name','upstream_id','tags')).casefold()
        if not all(term in haystack for term in terms):
            continue
        result.append({**row, 'state_text': state_text(row),
                       'price_text': pricing_text(row.get('pricing'), row.get('listed_pricing'))})
    if order != 'configured':
        key = {'name':'display_name','upstream':'upstream_name','family':'family'}[order]
        result.sort(key=lambda row: (row[key].casefold(), row['id']))
    return result


def _limits(caps):
    typed = caps.get('media_reference_limits')
    if typed:
        lines = []
        for kind, label in [('image','图片'),('video','视频'),('audio','音频')]:
            item = typed[kind]
            text = label + ' ≤' + str(item['maximum_count']) + '；单文件 ≤' + number(item['maximum_bytes']) + ' 字节'
            if item.get('maximum_duration_seconds'):
                text += '、≤' + number(item['maximum_duration_seconds']) + ' 秒'
            if item.get('maximum_total_duration_seconds'):
                text += '；合计 ≤' + number(item['maximum_total_duration_seconds']) + ' 秒'
            lines.append(text)
        lines.append('允许组合：' + '；'.join('+'.join({'image':'图','video':'视频','audio':'音频'}[k]
            for k in combo) for combo in typed['allowed_combinations']))
        lines.append('所有素材合计 ≤' + str(typed['maximum_total_count']) + ' 份、≤' +
                     number(typed['maximum_total_bytes']) + ' 字节')
        lines.append('音频参考与声音生成同时使用：' + ('允许' if typed['audio_reference_with_generated_audio'] else '不允许'))
        return '\n'.join(lines)
    return '图片总数 ≤' + str(caps.get('max_reference_images', 0)) + '，附加图片 ≤' + str(
        caps.get('max_additional_reference_images', 0)) + '；视频/音频参考未配置'


def card(config, identity, *, store_root=None):
    row = next((r for r in catalog(config) if r['id'] == identity), None)
    if row is None:
        raise ConfigError('Unknown binding for comparison')
    item = config['bindings'][identity]
    model, upstream = config['models'][row['model']], config['upstreams'][row['upstream_id']]
    configured = row['adapter'] != 'unconfigured' and row['setup_status'] != 'draft'
    binding = configured_binding(config, identity) if configured else None
    caps = binding.capabilities if binding else {}
    duration = caps.get('duration')
    duration_text = (number(duration['minimum']) + '–' + number(duration['maximum']) + ' 秒，步长 ' +
                     number(duration['step']) + ' 秒') if duration else '未配置' if row['kind']=='video' else '不适用'
    prompt = caps.get('prompt_limit')
    prompt_text = (number(prompt['maximum']) + '（' + prompt['counting_rule'] + '）') if prompt else (
        number(caps['max_prompt_bytes']) + ' UTF-8 字节') if 'max_prompt_bytes' in caps else '未配置'
    declared = item.get('declared_capabilities', {})
    claim = declared.get('summary', '')
    if not claim and declared:
        count = declared.get('references', {})
        claim = '；'.join(label + ' ' + ('未知' if count[k] is None else str(count[k]))
            for k,label in [('images','图'),('videos','视频'),('audios','音频')] if k in count)
    source = declared.get('source', {})
    fields = {
        '上游 / 账户': row['upstream_name'] + ' / ' + upstream.get('account_id', row['upstream_id']),
        '远端型号（原样）': row['remote_model'], '接入标识': identity,
        '媒体 / 家族': KINDS[row['kind']] + ' / ' + row['family'], '接入状态': state_text(row),
        '可发送操作': '、'.join(OPERATIONS.get(op,op) for op in row['operations']) or '未配置',
        '报价与单位': pricing_text(row.get('pricing'), row.get('listed_pricing')),
        '时长约束': duration_text,
        '画幅 / 分辨率': ('、'.join(caps.get('aspect_ratios', [])) + ' / ' + '、'.join(caps.get('resolutions', [])))
            if row['kind']=='video' and caps else '不适用' if row['kind']=='image' else '未配置',
        '提示词上限': prompt_text, '参考执行约束': _limits(caps) if caps else '未配置',
        '声音开关': {'explicit':'显式发送','model-default':'由模型默认控制','unsupported':'不支持',
            'unknown':'未知','not-applicable':'不适用'}.get(caps.get('audio_control'),'未配置'),
        '图片尺寸 / 输出格式': ('、'.join(caps.get('image_sizes', [])) + ' / ' + '、'.join(caps.get('output_formats', [])))
            if row['kind']=='image' and caps else '不适用' if row['kind']=='video' else '未配置',
        '供应商声明（非实测）': claim or '未录入',
        '声明来源': ' · '.join(source[k] for k in ('kind','observed_at','url') if source.get(k)) or '未录入',
        '型号备注': row['notes'] or '未录入', '上游备注': upstream.get('notes') or '未录入',
        '内部型号备注': model.get('notes') or '未录入',
        '文档': item.get('documentation_url') or upstream.get('documentation_url') or '未录入',
    }
    evidence = {}
    if binding and store_root is not None:
        from .evidence import status
        for op in row['operations']:
            result = status(store_root, binding, operation=op)
            evidence[op] = result
        fields['逐操作实测'] = '\n'.join(OPERATIONS.get(op,op) + '：' + '，'.join(
            STAGES[s] + ' ' + {'reported_pass':'有通过记录','fail':'有失败记录','unverified':'未核实'}[r['status']]
            for s,r in value['stages'].items()) for op,value in evidence.items()) or '未核实'
    else:
        fields['逐操作实测'] = '未配置；声明与启用状态不代表已生成或质量通过' if not configured else '未读取本机证据'
    return {'id': identity, 'name': row['display_name'], 'kind': row['kind'], 'fields': fields,
            'evidence': evidence}


def compare(config, identities, *, store_root=None, scenario=None):
    """A price/parameter preview, explicitly incomplete until actual references exist."""
    if not 2 <= len(identities) <= 4 or len(set(identities)) != len(identities):
        raise ConfigError('Select two to four distinct bindings for comparison')
    scenario = copy.deepcopy(scenario or {})
    if scenario:
        if set(scenario) - {'operation','seconds','resolution','aspect_ratio'}:
            raise ConfigError('Comparison scenario supports operation, seconds, resolution and aspect_ratio')
        if scenario.get('operation') not in OPERATIONS:
            raise ConfigError('Choose a known operation for comparison')
        seconds = scenario.get('seconds', 0)
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ConfigError('Comparison duration must be finite and positive')
    cards = [card(config, identity, store_root=store_root) for identity in identities]
    for result in cards:
        item = config['bindings'][result['id']]
        quote = {'currency': (item.get('pricing') or {}).get('currency'), 'amount': None,
                 'actual_payment': 'unknown'}
        preview = {'errors': [], 'scope': 'parameters-only; no source hashes, references, URLs or credentials checked'}
        if scenario:
            binding = configured_binding(config,result['id']) if item['adapter']!='unconfigured' and item.get('setup_status')!='draft' else None
            if binding:
                request = {'operation':scenario['operation'], 'prompt':''}
                if result['kind']=='video': request.update({k:v for k,v in scenario.items() if k!='operation'})
                preview['errors'] = validate_request(binding, request)['errors']
                if quote['currency']:
                    quote['amount'] = estimate(binding,scenario['seconds'],quote['currency'],parameters=scenario)
            else:
                preview['errors'].append('Protocol is not configured')
            if not item['enabled'] or item.get('archived') or config['upstreams'][item['upstream']].get('archived') or config['models'][item['model']].get('archived'):
                preview['errors'].append('Binding is disabled or archived')
            # A quote is still a quote for invalid parameters, never approval.
            preview['status'] = 'incompatible' if preview['errors'] else 'parameters-only'
            result['fields']['本次参数预览'] = '；'.join(preview['errors']) or '参数范围相符；尚未检查素材、凭据与完整请求'
            result['fields']['本次估算（非实付）'] = (quote['currency'] + ' ' + number(quote['amount'])) if quote['amount'] is not None else '未知，不能用于硬预算'
        result.update(quote=quote, parameter_preview=preview)
    return {'ok':True, 'cards':cards, 'scenario':scenario, 'paid_creates':0,
        'note':'报价按各自币种展示；未兑换或按价格排名。参数预览不批准请求，参考和完整运行预检仍须通过。'}
