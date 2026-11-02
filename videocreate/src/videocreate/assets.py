from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import os
import socket
import uuid
from pathlib import Path

from .catalog.bindings import route_bindings, validate_request
from .config.storage import ConfigError, atomic_json, safe_error
from .planning.project import content_hash, load_project, within
from .runtime.budget import estimate, reserve
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
                   references: list[Path], binding_id: str | None = None, size="1024x1024", quality="auto") -> dict:
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
    with submission_slot(store_root, binding.upstream_id, maximum):
        with state_lock(root):
            state = read_state(root)
            prior = state["jobs"].get(job_id)
            if prior:
                if prior.get("status") == "completed" and prior.get("input_hash") == input_hash:
                    artifact = prior["artifact"]
                    path = within(root, artifact["path"])
                    if hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]:
                        return {"ok": True, "skipped": True, "artifact": artifact, "paid_creates": 0}
                raise ConfigError("Image job was already attempted; inspect its state. Unknown submission cannot be automatically retried")
            reserve(state, config.get("budget", {}), attempt_id=attempt, job_id=job_id, kind="image",
                estimated=estimate(binding, 0, config.get("budget", {}).get("currency", "CNY")))
            state["jobs"][job_id] = {"kind": "image", "attempt_id": attempt, "status": "submitting",
                "input_hash": input_hash, "binding_snapshot": binding.snapshot(), "request": inputs,
                "prepared_request": prepared, "pid": os.getpid(), "host": socket.gethostname()}
            save_state(root, state)
        try:
            data = image_client.create(prompt, refs, size=size, quality=quality)
            from media_client import save_image_bytes
            path = save_image_bytes(data, root / "assets" / "generated" / job_id / attempt)
            artifact = {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}
        except Exception as error:
            with state_lock(root):
                state = read_state(root)
                state["jobs"][job_id].update(status="submission_unknown", error=safe_error(error, [binding.key]))
                next(e for e in state["ledger"] if e["attempt_id"] == attempt)["status"] = "submission_unknown"
                save_state(root, state)
            raise ConfigError(safe_error(error, [binding.key])) from None
    with state_lock(root):
        state = read_state(root)
        state["jobs"][job_id].update(status="completed", artifact=artifact, content_status="unverified")
        next(e for e in state["ledger"] if e["attempt_id"] == attempt)["status"] = "completed"
        save_state(root, state)
    return {"ok": True, "job_id": job_id, "artifact": artifact, "content": "unverified"}


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
        if current.get("kind") != "image" or current.get("status") not in {"submitting", "submission_unknown"}:
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
        current.update(status="completed", artifact=artifact, content_status="unverified", recovery=receipt)
        next(e for e in state["ledger"] if e["attempt_id"] == current["attempt_id"])["status"] = "completed"
        save_state(root, state)
    return {"ok": True, "artifact": artifact, "content": "unverified", "paid_creates": 0}
