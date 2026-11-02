from __future__ import annotations

import hashlib
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, safe_error
from ..planning.project import within
from .jobs import client, pinned_binding
from .state import read_state, save_state, state_lock


def reconcile(root: Path, config: dict, receipt: dict, *, store_root: Path) -> dict:
    jid = receipt.get("job_id")
    with state_lock(root):
        state = read_state(root)
        record = state["jobs"].get(jid)
        if not record or record.get("status") != "submission_unknown":
            raise ConfigError("Only an unknown submission can be reconciled")
        if receipt.get("attempt_id") != record["attempt_id"] or receipt.get("binding_fingerprint") != record["binding_snapshot"]["fingerprint"]:
            raise ConfigError("Resolution receipt does not match the original attempt/binding")
        pinned = record["binding_snapshot"]
        attempt_id = record["attempt_id"]
    outcome = receipt.get("outcome")
    if outcome == "unknown":
        return {"ok": True, "status": "submission_unknown", "paid_creates": 0}
    evidence = receipt.get("evidence", [])
    if not isinstance(evidence, list) or not evidence or not receipt.get("reviewer_id"):
        raise ConfigError("Resolution needs identified operator and actual upstream evidence")
    for item in evidence:
        try:
            path = within(root, item["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError()
        except (ConfigError, KeyError, TypeError, ValueError):
            raise ConfigError("Resolution evidence is missing or stale") from None
    task_id, status = receipt.get("task_id", ""), "rejected"
    if outcome == "accepted":
        if not isinstance(task_id, str) or not task_id.strip() or any(c.isspace() for c in task_id):
            raise ConfigError("Accepted receipt needs an actual provider task ID")
        binding = pinned_binding(config, pinned, store_root)
        try:
            status, _ = client(binding).query(task_id)
        except Exception as error:
            raise ConfigError(safe_error(error, [binding.key])) from None
        if status in {"", "unknown"}:
            raise ConfigError("Provider task could not be verified; keep submission unknown")
    elif outcome == "not-received":
        confirmation = receipt.get("upstream_confirmation", {})
        if receipt.get("method") != "upstream-audit" or confirmation.get("submission_received") is not False or confirmation.get("task_created") is not False or not confirmation.get("record_id"):
            raise ConfigError("查不到 is inconclusive; not-received requires explicit upstream confirmation of no received submission and no created task")
        if task_id:
            raise ConfigError("Not-received receipt must not include a task ID")
    else:
        raise ConfigError("Resolution outcome must be accepted/not-received/unknown")
    with state_lock(root):
        state = read_state(root)
        current = state["jobs"][jid]
        if current.get("status") != "submission_unknown" or current.get("attempt_id") != attempt_id:
            raise ConfigError("Attempt changed during verification; reread before resolving")
        atomic_json(root / "jobs" / jid / attempt_id / "resolution.json", receipt)
        current.update(status=status, task_id=task_id, reconciliation=receipt)
        next(e for e in state["ledger"] if e["attempt_id"] == attempt_id)["status"] = "submitted" if task_id else "confirmed-not-received"
        save_state(root, state)
    return {"ok": True, "job_id": jid, "status": status, "task_id": task_id, "paid_creates": 0}
