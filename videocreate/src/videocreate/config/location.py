"""Explicit config-store selection across Codex packaged and shell environments."""
import os
from pathlib import Path

from .storage import (ConfigError, active_config_path, active_config_pointer, atomic_json,
                      default_config_root, load_json, user_config_path)


def use(path):
    from .management import load, stamp
    target = Path(path).expanduser().resolve()
    record = load(target)
    if record['errors']:
        raise ConfigError('Selected configuration must pass validation before it becomes active')
    pointer = active_config_pointer()
    atomic_json(pointer, {'schema_version': 1, 'path': str(target), 'selected_at': stamp()})
    return {'ok': True, 'active_config': str(target), 'pointer': str(pointer),
            'environment_override_present': bool(os.environ.get('VIDEOCREATE_CONFIG_DIR', '').strip()),
            'precedence': '--config > VIDEOCREATE_CONFIG_DIR > saved active config > OS default',
            'credentials_moved': False, 'network_requests': 0, 'paid_creates': 0}


def locate():
    from .schema import validate_config
    candidates = [default_config_root() / 'videocreate.config.json']
    error = None; selected = None
    try:
        selected = user_config_path()
        saved = active_config_path()
        if saved: candidates.append(saved)
    except ConfigError as exc:
        error = str(exc)
    local = Path.home() / 'AppData/Local'
    if os.name == 'nt':
        candidates.append(local / 'VideoCreate/videocreate.config.json')
        candidates.extend(sorted((local / 'Packages').glob('OpenAI.Codex_*/LocalCache/Local/VideoCreate/videocreate.config.json')))
    rows = []
    for p in dict.fromkeys(p.resolve() for p in candidates):
        row = {'path': str(p), 'exists': p.is_file(), 'selected': p == selected, 'valid': False}
        if p.is_file():
            try:
                config = load_json(p); row['valid'] = not validate_config(config)
                # Counts locate a store without exposing labels, accounts or credentials.
                row['upstreams'] = len(config.get('upstreams', {})); row['bindings'] = len(config.get('bindings', {}))
            except (OSError, ValueError, TypeError):
                row['read_error'] = True
        rows.append(row)
    return {'ok': True, 'candidates': rows, 'pointer': str(active_config_pointer()), 'selection_error': error,
            'network_requests': 0, 'paid_creates': 0,
            'note': 'No automatic merging or newest-file guessing. Choose a valid existing config with config use --config PATH.'}
