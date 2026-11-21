"""Offline comparisons/evidence and preview-bound anonymous diagnostic exports."""
import secrets
import time

from .. import diagnostics
from ..catalog import presentation, suitability, evidence
from ..catalog.bindings import configured_binding
from ..config import management as m
from ..config.storage import ConfigError
from .changes import fields, TOKEN
from .dto import cleaner
from .errors import WebError


class Inspections:
    def __init__(self, service):
        self.service = service
        self.previews = {}
        self.folder = service.path.parent / 'diagnostics' / 'config-web' / service.identity

    def config(self):
        row = m.load(self.service.path)
        if row['errors']:
            raise WebError('invalid_configuration', '请先修复配置，再查看本机证据。')
        return row['config']

    def evidence(self, packet):
        fields(packet, {'binding'})
        value = self.config(); bid = packet.get('binding')
        if not isinstance(bid, str) or bid not in value['bindings']:
            raise WebError('unknown_binding', '请选择当前目录中的接入。')
        item = value['bindings'][bid]
        result = {}
        if item['adapter'] != 'unconfigured':
            binding = configured_binding(value, bid)
            for op in item['operations']:
                row = evidence.status(self.service.path.parent, binding, operation=op)
                result[op] = {stage: {'status': r['status'], 'receipt_count': len(r['receipts'])}
                              for stage, r in row['stages'].items()}
        return {'binding': bid, 'config_token': m.fingerprint(value), 'operations': result,
                'paid_creates': 0, 'network_requests': 0}

    def filter(self, packet):
        fields(packet, {'scenario'})
        value = self.config(); result = suitability.query(value, packet.get('scenario'))
        clean = cleaner(value)
        return {'rows': [{'id': clean(row['id']), 'fit': {**row['task_fit'],
                    **{key: [clean(s) for s in row['task_fit'][key]] for key in ('reasons','unknowns','warnings')}}}
                        for row in result['bindings']], 'counts': result['counts'],
                'paid_creates': 0, 'network_requests': 0}

    def compare(self, packet):
        fields(packet, {'bindings', 'scenario'})
        ids = packet.get('bindings')
        if not isinstance(ids, list) or any(not isinstance(bid, str) for bid in ids):
            raise WebError('invalid_comparison', '请选择二至四个不同接入。')
        value = self.config(); clean = cleaner(value)
        result = presentation.compare(value, ids, store_root=self.service.path.parent, scenario=packet.get('scenario'))
        # Account identities, raw URLs, local evidence and task paths never leave.
        safe = {'远端型号（原样）','媒体 / 家族','接入状态','可发送操作','报价与单位','时长约束',
                '画幅 / 分辨率','提示词上限','参考执行约束','声音开关','图片尺寸 / 输出格式',
                '供应商声明（非实测）','型号备注','逐操作实测','本次参数预览','本次估算（非实付）','本次计费说明'}
        return {'cards': [{'id': clean(card['id']), 'name': clean(card['name']),
                           'fields': {key: clean(v) for key, v in card['fields'].items() if key in safe}}
                          for card in result['cards']], 'paid_creates': 0, 'network_requests': 0}

    def diagnostic_preview(self, packet, *, session):
        fields(packet, set())
        preview = diagnostics.preview(self.service.path)
        token = secrets.token_hex(24)
        self.previews = {k: v for k, v in self.previews.items() if v['expires'] > time.monotonic()}
        if len(self.previews) >= 64:
            raise WebError('preview_limit', '待导出预览过多，请稍后重试。', status=429)
        self.previews[token] = {'preview': preview, 'session': session, 'expires': time.monotonic()+600}
        return {'preview_token': token, 'report': preview['report'], 'expires_in': 600}

    def diagnostic_export(self, packet, *, session):
        fields(packet, {'preview_token'})
        token = packet.get('preview_token')
        row = self.previews.get(token) if isinstance(token, str) else None
        if not row or row['expires'] <= time.monotonic() or row['session'] != session:
            raise WebError('preview_expired', '诊断预览已失效，请重新预览。', status=409)
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / ('diagnostic-' + token + '.json')
        try:
            diagnostics.export(self.service.path, row['preview'], target, token=row['preview']['preview_token'])
        except ConfigError:
            raise WebError('diagnostic_changed', '配置或证据已变化，或目标文件已存在；请重新预览后导出。', status=409, reload=True) from None
        return {'id': token, 'filename': target.name, 'download_url': '/api/diagnostics/files/' + token,
                'paid_creates': 0, 'network_requests': 0}

    def exported(self, token):
        if not TOKEN.fullmatch(token):
            raise WebError('unknown_export', '诊断文件不存在。', status=404)
        target = self.folder / ('diagnostic-' + token + '.json')
        if not target.is_file() or target.is_symlink() or target.resolve().parent != self.folder.resolve():
            raise WebError('unknown_export', '诊断文件不存在。', status=404)
        return target
