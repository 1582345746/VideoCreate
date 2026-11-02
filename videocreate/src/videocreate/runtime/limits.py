from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path

from ..config.storage import ConfigError
from .state import state_lock


@contextlib.contextmanager
def submission_slot(store_root: Path, upstream_id: str, maximum: int):
    """Host-local instance semaphore; never hold the project state lock here."""
    identity = hashlib.sha256(upstream_id.encode()).hexdigest()[:24]
    acquired = None
    for index in range(maximum):
        slot = state_lock(store_root / "runtime" / "submit-gates" / identity / str(index), timeout=0)
        try:
            slot.__enter__()
        except ConfigError:
            continue
        acquired = slot
        break
    if acquired is None:
        raise ConfigError("Upstream submission concurrency limit reached; no attempt was reserved and no create was sent")
    try:
        yield
    finally:
        acquired.__exit__(None, None, None)
