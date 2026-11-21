"""Configuration service boundary; no media jobs, shell or Tk dependencies."""
import hashlib
from pathlib import Path

from .. import __version__
from ..config import management
from ..config.schema import validate_config
from ..config.storage import ConfigError, load_json, user_config_path
from . import dto


class ConfigService:
    def __init__(self, path=None, *, read_only=True):
        self.path = user_config_path(path).resolve()
        self.read_only = read_only
        self.identity = hashlib.sha256(str(self.path).casefold().encode('utf-8')).hexdigest()

    def inspect(self):
        summary = {'product': 'VideoCreate', 'version': __version__, 'config_path': str(self.path),
                   'status': 'missing', 'editable': False, 'schema_version': None, 'revision': None,
                   'issue_count': 0, 'counts': {}, 'mode': 'read-only', 'paid_creates': 0}
        if not self.path.is_file():
            return summary, None
        try:
            value = load_json(self.path)
            summary['schema_version'] = value.get('schema_version') if type(value.get('schema_version')) is int else None
            if type(value.get('schema_version')) is not int or value['schema_version'] not in {3, 4}:
                summary['status'] = 'unsupported-version'
                return summary, None
            errors = validate_config(value)
            summary.update(revision=value.get('revision', 0) if type(value.get('revision', 0)) is int else None,
                           issue_count=len(errors))
            if errors:
                summary['status'] = 'invalid-schema'
                return summary, None
            summary.update(status='valid', token=management.fingerprint(value),
                           editable=not self.read_only and value['schema_version'] == 4,
                           mode='read-only' if self.read_only else 'editable',
                           counts={key: len(value[key]) for key in ('upstreams', 'models', 'bindings', 'routes')})
            return summary, value
        except ConfigError:
            summary.update(status='invalid-json', issue_count=1)
            from ..config.repair import versions
            try:
                explicit = versions(self.path.read_text(encoding='utf-8-sig'))
                if any(type(v) is not int or v not in {3, 4} for v in explicit):
                    summary['status'] = 'unsupported-version'
            except (OSError, UnicodeError):
                summary['status'] = 'unreadable'
        except (OSError, UnicodeError):
            summary.update(status='unreadable', issue_count=1)
        return summary, None

    def summary(self):
        return self.inspect()[0]

    def catalog(self):
        summary, value = self.inspect()
        return {'summary': summary, 'defaults': self.default_values(value),
                **(dto.catalog(value) if value is not None else {'upstreams': [], 'bindings': []})}

    def defaults(self):
        summary, value = self.inspect()
        return {'summary': summary, **self.default_values(value)}

    @staticmethod
    def default_values(value):
        if value is None:
            return {'image': None, 'video': None}
        result = {}
        for kind in ('image', 'video'):
            mid = value.get('defaults', {}).get(kind + '_model')
            result[kind] = {'binding': value['routes'].get(mid, {}).get('preferred_binding'),
                            'policy': value.get('selection', {}).get(kind, {}).get('when_unspecified', 'ask')}
        return result
