"""Render a pilot edit without replacing the complete production timeline."""
import copy
from pathlib import Path

from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash
from ..runtime.candidates import selected
from ..runtime.jobs import current_inputs
from ..runtime.state import read_state
from ..timeline.model import mapping, validate_timeline
from ..timeline.render import render as render_timeline
from .pipeline import checked


def _pieces(start, end, windows):
    pieces = []
    for old_start, old_end, new_start in windows:
        left, right = max(start, old_start), min(end, old_end)
        if right <= left:
            continue
        placed = new_start + left - old_start
        if pieces and abs(pieces[-1][1] - left) < 1e-6 and abs(pieces[-1][2] + pieces[-1][1] - pieces[-1][0] - placed) < 1e-6:
            pieces[-1] = (pieces[-1][0], right, pieces[-1][2])
        else:
            pieces.append((left, right, placed))
    return pieces


def _intact(pieces, start, end, label):
    if pieces and (len(pieces) != 1 or abs(pieces[0][0] - start) > 1e-6 or abs(pieces[0][1] - end) > 1e-6):
        raise ConfigError(label + ": pilot trim would cut a spoken line or subtitle; revise the edit explicitly")


def prepare(bundle, edits=None):
    """Project retained intervals and independently timed events into pilot time."""
    edits = {} if edits is None else edits
    if (not isinstance(edits, dict) or set(edits) - {"reason", "segments"}
            or not isinstance(edits.get("segments", {}), dict)):
        raise ConfigError("Pilot edit needs an object with reason and segments keyed by segment ID")
    changes = edits.get("segments", {})
    if changes and (not isinstance(edits.get("reason"), str) or not edits["reason"].strip()):
        raise ConfigError("Pilot trims need an observed editing reason")
    pilot = bundle["animation"]["adaptation"]["pilot_shot_ids"]
    original = bundle["timeline"]
    segments = [copy.deepcopy(s) for s in original["segments"] if s["shot_id"] in pilot]
    if {s["shot_id"] for s in segments} != set(pilot):
        raise ConfigError("Production timeline must contain every selected pilot shot")
    if set(changes) - {s["id"] for s in segments}:
        raise ConfigError("Pilot edit contains an unknown or non-pilot segment")
    for seg in segments:
        change = changes.get(seg["id"], {})
        if not isinstance(change, dict) or set(change) - {"source_in", "source_out", "source_audio", "cut_reason"}:
            raise ConfigError("Pilot edits may trim source windows, audio policy and cut reason only")
        lower, upper = seg["source_in"], seg["source_out"]
        seg.update(change)
        if not all(isinstance(seg.get(k), (int, float)) and not isinstance(seg[k], bool) for k in ("source_in", "source_out")):
            raise ConfigError("Pilot source windows must be numeric")
        if not lower <= seg["source_in"] < seg["source_out"] <= upper:
            raise ConfigError("Pilot trim must stay inside the production retained source window")
    timeline = {**copy.deepcopy(original), "segments": segments, "audio_tracks": [], "subtitles": [], "overlays": []}
    old_map = mapping(original)
    new_map = mapping(timeline)
    old_by_id = {s["id"]: s for s in old_map["segments"]}
    windows = []
    for seg in new_map["segments"]:
        old = old_by_id[seg["id"]]
        windows.append((old["timeline_start"] + (seg["source_in"] - old["source_in"]) / old.get("rate", 1),
            old["timeline_start"] + (seg["source_out"] - old["source_in"]) / old.get("rate", 1), seg["timeline_start"]))
    for track in original.get("audio_tracks", []):
        start = track["timeline_start"]
        end = start + track["source_out"] - track["source_in"]
        pieces = _pieces(start, end, windows)
        if track["kind"] == "dialogue":
            _intact(pieces, start, end, track["id"])
        for i, (left, right, placed) in enumerate(pieces):
            timeline["audio_tracks"].append({**track, "id": track["id"] if len(pieces) == 1 else track["id"] + f"-pilot-{i}",
                "source_in": track["source_in"] + left - start, "source_out": track["source_in"] + right - start,
                "timeline_start": placed})
    for cue in old_map["subtitles"]:
        pieces = _pieces(cue["start"], cue["end"], windows)
        _intact(pieces, cue["start"], cue["end"], "Subtitle")
        for left, right, placed in pieces:
            converted = {k: v for k, v in cue.items() if k not in {"segment_id", "source_start", "source_end"}}
            timeline["subtitles"].append({**converted, "start": placed, "end": placed + right - left})
    for overlay in original.get("overlays", []):
        pieces = _pieces(overlay["start"], overlay["end"], windows)
        for i, (left, right, placed) in enumerate(pieces):
            timeline["overlays"].append({**overlay, "id": overlay["id"] if len(pieces) == 1 else overlay["id"] + f"-pilot-{i}",
                "start": placed, "end": placed + right - left})
    needed = {s["clip_id"] for s in segments} | {t["clip_id"] for t in timeline["audio_tracks"] if t.get("clip_id")}
    timeline["clips"] = [c for c in original["clips"] if c["id"] in needed]
    problems = validate_timeline(timeline)
    if problems:
        raise ConfigError("; ".join(problems))
    return timeline


def render(root, *, edits=None, output_name="animation-pilot.mp4"):
    root = Path(root).resolve()
    bundle = checked(root)
    if Path(output_name).name != output_name or not output_name.endswith(".mp4") or output_name == "preview.mp4":
        raise ConfigError("Pilot output needs a separate plain MP4 filename, such as animation-pilot.mp4")
    target = root / "deliverables" / output_name
    if target.exists():
        manifest_path = target.with_suffix(".manifest.json")
        if not manifest_path.exists() or load_json(manifest_path).get("scope") != "animation-pilot":
            raise ConfigError("Pilot output would overwrite another edit; choose a separate output name")
    timeline = prepare(bundle, edits)
    state = read_state(root)
    jobs = {j["id"]: j for j in bundle["generation-plan"]["jobs"]}
    for clip in timeline["clips"]:
        if not clip.get("job_id"):
            continue
        job = jobs[clip["job_id"]]
        record = selected(state["jobs"].get(job["id"], {}))
        if record.get("status") != "completed" or record.get("input_hash") != current_inputs(root, bundle, job, record):
            raise ConfigError(job["id"] + ": pilot needs a completed candidate matching the current generation inputs")
    derived = copy.deepcopy(bundle)
    derived["timeline"] = timeline
    used_shots = {s["shot_id"] for s in timeline["segments"]}
    derived["director"]["shots"] = [s for s in derived["director"]["shots"] if s["id"] in used_shots]
    result = render_timeline(root, derived, state, output_name=output_name, scope="animation-pilot")
    result.update(source_project_hash=content_hash(bundle), pilot_shot_ids=bundle["animation"]["adaptation"]["pilot_shot_ids"],
        production_target_seconds=bundle["brief"]["target_seconds"], full_story_delivery=False,
        edit_reason=(edits or {}).get("reason", "Selected adjacent pilot shots"))
    atomic_json(target.with_suffix(".manifest.json"), {k: v for k, v in result.items() if k != "ok"})
    atomic_json(target.with_suffix(".timeline.json"), timeline)
    return result
