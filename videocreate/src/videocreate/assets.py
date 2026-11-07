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
    if not source.is_file() or mimetypes.guess_type(source.name)[0] not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise ConfigError("Reference must be an existing JPEG, PNG, WebP or GIF file")
    from .media.gif import probe_image
    probe_image(source)
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


def _image_candidates(config: dict, *, model: str, prompt: str, references: list[Path],
                      binding_id: str | None, size: str, quality: str, output_format: str,
                      store_root: Path) -> list:
    operation = "image-edit" if references else "text-to-image"
    candidates = route_bindings(config, model, operation=operation, preferred=binding_id, store_root=store_root)
    from .adapters.image import BindingImageClient
    eligible = []
    errors = []
    for candidate in candidates:
        try:
            BindingImageClient(candidate).prepare(prompt, references, size=size, quality=quality,
                                                  output_format=output_format)
            eligible.append(candidate)
        except ConfigError as error:
            errors.append(candidate.id + ": " + str(error))
    if not eligible:
        detail = "; ".join(errors) if errors else "no enabled image binding"
        raise ConfigError("No same-model image binding can satisfy this request: " + detail)
    return eligible


def _select_image_route(config: dict, *, requested_model: str | None, binding_id: str | None,
                        prompt: str, references: list[Path], size: str, quality: str,
                        output_format: str, store_root: Path) -> tuple[str, list, dict]:
    default_model = config["defaults"].get("image_model")
    if binding_id:
        binding = config.get("bindings", {}).get(binding_id)
        if not binding:
            raise ConfigError("Unknown image binding")
        if requested_model and requested_model != binding.get("model"):
            raise ConfigError("Explicit model and binding select different image models")
        models, policy = [binding["model"]], "fixed-binding"
    elif requested_model:
        models, policy = [requested_model], "explicit-model"
    else:
        selector = config.get("model_selection", {}).get("image", {})
        policy = selector.get("policy", "fixed")
        if policy == "first-compatible":
            models = selector.get("candidates", [])
            if not models and default_model:
                models = [default_model]
        else:
            models = [default_model] if default_model else []
    if not models:
        raise ConfigError("Configure defaults.image_model or model_selection.image.candidates")
    decisions = []
    for candidate_model in models:
        if not isinstance(candidate_model, str) or config.get("models", {}).get(candidate_model, {}).get("kind") != "image":
            decisions.append({"model": candidate_model, "eligible": False, "reason": "not a configured image model"})
            continue
        try:
            candidates = _image_candidates(config, model=candidate_model, prompt=prompt, references=references,
                binding_id=binding_id, size=size, quality=quality, output_format=output_format,
                store_root=store_root)
        except ConfigError as error:
            decisions.append({"model": candidate_model, "eligible": False, "reason": str(error)})
            continue
        decisions.append({"model": candidate_model, "eligible": True,
                          "binding_candidates": [item.id for item in candidates]})
        return candidate_model, candidates, {"policy": policy, "requested_model": requested_model,
            "selected_model": candidate_model, "decisions": decisions}
    raise ConfigError("No image model satisfies this request: " + "; ".join(
        f"{item['model']}: {item['reason']}" for item in decisions))


