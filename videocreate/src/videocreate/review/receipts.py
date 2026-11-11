from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash, within
from ..runtime.state import read_state, save_state, state_lock
from ..timeline.model import mapping

LAYERS = ("narrative", "performance_motion", "identity", "spatial_continuity", "audio", "clean_frame", "editorial")
TEMPORAL = {"performance_motion", "spatial_continuity", "editorial"}
METHODS = {"human-video", "model-audio-video", "human-listening", "asr-and-human", "codex-vision", "ocr-and-vision"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contracts(root: Path, bundle: dict, *, output_name: str = "preview.mp4") -> dict:
    root = root.resolve()
    if not isinstance(output_name, str) or Path(output_name).name != output_name or not output_name.endswith(".mp4"):
        raise ConfigError("Review output must be a plain MP4 filename")
    state, result = read_state(root), {}
    jobs = {job["id"]: job for job in bundle["generation-plan"]["jobs"]}
    shots = {shot["id"]: shot for shot in bundle["director"]["shots"]}
    assets = {asset["id"]: asset for asset in bundle["director"].get("assets", [])}
    def make(path, duration, selected, scope, windows):
        selected_assets = [assets[aid] for shot in selected for aid in shot.get("asset_ids", []) if aid in assets]
        return {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path), "duration": duration,
            "windows": windows, "contract_hash": content_hash(scope),
            "required_layers": [layer for layer in LAYERS if
                (layer != "narrative" or selected is all_shots and bundle["brief"].get("intent") == "narrative") and
                (layer != "editorial" or selected is all_shots) and
                (layer != "performance_motion" or any(s.get("actions") for s in selected)) and
                (layer != "identity" or bool(selected_assets)) and
                (layer != "spatial_continuity" or len(selected) > 1 or any(s.get("contacts") for s in selected)) and
                (layer != "audio" or any(s.get("audio", {}).get("mode") != "mute" for s in selected)
                 or selected is all_shots and bool(bundle["timeline"].get("audio_tracks")))]}
    all_shots = list(shots.values())
    clip_jobs = {clip["id"]: clip["job_id"] for clip in bundle["timeline"]["clips"]}
    retained = {}
    for segment in bundle["timeline"]["segments"]:
        retained.setdefault(clip_jobs[segment["clip_id"]], []).append([segment["source_in"], segment["source_out"]])
    for jid, record in state["jobs"].items():
        from ..runtime.candidates import selected
        record = selected(record)
        if record.get("status") != "completed" or jid not in jobs or jid not in retained:
            continue
        artifact = record.get("artifact", {})
        path = within(root, artifact["path"])
        if file_hash(path) != artifact.get("sha256"):
            raise ConfigError("Review source changed from downloaded bytes")
        selected = [shots[sid] for sid in jobs[jid]["shot_ids"]]
        duration = artifact.get("media", {}).get("duration", jobs[jid]["seconds"])
        windows = retained[jid]
        result[jid] = make(path, duration, selected, {"shots": selected, "references": jobs[jid].get("references", [])}, windows)
    final_path = root / "deliverables" / output_name
    if final_path.is_file():
        manifest = load_json(final_path.with_suffix(".manifest.json"))
        if manifest.get("sha256") != file_hash(final_path) or manifest.get("timeline_hash") != content_hash(bundle["timeline"]):
            raise ConfigError("Final edit/manifest is stale; rerender before reviewing")
        duration = manifest["media"]["duration"]
        from ..timeline.render import resolve_clips
        current_hashes = {cid: file_hash(path) for cid, path in resolve_clips(root, bundle["timeline"], state).items()}
        if manifest.get("source_hashes") != current_hashes:
            raise ConfigError("Final edit uses a different candidate; rerender before reviewing")
        from ..timeline.render import auxiliary_hashes
        if manifest.get("auxiliary_hashes", {}) != auxiliary_hashes(root, bundle["timeline"]):
            raise ConfigError("Final edit audio/overlay bytes changed; rerender before reviewing")
        result["final"] = make(final_path, duration, all_shots,
            {"story": bundle["story"], "director": bundle["director"], "timeline": bundle["timeline"],
             "research": bundle.get("research", {}), **({"animation": bundle["animation"]} if "animation" in bundle else {})}, [[0.0, duration]])
    return result


