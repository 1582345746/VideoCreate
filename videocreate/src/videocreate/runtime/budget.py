from __future__ import annotations

import math
from decimal import Decimal

from ..config.storage import ConfigError


def estimate(binding, seconds: float, currency: str, *, parameters=None) -> float | None:
    return estimate_details(binding, seconds, currency, parameters=parameters)['amount']


def image_parameters(binding, operation) -> dict:
    from ..adapters.image import requested_image_count
    result = {'operation': operation}
    count = requested_image_count(binding)
    if count is not None:
        result['image_count'] = count
    return result


def estimate_details(binding, seconds: float, currency: str, *, parameters=None) -> dict:
    """Explain the same budget estimate without exposing provider/auth/source data.

    A reason is a calculation result, never a readiness or actual-payment claim.
    Keep this the only rate/tier selection implementation used by estimate().
    """
    result = {'currency': currency, 'amount': None, 'actual_payment': 'unknown',
              'reason': 'price_missing', 'matched_tiers': [], 'missing_parameters': [],
              'billed_seconds': None, 'billed_images': None,
              'per_request': None, 'per_second': None, 'per_image': None}
    def unknown(reason):
        result['reason'] = reason
        return result

    pricing = binding.options.get("pricing")
    if not pricing:
        return result
    if pricing.get('currency') != currency:
        return unknown('currency_mismatch')
    if pricing.get('status') == 'unverified':
        return unknown('price_unverified')
    if not any(k in pricing for k in ('per_request', 'per_second', 'per_image', 'tiers')):
        return unknown('rate_missing')
    if type(seconds) not in {int, float} or not math.isfinite(seconds) or seconds < 0:
        return unknown('duration_invalid')
    for time_key in ('effective_at', 'valid_until'):
        if not pricing.get(time_key):
            continue
        from datetime import datetime, timezone
        try:
            instant = datetime.fromisoformat(pricing[time_key].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            if instant.tzinfo is None:
                return unknown('price_time_invalid')
            if time_key == 'valid_until' and instant <= now:
                return unknown('price_expired')
            if time_key == 'effective_at' and instant > now:
                return unknown('price_not_effective')
        except ValueError:
            return unknown('price_time_invalid')
    if pricing.get('tiers'):
        matches, missing = [], set()
        for index, tier in enumerate(pricing['tiers'], 1):
            when = tier['when']
            if not when.get('minimum_seconds', 0) <= seconds <= when.get('maximum_seconds', float('inf')):
                continue
            fields = {k:v for k,v in when.items() if k not in {'minimum_seconds', 'maximum_seconds'}}
            absent = {k for k in fields if k not in (parameters or {})}
            if all((parameters or {}).get(k) == v for k,v in fields.items() if k not in absent):
                missing.update(absent)
                if not absent:
                    matches.append(tier)
                    result['matched_tiers'].append(index)
        # Overlapping tiers and missing parameter context must never produce an arbitrary estimate.
        if len(matches) > 1:
            return unknown('tier_ambiguous')
        # One definite match is not unique while an unresolved tier can still
        # match. A general tier is not an implicit fallback or lower-price rule.
        if missing:
            # Return only schema field names, never arbitrary tier values.
            result['missing_parameters'] = sorted(missing & {'operation', 'resolution', 'aspect_ratio'})
            return unknown('tier_parameters_missing')
        if not matches:
            return unknown('tier_no_match')
        pricing = {**{k:v for k,v in pricing.items() if k not in {'per_request', 'per_second', 'per_image'}}, **matches[0]}
    billed_images = None
    if 'per_image' in pricing:
        if (parameters or {}).get('operation') not in {'text-to-image', 'image-edit'}:
            return unknown('image_operation_required')
        billed_images = (parameters or {}).get('image_count')
        if billed_images is None:
            return unknown('image_count_unknown')
        if type(billed_images) is not int or billed_images <= 0:
            return unknown('image_count_invalid')
    rate = pricing.get("per_request", 0)
    per_second = pricing.get("per_second", 0)
    billed_seconds = max(Decimal(str(seconds)), Decimal(str(pricing.get('minimum_seconds', 0))))
    if pricing.get('round_seconds'):
        from decimal import ROUND_CEILING
        step = Decimal(str(pricing['round_seconds']))
        billed_seconds = (billed_seconds / step).to_integral_value(rounding=ROUND_CEILING) * step
    amount = float(Decimal(str(rate)) + Decimal(str(per_second))*billed_seconds
                   + Decimal(str(pricing.get('per_image', 0))) * Decimal(billed_images or 0))
    if not math.isfinite(amount) or not math.isfinite(float(billed_seconds)):
        return unknown('estimate_not_finite')
    result.update(amount=amount, reason='estimated', billed_seconds=float(billed_seconds),
                  per_request=rate, per_second=per_second,
                  per_image=pricing.get('per_image'), billed_images=billed_images)
    return result


def reserve(state: dict, budget: dict, *, attempt_id: str, job_id: str, kind: str, estimated: float | None) -> dict:
    ledger = state.setdefault("ledger", [])
    if any(item["attempt_id"] == attempt_id for item in ledger):
        raise ConfigError("Attempt was already reserved")
    count = sum(item["kind"] == kind and item.get('status') != 'not-submitted' for item in ledger)
    if count >= budget.get(f"max_{kind}_requests", 12 if kind == "video" else 12):
        raise ConfigError("Request budget is exhausted; no create was sent")
    maximum = budget.get("max_total")
    if estimated is None:
        if budget.get("unknown_price_policy") == "block" or maximum is not None:
            raise ConfigError("Price is unknown; a hard monetary limit requires configured binding pricing")
    if maximum is not None:
        if any(item.get('currency') != budget.get('currency', 'CNY') for item in ledger):
            raise ConfigError('Existing attempts use a different currency; no implicit conversion for a hard monetary budget')
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
    currencies = sorted({i.get('currency', 'unknown') for i in ledger})
    by_currency = {currency: {'estimated_known_total': sum(i['estimated'] for i in ledger if i.get('currency', 'unknown') == currency and i.get('estimated') is not None),
        'actual_known_total': sum(i['actual'] for i in ledger if i.get('currency', 'unknown') == currency and i.get('actual') is not None)} for currency in currencies}
    return {"requests": sum(i.get('status') != 'not-submitted' for i in ledger),
            'local_preflight_rejections': sum(i.get('status') == 'not-submitted' for i in ledger), 'by_currency': by_currency,
            "estimated_known_total": sum(i["estimated"] for i in ledger if i.get("estimated") is not None) if len(currencies) < 2 else None,
            "unknown_price_requests": sum(i.get("estimated") is None for i in ledger),
            "unknown_submission_requests": sum(i.get("status") in {"reserved", "submission_unknown"} for i in ledger),
            "actual_known_total": sum(i["actual"] for i in ledger if i.get("actual") is not None) if len(currencies) < 2 else None,
            "actual_unverified_requests": sum(i.get("actual") is None for i in ledger)}
