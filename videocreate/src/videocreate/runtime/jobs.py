from __future__ import annotations

import hashlib
import os
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from pathlib import Path

from ..catalog.bindings import Binding, route_bindings, validate_request
from ..config.storage import ConfigError, atomic_json, load_json, resolve_key, safe_error
from ..planning.project import compile_job, content_hash, load_project, validate_plan, within
from .budget import estimate, reserve, summary
from .state import read_state, save_state, state_lock
from .limits import submission_slot


def client(binding: Binding):
    from ..cli import legacy_engine
    engine = legacy_engine()
    from ..adapters.video import BindingVideoClient
    readers = {"sub2api-json-v1": engine.Sub2ApiVideoClient,
               "newapi-json-v1": engine.NewApiJsonVideoClient,
               "newapi-multipart-v1": engine.NewApiVideoClient}
    return BindingVideoClient(binding, readers[binding.adapter](binding.base_url, binding.key, binding.remote_model))


def pinned_binding(config: dict, snapshot: dict, store_root: Path) -> Binding:
    upstream = config["upstreams"].get(snapshot["upstream_id"])
    if not upstream:
        raise ConfigError("Original task upstream is missing; restore its instance ID to resume")
    # Rotating a key is valid; changing a route/URL must not move an existing task.
    key = resolve_key(upstream["auth"], store_root=store_root)
    if not key:
        raise ConfigError("Original task credential is unavailable")
    return Binding(snapshot["binding_id"], snapshot["model"], snapshot["remote_model"], snapshot["upstream_id"],
        snapshot["base_url"], snapshot["adapter"], key, snapshot["capabilities"], snapshot.get("adapter_options", {}))


def job_inputs(bundle: dict, job: dict, compilation: dict) -> str:
    # Timeline, title, subtitle styles and other shots do not recreate this job.
    # Selection of a new default route likewise does not override pinned tasks.
    return content_hash({"job": {k: v for k, v in job.items() if k not in {"binding_id", "model"}},
                         "prompt_sha256": compilation["prompt_sha256"]})


def generation_inputs(root: Path, bundle: dict, job: dict, compilation: dict) -> str:
    """Exact persisted identity, shared by submission and offline reuse checks."""
    references = job.get("references", [])
    ordered = [r for r in references if r["role"] == "opening-frame"] + [
        r for r in references if r["role"] != "opening-frame"]
    generation = content_hash({"job_inputs": job_inputs(bundle, job, compilation),
        "resolution": bundle["brief"]["resolution"], "aspect_ratio": bundle["brief"]["aspect_ratio"]})
    return content_hash({"generation": generation, "references": [
        {"path": within(root, ref["path"]).relative_to(root).as_posix(),
         "sha256": hashlib.sha256(within(root, ref["path"]).read_bytes()).hexdigest()}
        for ref in ordered]})


def current_inputs(root: Path, bundle: dict, job: dict, record: dict) -> str:
    maximum = record.get("binding_snapshot", {}).get("capabilities", {}).get("max_prompt_bytes", 4096)
    compilation = compile_job(bundle, job, max_bytes=maximum, root=root)
    return generation_inputs(root, bundle, job, compilation)


def _owner_alive(record: dict) -> bool:
    if record.get("host") != socket.gethostname():
        return True  # Cannot prove another host stopped; hold for reconciliation.
    try:
        pid = int(record["pid"])
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() != 87  # Access denied is inconclusive, not proof of death.
            try:
                code = wintypes.DWORD()
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
            finally:
                kernel.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, KeyError):
        return False


