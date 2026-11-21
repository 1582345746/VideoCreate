"""Host-local cooldowns affect new automatic routes, never accepted tasks."""
from __future__ import annotations

import time
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json
from .state import state_lock


def _path(store_root: Path, binding) -> Path:
    return store_root / "runtime" / "binding-health" / (binding.snapshot()["fingerprint"] + ".json")


def cooling_down(store_root: Path, binding) -> bool:
    path = _path(store_root, binding)
    try:
        if not path.is_file():
            return False
        # Windows readers opened without delete sharing can prevent an atomic
        # replace. Use the writer's lock while holding the read handle too.
        with state_lock(path.parent):
            return load_json(path).get("retry_after_epoch", 0) > time.time()
    except (ConfigError, OSError, ValueError):
        return False


def observe(store_root: Path, binding, *, failed: bool, seconds: int = 60) -> None:
    path = _path(store_root, binding)
    with state_lock(path.parent):
        atomic_json(path, {"binding_id": binding.id, "observed_at": time.time(),
            "retry_after_epoch": time.time() + seconds if failed else 0,
            "scope": "binding", "paid_probes": 0})
