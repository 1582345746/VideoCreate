"""Explicit rejection contracts cannot override ambiguous or content failures."""
from __future__ import annotations


def confirmed_rejection(error, binding) -> bool:
    from vc_common import APIError
    if not isinstance(error, APIError):
        return False
    if error.status not in binding.options.get("confirmed_rejection_http_statuses", []):
        return False
    message = str(error).lower()
    return not any(word in message for word in (
        "moderation", "content policy", "safety policy", "content rejected", "prohibited", "nsfw"))
