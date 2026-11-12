from __future__ import annotations

import contextlib
import hashlib
import time
from pathlib import Path

from ..config.storage import ConfigError
from .state import state_lock


def capacity(config, upstream_id):
    """Aliases of a shared account use the same gate and most restrictive limit."""
    from .quotas import members
    identities = members(config, upstream_id)
    identity = ('shared:' + '|'.join(identities)) if len(identities) > 1 else upstream_id
    return identity, min(config['upstreams'][uid].get('max_concurrent_submissions', 1) for uid in identities)


@contextlib.contextmanager
def submission_slot(store_root: Path, upstream_id: str, maximum: int, *, wait: bool = False,
                    timeout_seconds: float = 120):
    """Host-local instance semaphore; never hold the project state lock here."""
    identity = hashlib.sha256(upstream_id.encode()).hexdigest()[:24]
    deadline = time.monotonic() + max(0, timeout_seconds)
    acquired = None
    while acquired is None:
        for index in range(maximum):
            slot = state_lock(store_root / "runtime" / "submit-gates" / identity / str(index), timeout=0)
            try:
                slot.__enter__()
            except (ConfigError, OSError):
                continue
            acquired = slot
            break
        if acquired is None:
            if not wait or time.monotonic() >= deadline:
                raise ConfigError("Upstream submission concurrency limit reached; no attempt was reserved and no create was sent")
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    try:
        yield
    finally:
        acquired.__exit__(None, None, None)
