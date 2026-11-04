"""Candidate selection does not change task lifecycle or discard original attempts."""
from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
from pathlib import Path

from ..config.storage import ConfigError, atomic_json
from ..planning.project import load_project, within
from .state import read_state, save_state, state_lock


def records(record: dict) -> list[dict]:
    return [*record.get("history", []), {k: v for k, v in record.items() if k not in {"history", "selection"}}]


def selected(record: dict) -> dict:
    attempt = record.get("selection", {}).get("attempt_id")
    if not attempt:
        return record
    found = next((r for r in records(record) if r.get("attempt_id") == attempt), None)
    if not found or found.get("status") != "completed":
        raise ConfigError("Selected candidate is not a completed attempt")
    if found.get("artifact", {}).get("sha256") != record["selection"].get("sha256"):
        raise ConfigError("Selected candidate bytes no longer match selection")
    return found


def list_candidates(root: Path, job_id: str | None = None) -> dict:
    state = read_state(root)
    if job_id and job_id not in state["jobs"]:
        raise ConfigError("Unknown generated job")
    result = {}
    for jid, rec in state["jobs"].items():
        if not job_id or job_id == jid:
            result[jid] = {"selected_attempt": rec.get("selection", {}).get("attempt_id", rec.get("attempt_id")),
                "candidates": [{k: r.get(k) for k in ("attempt_id", "task_id", "status", "artifact", "retry_reason", "input_hash")} for r in records(rec)]}
    return {"ok": True, "jobs": result, "paid_creates": 0}


def select(root: Path, job_id: str, attempt_id: str, reason: str) -> dict:
    if not reason.strip():
        raise ConfigError("Selection requires an observed reason")
    with state_lock(root):
        state = read_state(root)
        rec = state["jobs"].get(job_id, {})
        candidate = next((r for r in records(rec) if r.get("attempt_id") == attempt_id and r.get("status") == "completed"), None)
        if not candidate:
            raise ConfigError("Candidate is not a completed attempt of this job")
        artifact = candidate.get("artifact", {})
        path = within(root, artifact.get("path", ""))
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
            raise ConfigError("Candidate bytes changed")
        rec["selection"] = {"attempt_id": attempt_id, "sha256": artifact["sha256"], "reason": reason,
                            "content_status": "selection-is-not-approval"}
        save_state(root, state)
    return {"ok": True, "job_id": job_id, "selection": rec["selection"], "paid_creates": 0}


def handoff(root: Path, job_id: str, at: float, *, next_job: str | None = None) -> dict:
    bundle = load_project(root)
    state = read_state(root)
    rec = selected(state["jobs"].get(job_id, {}))
    if rec.get("status") != "completed":
        raise ConfigError("Handoff requires a completed selected candidate")
    artifact = rec["artifact"]
    source = within(root, artifact["path"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != artifact["sha256"]:
        raise ConfigError("Source candidate changed")
    from ..timeline.render import probe, run
    media = probe(source)
    if isinstance(at, bool) or not isinstance(at, (float, int)) or not math.isfinite(at) or not 0 <= at < media["duration"]:
        raise ConfigError("Handoff time must be inside actual source duration")
    job = None
    if next_job:
        job = next((j for j in bundle["generation-plan"]["jobs"] if j["id"] == next_job), None)
        if not job or next_job == job_id:
            raise ConfigError("Choose a different known next job")
        if state["jobs"].get(next_job):
            raise ConfigError("Next job already has attempts; explicitly replan it rather than replacing its inputs")
        # Reject cycles before mutating the next job.
        jobs = {j["id"]: j for j in bundle["generation-plan"]["jobs"]}
        todo, seen = [job_id], set()
        while todo:
            dep = todo.pop()
            if dep == next_job:
                raise ConfigError("Handoff would introduce a generation dependency cycle")
            if dep not in seen:
                seen.add(dep)
                todo.extend(jobs.get(dep, {}).get("depends_on", []))
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("FFmpeg is required")
    target = root / "assets" / "handoffs" / f"{rec['attempt_id']}-{round(at*1000000)}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        run([ffmpeg, "-v", "error", "-y", "-ss", str(at), "-i", str(source), "-frames:v", "1", str(target)])
    elif target.with_suffix(".provenance.json").is_file():
        from ..config.storage import load_json
        previous = load_json(target.with_suffix(".provenance.json"))
        if previous.get("source_sha256") != artifact["sha256"] or previous.get("frame", {}).get("sha256") != hashlib.sha256(target.read_bytes()).hexdigest():
            raise ConfigError("Existing handoff bytes changed; preserve provenance and extract at a new timestamp")
    else:
        raise ConfigError("Existing handoff has no provenance; cannot trust it as a decoded source frame")
    if not target.is_file() or not target.stat().st_size:
        raise ConfigError("No decoded frame at requested time")
    ref = {"path": target.relative_to(root).as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "role": "opening-frame"}
    provenance = {"source_job": job_id, "attempt_id": rec["attempt_id"], "source": artifact["path"],
        "source_sha256": artifact["sha256"], "requested_source_time": at, "frame": ref,
        "note": "Decoded frame near requested timestamp; only next opening-frame control, not a last-frame API lock"}
    atomic_json(target.with_suffix(".provenance.json"), provenance)
    if job is not None:
        with state_lock(root):
            if read_state(root)["jobs"].get(next_job) or load_project(root)["generation-plan"] != bundle["generation-plan"]:
                raise ConfigError("Next job or plan changed during extraction; no generation inputs were replaced")
            job.update(operation="image-to-video", references=[ref], depends_on=list(dict.fromkeys([*job.get("depends_on", []), job_id])))
            atomic_json(within(root, bundle["project"]["files"].get("generation-plan", "generation-plan.json")), bundle["generation-plan"])
    return {"ok": True, "reference": ref, "provenance": str(target.with_suffix(".provenance.json")), "next_job": next_job, "paid_creates": 0}
