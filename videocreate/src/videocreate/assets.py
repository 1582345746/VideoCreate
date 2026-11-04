from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import os
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .catalog.bindings import route_bindings, validate_request
from .config.storage import ConfigError, atomic_json, load_json, safe_error
from .planning.project import content_hash, load_project, within
from .runtime.budget import estimate, reserve, summary
from .runtime.state import read_state, save_state, state_lock
from .runtime.limits import submission_slot


def register(root: Path, asset_id: str, source: Path) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", asset_id):
        raise ConfigError("Asset ID is invalid")
    bundle = load_project(root)
    selected = next((a for a in bundle["director"]["assets"] if a["id"] == asset_id), None)
    if not selected:
        raise ConfigError("Register an asset description in director.assets before adding its reference")
    if not source.is_file() or mimetypes.guess_type(source.name)[0] not in {"image/jpeg", "image/png", "image/webp"}:
        raise ConfigError("Reference must be an existing JPEG, PNG or WebP file")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target = root / "assets" / "references" / f"{asset_id}-{digest[:16]}{source.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
    relative = target.relative_to(root).as_posix()
    with state_lock(root):
        current = load_project(root)
        selected = next(a for a in current["director"]["assets"] if a["id"] == asset_id)
        if relative not in selected.setdefault("references", []):
            selected["references"].append(relative)
        atomic_json(root / current["project"]["files"]["director"], current["director"])
    return {"ok": True, "asset_id": asset_id, "path": relative, "sha256": digest, "content": "unverified", "paid_creates": 0}