def _image_input_hash(root: Path, *, model: str, prompt: str, size: str, quality: str,
                      output_format: str, references: list[Path]) -> str:
    return content_hash({"prompt": prompt, "size": size, "quality": quality,
        "output_format": output_format, "selected_model": model,
        "references": [{"path": path.resolve().relative_to(root).as_posix(),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in references]})


def _image_artifact(root: Path, path: Path, data: bytes, output_format: str = "png", caps: dict | None = None) -> dict:
    artifact = {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(data).hexdigest()}
    if path.suffix.lower() == ".gif":
        from .media.gif import inspect_gif
        artifact.update(inspect_gif(data))
        caps = caps or {}
        if (artifact["frame_count"] > caps.get("max_animation_frames", 3000)
                or artifact["duration_ms"] > caps.get("max_animation_duration_seconds", 30) * 1000):
            raise ConfigError("GIF output exceeds the configured frame or duration limit")
    if output_format == "gif" and not artifact.get("animated"):
        raise ConfigError("The upstream did not return a multi-frame GIF for the animated output request")
    return artifact


def generate_image(root: Path, config: dict, *, store_root: Path, job_id: str, prompt: str,
                   references: list[Path], binding_id: str | None = None, size="1024x1024", quality="auto",
                   output_format: str = "png", wait_for_slot: bool = False,
                   retry: str | None = None, reason: str = "",
                   model: str | None = None, _route_candidates: list | None = None,
                   _candidate_index: int = 0, _selection: dict | None = None) -> dict:
    root = root.resolve()
    if retry and (retry not in {"content", "replan"} or not reason.strip()):
        raise ConfigError("Image retry needs content/replan and an observed reason")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", job_id):
        raise ConfigError("Image job ID is invalid")
    if any(job["id"] == job_id for job in load_project(root)["generation-plan"]["jobs"]):
        raise ConfigError("Image job ID must differ from planned video job IDs")
    if not prompt.strip():
        raise ConfigError("Image prompt must not be empty")
    refs = [path.resolve() for path in references]
    for path in refs:
        if not path.is_relative_to(root) or not path.is_file():
            raise ConfigError("Register image references inside the project first")
    if not retry:
        with state_lock(root):
            prior = read_state(root)["jobs"].get(job_id, {})
        snapshot = prior.get("binding_snapshot", {})
        pinned_model = snapshot.get("model")
        if (prior.get("status") == "completed" and pinned_model
                and (model is None or model == pinned_model)
                and (binding_id is None or binding_id == snapshot.get("binding_id"))):
            current_hash = _image_input_hash(root, model=pinned_model, prompt=prompt, size=size, quality=quality,
                output_format=output_format, references=refs)
            legacy_hash = content_hash({"prompt": prompt, "size": size, "quality": quality,
                "references": [{"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in refs]})
            accepted_hashes = {current_hash}
            if "output_format" not in prior.get("request", {}) and output_format == "png":
                accepted_hashes.add(legacy_hash)
            artifact = prior.get("artifact", {})
            path = within(root, artifact.get("path", ""), exists=False)
            if prior.get("input_hash") in accepted_hashes and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == artifact.get("sha256"):
                return {"ok": True, "skipped": True, "artifact": artifact, "model": pinned_model,
                    "binding": snapshot.get("binding_id"), "paid_creates": 0}
    if _route_candidates:
        selected_model, candidates = model, _route_candidates
        selection = _selection or {"policy": "same-model-fallback", "requested_model": model, "selected_model": model}
    else:
        selected_model, candidates, selection = _select_image_route(config, requested_model=model,
            binding_id=binding_id, prompt=prompt, references=refs, size=size, quality=quality,
            output_format=output_format, store_root=store_root)
    model = selected_model
    if _candidate_index >= len(candidates):
        raise ConfigError("No remaining same-model image upstream candidates")
    binding = candidates[_candidate_index]
    report = validate_request(binding, {"operation": "image-edit" if refs else "text-to-image", "prompt": prompt, "references": refs})
    if not report["ok"]:
        raise ConfigError("; ".join(report["errors"]))
    if len(prompt.encode()) > 4096:
        raise ConfigError("Retained image adapter supports at most 4096 prompt bytes")
    input_hash = _image_input_hash(root, model=model, prompt=prompt, size=size, quality=quality,
                                   output_format=output_format, references=refs)
    inputs = {"prompt": prompt, "size": size, "quality": quality, "output_format": output_format,
              "requested_model": selection.get("requested_model", model), "selected_model": model,
              "references": [{"path": path.relative_to(root).as_posix(),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in refs]}
    from .adapters.image import BindingImageClient
    image_client = BindingImageClient(binding)
    prepared = image_client.prepare(prompt, refs, size=size, quality=quality, output_format=output_format)
    attempt = uuid.uuid4().hex
    maximum = config["upstreams"][binding.upstream_id].get("max_concurrent_submissions", 1)
    attempt_error = None
    fallback_index = None
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
                automatic_rejection_recovery = (prior.get("status") == "rejected"
                    and prior.get("input_hash") == input_hash and retry == "content"
                    and reason.startswith("automatic same-model fallback after confirmed rejection"))
                if not automatic_rejection_recovery and (not retry or prior.get("status") not in {"completed", "output_invalid", "rejected", "failed"}):
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
                "retry_kind": retry or "initial", "retry_reason": reason,
                "requested_model": selection.get("requested_model", model),
                "selected_model": model, "selection": selection, "output_format": output_format}
            save_state(root, state)
        provider_response = None
        try:
            provider_response = image_client.create_payload(prompt, refs, size=size, quality=quality,
                                                            output_format=output_format)
            from .cli import legacy_engine
            legacy_engine()
            import media_client as wire
            data = wire._extract_image(provider_response)
            from media_client import save_image_bytes
            path = save_image_bytes(data, root / "assets" / "generated" / job_id / attempt)
            artifact = _image_artifact(root, path, data, output_format, binding.capabilities)
        except Exception as error:
            from .runtime.health import observe
            if provider_response is None:
                observe(store_root, binding, failed=True)
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
                from vc_common import APIError
                from .runtime.failures import confirmed_rejection
                rejected = confirmed_rejection(error, binding)
                status = ("rejected" if rejected else
                          "output_invalid" if isinstance(provider_response, dict) and response_path else "submission_unknown")
                state["jobs"][job_id].update(status=status, error=safe_error(error, [binding.key]),
                    provider_response=response_path)
                next(e for e in state["ledger"] if e["attempt_id"] == attempt)["status"] = status
                save_state(root, state)
            if rejected and _candidate_index + 1 < len(candidates):
                fallback_index = _candidate_index + 1
            else:
                attempt_error = safe_error(error, [binding.key])
    if attempt_error:
        raise ConfigError(attempt_error)
    if fallback_index is not None:
        return generate_image(root, config, store_root=store_root, job_id=job_id, prompt=prompt,
            references=refs, binding_id=candidates[fallback_index].id, size=size, quality=quality,
            output_format=output_format, wait_for_slot=wait_for_slot, retry="content",
            reason="automatic same-model fallback after confirmed rejection",
            model=model,
            _route_candidates=candidates, _candidate_index=fallback_index, _selection=selection)
    with state_lock(root):
        state = read_state(root)
        state["jobs"][job_id].update(status="completed", artifact=artifact, content_status="unverified",
            completed_at=time.time())
        next(e for e in state["ledger"] if e["attempt_id"] == attempt)["status"] = "completed"
        paid_creates = _candidate_index + 1
        save_state(root, state)
    from .runtime.health import observe
    observe(store_root, binding, failed=False)
    return {"ok": True, "job_id": job_id, "artifact": artifact, "content": "unverified",
        "binding": binding.id, "model": binding.model, "selection": selection, "paid_creates": paid_creates}


def generate_images(root: Path, config: dict, *, store_root: Path, items: list[dict]) -> dict:
    """Validate a whole image batch before dispatching independent requests."""
    root = root.resolve()
    if not isinstance(items, list) or not items:
        raise ConfigError("Image batch must contain at least one item")
    ids = [item.get("job_id") for item in items if isinstance(item, dict)]
    if len(ids) != len(items) or any(not isinstance(jid, str) for jid in ids) or len(set(ids)) != len(ids):
        raise ConfigError("Image batch needs unique job IDs")
    planned_ids = {job["id"] for job in load_project(root)["generation-plan"]["jobs"]}
    resolved_items = []
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
        model, candidates, selection = _select_image_route(config, requested_model=item.get("model"),
            binding_id=item.get("binding_id"), prompt=prompt, references=references,
            size=item.get("size", "1024x1024"), quality=item.get("quality", "auto"),
            output_format=item.get("output_format", "png"), store_root=store_root)
        if len(prompt.encode()) > 4096:
            raise ConfigError("Retained image adapter supports at most 4096 prompt bytes")
        with state_lock(root):
            prior = read_state(root)["jobs"].get(job_id)
        if prior:
            output_format = item.get("output_format", "png")
            inputs_hash = _image_input_hash(root, model=model, prompt=prompt,
                size=item.get("size", "1024x1024"), quality=item.get("quality", "auto"),
                output_format=output_format, references=references)
            artifact = prior.get("artifact", {})
            path = within(root, artifact.get("path", ""), exists=False)
            if not (prior.get("status") == "completed" and prior.get("input_hash") == inputs_hash
                    and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == artifact.get("sha256")):
                raise ConfigError(f"Image job {job_id} has already been attempted; inspect its state before retrying")
        resolved_items.append({**item, "model": model, "_selection": selection})
    items = resolved_items
    maximum = min(50, max(1, int(config.get("execution", {}).get("max_concurrent_image_tasks", 1))))
    results = {}
    with ThreadPoolExecutor(max_workers=min(maximum, len(items))) as pool:
        futures = {pool.submit(generate_image, root, config, store_root=store_root,
            job_id=item["job_id"], prompt=item["prompt"], references=item.get("references", []),
            binding_id=item.get("binding_id"), size=item.get("size", "1024x1024"),
            quality=item.get("quality", "auto"), output_format=item.get("output_format", "png"),
            model=item.get("model"),
            _selection=item.get("_selection"),
            wait_for_slot=True): item["job_id"] for item in items}
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
        artifact = _image_artifact(root, path, data, current.get("output_format", "png"), current["binding_snapshot"]["capabilities"])
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
        artifact = _image_artifact(root, path, data, current.get("output_format", "png"), current["binding_snapshot"]["capabilities"])
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
