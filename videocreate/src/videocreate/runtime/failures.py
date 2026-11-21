"""Explicit rejection contracts cannot override ambiguous or content failures."""
from __future__ import annotations

import re
from urllib.parse import urlsplit


REFERENCE_FETCH_CONTRACT = 'suanliai-reference-image-fetch-20261116'
PUBLIC_REFERENCE_CONTRACT = 'suanliai-speed-public-reference-validation-20261117'


def public_reference_rejection(status, message, snapshot) -> bool:
    """Exact observed create-time URL validation refusal on the Speed route.

    This is an explicit input-format rejection, not a generic generation
    failure. Require the provider's no-charge suffix and original data-uri
    transport. Billing remains unverified after reconciliation.
    """
    try:
        origin = urlsplit(snapshot['base_url'])
        if (origin.scheme != 'https' or origin.hostname != 'suanliai.top'
                or origin.port not in (None, 443) or origin.username or origin.password):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    if (status != 400 or snapshot.get('adapter') != 'newapi-json-v2'
            or snapshot.get('remote_model') != '稳定高速sd2.5(30参任选/4-30秒/720P)'
            or snapshot.get('adapter_options', {}).get('reference_transport') != 'data-uri'):
        return False
    return bool(re.fullmatch(
        r'HTTP 400: 生成失败：Jianwei references must use public HTTP\(S\) URLs '
        r'without embedded login credentials～（本次不扣费）'
        r'(?: \(request_id=[A-Za-z0-9_-]+\))?', str(message)))


def reference_fetch_rejection(status, message, snapshot) -> bool:
    """One documented pre-task rejection, not a blanket HTTP 400 rule.

    The provider's /docs?lite=1 reference-material section states that image
    download failures reject the submission before task creation. Keep video
    fetch errors and generic HTTP/content failures outside this contract.
    """
    try:
        origin = urlsplit(snapshot['base_url'])
        if (origin.scheme != 'https' or origin.hostname != 'suanliai.top'
                or origin.port not in (None, 443) or origin.username or origin.password):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    if (status != 400 or snapshot.get('adapter') != 'newapi-json-v2'
            or snapshot.get('remote_model') not in {
                '官渠sd2.5-flash(20参任选/10-5-5/5-30秒/480P)',
                '官渠sd2.5-flash(20参任选/10-5-5/5-30秒/720P)'}):
        return False
    return bool(re.fullmatch(
        r'HTTP 400: 参考素材 images\[\d+\] 下载失败或超时（[^\r\n（）]+），无法读取该链接。'
        r'请换成稳定的公网链接（图床、对象存储），或直接传 base64（data:<类型>;base64,<内容>）'
        r'(?:～?（本次不扣费）)?(?: \(request_id=[A-Za-z0-9_-]+\))?', str(message)))


def confirmed_rejection(error, binding) -> bool:
    from vc_common import APIError
    if not isinstance(error, APIError):
        return False
    if reference_fetch_rejection(error.status, str(error), binding.snapshot()):
        return True
    if public_reference_rejection(error.status, str(error), binding.snapshot()):
        return True
    if error.status not in binding.options.get("confirmed_rejection_http_statuses", []):
        return False
    message = str(error).lower()
    return not any(word in message for word in (
        "moderation", "content policy", "safety policy", "content rejected", "prohibited", "nsfw"))
