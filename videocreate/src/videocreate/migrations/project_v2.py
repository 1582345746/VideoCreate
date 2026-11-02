"""Adopt existing task ledgers without coercing old creative plans into v3."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json


def adopt(root: Path, *, apply: bool = False) -> dict:
    root = root.resolve()
    if apply:
        from ..cli import legacy_engine
        legacy_engine()
        from vc_common import project_state_lock
        with project_state_lock(root):
            report = adopt(root)
            path = root / "migration-receipts" / (report["source_hashes"]["state.json"] + ".json")
            atomic_json(path, {**report, "applied": True})
        return {**report, "applied": True, "receipt": str(path)}
    project = load_json(root / "project.json")
    state = load_json(root / "state.json")
    if project.get("schema_version") == 3 or "shots" not in project or not isinstance(state.get("shots"), dict):
        raise ConfigError("This migration adopts existing legacy projects only")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ("project.json", "state.json")}
    tasks = []
    for sid, shot in state["shots"].items():
        for kind in ("image", "video"):
            asset = shot.get(kind, {})
            if asset:
                tasks.append({"shot_id": sid, "kind": kind, **{key: asset.get(key) for key in (
                    "status", "task_id", "attempt_id", "provider", "upstream_id", "adapter", "model", "remote_model", "sha256", "signature")}})
    return {"ok": True, "applied": False, "product": "VideoCreate", "runtime": "legacy-v2-compatible",
            "project": str(root), "source_hashes": hashes, "tasks": tasks, "paid_creates": 0,
            "note": "Original project/state, task IDs, signatures, source bytes and review failures are preserved. Resume through legacy commands; create new v3 work in a separate plan."}