def template(root: Path, bundle: dict, *, output_name="preview.mp4") -> dict:
    actual = contracts(root, bundle, output_name=output_name)
    if not actual:
        raise ConfigError("No actual video assets exist to review; plan cards are not generation evidence")
    for asset in actual.values():
        asset["layers"] = {layer: {"status": "unverified", "method": "", "observations": [], "evidence": []} for layer in LAYERS}
    if "final" in actual:
        actual["final"]["blind_understanding"] = {key: "" for key in ("goal", "obstacle", "product_role", "choice", "result", "payoff")}
    return {"schema_version": 3, "reviewer_id": "", "output_name": output_name, "assets": actual}


def validate_receipt(root: Path, bundle: dict, receipt: dict) -> list[str]:
    if receipt.get("schema_version") != 3 or not isinstance(receipt.get("reviewer_id"), str) or not receipt["reviewer_id"].strip():
        return ["Review requires schema_version=3 and reviewer_id"]
    output_name = receipt.get("output_name", "preview.mp4")
    if Path(output_name).name != output_name:
        return ["Review output must be a plain filename"]
    actual = contracts(root, bundle, output_name=output_name)
    errors = []
    if not isinstance(receipt.get("assets"), dict) or not receipt["assets"]:
        return ["Review assets must be a nonempty object"]
    for aid, supplied in receipt["assets"].items():
        expected = actual.get(aid)
        if not expected or not isinstance(supplied, dict):
            errors.append("Unknown review asset")
            continue
        if any(supplied.get(k) != expected[k] for k in ("path", "sha256", "duration", "windows", "contract_hash", "required_layers")):
            errors.append(aid + ": stale asset bytes, scope or retained window")
        if not isinstance(supplied.get("layers"), dict):
            errors.append(aid + ": layers must be an object")
            continue
        for layer, observation in supplied["layers"].items():
            if layer not in LAYERS or not isinstance(observation, dict):
                errors.append(aid + ": unknown/malformed review layer")
                continue
            status = observation.get("status")
            if status not in {"pass", "fail", "unverified", "not_applicable"}:
                errors.append(aid + "/" + layer + ": invalid status")
            if status == "not_applicable" and layer in expected["required_layers"]:
                errors.append(aid + "/" + layer + ": applicable layer cannot be waived")
            if status not in {"pass", "fail"}:
                continue
            method = observation.get("method")
            if method not in METHODS:
                errors.append(aid + "/" + layer + ": actual observation method required")
            if layer in TEMPORAL and method not in {"human-video", "model-audio-video"}:
                errors.append(aid + "/" + layer + ": static frames cannot certify motion, continuity or editing")
            if layer == "audio" and method not in {"human-listening", "asr-and-human", "model-audio-video"}:
                errors.append(aid + "/audio: actual listening review required")
            observations, evidence = observation.get("observations"), observation.get("evidence")
            if not isinstance(observations, list) or not observations or not all(isinstance(v, str) and v.strip() for v in observations):
                errors.append(aid + "/" + layer + ": observed details required")
            if not isinstance(evidence, list) or not evidence:
                errors.append(aid + "/" + layer + ": hash-bound evidence and time interval required")
                continue
            for item in evidence:
                try:
                    path = within(root, item["path"])
                    valid = file_hash(path) == item["sha256"]
                    start, end = item["start"], item["end"]
                    valid = valid and isinstance(start, (int, float)) and isinstance(end, (int, float)) and 0 <= start < end <= expected["duration"] + 0.001
                    kind = item["kind"]
                    valid = valid and kind in {"frames", "video", "audio", "asr"}
                    if layer in TEMPORAL:
                        valid = valid and kind == "video"
                    if layer == "audio":
                        valid = valid and kind in {"audio", "video", "asr"}
                    if not valid:
                        raise ValueError()
                except (ConfigError, KeyError, TypeError, ValueError):
                    errors.append(aid + "/" + layer + ": invalid evidence hash, kind or interval")
            if status == "pass" and layer in TEMPORAL | {"clean_frame", "audio"}:
                # A few static frames or a short excerpt cannot certify an
                # entire performance, spoken sentence or watermark-free clip.
                allowed_kinds = {"video", "audio"} if layer == "audio" else {"video"}
                intervals = sorted((item.get("start", -1), item.get("end", -1)) for item in evidence
                    if isinstance(item, dict) and item.get("kind") in allowed_kinds
                    and isinstance(item.get("start"), (int, float)) and isinstance(item.get("end"), (int, float)))
                for window_start, window_end in expected["windows"]:
                    cursor = window_start
                    for start, end in intervals:
                        if end <= cursor:
                            continue
                        if start > cursor + 0.02:
                            break
                        cursor = max(cursor, end)
                    if cursor < window_end - 0.02:
                        errors.append(aid + "/" + layer + ": full temporal/audio coverage is required; sampled frames remain partial")
                        break
            if aid == "final" and layer == "narrative" and status == "pass":
                answer_keys = ["goal", "obstacle", "choice", "result"]
                if bundle["brief"].get("product"):
                    answer_keys.append("product_role")
                if bundle["brief"].get("genre", "").find("comedy") >= 0:
                    answer_keys.append("payoff")
                answers = supplied.get("blind_understanding", {})
                if not all(isinstance(answers.get(k), str) and answers[k].strip() for k in answer_keys):
                    errors.append("Final narrative pass needs viewer answers from the actual video")
    return errors


