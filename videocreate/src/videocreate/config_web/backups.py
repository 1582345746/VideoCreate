"""Controlled backup IDs: no browser-selected paths or raw configuration bytes."""
import hashlib
import re

from ..config import management as m, repair
from ..config.schema import validate_config
from ..config.storage import ConfigError, load_json
from .errors import WebError

BACKUP_ID = re.compile(r'^[0-9a-f]{64}$')


class Backups:
    def __init__(self, service):
        self.service = service
        self.folder = service.path.parent / 'backups'

    def get(self, identity):
        if not isinstance(identity, str) or not BACKUP_ID.fullmatch(identity):
            raise WebError('invalid_backup', '请选择列表中的有效备份。')
        target = self.folder / (self.service.path.stem + '-' + identity + '.json')
        if target.is_symlink() or target.resolve().parent != self.folder.resolve() or not target.is_file():
            raise WebError('backup_missing', '备份不可用，请重新读取列表。', status=409, reload=True)
        value = load_json(target)
        if validate_config(value) or value.get('schema_version') not in {3, 4} or m.fingerprint(value) != identity:
            raise WebError('backup_changed', '备份内容已变化或不受支持，原文件保留。', status=409, reload=True)
        return target, value

    def inspect(self):
        rows = []
        prefix = self.service.path.stem + '-'
        for target in self.folder.glob(prefix + '*.json'):
            identity = target.stem[len(prefix):]
            if not BACKUP_ID.fullmatch(identity):
                continue
            try:
                _, value = self.get(identity)
                rows.append({'id': identity, 'revision': value.get('revision', 0),
                             'schema_version': value['schema_version'],
                             'counts': {k: len(value[k]) for k in ('upstreams', 'models', 'bindings', 'routes')}})
            except (ConfigError, WebError, OSError, ValueError):
                continue
        rows.sort(key=lambda row: (row['revision'], row['id']), reverse=True)
        summary = self.service.summary()
        try:
            raw = self.service.path.read_bytes()
            source = hashlib.sha256(raw).hexdigest()
            # Do not return repair.inspect() errors: these can contain old keys.
            _, _, state = repair._read(self.service.path)
            can_repair = state['can_repair'] and not self.service.read_only
        except (OSError, ConfigError, ValueError):
            source, can_repair = None, False
        return {'summary': summary, 'source_token': source, 'can_repair': can_repair,
                'backups': rows, 'paid_creates': 0, 'network_requests': 0}

    def prepare_repair(self, identity, source):
        if self.service.read_only:
            raise WebError('read_only', '当前服务以只读模式运行。', status=403)
        baseline, value = self.get(identity)
        import json
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        report = repair.preview(self.service.path, text, source_token=source, baseline=baseline)
        return {'text': text, 'source_token': source, 'preview_token': report['preview_token'],
                'baseline': baseline}, {'counts': report['counts'],
                'preserved_count': len(report['preserved_entries']),
                'original_structure_verified': report['original_structure_verified']}
