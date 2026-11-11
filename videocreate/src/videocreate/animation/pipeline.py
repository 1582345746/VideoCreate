"""Thin orchestration over existing image/video jobs, timeline and receipts."""
from __future__ import annotations

import shutil
from pathlib import Path
from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash, load_project, validate_plan, within
from ..references import digest
from ..runtime.state import read_state, state_lock


def checked(root):
    bundle = load_project(root)
    report = validate_plan(bundle, root)
    if not report["ok"] or "animation" not in bundle:
        raise ConfigError("; ".join(report["errors"]) or "Requires an animation project")
    return bundle


def keyframe_spec(root, bundle, sid):
    shots = {s["id"]: s for s in bundle["director"]["shots"]}
    if sid not in shots:
        raise ConfigError("Unknown animation shot")
    shot = shots[sid]
    assets = {a["id"]: a for a in bundle["director"]["assets"]}
    scene = next(s for s in bundle["director"]["scenes"] if s["id"] == shot["scene_id"])
    # A shared cast sheet may be registered for several characters. Send its bytes once.
    refs, seen = [], set()
    for aid in shot.get("asset_ids", []):
        for reference in assets[aid].get("references", []):
            sha = digest(within(root, reference))
            if sha not in seen:
                seen.add(sha)
                refs.append(reference)
    from .references import guidance_sheet
    refs = guidance_sheet(root, refs)
    # Use start conditions, not the shot's later action/result. A board is never an opening image.
    prompt = "\n".join(["Create ONE clean full-frame opening image for an animated shot. No panels, turnaround, captions, watermark or floating graphic accents.",
        "Style: " + bundle["brief"]["visual_style"], "Scene: " + scene["map"], "Framing: " + shot["framing"],
        "Exact opening composition and prop state: " + shot["opening_frame"],
        "Starting positions: " + str(shot.get("entry_state", "")),
        *[aid + ": " + assets[aid]["description"] + "; " + "; ".join(assets[aid].get("invariants", [])) for aid in shot.get("asset_ids", [])],
        "References preserve character identity and wardrobe. Current opening composition/prop state takes precedence over the reference pose or objects.",
        "Camera axis: " + scene["axis"] + "; " + shot.get("screen_direction", "")])
    size = {"9:16": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"}.get(bundle["brief"]["aspect_ratio"], "1024x1536")
    return {"job_id": "keyframe-" + sid, "shot_id": sid, "prompt": prompt, "size": size,
        "references": refs, "input_hash": content_hash({"prompt": prompt, "size": size,
            "references": [{"path": r, "sha256": digest(within(root, r))} for r in refs]})}


def keyframes(root, *, shot_ids=None, config=None, store_root=None, generate=False, model=None, binding=None,
              retry=None, reason=""):
    bundle = checked(root)
    selected = shot_ids or bundle["animation"]["adaptation"]["pilot_shot_ids"]
    specs = [keyframe_spec(root, bundle, sid) for sid in dict.fromkeys(selected)]
    if not generate:
        return {"ok": True, "specifications": specs, "status": "prepared_only", "paid_creates": 0}
    if config is None or store_root is None:
        raise ConfigError("Generating keyframes requires configured image service")
    from ..assets import generate_image, generate_images
    if retry:
        if not shot_ids or len(specs) != 1 or not reason.strip():
            raise ConfigError("Image retries require one explicit shot and an observed reason")
        s = specs[0]
        return generate_image(root, config, store_root=store_root, job_id=s["job_id"], prompt=s["prompt"],
            references=[within(root, r) for r in s["references"]], size=s["size"], model=model,
            binding_id=binding, retry=retry, reason=reason)
    results = generate_images(root, config, store_root=store_root, items=[{
        "job_id": s["job_id"], "prompt": s["prompt"], "references": [within(root, r) for r in s["references"]],
        "size": s["size"], "model": model, "binding_id": binding, "retry": retry, "reason": reason} for s in specs])
    return results


FRAME_CHECKS = ("single_frame", "identities", "character_count", "wardrobe", "limbs", "props", "opening_state")


def select_frame(root, sid, source, observation, *, include_guidance=False):
    bundle = checked(root)
    spec = keyframe_spec(root, bundle, sid)
    from ..media.gif import probe_image
    media = probe_image(source)
    if media.get("animated"):
        raise ConfigError("Select a static single-frame opening image, not animation or a storyboard")
    sha = digest(source)
    if (observation.get("sha256") != sha or observation.get("input_hash") != spec["input_hash"]
            or observation.get("method") not in {"human-image", "codex-vision"}
            or not observation.get("reviewer_id") or not observation.get("notes")
            or set(observation.get("checks", {})) != set(FRAME_CHECKS)
            or any(observation["checks"].get(k) != "pass" for k in FRAME_CHECKS)):
        raise ConfigError("Opening image needs hash-bound inspection of single frame, identities, count, wardrobe, limbs, props and start state")
    target = root / "assets/animation/opening" / (sid + "-" + sha[:20] + source.suffix.lower())
    relative = target.relative_to(root).as_posix()
    with state_lock(root):
        current = checked(root)
        if keyframe_spec(root, current, sid)["input_hash"] != spec["input_hash"]:
            raise ConfigError("Shot changed during opening image review")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        job = next(j for j in current["generation-plan"]["jobs"] if j["shot_ids"] == [sid])
        job["operation"] = "image-to-video"
        job["references"] = [{"path": relative, "sha256": sha, "role": "opening-frame"}]
        for asset in current["director"]["assets"]:
            if include_guidance and asset["id"] in next(s for s in current["director"]["shots"] if s["id"] == sid).get("asset_ids", []):
                role = {"character": "identity", "prop": "prop", "scene": "scene"}.get(asset["kind"])
                if role:
                    job["references"].extend({"path": r, "sha256": digest(within(root, r)), "role": role} for r in asset.get("references", []))
        atomic_json(root / current["project"]["files"]["generation-plan"], current["generation-plan"])
        atomic_json(root / "animation-frames" / (sid + ".json"), {"shot_id": sid, "path": relative, **observation})
    return {"ok": True, "shot_id": sid, "path": relative, "content": "image-reviewed-video-unverified", "paid_creates": 0}


def run(root, config, *, store_root, stage="pilot", job_ids=None, poll_timeout=900, retry=None, reason=""):
    bundle = checked(root)
    jobs = bundle["generation-plan"]["jobs"]
    pilot_shots = bundle["animation"]["adaptation"]["pilot_shot_ids"]
    pilot_jobs = [j["id"] for j in jobs if any(s in pilot_shots for s in j["shot_ids"])]
    if stage not in {"pilot", "full"}:
        raise ConfigError("Unknown animation execution stage")
    if stage == "full":
        from ..review.receipts import summary
        reviews = summary(root, bundle)["assets"]
        for jid in pilot_jobs:
            if not reviews.get(jid) or any(reviews[jid].get(k) != "pass" for k in ("identity", "performance_motion", "clean_frame")):
                raise ConfigError("Review actual adjacent pilot motion and identity before expanding production")
    selected = list(dict.fromkeys(job_ids or (pilot_jobs if stage == "pilot" else [j["id"] for j in jobs])))
    if stage == "pilot" and not set(selected) <= set(pilot_jobs):
        raise ConfigError("Pilot stage only runs the selected adjacent sample shots")
    execution_guard(root, bundle, selected)
    from ..runtime.jobs import generate
    return generate(root, config, store_root=store_root, job_ids=selected, poll_timeout=poll_timeout, retry=retry, reason=reason)


def execution_guard(root, bundle, selected):
    """Also called by jobs run, so direct runtime entry preserves sample/first-frame checks."""
    if "animation" not in bundle:
        return
    jobs = bundle["generation-plan"]["jobs"]
    by_id = {j["id"]: j for j in jobs}
    selected = set(selected)
    def include(jid):
        for dep in by_id[jid].get("depends_on", []):
            if dep not in selected:
                selected.add(dep)
                include(dep)
    for jid in list(selected):
        if jid not in by_id:
            raise ConfigError("Unknown animation job")
        include(jid)
    pilot = bundle["animation"]["adaptation"]["pilot_shot_ids"]
    pilot_jobs = {j["id"] for j in jobs if any(s in pilot for s in j["shot_ids"])}
    if selected - pilot_jobs:
        from ..review.receipts import summary
        reviews = summary(root, bundle)["assets"]
        for jid in pilot_jobs:
            if not reviews.get(jid) or any(v not in {"pass", "not_applicable"} for v in reviews[jid].values()):
                raise ConfigError("Review adjacent pilot videos before generating later animation shots")
    for job in jobs:
        if job["id"] not in selected:
            continue
        for sid in job["shot_ids"]:
            receipt = load_json(root / "animation-frames" / (sid + ".json"))
            spec = keyframe_spec(root, bundle, sid)
            if receipt.get("input_hash") != spec["input_hash"]:
                raise ConfigError(sid + ": opening image no longer matches current shot; inspect a new opening image")
            refs = [r for r in job.get("references", []) if r["role"] == "opening-frame"]
            if len(refs) != 1 or refs[0]["sha256"] != receipt["sha256"] or digest(within(root, refs[0]["path"])) != receipt["sha256"]:
                raise ConfigError(sid + ": selected opening image differs from inspected bytes")


def import_voice(root, sid, line_index, source, *, voice_id, reviewer, notes):
    bundle = checked(root)
    shot = next((s for s in bundle["director"]["shots"] if s["id"] == sid), None)
    if shot is None or shot.get("audio", {}).get("mode") != "independent-voice":
        raise ConfigError("Voice import needs a shot using independent-voice")
    lines = shot["audio"].get("lines", [])
    if not 0 <= line_index < len(lines) or not all(str(v).strip() for v in (voice_id, reviewer, notes)):
        raise ConfigError("Voice import requires a valid line, stable voice ID and listening notes/reviewer")
    line = lines[line_index]
    import json
    import subprocess
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ConfigError("FFprobe is required to measure the voice track")
    probe = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)], capture_output=True)
    if probe.returncode:
        raise ConfigError("Voice file could not be decoded")
    measured = json.loads(probe.stdout)
    media = {"duration": float(measured.get("format", {}).get("duration", 0)),
        "has_audio": any(s.get("codec_type") == "audio" for s in measured.get("streams", []))}
    window = line["end"] - line["start"]
    if not media.get("has_audio") or not 0 < media["duration"] <= window + .05:
        raise ConfigError("Imported voice must contain audio and fit the authored line window; revise timing explicitly")
    sha = digest(source)
    target = root / "audio" / (f"{sid}-{line_index}-{sha[:20]}" + source.suffix.lower())
    with state_lock(root):
        voices_path = root / "animation-voices.json"
        voices = load_json(voices_path) if voices_path.exists() else {"characters": {}, "lines": {}}
        speaker = line["speaker"]
        established = voices["characters"].get(speaker)
        if established and established != voice_id:
            raise ConfigError("Character voice ID differs from established voice; explicitly revise animation-voices.json for a new voice version")
        voices["characters"][speaker] = voice_id
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() != source.resolve():
            shutil.copy2(source, target)
        track = next(t for t in bundle["timeline"]["audio_tracks"] if t["id"] == f"voice-{sid}-{line_index}")
        track.update(path=target.relative_to(root).as_posix(), source_out=media["duration"])
        voices["lines"][f"{sid}:{line_index}"] = {"speaker": speaker, "text": line["text"], "voice_id": voice_id,
            "sha256": sha, "path": track["path"], "reviewer_id": reviewer, "notes": notes, "method": "human-listening",
            "lip_sync": "unverified-nonhuman-face"}
        atomic_json(voices_path, voices)
        atomic_json(root / bundle["project"]["files"]["timeline"], bundle["timeline"])
    return {"ok": True, "track": track, "video_regeneration": False, "lip_sync": "unverified", "paid_creates": 0}


