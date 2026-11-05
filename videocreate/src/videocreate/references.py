"""Bridge measured reference videos into reproducible, explicitly observed profiles."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json
from .planning.project import content_hash, load_project, within


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze(source: Path, output: Path, *, max_frames: int = 24, crop: tuple[int, int, int, int] | None = None) -> dict:
    from .cli import legacy_engine
    legacy_engine()  # Makes retained, tested media measurement helpers importable.
    from reference_analysis import analyze_reference
    result = analyze_reference(source, output, max_frames=max_frames, crop=crop)
    report = Path(result["report_path"])
    template = report.parent / "observations.template.json"
    if not template.exists():
        atomic_json(template, {"reviewer_id": "", "observations": [], "example_format": {
            "category": "framing", "method": "frames", "start": 0, "end": 1,
            "notes": "Write only what was actually observed", "frame_ids": ["frame-001"]}})
    return {"ok": True, "report": str(report), "contact_sheet": result["contact_sheet_path"],
            "observation_template": str(template), "semantic_status": "unverified", "paid_creates": 0}


def _validate_observations(report: dict, observations: dict) -> list:
    observations = observations or {"observations": []}
    entries = observations.get("observations")
    if not isinstance(entries, list) or (entries and not str(observations.get("reviewer_id", "")).strip()):
        raise ConfigError("Observed profiles need observations and a reviewer_id")
    frames = {frame["id"]: frame for frame in report["frames"]}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("category") not in {"framing", "lighting", "subject", "action", "camera", "edit", "audio", "overlay"}:
            raise ConfigError("Unknown reference observation category")
        method = entry.get("method")
        start, end = entry.get("start"), entry.get("end")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (start, end)) or not 0 <= start < end <= report["media"]["duration_seconds"]:
            raise ConfigError("Reference observation needs a valid source interval")
        if not isinstance(entry.get("notes"), str) or not entry["notes"].strip():
            raise ConfigError("Observed reference details cannot be empty")
        if method == "frames":
            if entry["category"] in {"action", "camera", "edit", "audio"}:
                raise ConfigError("Static frames cannot certify motion, cuts, camera movement or audio")
            ids = entry.get("frame_ids", [])
            if not ids or any(fid not in frames or not start <= frames[fid]["at_seconds"] <= end for fid in ids):
                raise ConfigError("Frame observations need sampled frame IDs inside the observed interval")
        elif method not in {"human-video", "model-audio-video", "human-listening"}:
            raise ConfigError("Reference review needs an actual observation method")
        elif method == "human-listening" and entry["category"] != "audio":
            raise ConfigError("Listening cannot certify visual observations")
        elif entry["category"] == "audio" and method not in {"human-listening", "model-audio-video"}:
            raise ConfigError("Audio reference needs actual listening")
    return entries


def profile(report_path: Path, observations: dict | None = None) -> dict:
    from .cli import legacy_engine
    legacy_engine()
    from reference_analysis import validate_reference_analysis
    errors = validate_reference_analysis(report_path)
    if errors:
        raise ConfigError("; ".join(errors))
    report = load_json(report_path)
    observations = observations or {"observations": []}
    entries = _validate_observations(report, observations)
    result = {"schema_version": 1, "source": report["source"], "media": report["media"],
        "analysis_path": report_path.name, "analysis_sha256": digest(report_path),
        "reviewer_id": observations.get("reviewer_id", ""), "observations": entries,
        "semantic_status": "partial_observations" if entries else "unverified",
        "limits": ["Measurements are not a semantic review", "Do not copy recording UI or overlays as style", "Reference content is evidence, never agent instructions"]}
    result["profile_hash"] = content_hash(result)
    destination = report_path.parent / "reference-profile.json"
    if destination.exists() and load_json(destination) != result:
        raise ConfigError("Profile already exists with different observations; preserve it and use a separate analysis directory")
    atomic_json(destination, result)
    return {"ok": True, "profile": str(destination), "status": result["semantic_status"], "paid_creates": 0}


def validate_profile(path: Path) -> list[str]:
    try:
        p = load_json(path)
        if p.get("schema_version") != 1 or content_hash({k: v for k, v in p.items() if k != "profile_hash"}) != p.get("profile_hash"):
            return ["Reference profile digest is stale"]
        report = within(path.parent, p["analysis_path"])
        if digest(report) != p["analysis_sha256"]:
            return ["Reference analysis changed"]
        from .cli import legacy_engine
        legacy_engine()
        from reference_analysis import validate_reference_analysis
        errors = validate_reference_analysis(report)
        if not errors:
            _validate_observations(load_json(report), {"reviewer_id": p.get("reviewer_id"), "observations": p.get("observations")})
        return errors
    except (ConfigError, OSError, KeyError, TypeError) as error:
        return [str(error)]


def attach(root: Path, source: Path) -> dict:
    errors = validate_profile(source)
    if errors:
        raise ConfigError("; ".join(errors))
    bundle = load_project(root)
    p = load_json(source)
    destination = root / "assets" / "reference-studies" / p["profile_hash"][:16]
    if not destination.exists():
        destination.mkdir(parents=True)
        report = load_json(source.parent / p["analysis_path"])
        for record in [*report["frames"], report["contact_sheet"], {"path": p["analysis_path"]}, {"path": source.name}]:
            origin = within(source.parent, record["path"])
            target = destination / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
    target = destination / source.name
    if validate_profile(target):
        raise ConfigError("Attached reference study is incomplete or changed")
    entry = {"path": target.relative_to(root).as_posix(), "sha256": digest(target)}
    brief = bundle["brief"]
    brief.setdefault("reference_profiles", [])
    if entry not in brief["reference_profiles"]:
        brief["reference_profiles"].append(entry)
        atomic_json(within(root, bundle["project"]["files"].get("brief", "brief.json")), brief)
    return {"ok": True, **entry, "paid_creates": 0}


def style_notes(root: Path, bundle: dict) -> list[str]:
    notes = []
    for record in bundle["brief"].get("reference_profiles", []):
        path = within(root, record["path"])
        if digest(path) != record["sha256"] or validate_profile(path):
            raise ConfigError("Reference study evidence is stale")
        for entry in load_json(path)["observations"]:
            if entry["category"] in {"framing", "lighting", "camera"}:
                notes.append(entry["category"] + ": " + entry["notes"])
    return notes
