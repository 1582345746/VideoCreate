"""Private manager recovery snapshots, separate from authoritative configuration."""
import hashlib
import json
import os
import re
import socket
import tempfile
import uuid
from pathlib import Path

from .. import __version__
from . import management, secrets
from .storage import ConfigError, parse_json


MAX_BYTES = 16 * 1024 * 1024


def owner_status(owner):
    """Only a proven stopped process permits recovery; PID reuse stays blocked."""
    if owner.get('host') != socket.gethostname():return 'unknown'
    pid = owner.get('pid')
    if type(pid) is not int or pid < 1:return 'unknown'
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:return 'stopped' if ctypes.get_last_error() == 87 else 'unknown'
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):return 'unknown'
            return 'active' if code.value == 259 else 'stopped'
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid, 0)
    except ProcessLookupError:return 'stopped'
    except (PermissionError, OSError):return 'unknown'
    return 'active'


class DraftStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.session = uuid.uuid4().hex
        # Distinguish multiple configuration files in the same directory.
        identity = hashlib.sha256(str(self.path).encode('utf-8')).hexdigest()
        self.directory = self.path.parent / 'runtime' / 'manager-drafts' / identity
        self.target = self.directory / (self.session + '.dpapi')

    def _target(self, session):
        if not isinstance(session, str) or not re.fullmatch(r'[0-9a-f]{32}', session):
            raise ConfigError('Invalid recovery snapshot identity')
        return self.directory / (session + '.dpapi')

    def save(self, base_token, value, forms):
        payload = {'schema_version':1, 'manager_version':__version__, 'session':self.session,
            'configuration_path':str(self.path), 'base_token':base_token, 'saved_at':management.stamp(),
            'owner':{'pid':os.getpid(), 'host':socket.gethostname()}, 'value':value, 'forms':forms}
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(raw) > MAX_BYTES:raise ConfigError('Recovery draft exceeds the local size limit')
        encrypted = secrets.protect(raw)  # No plaintext file, even when encryption fails.
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.draft-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encrypted);stream.flush();os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.target)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        return {'saved_at':payload['saved_at'], 'session':self.session}

    def read(self, session):
        try:
            target = self._target(session)
            if target.stat().st_size > MAX_BYTES + 65536:raise ValueError()
            value = parse_json(secrets.unprotect(target.read_bytes()).decode('utf-8'))
            if (value.get('schema_version') != 1 or value.get('session') != session
                    or value.get('configuration_path') != str(self.path)
                    or not isinstance(value.get('value'), dict) or not isinstance(value.get('forms'), list)
                    or not isinstance(value.get('owner'), dict)
                    or not re.fullmatch(r'[0-9a-f]{64}', value.get('base_token', ''))):raise ValueError()
            return value
        except (OSError, ValueError, TypeError, UnicodeError):
            raise ConfigError('Recovery snapshot is unreadable; original encrypted file is retained') from None

    def inventory(self):
        rows = []
        for path in sorted(self.directory.glob('*.dpapi')):
            if path == self.target:continue
            try:
                value = self.read(path.stem)
                state = owner_status(value['owner'])
                if state == 'stopped' and value.get('manager_version') != __version__:state = 'other-version'
                if state == 'stopped' and management.load(self.path)['token'] != value['base_token']:state = 'conflict'
                rows.append({'session':path.stem, 'status':state, 'saved_at':value.get('saved_at', ''),
                    'forms':len(value['forms'])})
            except (OSError, ValueError):rows.append({'session':path.stem, 'status':'unreadable', 'saved_at':'', 'forms':None})
        return rows

    def recover(self, session):
        value = self.read(session)
        if owner_status(value['owner']) != 'stopped':raise ConfigError('The original editor is active or cannot be proven stopped')
        if value.get('manager_version') != __version__:raise ConfigError('Use the original manager version to recover this form layout')
        record = management.load(self.path)
        if not record['editable'] or record['token'] != value['base_token']:
            raise ConfigError('Configuration changed; recovery cannot replace or merge it automatically')
        return value

    def discard(self, session=None):
        target = self.target if session is None else self._target(session)
        if session is not None and session != self.session:
            value = self.read(session)
            if owner_status(value['owner']) != 'stopped':raise ConfigError('Close the original editor before discarding its snapshot')
        target.unlink(missing_ok=True)
