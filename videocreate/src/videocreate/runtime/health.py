"""Host-local cooldowns affect new automatic routes, never accepted tasks."""
from __future__ import annotations

import time
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json
from .state import state_lock


def _path(store_root: Path, binding) -> Path:
    return store_root / "runtime" / "binding-health" / (binding.snapshot()["fingerprint"] + ".json")


def cooling_down(store_root: Path, binding) -> bool:
    try:
        return load_json(_path(store_root, binding)).get("retry_after_epoch", 0) > time.time()
    except (ConfigError, OSError, ValueError):
        return False


def observe(store_root: Path, binding, *, failed: bool, seconds: int = 60) -> None:
    path = _path(store_root, binding)
    with state_lock(path.parent):
        atomic_json(path, {"binding_id": binding.id, "observed_at": time.time(),
            "retry_after_epoch": time.time() + seconds if failed else 0,
            "scope": "binding", "paid_probes": 0})