def _generate_serial(root: Path, config: dict, *, store_root: Path, job_ids: list[str] | None = None,
             poll_timeout: int = 900, retry: str | None = None, reason: str = "", progress=None,
             binding_override: dict[str, str] | None = None, wait_for_slot: bool = False,
             include_dependencies: bool = True, explicit_job_ids: set[str] | None = None) -> dict:
    bundle = load_project(root)
    validation = validate_plan(bundle, root)
    if not validation["ok"]:
        raise ConfigError("; ".join(validation["errors"]))
    jobs = {job["id"]: job for job in bundle["generation-plan"]["jobs"]}
    requested = list(jobs) if not job_ids else list(dict.fromkeys(job_ids))
    explicitly_requested = set(requested) if explicit_job_ids is None else explicit_job_ids
    if any(jid not in jobs for jid in requested):
        raise ConfigError("Unknown job ID")
    if "animation" in bundle:
        from ..animation.pipeline import execution_guard
        execution_guard(root, bundle, requested)
    if retry and (retry not in {"network", "content", "replan"} or not reason.strip() or not job_ids):
        raise ConfigError("Retry needs explicit jobs, kind network/content/replan and a reason")
    ordered, seen = [], set()
    def add(jid):
        if jid in seen:
            return
        seen.add(jid)
        for dep in jobs[jid].get("depends_on", []):
            add(dep)
        ordered.append(jid)
    if include_dependencies:
        for jid in requested:
            add(jid)
    else:
        ordered = requested
    results = []
    for jid in ordered:
        job = jobs[jid]
        with state_lock(root):
            state = read_state(root)
            prior = state["jobs"].get(jid, {})
            if prior.get("status") == "submitting":
                if _owner_alive(prior):
                    raise ConfigError(jid + ": another submit is active; no duplicate create was sent")
                prior["status"] = "submission_unknown"
                for entry in state["ledger"]:
                    if entry["attempt_id"] == prior.get("attempt_id"):
                        entry["status"] = "submission_unknown"
                save_state(root, state)
            if prior.get("status") == "submission_unknown":
                raise ConfigError(jid + ": submission unknown; 查不到记录 is not proof of rejection. Reconcile the original attempt")
            snapshot = prior.get("binding_snapshot")
        if snapshot and not (retry in {"content", "replan"} and jid in explicitly_requested) and not (binding_override and jid in binding_override):
            binding = pinned_binding(config, snapshot, store_root)
            candidates = [binding]
        else:
            model = job.get("model") or config["defaults"]["video_model"]
            preferred = (binding_override or {}).get(jid, job.get("binding_id"))
            candidates = route_bindings(config, model, operation=job["operation"], preferred=preferred, store_root=store_root)
            binding = candidates[0]
        if bundle["brief"].get("workflow_profile") == "explainer":
            from ..education import validate_research
            research = validate_research(bundle, root=root, ready=True, shot_ids=job["shot_ids"])
            if not research["ok"]:
                raise ConfigError("; ".join(research["errors"]))
        from ..routing import require_quality
        from ..series import check_episode_context
        check_episode_context(root, bundle)
        reference_entries = job.get("references", [])
        primary_entry = next((ref for ref in reference_entries if ref["role"] == "opening-frame"), None)
        primary_reference = within(root, primary_entry["path"]) if primary_entry else None
        reference_images = [within(root, ref["path"]) for ref in reference_entries if ref["role"] != "opening-frame"]
        actor_shots = [s for s in bundle["director"]["shots"] if s["id"] in job["shot_ids"]]
        kwargs = {"seconds": job["seconds"], "size": "auto", "resolution": bundle["brief"]["resolution"],
            "aspect_ratio": bundle["brief"]["aspect_ratio"],
            "generate_audio": any(s.get("audio", {}).get("mode", "ambience") in {"native-dialogue", "offscreen", "ambience"} for s in actor_shots),
            "primary_reference": primary_reference, "reference_images": reference_images}
        decisions = []
        for candidate in candidates:
            try:
                require_quality(store_root, candidate, job)
                candidate_compilation = compile_job(bundle, job, max_bytes=candidate.capabilities["max_prompt_bytes"], root=root)
                request = validate_request(candidate, {"operation": job["operation"], "prompt": candidate_compilation["prompt"],
                    "seconds": kwargs["seconds"], "resolution": kwargs["resolution"],
                    "aspect_ratio": kwargs["aspect_ratio"], "generate_audio": kwargs["generate_audio"],
                    "primary_reference": primary_reference, "reference_images": reference_images})
                if not request["ok"]:
                    raise ConfigError("; ".join(request["errors"]))
                candidate_client = client(candidate)
                candidate_prepared = candidate_client.prepare(candidate_compilation["prompt"], **kwargs)
            except ConfigError as error:
                decisions.append({"binding": candidate.id, "eligible": False, "reason": str(error)})
                continue
            binding, video_client = candidate, candidate_client
            compilation, prepared = candidate_compilation, candidate_prepared
            decisions.append({"binding": binding.id, "eligible": True})
            break
        else:
            raise ConfigError(jid + ": no compatible video binding: " + "; ".join(d["reason"] for d in decisions))
        selection = {"selected_model": binding.model, "selected_binding": binding.id, "decisions": decisions}
        input_hash = generation_inputs(root, bundle, job, compilation)
        needs_slot = not prior.get("task_id") or (retry in {"content", "replan"} and jid in explicitly_requested)
        maximum = config["upstreams"][binding.upstream_id].get("max_concurrent_submissions", 1)
        gate = submission_slot(store_root, binding.upstream_id, maximum, wait=wait_for_slot,
            timeout_seconds=config["upstreams"][binding.upstream_id].get("request_timeout_seconds", 120)) if needs_slot else nullcontext()
        create_error = None
        with gate:
            attempt_id, task_id, should_create = "", "", False
            with state_lock(root):
                state = read_state(root)
                current = state["jobs"].get(jid, {})
                if current.get("attempt_id") != prior.get("attempt_id"):
                    raise ConfigError(jid + ": job changed while preparing; reread state before proceeding")
                if current and current.get("input_hash") != input_hash and retry != "replan":
                    raise ConfigError(jid + ": generation inputs changed; explicitly replan only this job")
                task_id = current.get("task_id", "")
                if current.get("status") == "completed" and not (retry in {"content", "replan"} and jid in explicitly_requested):
                    artifact = current.get("artifact", {})
                    target = within(root, artifact.get("path", ""), exists=False)
                    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == artifact.get("sha256"):
                        results.append({"job_id": jid, "status": "completed", "skipped": True})
                        continue
                if retry == "network" and task_id:
                    pass  # Retry reads on the original task, never create another.
                elif retry in {"content", "replan"} and jid in explicitly_requested:
                    if current.get("status") not in {"completed", "rejected", "failed"}:
                        raise ConfigError(jid + ": cannot content-retry a pending or ambiguous task")
                    task_id = ""
                elif retry == "network" and current and current.get("status") != "rejected" and not task_id:
                    raise ConfigError(jid + ": network retry may create only after confirmed rejection")
                if not task_id:
                    if current and current.get("status") not in {"rejected", "failed", "completed"}:
                        raise ConfigError(jid + ": attempt is unresolved; no duplicate create")
                    if current and not retry:
                        raise ConfigError(jid + ": another create needs an explicit retry kind and reason")
                    history = current.get("history", []) + ([{k: v for k, v in current.items() if k != "history"}] if current else [])
                    attempts = len(history) + 1
                    if attempts > config.get("execution", {}).get("max_create_attempts_per_task", 2):
                        raise ConfigError(jid + ": maximum create attempts reached")
                    attempt_id = uuid.uuid4().hex
                    reserve(state, config.get("budget", {}), attempt_id=attempt_id, job_id=jid, kind="video",
                        estimated=estimate(binding, job["seconds"], config.get("budget", {}).get("currency", "CNY")))
                    current = {"status": "submitting", "attempt_id": attempt_id, "task_id": "", "input_hash": input_hash,
                        "binding_snapshot": binding.snapshot(), "prepared_request": prepared, "compilation": compilation,
                        "history": history, "retry_kind": retry or "initial", "retry_reason": reason,
                        "pid": os.getpid(), "host": socket.gethostname(), "created_at": int(time.time())}
                    current["selection"] = selection
                    state["jobs"][jid] = current
                    save_state(root, state)  # Durable intent before the only billable call.
                    job_dir = root / "jobs" / jid / attempt_id
                    atomic_json(job_dir / "request.json", {"prepared": prepared, "compilation": compilation, "input_hash": input_hash})
                    should_create = True
                else:
                    attempt_id = current["attempt_id"]
            if progress:
                progress({"job_id": jid, "phase": "submit" if should_create else "resume", "binding": binding.id})
            if should_create:
                try:
                    task_id = video_client.create(compilation["prompt"], **kwargs)
                except Exception as error:
                    from .health import observe
                    observe(store_root, binding, failed=True)
                    # A transport/5xx/trace-only response is ambiguous. Retrying a
                    # structured 4xx rejection still requires explicit intent.
                    from vc_common import APIError
                    from .failures import confirmed_rejection
                    rejected = confirmed_rejection(error, binding)
                    with state_lock(root):
                        state = read_state(root)
                        current = state["jobs"][jid]
                        current.update(status="rejected" if rejected else "submission_unknown", error=safe_error(error, [binding.key]),
                            submission_receipt=video_client.last_submission)
                        next(e for e in state["ledger"] if e["attempt_id"] == attempt_id)["status"] = current["status"]
                        save_state(root, state)
                    create_error = error
                if create_error is None:
                    from .health import observe
                    observe(store_root, binding, failed=False)
                    with state_lock(root):
                        state = read_state(root)
                        state["jobs"][jid].update(status="queued", task_id=task_id, submission_receipt=video_client.last_submission)
                        next(e for e in state["ledger"] if e["attempt_id"] == attempt_id)["status"] = "submitted"
                        save_state(root, state)
        if create_error is not None:
            from vc_common import APIError
            from .failures import confirmed_rejection
            if confirmed_rejection(create_error, binding):
                route = config.get("routes", {}).get(binding.model, {})
                candidates = route_bindings(config, binding.model, operation=job["operation"],
                    preferred=job.get("binding_id"), store_root=store_root, include_cooling=True)
                ids = [candidate.id for candidate in candidates]
                next_id = ids[ids.index(binding.id)+1] if route.get("policy") == "automatic-same-model" and binding.id in ids and ids.index(binding.id)+1 < len(ids) else None
                if next_id:
                    fallback_result = generate(root, config, store_root=store_root, job_ids=[jid], poll_timeout=poll_timeout,
                        retry="network", reason="configured same-model fallback after confirmed rejection",
                        progress=progress, binding_override={jid: next_id})
                    results.extend(fallback_result["jobs"])
                    continue
            raise ConfigError(safe_error(create_error, [binding.key])) from None
        try:
            def status_update(status, payload):
                with state_lock(root):
                    state = read_state(root)
                    state["jobs"][jid].update(status=status, last_polled_at=int(time.time()))
                    save_state(root, state)
                if progress:
                    progress({"job_id": jid, "phase": "poll", "status": status})
            destination = root / "jobs" / jid / attempt_id / "source.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            result_path = destination.parent / "provider-result.json"
            payload = None
            if current.get("provider_completed_at") and result_path.is_file():
                try:
                    saved = load_json(result_path)
                    if isinstance(saved, dict):
                        payload = saved
                except (ConfigError, OSError, UnicodeError):
                    pass  # A damaged local receipt can fall back to the known task's read path.
            if payload is None:
                payload = video_client.poll(task_id, timeout_seconds=poll_timeout, on_status=status_update)
                atomic_json(result_path, payload)
            with state_lock(root):
                state = read_state(root)
                state["jobs"][jid].update(status="downloading", provider_completed_at=int(time.time()),
                    provider_reported_model=payload.get("model") if isinstance(payload, dict) else None)
                save_state(root, state)
            if progress:
                progress({"job_id": jid, "phase": "download", "task_id": task_id})
            video_client.download(task_id, payload, destination)
            from ..timeline.render import probe
            media = probe(destination)
            artifact = {"path": destination.relative_to(root).as_posix(), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "media": media}
            with state_lock(root):
                state = read_state(root)
                state["jobs"][jid].update(status="completed", artifact=artifact, content_status="unverified",
                    completed_at=time.time())
                next(e for e in state["ledger"] if e["attempt_id"] == attempt_id)["status"] = "completed"
                save_state(root, state)
            reported_model = payload.get("model") if isinstance(payload, dict) else None
            results.append({"job_id": jid, "status": "completed", "artifact": artifact, "content": "unverified",
                "binding": binding.id, "model": binding.model, "remote_model": binding.remote_model,
                "provider_reported_model": reported_model,
                "warnings": ["Provider reports a different model ID; equivalence is unverified"]
                    if reported_model and reported_model != binding.remote_model else []})
        except Exception as error:
            from provider_contracts import ProviderTaskFailedError
            with state_lock(root):
                state = read_state(root)
                state["jobs"][jid].update(status="failed" if isinstance(error, ProviderTaskFailedError) else "read_pending",
                    error=safe_error(error, [binding.key]))
                save_state(root, state)
            raise ConfigError(safe_error(error, [binding.key])) from None
    return {"ok": True, "jobs": results, "budget": summary(read_state(root)), "content": "unverified"}