def apply(root: Path, bundle: dict, receipt: dict) -> dict:
    errors = validate_receipt(root, bundle, receipt)
    if errors:
        raise ConfigError("; ".join(errors))
    path = root / "reviews" / f"{time.time_ns()}-{uuid.uuid4().hex[:8]}.json"
    atomic_json(path, receipt)
    actual = contracts(root, bundle, output_name=receipt.get("output_name", "preview.mp4"))
    overall = summary(root, bundle, output_name=receipt.get("output_name", "preview.mp4"))
    with state_lock(root):
        state = read_state(root)
        for asset_id, supplied in receipt["assets"].items():
            record = state["jobs"].get(asset_id)
            expected = actual.get(asset_id)
            if not record or not expected or record.get("kind") == "image":
                continue
            layers = overall["assets"].get(asset_id, {})
            statuses = [layers.get(layer, "unverified") for layer in expected["required_layers"]]
            record["content_status"] = "rejected" if "fail" in statuses else (
                "reviewed" if all(status == "pass" for status in statuses) else "review_pending")
            record["review_receipt"] = path.relative_to(root).as_posix()
            record["reviewed_sha256"] = expected["sha256"]
            record["reviewed_contract_hash"] = expected["contract_hash"]
        save_state(root, state)
    return {"ok": True, "receipt": str(path), "summary": overall}


def inbox(root: Path, *, pending_only: bool = False) -> dict:
    state = read_state(root)
    items = []
    video_contracts = None
    for job_id, record in state["jobs"].items():
        from ..runtime.candidates import selected
        candidate = selected(record)
        if candidate.get("status") != "completed" or not candidate.get("artifact"):
            continue
        review_status = record.get("content_status", "unverified")
        artifact = candidate["artifact"]
        path = within(root, artifact["path"], exists=False)
        if not path.is_file() or file_hash(path) != artifact.get("sha256"):
            review_status = "artifact_changed"
        elif review_status in {"reviewed", "rejected"}:
            if record.get("reviewed_sha256") != artifact["sha256"]:
                review_status = "unverified"
            elif record.get("kind") != "image":
                if video_contracts is None:
                    from ..planning.project import load_project
                    video_contracts = contracts(root, load_project(root))
                expected = video_contracts.get(job_id, {})
                if record.get("reviewed_contract_hash") != expected.get("contract_hash"):
                    review_status = "unverified"
        if pending_only and review_status in {"reviewed", "rejected"}:
            continue
        items.append({"job_id": job_id, "kind": record.get("kind", "video"),
            "completed_at": candidate.get("completed_at", candidate.get("created_at", 0)),
            "artifact": artifact, "review_status": review_status})
    items.sort(key=lambda item: (item["completed_at"], item["job_id"]))
    return {"ok": True, "items": items, "count": len(items), "paid_creates": 0}


