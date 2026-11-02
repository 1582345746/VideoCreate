"""Local Windows DPAPI; no registry/configuration/network side effects."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .storage import ConfigError


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


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
