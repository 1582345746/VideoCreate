"""Offline source study, original adaptation, and projection to the v3 plan."""
from __future__ import annotations

import copy
from pathlib import Path
from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import LAYERS, content_hash, load_project, save_bundle, validate_plan, within
from ..references import digest
from . import themes
from .schema import errors

AUTHOR = "animation.authoring.json"


def initialize(root, *, title="未命名动画", theme="lulu-lumei", theme_file=None):
    if (root / AUTHOR).exists() or (root / "project.json").exists():
        raise ConfigError("Animation workspace already exists")
    document = {"schema_version": 1, "product": "VideoCreate-animation", "title": title,
        "theme": themes.load(theme, theme_file), "sources": [],
        "study": {"analyst": "", "observations": [], "segments": []}}
    atomic_json(root / AUTHOR, document)
    return {"ok": True, "authoring": str(root / AUTHOR), "status": "story_authoring_required", "paid_creates": 0}


def read(root):
    document = load_json(root / AUTHOR)
    problems = errors(document)
    if problems:
        raise ConfigError("; ".join(problems))
    themes.validate(document["theme"])
    return document


def _editable(root):
    if (root / "project.json").exists():
        raise ConfigError("Plan already exists; edit its layers for local repairs, or create a new adaptation workspace")


def inspect(root, sources, *, purpose="story", max_frames=16):
    _editable(root)
    document = read(root)
    if purpose not in {"story", "character", "art"}:
        raise ConfigError("Unknown reference purpose")
    from ..references import analyze
    results = []
    for path in sources:
        path = Path(path).resolve()
        sha = digest(path)
        known = next((s for s in document["sources"] if s["sha256"] == sha and s["purpose"] == purpose), None)
        if known:
            results.append({"id": known["id"], "duplicate": True})
            continue
        sid = "source-" + sha[:20] + "-" + purpose
        result = analyze(path, root / "animation-sources" / sid, max_frames=max_frames)
        report_path = Path(result["report"])
        report = load_json(report_path)
        # Retained analyzer publishes media.duration_seconds.
        media = report.get("media", {})
        duration = media.get("duration_seconds", media.get("duration"))
        if duration is None:
            duration = report.get("duration_seconds")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ConfigError("Reference report has no measured duration")
        row = {"id": sid, "path": str(path), "sha256": sha, "purpose": purpose,
            "duration": duration, "report": report_path.relative_to(root).as_posix(), "report_sha256": digest(report_path)}
        document["sources"].append(row)
        atomic_json(root / AUTHOR, document)
        results.append({**row, "contact_sheet": result["contact_sheet"], "semantic_status": "unverified"})
    return {"ok": True, "sources": results, "paid_creates": 0,
        "next": "Observe the media and author study/outline. Frames do not establish dialogue or continuous action."}


def _unique(rows, label):
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)) or any(not s.strip() for s in ids):
        raise ConfigError(label + " requires unique nonempty IDs")
    return {row["id"]: row for row in rows}