def audit_contract(root, bundle, output_name="preview.mp4"):
    from ..review.receipts import contracts
    final = contracts(root, bundle, output_name=output_name).get("final")
    if final is None:
        raise ConfigError("Animation story review requires an actual final video")
    return {"final_sha256": final["sha256"], "contract_hash": final["contract_hash"],
        "animation_hash": content_hash(bundle["animation"]), "duration": final["duration"], "output_name": output_name}


def review(root, receipt=None, *, output_name="preview.mp4"):
    bundle = checked(root)
    contract = audit_contract(root, bundle, output_name)
    points = [p["id"] for p in bundle["animation"]["outline"]["core_points"]]
    if receipt is None:
        return {"ok": True, "template": {**contract, "reviewer_id": "", "method": "human-video",
            "interval": [0, contract["duration"]], "points": {pid: {"status": "unverified", "observation": ""} for pid in points},
            "theme_consistency": {"status": "unverified", "observation": ""}}, "paid_creates": 0}
    _validate_review(receipt, contract, points)
    checks = [*receipt["points"].values(), receipt["theme_consistency"]]
    receipt_hash = content_hash(receipt)
    atomic_json(root / "animation-reviews" / (receipt_hash + ".json"), receipt)
    return {"ok": True, "story_review": "fail" if any(c["status"] == "fail" for c in checks) else "pass",
        "standard_video_reviews_still_required": True, "paid_creates": 0}


