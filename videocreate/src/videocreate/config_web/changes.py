"""Whitelisted configuration changes and recoverable credential/config commits."""
import copy
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from ..config import management as m, repair
from ..config.schema import validate_config
from ..config.secrets import store_credential
from ..config.storage import ConfigError, atomic_json, load_json
from ..runtime.state import state_lock
from .errors import WebError
from .backups import Backups

TOKEN = re.compile(r'^[0-9a-f]{48}$')
META = {'display_name', 'notes', 'tags', 'favorite', 'sort_order', 'documentation_url'}


def fields(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise WebError('invalid_fields', '请求包含不支持的字段。')


def text(value, name, *, required=False, limit=16000):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise WebError('invalid_field', '请检查此字段的内容或长度。', field=name)
    return value.strip()


def endpoint(value):
    value = text(value, 'url', required=True, limit=2048).rstrip('/')
    try:
        u = urlsplit(value)
        if (u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment
                or (u.port is not None and not 1 <= u.port <= 65535) or any(c.isspace() for c in value)):
            raise ValueError()
    except ValueError:
        raise WebError('invalid_url', '请填写不含账户、密钥、查询或片段的 HTTPS API 地址。', field='url') from None
    return value


class Changes:
    def __init__(self, service, *, read_only=None):
        self.service = service
        self.read_only = service.read_only if read_only is None else read_only
        self.previews = {}
        self.folder = service.path.parent / 'runtime' / 'config-web' / service.identity / 'changes'
        self.backups = Backups(service)

    def require_editable(self):
        if self.read_only:
            raise WebError('read_only', '当前服务以只读模式运行。', status=403)
        record = m.load(self.service.path)
        if not record['editable'] or record['config']['schema_version'] != 4:
            raise WebError('not_editable', '此配置需要先迁移或修复，原文件保留。', status=409, reload=True)
        return record

    def prepare(self, value, operation, identity, data, token):
        result = copy.deepcopy(value)
        credential = None
        if operation == 'upstream.create':
            fields(data, {'url', 'name', 'notes'})
            url = endpoint(data.get('url'))
            identity = 'upstream-' + token[:20]
            account = 'account-' + token[:20]
            version = token[20:40]
            credential = {'account': account, 'version': version}
            result['upstreams'][identity] = {
                'base_url': url, 'display_name': text(data.get('name', ''), 'name', limit=200) or urlsplit(url).hostname,
                'notes': text(data.get('notes', ''), 'notes'), 'account_id': account,
                'credential_version': version,
                'auth': {'type': 'bearer', 'secret_ref': 'provider_accounts.' + account + '.' + version}}
        elif operation in {'upstream.update', 'upstream.archive', 'upstream.rotate'}:
            if identity not in result['upstreams']:
                raise WebError('unknown_upstream', '找不到所选上游，请刷新。', status=409, reload=True)
            upstream = result['upstreams'][identity]
            if operation == 'upstream.update':
                fields(data, {'name', 'notes'})
                for key, target in [('name', 'display_name'), ('notes', 'notes')]:
                    if key in data:
                        upstream[target] = text(data[key], key, limit=200 if key == 'name' else 16000)
            elif operation == 'upstream.archive':
                fields(data, set())
                result = m.archive(result, 'upstreams', identity)
            else:
                fields(data, {'same_account'})
                if data.get('same_account') is not True:
                    raise WebError('account_confirmation_required', '仅同账户换钥可轮换；更换账户请添加新的上游实例。', field='same_account')
                account = upstream.get('account_id', identity)
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', account):
                    raise WebError('legacy_account_id', '此旧账户标识不能直接轮换，请先通过 Codex 整理账户身份。')
                version = token[:20]
                credential = {'account': account, 'version': version}
                upstream.update(account_id=account, credential_version=version,
                                auth={'type': 'bearer', 'secret_ref': 'provider_accounts.' + account + '.' + version})
        elif operation == 'binding.update':
            allowed = META | {'enabled', 'setup_status', 'remote_model', 'adapter', 'operations',
                              'declared_capabilities', 'capability_overrides', 'pricing', 'listed_pricing', 'adapter_options'}
            fields(data, allowed)
            if identity not in result['bindings']:
                raise WebError('unknown_binding', '接入已变更，请刷新。', status=409, reload=True)
            target = result['bindings'][identity]
            optional = {'declared_capabilities', 'capability_overrides', 'pricing', 'listed_pricing', 'adapter_options'}
            for key, item in data.items():
                if key in optional and item is None:
                    # Explicitly clearing a claim restores unknown pricing or
                    # capabilities; never substitute a zero/default rate.
                    target.pop(key, None)
                else:
                    target[key] = copy.deepcopy(item)
        elif operation == 'defaults.update':
            fields(data, {'image', 'video'})
            for kind, choice in data.items():
                fields(choice, {'binding', 'policy'})
                if choice.get('policy') not in {'ask', 'use-default'}:
                    raise WebError('invalid_policy', '请选择先询问或沿用默认。', field=kind)
                bid = choice.get('binding')
                if bid:
                    b = result['bindings'].get(bid)
                    if (not b or result['models'][b['model']]['kind'] != kind or not b['enabled'] or b.get('archived')
                            or result['upstreams'][b['upstream']].get('archived') or result['models'][b['model']].get('archived')
                            or b['adapter'] == 'unconfigured' or b.get('setup_status') == 'draft' or not b['operations']):
                        raise WebError('invalid_default', '请选择有效且已启用的接入。', field=kind)
                    route = result['routes'].get(b['model'])
                    if not route or bid not in route['candidates']:
                        raise WebError('invalid_default_route', '此接入尚未登记到模型路线。', field=kind)
                    route['preferred_binding'] = bid
                    result['defaults'][kind + '_model'] = b['model']
                elif choice['policy'] == 'use-default':
                    raise WebError('default_required', '直接沿用默认前，请先选择接入。', field=kind)
                result.setdefault('selection', {})[kind] = {'when_unspecified': choice['policy'], 'remember_scope': 'project'}
        elif operation == 'config.restore':
            fields(data, {'backup_id'})
            _, old = self.backups.get(data.get('backup_id'))
            result = m.restore_candidate(value, old)
        elif operation == 'catalog.import':
            from datetime import datetime, timezone
            from ..catalog import observations, discovery
            fields(data, {'observation_id', 'ids', 'kind'})
            if data.get('kind') not in {'image', 'video'}:
                raise WebError('invalid_kind', '请明确图片或视频类型，不按型号名称猜测。')
            observed = observations.show(value, identity, store_root=self.service.path.parent)
            if observed.get('observation', {}).get('observation_hash') != data.get('observation_id'):
                raise WebError('observation_changed', '目录观察已变化，请重新选择。', status=409, reload=True)
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(observed['observed_at'])).total_seconds()
            if not 0 <= age <= 86400:
                raise WebError('observation_expired', '目录观察已过期，请明确刷新目录后再导入。', status=409)
            if not data.get('ids'):
                raise WebError('empty_import', '请至少选择一个精确型号。')
            result, _ = discovery.import_models(value, identity, data.get('ids'), kind=data['kind'],
                                                observation=observed['observation'])
        elif operation == 'contract.apply':
            from ..catalog import contracts
            fields(data, {'contract_id', 'revision'})
            result, identity = contracts.apply(value, identity, data.get('contract_id'), data.get('revision'))
        else:
            raise WebError('unknown_operation', '此配置操作尚不受支持。')
        errors = validate_config(result)
        if errors:
            # Raw schema diagnostics can include the user's submitted data.
            raise WebError('invalid_configuration', '配置字段或操作组合不符合合同，请检查输入。')
        return result, identity, credential

    def preview(self, packet, *, session):
        fields(packet, {'expected_token', 'operation', 'id', 'values'})
        text(packet.get('operation'), 'operation', required=True, limit=100)
        if packet.get('id') is not None:
            text(packet['id'], 'id', required=True, limit=128)
        token = secrets.token_hex(24)
        repair_args, extra = None, {}
        if packet['operation'] == 'config.repair':
            fields(packet.get('values'), {'backup_id'})
            repair_args, extra = self.backups.prepare_repair(packet['values'].get('backup_id'), packet.get('expected_token'))
            before, candidate, identity, credential = packet['expected_token'], None, None, None
        else:
            record = self.require_editable()
            if packet.get('expected_token') != record['token']:
                raise WebError('configuration_conflict', '配置已在其他窗口修改，请刷新后合并。', status=409, reload=True)
            before = record['token']
            candidate, identity, credential = self.prepare(record['config'], packet.get('operation'), packet.get('id'), packet.get('values', {}), token)
            if packet['operation'] == 'config.restore':
                extra = {'counts': {k: len(candidate[k]) for k in ('upstreams', 'models', 'bindings', 'routes')},
                         'changed_count': len(m.changed_paths(record['config'], candidate))}
        self.previews = {k: v for k, v in self.previews.items() if v['expires'] > time.monotonic()}
        if len(self.previews) >= 128:
            raise WebError('preview_limit', '待保存预览过多，请稍后重试。', status=429)
        self.previews[token] = {'session': session, 'expires': time.monotonic() + 600,
                                'before': before, 'candidate': candidate, 'credential': credential, 'repair': repair_args,
                                'backup_id': packet.get('values', {}).get('backup_id'),
                                'identity': identity, 'operation': packet['operation']}
        # Names only, never a JSON diff of old auth or new credential references.
        return {'preview_token': token, 'id': identity, 'credential_required': bool(credential),
                'changed_fields': sorted(packet.get('values', {})), 'expires_in': 600, 'paid_creates': 0, **extra}

    def journal_path(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise WebError('invalid_preview', '保存标识无效，请重新预览。')
        return self.folder / (token + '.json')

    def reconcile(self, journal):
        if journal.get('status') == 'committed':
            return True
        after = journal.get('expected_after')
        if after:
            try:
                current = load_json(self.service.path)
            except (ConfigError, OSError, ValueError):
                current = None
            backup = self.service.path.parent / 'backups' / (self.service.path.stem + '-' + after + '.json')
            if m.fingerprint(current) == after or (backup.is_file() and m.fingerprint(load_json(backup)) == after):
                journal.update(status='committed', result={'ok': True, 'changed': True, 'id': journal['id'],
                               'token': after, 'recovered': True, 'paid_creates': 0})
                return True
        return journal.get('status') == 'committed'

    def status(self, packet):
        fields(packet, {'preview_token'})
        self.journal_path(packet.get('preview_token'))
        # A disconnected browser may reconcile while the original commit is
        # still encrypting/writing. Never report "not submitted" mid-commit.
        with state_lock(self.service.path.parent / 'web-change-lock'):
            return self._status(packet)

    def _status(self, packet):
        target = self.journal_path(packet.get('preview_token'))
        if not target.is_file():
            return {'status': 'not-submitted'}
        journal = load_json(target)
        if self.reconcile(journal):
            return {'status': 'committed', 'result': journal['result']}
        try:
            current = self.service.path.read_bytes()
            current_token = (repair.sha(current) if journal.get('operation') == 'config.repair'
                             else m.fingerprint(load_json(self.service.path)))
        except (ConfigError, OSError, ValueError):
            current_token = None
        if current_token == journal['before']:
            return {'status': 'not-committed', 'credential_staged': journal.get('status') == 'credential-staged'}
        return {'status': 'unknown', 'message': '配置已有其他变更，请先核对当前目录；不会自动重复新增。'}

    def commit(self, packet, *, session):
        fields(packet, {'preview_token', 'credential'})
        token = packet.get('preview_token')
        target = self.journal_path(token)
        if self.read_only:
            raise WebError('read_only', '当前服务以只读模式运行。', status=403)
        # Serializes Web receipts; CLI writes still use management.save's own lock/token.
        with state_lock(self.service.path.parent / 'web-change-lock'):
            journal = load_json(target) if target.is_file() else None
            if journal is not None:
                # Reconcile completed writes after restart by unguessable receipt
                # ID. This path grants no permission to perform pending writes.
                if self.reconcile(journal):
                    atomic_json(target, journal)
                    return journal['result']
                if journal.get('session') != m.fingerprint(session):
                    raise WebError('preview_owner', '保存记录属于另一个会话，请重新核对。', status=403)
            preview = self.previews.get(token)
            if not preview or preview['expires'] <= time.monotonic() or preview['session'] != session:
                raise WebError('preview_expired', '保存预览已失效，请重新核对；原配置和已保存凭据版本保留。', status=409, reload=True)
            if preview.get('repair'):
                current_token = repair.sha(self.service.path.read_bytes())
            else:
                current_token = self.require_editable()['token']
            if preview.get('backup_id'):
                self.backups.get(preview['backup_id'])
            if current_token != preview['before']:
                raise WebError('configuration_conflict', '配置已变更，请刷新后合并；本次未覆盖。', status=409, reload=True)
            journal = journal or {'status': 'prepared', 'session': m.fingerprint(session), 'id': preview['identity'],
                                   'before': preview['before'], 'operation': preview['operation']}
            atomic_json(target, journal)
            if preview['credential'] and journal.get('status') != 'credential-staged':
                key = text(packet.get('credential', ''), 'credential', required=True, limit=16384)
                if key in {'***', '••••••••'}:
                    raise WebError('invalid_credential', '请输入实际密钥。', field='credential')
                c = preview['credential']
                store_credential(self.service.path.parent, c['account'], key, version=c['version'])
                journal['status'] = 'credential-staged'
                atomic_json(target, journal)
            elif packet.get('credential') and not preview['credential']:
                raise WebError('unexpected_credential', '此操作不接受密钥，请使用专用换钥入口。')

            def prepared(after):
                journal['expected_after'] = after
                atomic_json(target, journal)
            try:
                if preview.get('repair'):
                    args = preview['repair']
                    saved = repair.apply(self.service.path, **args, on_prepared=prepared)
                else:
                    saved = m.save(self.service.path, preview['candidate'], expected_token=preview['before'],
                                   reason='Web configuration change ' + token, on_prepared=prepared)
            except ConfigError:
                raise WebError('configuration_conflict', '配置未能提交，请重新读取后核对；已加密的新凭据版本保留。', status=409, reload=True) from None
            result = {'ok': True, 'changed': saved.get('changed', True), 'id': preview['identity'],
                      'token': saved['token'], 'revision': saved.get('revision'),
                      'warning': '配置已保存，但历史记录写入失败；备份已保留。' if saved.get('warning') else None,
                      'paid_creates': 0}
            journal.update(status='committed', result=result)
            try:
                atomic_json(target, journal)
            except OSError:
                # Prepared hash already persisted; retry reconciles actual bytes.
                result['warning'] = '配置已保存，提交回执暂未写入；重试会核对原提交。'
            return result