def validate_document(document, root=None, *, ready=False):
    problems, warnings = errors(document), []
    if problems:
        return {"ok": False, "errors": problems, "warnings": warnings}
    try:
        themes.validate(document["theme"])
        sources = _unique(document["sources"], "Sources")
        observations = _unique(document["study"]["observations"], "Observations")
        _unique(document["study"]["segments"], "Source segments")
        if observations and not document["study"]["analyst"].strip():
            problems.append("Source study requires an analyst")
        for source in sources.values():
            if root:
                path = within(root, source["report"])
                if digest(path) != source["report_sha256"]:
                    problems.append(source["id"] + ": source analysis report changed")
                report = load_json(path)
                if (report.get("source", {}).get("sha256") != source["sha256"] or
                        report.get("media", {}).get("duration_seconds") != source["duration"]):
                    problems.append(source["id"] + ": measured source provenance differs from registry")
                original = Path(source["path"])
                if original.is_file() and digest(original) != source["sha256"]:
                    problems.append(source["id"] + ": source video bytes changed")
                elif not original.is_file():
                    warnings.append(source["id"] + ": original offline; retained study only")
        for row in [*observations.values(), *document["study"]["segments"]]:
            source = sources.get(row["source_id"])
            if not source or not 0 <= row["start"] < row["end"] <= source["duration"] + .001:
                problems.append(row["id"] + ": invalid source time interval")
        for observation in observations.values():
            method, kind = observation["method"], observation["kind"]
            if not observation["notes"].strip() or not observation["evidence_ids"]:
                problems.append(observation["id"] + ": cite inspected frame IDs or playback/ASR evidence identifiers")
            if method in {"frames", "ocr"} and kind not in {"visible-state", "overlay", "interpretation"}:
                problems.append(observation["id"] + ": static evidence cannot establish motion or sound")
            if kind in {"dialogue", "sound"} and method not in {"model-audio-video", "asr", "human-listening"}:
                problems.append(observation["id"] + ": audible claims need audio evidence; overlays are not heard dialogue")
            if method == "asr" and kind not in {"dialogue", "interpretation"}:
                problems.append(observation["id"] + ": ASR cannot establish visual events or sound quality")
            if kind == "interpretation" and observation["certainty"] != "inferred":
                problems.append(observation["id"] + ": interpretation must remain inferred")
            if root and method == "frames" and observation["source_id"] in sources:
                report = load_json(within(root, sources[observation["source_id"]]["report"]))
                frames = {f["id"] for f in report.get("frames", [])}
                if not set(observation["evidence_ids"]) <= frames:
                    problems.append(observation["id"] + ": frame IDs must exist in measured report")
                else:
                    for frame in report["frames"]:
                        if frame["id"] in observation["evidence_ids"]:
                            frame_path = within(within(root, sources[observation["source_id"]]["report"]).parent, frame["path"])
                            if digest(frame_path) != frame["sha256"] or not observation["start"] <= frame["at_seconds"] <= observation["end"]:
                                problems.append(observation["id"] + ": frame bytes/time do not support observation interval")
        for source in sources.values():
            audio = [o for o in observations.values() if o["source_id"] == source["id"] and o["kind"] in {"dialogue", "sound"}]
            if not audio:
                warnings.append(source["id"] + ": source audio not studied; do not infer its dialogue or timing")
        outline = document.get("outline")
        if ready and not outline:
            problems.append("Author an outline before adapting")
        if outline:
            points = _unique(outline["core_points"], "Story points")
            for point in points.values():
                obs = [observations.get(oid) for oid in point["observation_ids"]]
                if any(o is None for o in obs):
                    problems.append(point["id"] + ": unknown observation")
                if point["origin"] == "source":
                    if not obs or any(o and sources[o["source_id"]]["purpose"] != "story" for o in obs):
                        problems.append(point["id"] + ": source story point needs story-purpose evidence")
                    if any(o and o["certainty"] == "inferred" for o in obs):
                        warnings.append(point["id"] + ": story premise uses an explicit inference; verify before claiming fidelity")
            if not outline["roles"] or any(not outline[k].strip() for k in ("premise", "goal", "obstacle", "choice", "result")):
                problems.append("Outline needs roles and a complete goal/obstacle/choice/result chain")
        adaptation = document.get("adaptation")
        if ready and not adaptation:
            problems.append("Author an original adaptation before planning")
        if adaptation and outline:
            cast = adaptation["casting"]
            characters = {c["id"]: c for c in document["theme"]["characters"]}
            if set(cast) != set(outline["roles"]) or any(cid not in characters for cid in cast.values()):
                problems.append("Casting must map each story role to a character from the selected theme")
            variants = {v["character_id"]: v["variant_id"] for v in adaptation["variants"]}
            if len(variants) != len(adaptation["variants"]) or set(variants) != set(cast.values()):
                problems.append("Choose exactly one wardrobe variant per cast character")
            for cid, variant in variants.items():
                if cid not in characters or variant not in {v["id"] for v in characters[cid]["variants"]}:
                    problems.append("Unknown character wardrobe variant: " + cid)
            shots = _unique(adaptation["director"]["shots"], "Shots")
            if any(not s.get("opening_frame", "").strip() for s in shots.values()):
                problems.append("Animation shots need an explicit opening_frame with current prop state; do not infer a generic happy poster")
            beats = _unique(adaptation["story"]["beats"], "Beats")
            designs = {d["scene_id"]: d for d in adaptation["scene_designs"]}
            if len(designs) != len(adaptation["scene_designs"]) or set(designs) != {s["id"] for s in adaptation["director"]["scenes"]}:
                problems.append("Design each original scene exactly once")
            if any(not d[k].strip() for d in designs.values() for k in ("description", "layout", "scale", "lighting")):
                problems.append("Scene design needs layout, lighting and character/prop scale")
            mapped = set()
            for mapping in adaptation["point_map"]:
                pid = mapping["point_id"]
                if pid in mapped or pid not in points or not mapping["explanation"].strip():
                    problems.append("Each story point needs one explained adaptation mapping")
                mapped.add(pid)
                if not mapping["beat_ids"] or not mapping["shot_ids"] or not set(mapping["beat_ids"]) <= beats.keys() or not set(mapping["shot_ids"]) <= shots.keys():
                    problems.append(pid + ": mapping needs existing beats and shots")
                elif any(shots[s]["beat_id"] not in mapping["beat_ids"] for s in mapping["shot_ids"]):
                    problems.append(pid + ": mapped shot does not cover its mapped beat")
            if mapped != set(points):
                problems.append("Preserve every declared core story point in the new adaptation")
            pair = adaptation["pilot_shot_ids"]
            order = list(shots)
            expected = min(2, len(order))
            if len(pair) != expected or any(s not in shots for s in pair) or (len(pair) == 2 and order.index(pair[1]) != order.index(pair[0]) + 1):
                problems.append("Pilot must select two adjacent shots (one for a single-shot story)")
    except (ConfigError, KeyError, TypeError) as error:
        problems.append(str(error))
    return {"ok": not problems, "errors": problems, "warnings": warnings,
        "semantic_status": "declared-not-verified", "paid_creates": 0}