def _validate_review(receipt, contract, points):
    if any(receipt.get(k) != v for k, v in contract.items()):
        raise ConfigError("Animation review bytes, plan or theme changed")
    interval = receipt.get("interval", [])
    if (not isinstance(receipt.get("reviewer_id"), str) or not receipt["reviewer_id"].strip()
            or receipt.get("method") not in {"human-video", "model-audio-video"}
            or interval != [0, contract["duration"]] or not isinstance(receipt.get("points"), dict)
            or set(receipt["points"]) != set(points)):
        raise ConfigError("Animation review must cover all story points and full final video through actual playback")
    checks = [*receipt["points"].values(), receipt.get("theme_consistency", {})]
    if any(not isinstance(c, dict) or c.get("status") not in {"pass", "fail"}
            or not isinstance(c.get("observation"), str) or not c["observation"].strip() for c in checks):
        raise ConfigError("Record observed story/theme results, including real defects")


def review_status(root, bundle, *, output_name="preview.mp4"):
    if "animation" not in bundle:
        return "not_applicable"
    try:
        contract = audit_contract(root, bundle, output_name)
    except ConfigError:
        return "unverified"
    statuses = []
    points = [p["id"] for p in bundle["animation"]["outline"]["core_points"]]
    for path in (root / "animation-reviews").glob("*.json"):
        receipt = load_json(path)
        try:
            _validate_review(receipt, contract, points)
            checks = [*receipt.get("points", {}).values(), receipt.get("theme_consistency", {})]
            statuses.append("fail" if any(c.get("status") == "fail" for c in checks) else "pass")
        except ConfigError:
            continue
    return "fail" if "fail" in statuses else "pass" if "pass" in statuses else "unverified"


