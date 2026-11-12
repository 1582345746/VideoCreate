"""Local Windows DPAPI; no registry/configuration/network side effects."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .storage import ConfigError


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes) -> bytes:
    if os.name != 'nt':
        raise ConfigError('Encrypted credential editing requires Windows; use an environment variable on this OS')
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.windll.crypt32
    crypt.CryptProtectData.restype = wintypes.BOOL
    if not crypt.CryptProtectData(ctypes.byref(source), 'VideoCreate', None, None, None, 1, ctypes.byref(result)):
        raise ConfigError('Windows could not encrypt this credential')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def store_credential(root, account_id: str, value: str, *, version: str):
    """Add a versioned secret without exposing it to JSON, command arguments or logs."""
    import json
    import re
    import tempfile
    import hashlib
    from pathlib import Path
    from .storage import private_store
    from ..runtime.state import state_lock
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', account_id) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', version):
        raise ConfigError('Invalid account ID or credential version')
    if not value.strip():
        raise ConfigError('Empty credential; existing value preserved')
    root = Path(root)
    with state_lock(root / 'credential-lock'):
        values = private_store(root)
        versions = values.setdefault('provider_accounts', {}).setdefault(account_id, {})
        if version in versions and versions[version] != value.strip():
            raise ConfigError('Use a new credential version to preserve the previous value for recovery')
        versions[version] = value.strip()
        encrypted = protect(json.dumps(values, ensure_ascii=False).encode('utf-8'))
        target = root / 'secrets.dpapi'
        if target.exists():
            prior = target.read_bytes()
            backup = root / 'backups' / ('secrets-' + hashlib.sha256(prior).hexdigest() + '.dpapi')
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                backup.write_bytes(prior)
        fd, temp = tempfile.mkstemp(prefix='secret-', suffix='.tmp', dir=root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return {'type': 'bearer', 'secret_ref': 'provider_accounts.' + account_id + '.' + version}


def unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise ConfigError("Windows encrypted credentials require the original Windows account")
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.windll.crypt32
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ConfigError("Encrypted credential store could not be read by this account")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)
