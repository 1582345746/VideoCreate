"""Nonsecret Web drafts: explicit fields, tab capability, source and form version."""
import math
import hashlib
import heapq
import secrets
import time

from ..config import management as m
from ..config.schema import configuration_schema
from ..config.storage import ConfigError, atomic_json, parse_json
from ..runtime.state import state_lock
from .changes import fields, text, endpoint, TOKEN
from .errors import WebError

TTL = 7 * 24 * 60 * 60
SECTIONS = {'declared_capabilities', 'capability_overrides', 'listed_pricing', 'pricing', 'adapter_options'}


def raw_text(value, name, limit=16000):
    # A draft preserves whitespace and incomplete numeric input, not just values
    # that could already be committed to the authoritative configuration.
    text(value, name, limit=limit)
    return value


def safe_section(value, schema, depth=0, name=''):
    """Only named schema fields; never persist arbitrary nested JSON objects."""
    if depth > 20:
        return False
    if isinstance(value, dict):
        if schema.get('type') != 'object':
            return False
        props = schema.get('properties', {})
        return all(key in props and safe_section(child, props[key], depth+1, key) for key, child in value.items())
    if isinstance(value, list):
        return len(value) <= 1000 and 'items' in schema and all(safe_section(v, schema['items'], depth+1) for v in value)
    kinds = schema.get('type', [])
    if isinstance(kinds, str):
        kinds = [kinds]
    if isinstance(value, str):
        if 'string' not in kinds or len(value) > 16000:
            return False
        # Source URLs must not become an alternate credential channel.
        candidate = value.strip()
        if candidate and (name == 'url' or candidate.lower().startswith(('http:', 'https:'))):
            try:
                endpoint(candidate)
            except WebError:
                return False
        return True
    return value is None or type(value) in {bool, int} or (type(value) is float and math.isfinite(value))