def status(root):
    bundle = checked(root)
    state = read_state(root)
    from ..runtime.jobs import current_inputs
    from ..runtime.budget import summary as budget_summary
    from ..runtime.candidates import selected
    rows = []
    for job in bundle["generation-plan"]["jobs"]:
        record = selected(state["jobs"].get(job["id"], {}))
        current = current_inputs(root, bundle, job, record)
        artifact = record.get("artifact", {})
        artifact_path = within(root, artifact.get("path", "missing"), exists=False)
        reusable = (record.get("status") == "completed" and record.get("input_hash") == current
            and artifact_path.is_file() and digest(artifact_path) == artifact.get("sha256"))
        rows.append({"id": job["id"], "status": record.get("status", "not_started"), "input_hash": current,
            "reuse": reusable,
            "held_unknown": record.get("status") == "submission_unknown",
            "reason": record.get("retry_reason", ""), "planned_seconds": job["seconds"],
            "actual_seconds": artifact.get("media", {}).get("duration")})
    from ..review.receipts import summary
    report = summary(root, bundle)
    clip_jobs = {c["id"]: c["job_id"] for c in bundle["timeline"]["clips"]}
    retained = 0
    for segment in bundle["timeline"]["segments"]:
        reviewed = report["assets"].get(clip_jobs[segment["clip_id"]], {})
        if reviewed and all(v in {"pass", "not_applicable"} for v in reviewed.values()):
            retained += (segment["source_out"] - segment["source_in"]) / segment.get("rate", 1)
    return {"ok": True, "jobs": rows, "budget": budget_summary(state), "review": report,
        "planned_seconds": sum(j["seconds"] for j in bundle["generation-plan"]["jobs"]),
        "completed_seconds": sum(j["actual_seconds"] or 0 for j in rows if j["status"] == "completed"),
        "completed_duration_unknown": sum(j["actual_seconds"] is None for j in rows if j["status"] == "completed"),
        "reviewed_usable_seconds": retained,
        "retry_reasons": [{"job_id": jid, "reason": item["retry_reason"]} for jid,record in state["jobs"].items()
            for item in [*record.get("history", []), record] if item.get("retry_reason")], "paid_creates": 0}