def generate_image(root: Path, config: dict, *, store_root: Path, job_id: str, prompt: str,
                   references: list[Path], binding_id: str | None = None, size="1024x1024", quality="auto",
                   wait_for_slot: bool = False, retry: str | None = None, reason: str = "") -> dict:
    if retry and (retry not in {"content", "replan"} or not reason.strip()):
        raise ConfigError("Image retry needs content/replan and an observed reason")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", job_id):
        raise ConfigError("Image job ID is invalid")
    if any(job["id"] == job_id for job in load_project(root)["generation-plan"]["jobs"]):
        raise ConfigError("Image job ID must differ from planned video job IDs")
    model = config["defaults"].get("image_model")
    if not model:
        raise ConfigError("Configure an independent defaults.image_model and route first")
    binding = route_bindings(config, model, operation="image-edit" if references else "text-to-image",
        preferred=binding_id, store_root=store_root)[0]
    if not prompt.strip():
        raise ConfigError("Image prompt must not be empty")
    refs = [path.resolve() for path in references]
    for path in refs:
        if not path.is_relative_to(root) or not path.is_file():
            raise ConfigError("Register image references inside the project first")
    report = validate_request(binding, {"operation": "image-edit" if refs else "text-to-image", "prompt": prompt, "references": refs})
    if not report["ok"]:
        raise ConfigError("; ".join(report["errors"]))
    if len(prompt.encode()) > 4096:
        raise ConfigError("Retained image adapter supports at most 4096 prompt bytes")
    inputs = {"prompt": prompt, "size": size, "quality": quality,
        "references": [{"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in refs]}
    input_hash = content_hash(inputs)
    from .adapters.image import BindingImageClient
    image_client = BindingImageClient(binding)
    prepared = image_client.prepare(prompt, refs, size=size, quality=quality)
    attempt = uuid.uuid4().hex
    maximum = config["upstreams"][binding.upstream_id].get("max_concurrent_submissions", 1)
    with submission_slot(store_root, binding.upstream_id, maximum, wait=wait_for_slot,
            timeout_seconds=config["upstreams"][binding.upstream_id].get("request_timeout_seconds", 120)):
        with state_lock(root):
            state = read_state(root)
            prior = state["jobs"].get(job_id)
            if prior:
                if not retry and prior.get("status") == "completed" and prior.get("input_hash") == input_hash:
                    artifact = prior["artifact"]
                    path = within(root, artifact["path"])
                    if hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]:
                        return {"ok": True, "skipped": True, "artifact": artifact, "paid_creates": 0}
                if not retry or prior.get("status") not in {"completed", "output_invalid", "rejected", "failed"}:
                    raise ConfigError("Image job was already attempted; inspect its state. Unknown submission cannot be automatically retried")
                if prior.get("input_hash") != input_hash and retry != "replan":
                    raise ConfigError("Image inputs changed; use an explicit replan with a reason")
            history = prior.get("history", []) + [{k: v for k, v in prior.items() if k != "history"}] if prior else []
            if len(history) >= config.get("execution", {}).get("max_create_attempts_per_task", 2):
                raise ConfigError("Maximum image create attempts reached")
            reserve(state, config.get("budget", {}), attempt_id=attempt, job_id=job_id, kind="image",
                estimated=estimate(binding, 0, config.get("budget", {}).get("currency", "CNY")))
            state["jobs"][job_id] = {"kind": "image", "attempt_id": attempt, "status": "submitting",
                "input_hash": input_hash, "binding_snapshot": binding.snapshot(), "request": inputs,
                "prepared_request": prepared, "pid": os.getpid(), "host": socket.gethostname(),
                "created_at": int(time.time()), "history": history,
                "retry_kind": retry or "initial", "retry_reason": reason}
            save_state(root, state)
        provider_response = None
        try:
            provider_response = image_client.create_payload(prompt, refs, size=size, quality=quality)
            from .cli import legacy_engine
            legacy_engine()
            import media_client as wire
            data = wire._extract_image(provider_response)
            from media_client import save_image_bytes
            path = save_image_bytes(data, root / "assets" / "generated" / job_id / attempt)
            artifact = {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}
        except Exception as error:
            response_path = None
            if isinstance(provider_response, dict):
                destination = root / "jobs" / job_id / attempt / "provider-response.json"
                try:
                    atomic_json(destination, provider_response)
                    response_path = destination.relative_to(root).as_posix()
                except (ConfigError, OSError, TypeError, ValueError):
                    response_path = None
            with state_lock(root):
                state = read_state(root)
                status = "output_invalid" if isinstance(provider_response, dict) and response_path else "submission_unknown"
                state["jobs"][job_id].update(status=status, error=safe_error(error, [binding.key]),
                    provider_response=response_path)
                next(e for e in state["ledger"] if e["attempt_id"] == attempt)["status"] = status
                save_state(root, state)
            raise ConfigError(safe_error(error, [binding.key])) from None
    with state_lock(root):
        state = read_state(root)
        state["jobs"][job_id].update(status="completed", artifact=artifact, content_status="unverified",
            completed_at=time.time())
        next(e for e in state["ledger"] if e["attempt_id"] == attempt)["status"] = "completed"
        save_state(root, state)
    return {"ok": True, "job_id": job_id, "artifact": artifact, "content": "unverified"}


def generate_images(root: Path, config: dict, *, store_root: Path, items: list[dict]) -> dict:
    """Validate a whole image batch before dispatching independent requests."""
    if not isinstance(items, list) or not items:
        raise ConfigError("Image batch must contain at least one item")
    ids = [item.get("job_id") for item in items if isinstance(item, dict)]
    if len(ids) != len(items) or any(not isinstance(jid, str) for jid in ids) or len(set(ids)) != len(ids):
        raise ConfigError("Image batch needs unique job IDs")
    planned_ids = {job["id"] for job in load_project(root)["generation-plan"]["jobs"]}
    bindings = {}
    for item in items:
        job_id, prompt = item.get("job_id"), item.get("prompt")
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", job_id):
            raise ConfigError("Image job ID is invalid")
        if job_id in planned_ids or not isinstance(prompt, str) or not prompt.strip():
            raise ConfigError("Image IDs must be separate from video jobs and prompts must not be empty")
        references = item.get("references", [])
        if not isinstance(references, list) or any(not isinstance(path, Path) or not path.resolve().is_relative_to(root) or not path.is_file() for path in references):
            raise ConfigError("Image references must be registered files inside the project")
        if item.get("binding_id") is not None and not isinstance(item["binding_id"], str):
            raise ConfigError("Image binding ID must be a string")
        model = config["defaults"].get("image_model")
        if not model:
            raise ConfigError("Configure an independent defaults.image_model and route first")
        operation = "image-edit" if references else "text-to-image"
        binding = route_bindings(config, model, operation=operation, preferred=item.get("binding_id"),
            store_root=store_root)[0]
        bindings[job_id] = binding
        from .adapters.image import BindingImageClient
        BindingImageClient(binding).prepare(prompt, references, size=item.get("size", "1024x1024"),
            quality=item.get("quality", "auto"))
        if len(prompt.encode()) > 4096:
            raise ConfigError("Retained image adapter supports at most 4096 prompt bytes")
        with state_lock(root):
            prior = read_state(root)["jobs"].get(job_id)
        if prior:
            inputs = {"prompt": prompt, "size": item.get("size", "1024x1024"), "quality": item.get("quality", "auto"),
                "references": [{"path": p.resolve().relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in references]}
            artifact = prior.get("artifact", {})
            path = within(root, artifact.get("path", ""), exists=False)
            if not (prior.get("status") == "completed" and prior.get("input_hash") == content_hash(inputs)
                    and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == artifact.get("sha256")):
                raise ConfigError(f"Image job {job_id} has already been attempted; inspect its state before retrying")
    maximum = min(50, max(1, int(config.get("execution", {}).get("max_concurrent_image_tasks", 1))))
    results = {}
    with ThreadPoolExecutor(max_workers=min(maximum, len(items))) as pool:
        futures = {pool.submit(generate_image, root, config, store_root=store_root,
            job_id=item["job_id"], prompt=item["prompt"], references=item.get("references", []),
            binding_id=bindings[item["job_id"]].id, size=item.get("size", "1024x1024"),
            quality=item.get("quality", "auto"), wait_for_slot=True): item["job_id"] for item in items}
        for future in as_completed(futures):
            job_id = futures[future]
            try:
                results[job_id] = future.result()
            except Exception as error:
                results[job_id] = {"ok": False, "job_id": job_id, "status": "error", "error": str(error)}
    ordered = [results[item["job_id"]] for item in items]
    return {"ok": all(item.get("ok") for item in ordered), "images": ordered,
        "budget": summary(read_state(root)), "content": "unverified"}


def recover_image(root: Path, job_id: str, source: Path, receipt: dict) -> dict:
    """Attach an operator-recovered original result without another paid call."""
    from .catalog.evidence import verified_evidence
    from .runtime.jobs import _owner_alive
    verified_evidence(receipt.get("evidence"), root=root)
    if receipt.get("method") != "upstream-result" or not receipt.get("reviewer_id") or not receipt.get("upstream_record_id"):
        raise ConfigError("Recovered output needs upstream-result method, reviewer and original upstream record")
    if not source.is_file():
        raise ConfigError("Recovered image is missing")
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if receipt.get("output_sha256") != digest:
        raise ConfigError("Recovered output bytes do not match the receipt")
    with state_lock(root):
        state = read_state(root)
        current = state["jobs"].get(job_id, {})
        if current.get("kind") != "image" or current.get("status") not in {"submitting", "submission_unknown", "output_invalid"}:
            raise ConfigError("Only an unresolved image submission can recover an original output")
        if current["status"] == "submitting" and _owner_alive(current):
            raise ConfigError("Original image submission is still active")
        if current.get("attempt_id") != receipt.get("attempt_id") or current["binding_snapshot"]["fingerprint"] != receipt.get("binding_fingerprint"):
            raise ConfigError("Recovery must match the original image attempt/binding")
        from .cli import legacy_engine
        legacy_engine()
        from media_client import save_image_bytes
        path = save_image_bytes(data, root / "assets" / "generated" / job_id / current["attempt_id"])
        artifact = {"path": path.relative_to(root).as_posix(), "sha256": digest}
        atomic_json(root / "jobs" / job_id / current["attempt_id"] / "image-recovery.json", receipt)
        current.update(status="completed", artifact=artifact, content_status="unverified", recovery=receipt,
            completed_at=int(time.time()))
        next(e for e in state["ledger"] if e["attempt_id"] == current["attempt_id"])["status"] = "completed"
        save_state(root, state)
    return {"ok": True, "artifact": artifact, "content": "unverified", "paid_creates": 0}


def reprocess_image(root: Path, job_id: str) -> dict:
    """Decode the saved response again; never create another upstream image."""
    with state_lock(root):
        current = read_state(root)["jobs"].get(job_id, {})
        if current.get("kind") != "image" or current.get("status") not in {"submission_unknown", "output_invalid"} or not current.get("provider_response"):
            raise ConfigError("Reprocess requires an unresolved image with a saved provider response")
        attempt = current["attempt_id"]
        response_path = within(root, current["provider_response"])
    from .cli import legacy_engine
    legacy_engine()
    import media_client as wire
    try:
        data = wire._extract_image(load_json(response_path))
        path = wire.save_image_bytes(data, root / "assets" / "generated" / job_id / attempt)
        artifact = {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}
    except Exception as error:
        with state_lock(root):
            state = read_state(root)
            record = state["jobs"].get(job_id, {})
            if record.get("attempt_id") != attempt:
                raise ConfigError("Image attempt changed while decoding")
            record.update(status="output_invalid", error=safe_error(error))
            next(item for item in state["ledger"] if item["attempt_id"] == attempt)["status"] = "output_invalid"
            save_state(root, state)
        return {"ok": False, "job_id": job_id, "status": "output_invalid", "error": safe_error(error), "paid_creates": 0}
    with state_lock(root):
        state = read_state(root)
        record = state["jobs"].get(job_id, {})
        if record.get("attempt_id") != attempt:
            raise ConfigError("Image attempt changed while decoding")
        record.update(status="completed", artifact=artifact, content_status="unverified", completed_at=int(time.time()))
        next(item for item in state["ledger"] if item["attempt_id"] == attempt)["status"] = "completed"
        save_state(root, state)
    return {"ok": True, "job_id": job_id, "artifact": artifact, "content": "unverified", "paid_creates": 0}