def generate(root: Path, config: dict, *, store_root: Path, job_ids: list[str] | None = None,
             poll_timeout: int = 900, retry: str | None = None, reason: str = "", progress=None,
             binding_override: dict[str, str] | None = None) -> dict:
    root = root.resolve()
    bundle = load_project(root)
    validation = validate_plan(bundle, root)
    if not validation["ok"]:
        raise ConfigError("; ".join(validation["errors"]))
    jobs = {job["id"]: job for job in bundle["generation-plan"]["jobs"]}
    requested = list(jobs) if not job_ids else list(dict.fromkeys(job_ids))
    if any(jid not in jobs for jid in requested):
        raise ConfigError("Unknown job ID")
    ordered, seen = [], set()
    def add(jid):
        if jid in seen:
            return
        seen.add(jid)
        for dep in jobs[jid].get("depends_on", []):
            add(dep)
        ordered.append(jid)
    for jid in requested:
        add(jid)
    maximum = min(50, max(1, int(config.get("execution", {}).get("max_concurrent_video_tasks", 1))))
    if maximum == 1 or len(ordered) < 2:
        return _generate_serial(root, config, store_root=store_root, job_ids=requested, poll_timeout=poll_timeout,
            retry=retry, reason=reason, progress=progress, binding_override=binding_override)

    remaining, completed, levels = set(ordered), set(), []
    while remaining:
        ready = [jid for jid in ordered if jid in remaining and set(jobs[jid].get("depends_on", [])).issubset(completed)]
        if not ready:
            raise ConfigError("Generation job dependencies contain a cycle")
        levels.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)

    results, failures = [], []
    for level in levels:
        level_results = {}
        current_state = read_state(root)
        runnable = []
        for jid in level:
            dependencies = jobs[jid].get("depends_on", [])
            if any(current_state["jobs"].get(dep, {}).get("status") != "completed" for dep in dependencies):
                level_results[jid] = {"job_id": jid, "status": "blocked", "blocked_by": dependencies}
                failures.append(jid)
            else:
                runnable.append(jid)
        with ThreadPoolExecutor(max_workers=min(maximum, max(1, len(runnable)))) as pool:
            futures = {pool.submit(_generate_serial, root, config, store_root=store_root, job_ids=[jid],
                poll_timeout=poll_timeout, retry=retry, reason=reason, progress=progress,
                binding_override=binding_override, wait_for_slot=True, include_dependencies=False,
                explicit_job_ids=set(requested)): jid for jid in runnable}
            for future in as_completed(futures):
                jid = futures[future]
                try:
                    items = future.result().get("jobs", [])
                    level_results[jid] = next((item for item in reversed(items) if item.get("job_id") == jid),
                        {"job_id": jid, "status": "unknown"})
                except Exception as error:
                    level_results[jid] = {"job_id": jid, "status": "error", "error": str(error)}
                    failures.append(jid)
        results.extend(level_results[jid] for jid in level)
    state = read_state(root)
    for jid in ordered:
        status = state["jobs"].get(jid, {}).get("status")
        if status not in {"completed"}:
            result = next((item for item in results if item["job_id"] == jid), None)
            if result and result.get("status") == "completed":
                continue
            if result is None:
                results.append({"job_id": jid, "status": status or "blocked"})
    results.sort(key=lambda item: ordered.index(item["job_id"]))
    return {"ok": not failures and all(item.get("status") == "completed" for item in results),
        "jobs": results, "errors": failures, "budget": summary(state), "content": "unverified"}
