from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json


@contextlib.contextmanager
def state_lock(root: Path, *, timeout: float = 15):
    """Only protect state transitions. Network and media work happen outside."""
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / ".videocreate-state.lock").open("a+b")
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise ConfigError("Project state is busy; no request was submitted") from None
                time.sleep(0.03)
        # Initialize under the lock: concurrent writers to a new Windows lock
        # file can otherwise fail before entering the cleanup block.
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def read_state(root: Path) -> dict:
    path = root / "state.json"
    state = load_json(path) if path.exists() else {"schema_version": 3, "jobs": {}, "ledger": []}
    if state.get("schema_version") != 3 or not isinstance(state.get("jobs"), dict) or not isinstance(state.get("ledger"), list):
        raise ConfigError("This runtime requires v3 state; legacy state is preserved")
    return state


def save_state(root: Path, state: dict) -> None:
    atomic_json(root / "state.json", state)
