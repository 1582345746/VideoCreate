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
            from .quotas import network_scope, watch
            watch(store_root, root)
            with network_scope(store_root, config, binding.upstream_id, 'poll'):
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
    elif outcome == 'rejected-before-task':
        from .failures import (REFERENCE_FETCH_CONTRACT, reference_fetch_rejection,
                               PUBLIC_REFERENCE_CONTRACT, public_reference_rejection,
                               XING_VIDEO_REFERENCE_CONTRACT, xing_video_reference_rejection,
                               XING_REFERENCE_VIDEO_CONTRACT, xing_reference_video_rejection)
        trace = record.get('submission_receipt', {}).get('trace_ids', {}).get('request_id')
        contract = receipt.get('contract_id')
        documented = (contract == REFERENCE_FETCH_CONTRACT
                      and receipt.get('method') == 'documented-create-response'
                      and reference_fetch_rejection(400, record.get('error', ''), pinned))
        explicit = (contract == PUBLIC_REFERENCE_CONTRACT
                    and receipt.get('method') == 'explicit-create-validation-rejection'
                    and public_reference_rejection(400, record.get('error', ''), pinned))
        unsupported = (contract == XING_VIDEO_REFERENCE_CONTRACT
                       and receipt.get('method') == 'explicit-create-validation-rejection'
                       and xing_video_reference_rejection(400, record.get('error', ''), pinned))
        unsupported_reference = (contract == XING_REFERENCE_VIDEO_CONTRACT
                       and receipt.get('method') == 'explicit-create-validation-rejection'
                       and xing_reference_video_rejection(400, record.get('error', ''), pinned))
        if (not (documented or explicit or unsupported or unsupported_reference)
                or not trace or receipt.get('request_id') != trace
                or record.get('task_id') or task_id):
            raise ConfigError('Saved create response does not establish this documented pre-task rejection')
        # Preserve the actual received-and-rejected response. This is not an
        # upstream audit claiming the request never arrived, or a billing receipt.
        if not any(item.get('kind') == 'provider-contract' for item in evidence):
            raise ConfigError('Documented rejection needs the hashed provider contract')
        if (explicit or unsupported or unsupported_reference) and not any(item.get('kind') == 'create-response' for item in evidence):
            raise ConfigError('Explicit validation rejection needs the hashed create response')
        if unsupported or unsupported_reference:
            if (f'(request_id={trace})' not in record.get('error', '')
                    or not any(ref.get('kind') == 'video' for ref in
                               record.get('submission_receipt', {}).get('media_references', []))
                    or not any(item.get('kind') == 'create-response'
                               and within(root, item['path']).read_text(encoding='utf-8') == record['error']
                               for item in evidence)):
                raise ConfigError('Unsupported-video rejection needs the exact saved response, trace and video input')
    else:
        raise ConfigError("Resolution outcome must be accepted/not-received/rejected-before-task/unknown")
    with state_lock(root):
        state = read_state(root)
        current = state["jobs"][jid]
        if current.get("status") != "submission_unknown" or current.get("attempt_id") != attempt_id:
            raise ConfigError("Attempt changed during verification; reread before resolving")
        atomic_json(root / "jobs" / jid / attempt_id / "resolution.json", receipt)
        current.update(status=status, task_id=task_id, reconciliation=receipt)
        next(e for e in state["ledger"] if e["attempt_id"] == attempt_id)["status"] = (
            'submitted' if task_id else 'confirmed-pre-task-rejection'
            if outcome == 'rejected-before-task' else 'confirmed-not-received')
        save_state(root, state)
    return {"ok": True, "job_id": jid, "status": status, "task_id": task_id, "paid_creates": 0}