def review_image(root: Path, *, job_id: str, status: str, reviewer_id: str, observation: str,
                 temporal_observation: bool = False) -> dict:
    if status not in {"pass", "fail"} or not reviewer_id.strip() or not observation.strip():
        raise ConfigError("Image review needs pass/fail, reviewer ID and an observed detail")
    with state_lock(root):
        state = read_state(root)
        record = state["jobs"].get(job_id, {})
        if record.get("kind") != "image" or record.get("status") != "completed":
            raise ConfigError("Only a completed image job can be reviewed")
        artifact = record.get("artifact", {})
        path = within(root, artifact.get("path", ""))
        digest = file_hash(path)
        if digest != artifact.get("sha256"):
            raise ConfigError("Image bytes changed after generation; review the current artifact")
        if path.suffix.lower() == ".gif":
            from ..media.gif import inspect_gif
            if inspect_gif(path.read_bytes())["animated"] and not temporal_observation:
                raise ConfigError("Animated GIF review needs full playback observation and --temporal-observation")
        receipt = {"schema_version": 1, "job_id": job_id, "reviewer_id": reviewer_id,
            "status": status, "observation": observation, "temporal_observation": temporal_observation,
            "artifact": artifact, "reviewed_at": int(time.time())}
        target = root / "reviews" / "images" / f"{time.time_ns()}-{uuid.uuid4().hex[:8]}.json"
        atomic_json(target, receipt)
        previously_failed = record.get("content_status") == "rejected" and record.get("reviewed_sha256") == digest
        record.update(content_status="rejected" if status == "fail" or previously_failed else "reviewed", reviewed_sha256=digest,
            review_receipt=target.relative_to(root).as_posix())
        save_state(root, state)
    return {"ok": True, "job_id": job_id, "status": record["content_status"],
        "receipt": target.relative_to(root).as_posix(), "paid_creates": 0}


def summary(root: Path, bundle: dict, *, output_name="preview.mp4") -> dict:
    actual = contracts(root, bundle, output_name=output_name)
    records = []
    for path in sorted((root / "reviews").glob("*.json")):
        if path.name.endswith(".template.json"):
            continue
        receipt = load_json(path)
        if receipt.get("output_name", "preview.mp4") != output_name:
            continue
        try:
            if not validate_receipt(root, bundle, receipt):
                records.append(receipt)
        except ConfigError:
            continue
    layers = {}
    for aid, asset in actual.items():
        result = {}
        for layer in LAYERS:
            statuses = [record["assets"].get(aid, {}).get("layers", {}).get(layer, {}).get("status", "unverified") for record in records]
            # Any observed defect on these same bytes/scope dominates passes.
            result[layer] = ("fail" if "fail" in statuses else "pass" if "pass" in statuses else
                "not_applicable" if layer not in asset["required_layers"] else "unverified")
        layers[aid] = result
    rejected = any(v == "fail" for asset in layers.values() for v in asset.values())
    accepted = bool(actual) and "final" in actual and all(v in {"pass", "not_applicable"} for asset in layers.values() for v in asset.values())
    animation_status = "not_applicable"
    if "animation" in bundle:
        from ..animation.pipeline import review_status
        animation_status = review_status(root, bundle, output_name=output_name)
        rejected = rejected or animation_status == "fail"
        accepted = accepted and animation_status == "pass"
    return {"status": "rejected" if rejected else "accepted_delivery" if accepted else "review_pending" if actual else "draft_preview",
        "structural_is_content_approval": False, "assets": layers, "valid_receipts": len(records), "animation_story": animation_status}
