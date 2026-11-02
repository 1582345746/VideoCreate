from __future__ import annotations

import math
from pathlib import Path

from ..catalog.evidence import verified_evidence
from ..config.storage import ConfigError, atomic_json
from .state import read_state, save_state, state_lock


def settle(root: Path, receipt: dict) -> dict:
    amount = receipt.get("amount")
    if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0:
        raise ConfigError("Billing amount must be a finite nonnegative number")
    if not receipt.get("reviewer_id") or not receipt.get("upstream_record_id"):
        raise ConfigError("Settlement requires reviewer and actual upstream billing record ID")
    verified_evidence(receipt.get("evidence"), root=root)
    with state_lock(root):
        state = read_state(root)
        entry = next((e for e in state["ledger"] if e["attempt_id"] == receipt.get("attempt_id") and e["job_id"] == receipt.get("job_id")), None)
        if not entry or receipt.get("currency") != entry["currency"]:
            raise ConfigError("Billing receipt must match original attempt/job/currency")
        if entry.get("actual") is not None:
            if entry.get("billing_receipt") == receipt:
                return {"ok": True, "unchanged": True, "paid_creates": 0}
            raise ConfigError("Attempt is already settled; preserve its original billing audit")
        atomic_json(root / "jobs" / entry["job_id"] / entry["attempt_id"] / "billing.json", receipt)
        entry.update(actual=amount, billing_receipt=receipt)
        save_state(root, state)
    return {"ok": True, "attempt_id": entry["attempt_id"], "actual": amount, "currency": entry["currency"], "paid_creates": 0}
