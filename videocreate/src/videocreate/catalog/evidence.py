"""Independent, hash-bound evidence; never upgrades configured wire capabilities."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json

STAGES = ("catalog", "contract", "smoke", "quality")


def verified_evidence(items: list, *, root: Path | None = None) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ConfigError("Actual evidence files and SHA-256 are required")
    results = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ConfigError("Evidence needs a path and SHA-256")
        path = Path(item["path"])
        if root and not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            raise ConfigError("Evidence file is missing or its bytes changed")
        results.append({"path": str(path), "sha256": item["sha256"]})
    return results


def record(store_root: Path, binding, receipt: dict) -> dict:
    stage = receipt.get("stage")
    if stage not in STAGES or receipt.get("result") not in {"pass", "fail"}:
        raise ConfigError("Evidence stage/result must be catalog|contract|smoke|quality and pass|fail")
    if receipt.get("binding_fingerprint") != binding.snapshot()["fingerprint"]:
        raise ConfigError("Evidence belongs to a different binding snapshot")
    if receipt.get("operation") not in binding.capabilities["operations"]:
        raise ConfigError("Evidence operation is unsupported by this binding")
    if not all(isinstance(receipt.get(k), str) and receipt[k].strip() for k in ("reviewer_id", "method")):
        raise ConfigError("Evidence requires reviewer_id and method")
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or not checks or any(type(v) is not bool for v in checks.values()):
        raise ConfigError("Evidence checks must contain actual boolean observations")
    if receipt["result"] == "pass" and not all(checks.values()):
        raise ConfigError("A failing observation cannot produce a passing receipt")
    if stage in {"smoke", "quality"} and receipt["result"] == "pass":
        if not receipt.get("attempt_id") or not receipt.get("task_id"):
            raise ConfigError("Generation/quality evidence requires original attempt_id and provider task_id")
    saved = {k: receipt[k] for k in ("stage", "result", "binding_fingerprint", "operation", "reviewer_id", "method", "checks")}
    for key in ("attempt_id", "task_id"):
        if receipt.get(key):
            saved[key] = str(receipt[key])
    saved["evidence"] = verified_evidence(receipt.get("evidence"))
    saved["id"] = uuid.uuid4().hex
    destination = store_root / "binding-evidence" / binding.snapshot()["fingerprint"] / (saved["id"] + ".json")
    atomic_json(destination, saved)
    return {"ok": True, "receipt": str(destination), "stage": stage, "result": saved["result"], "paid_creates": 0}


def status(store_root: Path, binding) -> dict:
    folder = store_root / "binding-evidence" / binding.snapshot()["fingerprint"]
    rows = {stage: {"status": "unverified", "receipts": []} for stage in STAGES}
    stale = []
    for path in sorted(folder.glob("*.json")):
        try:
            receipt = load_json(path)
            if receipt["stage"] not in rows or receipt["binding_fingerprint"] != binding.snapshot()["fingerprint"]:
                raise ConfigError("Mismatched evidence")
            verified_evidence(receipt["evidence"])
            row = rows[receipt["stage"]]
            row["receipts"].append({"path": str(path), "operation": receipt["operation"], "result": receipt["result"]})
            row["status"] = "fail" if receipt["result"] == "fail" or row["status"] == "fail" else "reported_pass"
        except (ConfigError, OSError, KeyError, TypeError, ValueError):
            stale.append(str(path))
    return {"binding": binding.id, "fingerprint": binding.snapshot()["fingerprint"], "configured": True,
            "stages": rows, "stale_receipts": stale, "note": "Stages are independent observations for the listed operations. No evidence changes capability limits or guarantees artistic quality."}
