"""Independent, hash-bound evidence; never upgrades configured wire capabilities."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
import json
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json

STAGES = ("catalog", "contract", "smoke", "quality")


def quality_method_errors(receipt: dict) -> list[str]:
    if receipt.get("stage") != "quality":
        return []
    # Unknown custom checks require video observation. Only these explicit
    # static/audio subsets may be certified by a narrower method.
    checks = receipt.get("checks", {})
    if not isinstance(checks, dict) or not checks or any(type(v) is not bool for v in checks.values()):
        return ["Quality checks must be nonempty boolean observations"]
    method = receipt.get("method")
    if method in {"human-video", "model-audio-video"}:
        if method == "human-video" and any(k in {"speech_intelligibility", "voice_identity", "audio_clean"} for k in checks):
            return ["Audio checks require actual listening"]
        return []
    if method in {"codex-vision", "ocr-and-vision"} and set(checks) <= {"sampled_framing", "sampled_identity", "sampled_lighting"}:
        return []
    if method in {"human-listening", "asr-and-human"} and set(checks) <= {"speech_intelligibility", "voice_identity", "audio_clean"}:
        return []
    return ["Temporal quality checks need video observation; sampled frames/audio certify only their named checks"]


def verified_evidence(items: list, *, root: Path | None = None) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ConfigError("Actual evidence files and SHA-256 are required")
    results = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ConfigError("Evidence needs a path and SHA-256")
        path = Path(item["path"])
        if root and not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            raise ConfigError("Evidence file is missing or its bytes changed")
        results.append({"path": str(path), "sha256": item["sha256"]})
    return results


def verify_quality_task(binding_fingerprint: str, receipt: dict) -> str:
    """Bind quality observations to the exact completed output of a saved task."""
    from ..planning.project import within
    from ..runtime.state import read_state

    project_value = receipt.get("project_root")
    if not isinstance(project_value, str) or not project_value.strip():
        raise ConfigError("Quality evidence needs the project_root containing the original completed task")
    project_root = Path(project_value).resolve()
    if not project_root.is_dir():
        raise ConfigError("Quality evidence project_root does not exist")
    attempt_id, task_id = receipt.get("attempt_id"), receipt.get("task_id")
    if not isinstance(attempt_id, str) or not attempt_id or not isinstance(task_id, str) or not task_id:
        raise ConfigError("Quality evidence requires original attempt_id and provider task_id")
    evidence = verified_evidence(receipt.get("evidence"))
    state = read_state(project_root)
    match = None
    for job in state["jobs"].values():
        candidates = [*job.get("history", []), job]
        for candidate in candidates:
            snapshot = candidate.get("binding_snapshot", {})
            if (candidate.get("status") == "completed" and candidate.get("attempt_id") == attempt_id
                    and candidate.get("task_id") == task_id
                    and snapshot.get("fingerprint") == binding_fingerprint):
                match = candidate
    if not match:
        raise ConfigError("Quality evidence IDs do not match a completed task on this binding")
    artifact = match.get("artifact", {})
    artifact_path = within(project_root, artifact.get("path", ""))
    artifact_sha = artifact.get("sha256")
    if not isinstance(artifact_sha, str) or hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact_sha:
        raise ConfigError("Completed task artifact is missing or its bytes changed")
    if not any(Path(item["path"]).resolve() == artifact_path.resolve() and item["sha256"] == artifact_sha for item in evidence):
        raise ConfigError("Quality evidence must include the exact downloaded video artifact for this task")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ConfigError("FFprobe is required to verify quality evidence is a video")
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(artifact_path)],
        capture_output=True)
    if probe.returncode:
        raise ConfigError("FFprobe could not inspect the completed task artifact")
    streams = json.loads(probe.stdout).get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ConfigError("Quality task evidence is not a video artifact")
    return str(project_root)


def record(store_root: Path, binding, receipt: dict) -> dict:
    errors = quality_method_errors(receipt)
    if errors:
        raise ConfigError("; ".join(errors))
    stage = receipt.get("stage")
    if stage not in STAGES or receipt.get("result") not in {"pass", "fail"}:
        raise ConfigError("Evidence stage/result must be catalog|contract|smoke|quality and pass|fail")
    if receipt.get("binding_fingerprint") != binding.snapshot()["fingerprint"]:
        raise ConfigError("Evidence belongs to a different binding snapshot")
    if receipt.get("operation") not in binding.capabilities["operations"]:
        raise ConfigError("Evidence operation is unsupported by this binding")
    if not all(isinstance(receipt.get(k), str) and receipt[k].strip() for k in ("reviewer_id", "method")):
        raise ConfigError("Evidence requires reviewer_id and method")
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or not checks or any(type(v) is not bool for v in checks.values()):
        raise ConfigError("Evidence checks must contain actual boolean observations")
    if receipt["result"] == "pass" and not all(checks.values()):
        raise ConfigError("A failing observation cannot produce a passing receipt")
    if stage in {"smoke", "quality"} and receipt["result"] == "pass":
        if not receipt.get("attempt_id") or not receipt.get("task_id"):
            raise ConfigError("Generation/quality evidence requires original attempt_id and provider task_id")
    if stage == "quality":
        project_root = verify_quality_task(binding.snapshot()["fingerprint"], receipt)
    else:
        project_root = None
    saved = {k: receipt[k] for k in ("stage", "result", "binding_fingerprint", "operation", "reviewer_id", "method", "checks")}
    for key in ("attempt_id", "task_id"):
        if receipt.get(key):
            saved[key] = str(receipt[key])
    if project_root:
        saved["project_root"] = project_root
    saved["evidence"] = verified_evidence(receipt.get("evidence"))
    saved["id"] = uuid.uuid4().hex
    destination = store_root / "binding-evidence" / binding.snapshot()["fingerprint"] / (saved["id"] + ".json")
    atomic_json(destination, saved)
    return {"ok": True, "receipt": str(destination), "stage": stage, "result": saved["result"], "paid_creates": 0}


def status(store_root: Path, binding) -> dict:
    folder = store_root / "binding-evidence" / binding.snapshot()["fingerprint"]
    rows = {stage: {"status": "unverified", "receipts": []} for stage in STAGES}
    stale = []
    for path in sorted(folder.glob("*.json")):
        try:
            receipt = load_json(path)
            if receipt["stage"] not in rows or receipt["binding_fingerprint"] != binding.snapshot()["fingerprint"]:
                raise ConfigError("Mismatched evidence")
            verified_evidence(receipt["evidence"])
            if receipt["stage"] == "quality":
                verify_quality_task(binding.snapshot()["fingerprint"], receipt)
            row = rows[receipt["stage"]]
            row["receipts"].append({"path": str(path), "operation": receipt["operation"], "result": receipt["result"]})
            row["status"] = "fail" if receipt["result"] == "fail" or row["status"] == "fail" else "reported_pass"
        except (ConfigError, OSError, KeyError, TypeError, ValueError):
            stale.append(str(path))
    return {"binding": binding.id, "fingerprint": binding.snapshot()["fingerprint"], "configured": True,
            "stages": rows, "stale_receipts": stale, "note": "Stages are independent observations for the listed operations. No evidence changes capability limits or guarantees artistic quality."}