def author(root, supplied):
    _editable(root)
    document = read(root)
    if set(supplied) - {"study", "outline", "adaptation"}:
        raise ConfigError("Authoring import accepts study, outline and adaptation only; theme/sources are managed separately")
    document.update(copy.deepcopy(supplied))
    report = validate_document(document, root, ready="adaptation" in supplied)
    if not report["ok"]:
        raise ConfigError("; ".join(report["errors"]))
    atomic_json(root / AUTHOR, document)
    return {**report, "authoring": str(root / AUTHOR)}


def project_bundle(document, *, model=None, binding=None):
    report = validate_document(document, ready=True)
    if not report["ok"]:
        raise ConfigError("; ".join(report["errors"]))
    adaptation = document["adaptation"]
    director = copy.deepcopy(adaptation["director"])
    theme = document["theme"]
    characters = {c["id"]: c for c in theme["characters"]}
    variants = {v["character_id"]: v["variant_id"] for v in adaptation["variants"]}
    if any(a["kind"] == "character" for a in director["assets"]):
        raise ConfigError("Theme characters are injected from casting; use a custom theme to add guests")
    for cid in dict.fromkeys(adaptation["casting"].values()):
        c = characters[cid]
        wardrobe = next(v["description"] for v in c["variants"] if v["id"] == variants[cid])
        director["assets"].append({"id": cid, "kind": "character", "description": c["description"] + "；" + wardrobe,
            "references": [], "identity_origin": f"theme:{theme['id']}@{theme['version']}", "invariants": c["invariants"]})
    for scene in director["scenes"]:
        design = next(d for d in adaptation["scene_designs"] if d["scene_id"] == scene["id"])
        scene["map"] = "；".join(design[k] for k in ("description", "layout", "scale", "lighting"))
    brief = copy.deepcopy(adaptation["brief"])
    brief.update(workflow_profile="animation-story", visual_style=theme["style"] + "；" + brief.get("visual_style", ""))
    total = sum(s["planned_seconds"] for s in director["shots"])
    brief["target_seconds"] = total
    width, height = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (1024, 1024)}.get(brief["aspect_ratio"], (720, 1280))
    bundle = {"project": {"schema_version": 3, "product": "VideoCreate", "title": document["title"],
        "files": {**{n: n + ".json" for n in LAYERS}, "animation": "animation.json"}, "status": "draft_plan"},
        "brief": brief, "story": copy.deepcopy(adaptation["story"]), "director": director,
        "generation-plan": {"jobs": []}, "timeline": {"fps": "30/1", "width": width, "height": height,
            "clips": [], "segments": [], "audio_tracks": [], "subtitles": []}, "animation": copy.deepcopy(document)}
    cursor = 0
    for i, shot in enumerate(director["shots"], 1):
        jid, clip, segment = f"job-{i:03}", f"clip-{i:03}", f"seg-{i:03}"
        # required_quality_checks selects historically verified *bindings*.
        # A first experimental sample has no such history; its actual content
        # must still pass the shared reviews before any production expansion.
        job = {"id": jid, "shot_ids": [shot["id"]], "operation": "text-to-video", "seconds": shot["planned_seconds"]}
        if model:
            job["model"] = model
        if binding:
            job["binding_id"] = binding
        bundle["generation-plan"]["jobs"].append(job)
        bundle["timeline"]["clips"].append({"id": clip, "job_id": jid})
        audio = shot.get("audio", {})
        bundle["timeline"]["segments"].append({"id": segment, "shot_id": shot["id"], "clip_id": clip,
            "source_in": 0, "source_out": shot["planned_seconds"], "source_audio": "mute" if audio.get("mode") in {"mute", "independent-voice"} else "preserve",
            "cut_reason": shot["cut_motivation"]})
        for n, line in enumerate(audio.get("lines", [])):
            bundle["timeline"]["subtitles"].append({"text": line["text"], "segment_id": segment,
                "source_start": line["start"], "source_end": line["end"]})
            if audio["mode"] == "independent-voice":
                bundle["timeline"]["audio_tracks"].append({"id": f"voice-{shot['id']}-{n}", "kind": "dialogue",
                    "path": f"audio/pending-{shot['id']}-{n}.wav", "source_in": 0,
                    "source_out": line["end"] - line["start"], "timeline_start": cursor + line["start"]})
        cursor += shot["planned_seconds"]
    result = validate_plan(bundle)
    if not result["ok"]:
        raise ConfigError("; ".join(result["errors"]))
    return bundle