class Drafts:
    def __init__(self, service):
        self.service = service
        self.folder = service.path.parent / 'runtime' / 'config-web' / service.identity / 'drafts'

    def path(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise WebError('invalid_draft', '草稿标识无效。')
        return self.folder / (token + '.json')

    def raw(self, token, *, missing_ok=False):
        target = self.path(token)
        if target.is_symlink():
            raise WebError('invalid_draft', '草稿文件不可读取。')
        if not target.is_file():
            if missing_ok:
                return None, None
            raise WebError('draft_missing', '草稿不存在或已丢弃。', status=404)
        # Bound parsing memory even for a damaged local file. Its exact byte
        # digest still permits an explicit, version-checked discard.
        digest, chunks, size = hashlib.sha256(), [], 0
        with target.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                digest.update(chunk); size += len(chunk)
                if size <= 512 * 1024:
                    chunks.append(chunk)
        return b''.join(chunks) if size <= 512 * 1024 else None, digest.hexdigest()

    def checked(self, raw):
        try:
            row = parse_json(raw.decode('utf-8-sig'))
        except (AttributeError, UnicodeError, ConfigError, RecursionError):
            raise WebError('draft_corrupt', '草稿文件无法读取，原记录保留。', status=409) from None
        if (type(row.get('schema_version')) is not int or row['schema_version'] != 1
                or type(row.get('form_version')) is not int or row['form_version'] not in (1, 2)
                or row.get('config_id') != self.service.identity):
            raise WebError('draft_version', '草稿版本或来源不受支持，原记录保留。', status=409)
        if (type(row.get('expires_at')) not in {int, float} or not math.isfinite(row['expires_at'])
                or not self.is_version(row.get('source_token')) or not self.is_version(row.get('owner'))
                or not isinstance(row.get('form'), dict)
                or not isinstance(row.get('omitted_sections', []), list)
                or any(not isinstance(k, str) or k not in SECTIONS for k in row.get('omitted_sections', []))):
            raise WebError('draft_corrupt', '草稿字段无效，原记录保留。', status=409)
        if row['expires_at'] <= time.time():
            raise WebError('draft_expired', '草稿已超过七天，请重新填写。', status=409)
        # Validate the persisted form again, never pass arbitrary JSON through.
        try:
            form, omitted = self.form(row['form'])
        except (TypeError, ValueError, RecursionError):
            raise WebError('draft_corrupt', '草稿字段无效，原记录保留。', status=409) from None
        if row['form_version'] == 1 and form.get('kind'):
            raise WebError('draft_version', '草稿版本不匹配，原记录保留。', status=409)
        row['form'] = form
        row['omitted_sections'] = sorted(set(row.get('omitted_sections', [])) | set(omitted))
        return row

    @staticmethod
    def is_version(value):
        return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)

    def compare(self, packet, current):
        expected = packet.get('expected_version')
        if (expected is not None and not self.is_version(expected)):
            raise WebError('invalid_draft_version', '草稿版本标识无效。')
        if expected != current:
            raise WebError('draft_conflict', '草稿已被另一窗口更新或丢弃。当前输入保留，请重新读取或另存新草稿。', status=409)

    def list(self, packet, *, session):
        fields(packet, {'cursor', 'limit'})
        cursor, limit = packet.get('cursor', ''), packet.get('limit', 25)
        if cursor:
            self.path(cursor)
        if not isinstance(cursor, str) or type(limit) is not int or not 1 <= limit <= 50:
            raise WebError('invalid_draft_page', '草稿列表分页无效。')
        rows = []
        with state_lock(self.folder):
            names = heapq.nsmallest(limit + 1, (p.stem for p in self.folder.glob('*.json')
                if TOKEN.fullmatch(p.stem) and p.stem > cursor and p.is_file() and not p.is_symlink()))
            for token in names[:limit]:
                raw, version = self.raw(token)
                item = {'draft_token':token, 'draft_version':version, 'kind':'unknown',
                        'updated_at':self.path(token).stat().st_mtime, 'expires_at':None, 'status':'unavailable'}
                try:
                    row = self.checked(raw)
                    item.update(kind=row['form'].get('kind', 'upstream'), status='available', expires_at=row['expires_at'])
                except WebError as error:
                    item['status'] = {'draft_expired':'expired', 'draft_version':'unsupported'}.get(error.code, 'unavailable')
                rows.append(item)
        return {'drafts':rows, 'next_cursor':names[limit-1] if len(names) > limit else None, 'config_changed':False}

    @staticmethod
    def form(value):
        if isinstance(value, dict) and value.get('kind') == 'defaults':
            fields(value, {'kind', 'image', 'video'})
            result = {'kind': 'defaults'}
            for kind in ('image', 'video'):
                choice = value.get(kind)
                fields(choice, {'binding', 'policy'})
                if choice.get('policy') not in {'ask', 'use-default'}:
                    raise WebError('draft_form', '默认策略草稿无效。')
                result[kind] = {'binding': raw_text(choice.get('binding', ''), 'binding', 128), 'policy': choice['policy']}
            return result, []
        if isinstance(value, dict) and value.get('kind') == 'repair':
            fields(value, {'kind', 'mode', 'backup_id'})
            if value.get('mode') not in {'repair', 'restore'}:
                raise WebError('draft_form', '修复草稿模式无效。')
            from .backups import BACKUP_ID
            identity = value.get('backup_id')
            if not isinstance(identity, str) or not BACKUP_ID.fullmatch(identity):
                raise WebError('draft_form', '修复草稿只能保留列表中的备份标识。')
            return dict(value), []
        if isinstance(value, dict) and value.get('kind') == 'binding':
            fields(value, {'kind', 'id', 'display_name', 'notes', 'favorite', 'sort_order', 'tags',
                           'advanced', 'enabled', 'remote_model', 'adapter', 'operations', 'setup_status', 'sections'})
            result = {'kind': 'binding'}
            for key, limit in [('id', 128), ('display_name', 200), ('notes', 16000), ('sort_order', 100),
                               ('tags', 16000), ('remote_model', 200), ('adapter', 100), ('setup_status', 100)]:
                result[key] = raw_text(value.get(key, ''), key, limit)
            for key in ('favorite', 'advanced', 'enabled'):
                if type(value.get(key)) is not bool:
                    raise WebError('draft_form', '模型草稿选项无效。')
                result[key] = value[key]
            operations = value.get('operations')
            from ..config.schema import OPERATIONS
            if not isinstance(operations, list) or len(operations) > len(OPERATIONS) or any(op not in OPERATIONS for op in operations):
                raise WebError('draft_form', '模型草稿操作无效。')
            result['operations'] = operations
            sections = value.get('sections', {})
            fields(sections, SECTIONS)
            schema = configuration_schema()['properties']['bindings']['additionalProperties']['properties']
            result['sections'], omitted = {}, []
            for key, raw in sections.items():
                raw = raw_text(raw, key)
                try:
                    parsed = parse_json(raw)
                    if not isinstance(parsed, dict) or not safe_section(parsed, schema[key]):
                        raise ValueError()
                    result['sections'][key] = raw
                except (ConfigError, ValueError, RecursionError):
                    omitted.append(key)
            return result, sorted(omitted)
        fields(value, {'mode', 'id', 'url', 'name', 'notes'})
        if value.get('mode') not in {'create', 'copy', 'update'}:
            raise WebError('draft_form', '此表单不支持恢复。')
        result = {key: text(value.get(key, ''), key, limit=128 if key=='id' else 200 if key=='name' else 2048 if key=='url' else 16000)
                  for key in ('mode','id','url','name','notes')}
        if result['url']:
            result['url'] = endpoint(result['url'])
        return result, []

    def save(self, packet, *, session):
        fields(packet, {'draft_token','source_token','form','expected_version'})
        if self.service.read_only:
            raise WebError('read_only', '只读服务不保存表单草稿。', status=403)
        form, omitted = self.form(packet.get('form'))
        source = packet.get('source_token')
        if not isinstance(source, str) or len(source)!=64 or any(c not in '0123456789abcdef' for c in source):
            raise WebError('draft_source', '草稿缺少有效配置来源。')
        token = packet.get('draft_token') or secrets.token_hex(24)
        target = self.path(token)
        with state_lock(self.folder):
            raw, version = self.raw(token, missing_ok=True)
            self.compare(packet, version)
            if version:
                old = self.checked(raw)
                if old['owner'] != m.fingerprint(session):
                    raise WebError('draft_owner', '请先明确恢复此标签页的草稿，再编辑。', status=409)
                if (old['form'].get('kind'), old['form'].get('id')) != (form.get('kind'), form.get('id')):
                    raise WebError('draft_form', '不同表单或模型必须使用独立草稿。', status=409)
            row = {'schema_version':1,'form_version':2 if form.get('kind') else 1,'config_id':self.service.identity,
                   'owner':m.fingerprint(session),'source_token':source,'form':form,'expires_at':time.time()+TTL,
                   'omitted_sections':omitted, 'updated_at':time.time(), 'claim_nonce':secrets.token_hex(24)}
            atomic_json(target, row)
            _, version = self.raw(token)
        return {'draft_token':token,'draft_version':version,'expires_in':TTL,'credential_saved':False,'omitted_sections':omitted}

    def load(self, packet, *, session):
        fields(packet, {'draft_token','claim','expected_version'})
        token = packet.get('draft_token')
        self.path(token)
        if type(packet.get('claim', False)) is not bool:
            raise WebError('invalid_claim', '草稿恢复选项无效。')
        if packet.get('claim') is True:
            if self.service.read_only:
                raise WebError('read_only', '只读服务不修改草稿。', status=403)
        with state_lock(self.folder):
            raw, version = self.raw(token)
            if packet.get('claim') or packet.get('expected_version') is not None:
                self.compare(packet, version)
            row = self.checked(raw)
            if packet.get('claim') is True:
                row['owner'] = m.fingerprint(session)
                row['claim_nonce'] = secrets.token_hex(24)
                atomic_json(self.path(token), row)
                _, version = self.raw(token)
        summary = self.service.summary()
        source = summary.get('token')
        if row['form'].get('kind') == 'repair' and row['form']['mode'] == 'repair':
            from ..config.repair import sha
            try:
                source = sha(self.service.path.read_bytes())
            except OSError:
                source = None
        return {'draft_token':token,'draft_version':version,'source_token':row['source_token'],'form':row['form'],
                'conflict':row['source_token']!=source,'expires_at':row['expires_at'],
                'credential_saved':False,'omitted_sections':row['omitted_sections']}

    def discard(self, packet, *, session):
        fields(packet, {'draft_token','expected_version'})
        if self.service.read_only:
            raise WebError('read_only', '只读服务不修改草稿。', status=403)
        target = self.path(packet.get('draft_token'))
        with state_lock(self.folder):
            _, version = self.raw(packet.get('draft_token'), missing_ok=True)
            if version is not None:
                self.compare(packet, version)
                target.unlink()
        return {'discarded':True,'config_changed':False}
