from __future__ import annotations

import math
from decimal import Decimal

from ..config.storage import ConfigError


def estimate(binding, seconds: float, currency: str) -> float | None:
    pricing = binding.options.get("pricing")
    if not pricing or pricing.get("currency") != currency:
        return None
    rate = pricing.get("per_request", 0)
    per_second = pricing.get("per_second", 0)
    return float(Decimal(str(rate)) + Decimal(str(per_second))*Decimal(str(seconds)))


def reserve(state: dict, budget: dict, *, attempt_id: str, job_id: str, kind: str, estimated: float | None) -> dict:
    ledger = state.setdefault("ledger", [])
    if any(item["attempt_id"] == attempt_id for item in ledger):
        raise ConfigError("Attempt was already reserved")
    count = sum(item["kind"] == kind for item in ledger)
    if count >= budget.get(f"max_{kind}_requests", 12 if kind == "video" else 12):
        raise ConfigError("Request budget is exhausted; no create was sent")
    maximum = budget.get("max_total")
    if estimated is None:
        if budget.get("unknown_price_policy") == "block" or maximum is not None:
            raise ConfigError("Price is unknown; a hard monetary limit requires configured binding pricing")
    if maximum is not None:
        if any(item.get("estimated") is None and item.get("actual") is None for item in ledger):
            raise ConfigError("Existing unpriced attempts prevent proving the monetary limit")
        total = sum(Decimal(str(item.get("actual") if item.get("actual") is not None else item.get("estimated", 0))) for item in ledger)
        if total + Decimal(str(estimated or 0)) > Decimal(str(maximum)):
            raise ConfigError("Monetary budget would be exceeded; no create was sent")
    item = {"attempt_id": attempt_id, "job_id": job_id, "kind": kind, "estimated": estimated,
            "actual": None, "currency": budget.get("currency", "CNY"), "status": "reserved"}
    ledger.append(item)
    return item


def summary(state: dict) -> dict:
    ledger = state.get("ledger", [])
    return {"requests": len(ledger), "estimated_known_total": sum(i["estimated"] for i in ledger if i.get("estimated") is not None),
            "unknown_price_requests": sum(i.get("estimated") is None for i in ledger),
            "unknown_submission_requests": sum(i.get("status") in {"reserved", "submission_unknown"} for i in ledger),
            "actual_known_total": sum(i["actual"] for i in ledger if i.get("actual") is not None),
            "actual_unverified_requests": sum(i.get("actual") is None for i in ledger)}