def plan(root, *, model=None, binding=None):
    document = read(root)
    report = validate_document(document, root, ready=True)
    if not report["ok"]:
        raise ConfigError("; ".join(report["errors"]))
    bundle = project_bundle(document, model=model, binding=binding)
    save_bundle(root, bundle)
    return {"ok": True, "project": str(root), "validation": validate_plan(bundle, root),
        "pilot_shot_ids": document["adaptation"]["pilot_shot_ids"], "paid_creates": 0}


def validate_context(bundle, root=None):
    document = bundle.get("animation")
    if document is None:
        return {"ok": False, "errors": ["Animation workflow requires a linked animation context"], "warnings": []}
    report = validate_document(document, root, ready=True)
    if not report["ok"]:
        return report
    # Validate mappings against the current plan, so later local edits cannot silently drop a payoff.
    current = copy.deepcopy(document)
    current["adaptation"]["story"] = bundle["story"]
    current["adaptation"]["director"] = bundle["director"]
    report = validate_document(current, root, ready=True)
    if not report["ok"]:
        return report
    assets = {a["id"]: a for a in bundle["director"]["assets"]}
    if {a["id"] for a in assets.values() if a["kind"] == "character"} != set(document["adaptation"]["casting"].values()):
        report["errors"].append("On-screen character assets must match this adaptation's selected theme cast")
    for scene in bundle["director"]["scenes"]:
        design = next(d for d in document["adaptation"]["scene_designs"] if d["scene_id"] == scene["id"])
        if scene["map"] != "；".join(design[k] for k in ("description", "layout", "scale", "lighting")):
            report["errors"].append(scene["id"] + ": update original scene design and projected layout together")
    for shot in bundle["director"]["shots"]:
        for contact in shot.get("contacts", []):
            if any(contact[k] not in shot.get("asset_ids", []) for k in ("subject", "object")):
                report["errors"].append(shot["id"] + ": contact participants must be visible registered assets")
    variants = {v["character_id"]: v["variant_id"] for v in document["adaptation"]["variants"]}
    for character in document["theme"]["characters"]:
        cid = character["id"]
        if cid not in variants:
            continue
        wardrobe = next(v["description"] for v in character["variants"] if v["id"] == variants[cid])
        asset = assets.get(cid, {})
        if asset.get("description") != character["description"] + "；" + wardrobe or asset.get("invariants") != character["invariants"]:
            report["errors"].append(cid + ": theme identity/wardrobe changed; author a new theme/variant version")
    report["ok"] = not report["errors"]
    return report
