from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from ..config.storage import ConfigError, atomic_json, load_json

LAYERS = ("brief", "story", "director", "generation-plan", "timeline")
PACE = {
    "comedy": {"max_actions": 2, "seconds_per_action": 1.2},
    "dialogue": {"max_actions": 2, "seconds_per_action": 1.2},
    "suspense": {"max_actions": 2, "seconds_per_action": 1.6},
    "slow-cinema": {"max_actions": 2, "seconds_per_action": 2.0},
    "product-demo": {"max_actions": 3, "seconds_per_action": 1.5},
    "action": {"max_actions": 3, "seconds_per_action": 1.0},
}


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def within(root: Path, relative: str, *, exists: bool = True) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or (exists and not path.is_file()):
        raise ConfigError("Project reference must resolve to a file inside the project")
    return path


def load_project(root: Path) -> dict[str, Any]:
    project = load_json(root / "project.json")
    if project.get("schema_version") != 3 or project.get("product") != "VideoCreate":
        raise ConfigError("Use the legacy project commands for v1/v2 projects; this command requires a v3 plan")
    result = {"project": project}
    for name in LAYERS:
        result[name] = load_json(within(root, project.get("files", {}).get(name, name + ".json")))
    return result


def _index(items: Any, field: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(items, list):
        errors.append(field + ": expected array")
        return {}
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", item["id"]):
            errors.append(field + ": each item needs a string id")
        elif item["id"] in result:
            errors.append(field + ": duplicate id " + item["id"])
        else:
            result[item["id"]] = item
    return result


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def validate_plan(bundle: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Check declared causality and coverage, never claim to have viewed output."""
    errors, warnings = [], []
    from .schema import schema_errors
    errors.extend(schema_errors(bundle))
    if errors:
        return {"ok": False, "structural": "fail", "content": "unverified", "evidence_kind": "declared-plan",
            "errors": errors, "warnings": [], "coverage": [], "paid_creates": 0}
    brief, story, director = (bundle[name] for name in ("brief", "story", "director"))
    generation, timeline = (bundle[name] for name in ("generation-plan", "timeline"))
    intent = brief.get("intent")
    allowed = brief.get("allowed_elements", [])
    if set(allowed) & set(brief.get("forbidden_elements", [])):
        warnings.append("Explicit allowed_elements override matching forbidden_elements in the compiled prompt")
    if re.search(r"no modern (?:objects|technology|products)|禁止现代|不得出现现代", brief.get("visual_style", ""), re.I) and re.search(
            r"汽车|手机|电脑|特斯拉|小鹏|无人机|car|phone|computer|tesla|xpeng|drone", " ".join(allowed), re.I):
        errors.append("brief.visual_style: broad ban conflicts with allowed modern story products; remove the ban and declare specific forbidden_elements")
    if intent not in {"narrative", "demonstration", "montage", "single-shot"}:
        errors.append("brief.intent: choose narrative/demonstration/montage/single-shot")
    profile = brief.get("pace_profile", "comedy")
    if profile not in PACE:
        errors.append("brief.pace_profile: unknown profile")
    pace = PACE.get(profile, PACE["comedy"])
    assets = _index(director.get("assets", []), "director.assets", errors)
    scenes = _index(director.get("scenes", []), "director.scenes", errors)
    for scene_id, scene in scenes.items():
        if not scene.get("map", "").strip() or not scene.get("axis", "").strip():
            errors.append(scene_id + ": scene geography and camera axis must not be empty")
    beats = _index(story.get("beats", []), "story.beats", errors)
    shots = _index(director.get("shots", []), "director.shots", errors)
    jobs = _index(generation.get("jobs", []), "generation-plan.jobs", errors)
    clips = _index(timeline.get("clips", []), "timeline.clips", errors)
    if not shots or not jobs:
        errors.append("At least one shot and one generation job are required")
    if intent == "narrative":
        for key in ("logline", "goal", "obstacle", "choice", "consequence"):
            if not isinstance(story.get(key), str) or not story[key].strip():
                errors.append("story." + key + ": required for narrative")
        if not beats:
            errors.append("Narrative requires a visible event chain, including silent/comedy/product stories")
    state = dict(story.get("initial_state", {}))
    seen, covered, coverage = set(), set(), []
    for bid, beat in beats.items():
        requires, effects = beat.get("requires", {}), beat.get("effects", {})
        if not isinstance(requires, dict) or not isinstance(effects, dict):
            errors.append(bid + ": requires/effects must be objects")
            continue
        if any(state.get(k) != v for k, v in requires.items()):
            errors.append(bid + ": input state contradicts preceding events")
        causes = beat.get("causes", [])
        if not isinstance(causes, list) or any(cause not in seen for cause in causes):
            errors.append(bid + ": causal link must refer to an earlier beat")
        if seen and intent == "narrative" and not causes:
            errors.append(bid + ": event is disconnected from its cause")
        if not effects or all(state.get(k) == v for k, v in effects.items()):
            errors.append(bid + ": beat does not change declared state; use shot coverage instead")
        if not beat.get("audience_learns") or not beat.get("visible_evidence_needed"):
            errors.append(bid + ": declare viewer information and observable evidence")
        state.update(effects)
        seen.add(bid)
    for sid, shot in shots.items():
        bid = shot.get("beat_id")
        if bid not in beats and intent == "narrative":
            errors.append(sid + ": unknown beat_id")
        scene = scenes.get(shot.get("scene_id"))
        if scene is None:
            errors.append(sid + ": scene map is missing")
        if not shot.get("information_goal") or not shot.get("framing") or not shot.get("cut_motivation"):
            errors.append(sid + ": information_goal, framing and cut_motivation are required")
        for aid in shot.get("asset_ids", []):
            if aid not in assets:
                errors.append(sid + ": unknown asset " + str(aid))
        evidence = shot.get("visible_evidence", [])
        if not isinstance(evidence, list):
            errors.append(sid + ": visible_evidence must be an array")
            evidence = []
        covered.update((bid, evidence_id) for evidence_id in evidence)
        if shot.get("actors"):
            if any(aid not in assets or assets[aid]["kind"] != "character" for aid in shot["actors"]):
                errors.append(sid + ": actors must reference registered character assets")
            performance = shot.get("performance", {})
            if not all(performance.get(key) for key in ("trigger", "attention", "visible_response", "decision")):
                errors.append(sid + ": acting needs trigger, attention, visible_response and decision")
            if not shot.get("eyeline") or not shot.get("screen_direction"):
                errors.append(sid + ": acting needs eyeline and screen direction")
        for aid in shot.get("asset_ids", []):
            if assets.get(aid, {}).get("kind") == "character" and not assets[aid].get("references"):
                warnings.append(sid + ": character identity has no registered reference; likeness remains unverified")
        actions = shot.get("actions", [])
        if not isinstance(actions, list) or not actions or any(not isinstance(a, dict) or not a.get("description") for a in actions):
            errors.append(sid + ": explicit visible actions are required")
            actions = []
        if shot.get("role") == "reaction" and not any(a.get("kind") == "reaction" for a in actions):
            errors.append(sid + ": reaction tag has no declared observable reaction")
        for contact in shot.get("contacts", []):
            if not isinstance(contact, dict) or not all(contact.get(k) for k in ("subject", "object", "relation")):
                errors.append(sid + ": invalid contact relationship")
        seconds = shot.get("planned_seconds")
        if not _positive(seconds):
            errors.append(sid + ": invalid planned_seconds")
        elif len(actions) > pace["max_actions"] or len(actions) * pace["seconds_per_action"] > seconds:
            errors.append(sid + ": action load exceeds declared pace; split action/arrival/reaction coverage")
        for line in shot.get("audio", {}).get("lines", []):
            if not 0 <= line["start"] < line["end"]:
                errors.append(sid + ": invalid dialogue interval")
            if line["speaker"] not in assets or (line["on_screen"] and line["speaker"] not in shot.get("asset_ids", [])):
                errors.append(sid + ": dialogue speaker must be registered and visible when on_screen=true")
            units = len(re.sub(r"[\W_]", "", line["text"]))
            if line["end"] > line["start"] and units / (line["end"]-line["start"]) > 8:
                warnings.append(sid + ": declared dialogue may be too fast; validate actual voice timing")
        audio = shot.get("audio", {})
        if audio.get("mode") in {"mute", "ambience"} and audio.get("lines"):
            errors.append(sid + ": mute/ambience cannot request dialogue; select an explicit voice strategy")
        if audio.get("mode") == "independent-voice" and audio.get("lines"):
            if not any(track.get("kind") == "dialogue" for track in timeline.get("audio_tracks", [])):
                errors.append(sid + ": independent voice requires a planned natural-speed dialogue track")
        coverage.append({"shot_id": sid, "beat_id": bid, "evidence": evidence, "action_count": len(actions)})
    for bid, beat in beats.items():
        for evidence in beat.get("visible_evidence_needed", []):
            if (bid, evidence) not in covered:
                errors.append(bid + ": missing visual coverage for " + str(evidence))
    product = brief.get("product")
    if product:
        if not isinstance(product, dict) or not all(product.get(k) for k in ("function", "enables_choice", "visible_result", "removal_breaks_story")):
            errors.append("Product needs function → choice → visible result and a removal counterfactual")
        elif any(product[k] not in beats for k in ("enables_choice", "visible_result")):
            errors.append("Product choice/result must reference actual beats")
    assigned = set()
    for jid, job in jobs.items():
        selected = job.get("shot_ids", [])
        if not selected or any(sid not in shots for sid in selected):
            errors.append(jid + ": job needs known shot_ids")
        assigned.update(selected)
        if not _positive(job.get("seconds")):
            errors.append(jid + ": invalid generation seconds")
        if job.get("operation") not in {"text-to-video", "image-to-video"}:
            errors.append(jid + ": unsupported generation operation")
        refs = job.get("references", [])
        if job.get("operation") == "image-to-video" and not refs:
            errors.append(jid + ": image-to-video needs actual references")
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("role") not in {"opening-frame", "identity", "prop", "scene"} or not ref.get("path"):
                errors.append(jid + ": reference needs a supported role and path")
            elif root:
                try:
                    path = within(root, ref["path"])
                    if ref.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
                        errors.append(jid + ": reference hash is missing or stale")
                except ConfigError:
                    errors.append(jid + ": reference is missing or outside project")
            if ref.get("role") != "opening-frame":
                errors.append(jid + ": current video adapters transmit opening-frame references only; compose a keyframe from identity/prop/scene assets first")
        if len(selected) > 1:
            warnings.append(jid + ": multi-shot generation requires actual cut-point identification and separate coverage review")
        for dep in job.get("depends_on", []):
            if dep not in jobs or dep == jid:
                errors.append(jid + ": invalid dependency")
    if set(shots) - assigned:
        errors.append("Some planned shots have no generation job")
    visiting, visited = set(), set()
    def visit(jid):
        if jid in visiting:
            errors.append("generation-plan: cyclic dependency")
            return
        if jid in visited or jid not in jobs:
            return
        visiting.add(jid)
        for dep in jobs[jid].get("depends_on", []):
            visit(dep)
        visiting.remove(jid)
        visited.add(jid)
    for jid in jobs:
        visit(jid)
    for cid, clip in clips.items():
        if clip.get("job_id") not in jobs:
            errors.append(cid + ": unknown source job")
    from ..timeline.model import validate_timeline
    errors.extend(validate_timeline(timeline))
    clip_to_job = {cid: jobs.get(c.get("job_id"), {}) for cid, c in clips.items()}
    for seg in timeline.get("segments", []):
        sid = seg.get("shot_id")
        if sid not in shots or sid not in clip_to_job.get(seg.get("clip_id"), {}).get("shot_ids", []):
            errors.append(seg["id"] + ": segment shot is not covered by its source job")
        if seg.get("source_out", 0) > clip_to_job.get(seg.get("clip_id"), {}).get("seconds", 0):
            errors.append(seg["id"] + ": source window exceeds planned generated seconds")
        if sid in shots:
            for line in shots[sid].get("audio", {}).get("lines", []):
                if not seg["source_in"] <= line["start"] < line["end"] <= seg["source_out"]:
                    if not any(track.get("kind") == "dialogue" and track.get("clip_id") == seg["clip_id"] and track["source_in"] <= line["start"] < line["end"] <= track["source_out"] for track in timeline.get("audio_tracks", [])):
                        errors.append(seg["id"] + ": edit cuts dialogue; retain the full line or bridge it on an independent audio track")
                if seg.get("rate", 1) != 1 and seg.get("source_audio", "mute") != "mute":
                    errors.append(seg["id"] + ": speaking source cannot be slowed with picture; move natural-speed dialogue to an independent track")
    spatial = {}
    for sid, shot in shots.items():
        scene_id, entry, exit_state = shot["scene_id"], shot.get("entry_state"), shot.get("exit_state")
        if isinstance(entry, dict) and scene_id in spatial:
            changed = {k for k, v in entry.items() if k in spatial[scene_id] and spatial[scene_id][k] != v}
            if changed:
                transition = shot.get("state_transition", {})
                ev = transition.get("evidence_shot_ids", [])
                if transition.get("cause_beat_id") not in beats or not ev or any(s not in shots for s in ev):
                    errors.append(sid + ": spatial state changed without a causal beat and visible transition coverage")
        if isinstance(exit_state, dict):
            spatial[scene_id] = exit_state
    return {"ok": not errors, "structural": "pass" if not errors else "fail", "content": "unverified",
            "evidence_kind": "declared-plan", "errors": errors, "warnings": warnings,
            "coverage": coverage, "final_state": state, "paid_creates": 0}


def compile_job(bundle: dict[str, Any], job: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    """Project only this job's shots; nothing from the future story or cast."""
    shots = {shot["id"]: shot for shot in bundle["director"]["shots"]}
    assets = {asset["id"]: asset for asset in bundle["director"].get("assets", [])}
    scenes = {scene["id"]: scene for scene in bundle["director"].get("scenes", [])}
    sections, retained = [], []
    style = bundle["brief"].get("visual_style", "cinematic natural light")
    sections.append("Visual style: " + style)
    for sid in job["shot_ids"]:
        shot = shots[sid]
        sections.append("Current shot " + sid + ": " + shot["information_goal"])
        scene = scenes[shot["scene_id"]]
        sections.append("Scene geography: " + scene["map"] + "; camera axis: " + scene["axis"])
        positions = {aid: value for aid, value in scene.get("positions", {}).items() if aid in shot.get("asset_ids", [])}
        if positions:
            sections.append("Visible positions: " + json.dumps(positions, ensure_ascii=False, separators=(",", ":")))
        retained.append(sid + ".scene_geography_and_axis")
        for key in ("framing", "camera_position", "camera_motion", "eyeline", "screen_direction", "entry_state", "exit_state"):
            if shot.get(key):
                sections.append(key + ": " + str(shot[key]))
                retained.append(sid + "." + key)
        for aid in shot.get("asset_ids", []):
            asset = assets[aid]
            sections.append("Visible " + aid + ": " + asset["description"])
        for action in shot["actions"]:
            sections.append("Subject action: " + action["description"])
        if shot.get("performance"):
            sections.append("Acting: " + json.dumps(shot["performance"], ensure_ascii=False, separators=(",", ":")))
        if shot.get("contacts"):
            sections.append("Contacts: " + json.dumps(shot["contacts"], ensure_ascii=False, separators=(",", ":")))
        audio = shot.get("audio", {"mode": "ambience"})
        sections.append("Audio strategy: " + str(audio.get("mode")))
        if audio.get("mode") == "independent-voice":
            sections.append("Voice is supplied on an independent soundtrack. Do not generate audible dialogue.")
        else:
            for line in audio.get("lines", []):
                sections.append("Speech: " + json.dumps(line, ensure_ascii=False, separators=(",", ":")))
        if not audio.get("lines") or audio.get("mode") in {"mute", "ambience"}:
            sections.append("No speech; visible mouths stay closed. " + str(audio.get("ambience", "")))
        sections.append("Cut motivation: " + shot["cut_motivation"])
        retained += [sid + ".actions", sid + ".performance", sid + ".contacts", sid + ".audio"]
    allowed = bundle["brief"].get("allowed_elements", [])
    forbidden = [item for item in bundle["brief"].get("forbidden_elements", []) if item not in allowed]
    sections.append("Single full-frame physical scene; plausible body and prop contact. No accidental overlays, captions or watermarks.")
    if allowed:
        sections.append("Explicitly allowed story objects/marks: " + ", ".join(allowed))
    else:
        sections.append("No incidental logos or readable screen text.")
    if forbidden:
        sections.append("Excluded incidental elements (explicit story exceptions above take precedence): " + ", ".join(forbidden))
    prompt = "\n".join(sections)
    if len(prompt.encode()) > max_bytes:
        raise ConfigError("Current job prompt exceeds binding byte limit; split or rewrite it. No essential field was silently dropped")
    return {"compiler": "videocreate-local-v1", "prompt": prompt, "utf8_bytes": len(prompt.encode()),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "retained": retained,
            "omitted_scope": ["future beats", "global ending", "non-visible cast", "unrelated scene state"],
            "dropped_essential_fields": [], "verification": "compiled-not-generated"}


def save_bundle(root: Path, bundle: dict[str, Any]) -> None:
    if (root / "project.json").exists():
        raise ConfigError("Project already exists; edit its layer files in place")
    root.mkdir(parents=True, exist_ok=True)
    for name in LAYERS:
        atomic_json(root / (name + ".json"), bundle[name])
    atomic_json(root / "project.json", bundle["project"])
