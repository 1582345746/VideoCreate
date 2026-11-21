"""Explicit catalog reads and safe account-bound observation projections."""
from ..catalog import discovery, observations, contracts
from ..config import management as m
from ..config.storage import ConfigError
from .changes import fields, text
from .dto import cleaner
from .errors import WebError


class Checks:
    def __init__(self, service):
        self.service = service

    def read(self, packet, *, refresh=False):
        fields(packet, {'upstream'})
        uid = text(packet.get('upstream'), 'upstream', required=True, limit=128)
        record = m.load(self.service.path)
        config = record['config']
        if record['errors'] or uid not in config['upstreams']:
            raise WebError('invalid_upstream', '请先保存有效上游，再进行只读检查。')
        if config['upstreams'][uid].get('archived') and refresh:
            raise WebError('archived_upstream', '此上游已归档，不再进行新目录检查。')
        failure = None
        try:
            value = (discovery.models(config, uid, store_root=self.service.path.parent) if refresh else
                     observations.show(config, uid, store_root=self.service.path.parent))
        except ConfigError as exc:
            message = str(exc)
            code = ('unauthorized' if 'HTTP 401' in message or 'HTTP 403' in message else
                    'not-supported' if 'HTTP 404' in message or 'response format' in message else
                    'redirect-blocked' if 'HTTP 30' in message else
                    'credential-unavailable' if 'credential' in message else 'read-failed')
            failure = {'status': code, 'message': {'unauthorized': '目录鉴权失败，请核对账户密钥。',
                    'not-supported': '上游没有受支持的目录接口；已保存配置可继续按已知文档整理。',
                    'redirect-blocked': '目录发生重定向，已停止，未向新地址转发密钥。',
                    'credential-unavailable': '当前 Windows 账户无法读取此上游的已存凭据。',
                    'read-failed': '目录读取失败或超时，请稍后明确重试。'}[code],
                    'config_changed': False, 'paid_creates': 0}
        # Document recipes do not depend on a successful /models request.
        # Both success and failure must still belong to the current account/address.
        try:
            latest = m.load(self.service.path)
            origin = observations.identity(latest['config'], uid) if not latest['errors'] else None
        except (OSError, ValueError):
            origin = None
        if observations.identity(config, uid) != origin:
            raise WebError('catalog_source_changed', '上游地址或账户已变化，请重新检查。', status=409, reload=True)
        available = contracts.available(latest['config'], uid)
        if failure is not None:
            return {**failure, 'rows': [], 'contracts': available}
        clean = cleaner(config)
        rows = [{key: clean(row[key]) if isinstance(row[key], str) else row[key]
                 for key in ('remote_model', 'catalog_status', 'local_status', 'change', 'importable')}
                for row in value.get('rows', [])]
        return {'status': value.get('status', 'observed'), 'rows': rows,
                'observation_id': value.get('observation', {}).get('observation_hash'),
                'observed_at': value.get('observed_at'), 'contracts': available,
                'config_changed': False, 'network_requests': value.get('network_requests', 0), 'paid_creates': 0}
