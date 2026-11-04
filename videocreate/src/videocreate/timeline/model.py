from __future__ import annotations

import math
from fractions import Fraction
from typing import Any


def number(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def rational(value: Any) -> Fraction:
    if not isinstance(value, str):
        raise ValueError("fps must be a rational string such as 24000/1001")
    result = Fraction(value)
    if result <= 0 or result > 240:
        raise ValueError("fps must be positive and at most 240")
    return result


def validate_timeline(timeline: dict[str, Any]) -> list[str]:
    errors = []
    try:
        rational(timeline.get("fps"))
    except (ValueError, TypeError, ZeroDivisionError):
        errors.append("timeline.fps: use a positive rational frame rate")
    clips = {c["id"]: c for c in timeline.get("clips", []) if isinstance(c, dict) and isinstance(c.get("id"), str)}
    ids = set()
    cursor = 0.0
    segments = timeline.get("segments")
    if not isinstance(segments, list) or not segments:
        return errors + ["timeline.segments: nonempty array required"]
    for seg in segments:
        if not isinstance(seg, dict) or not isinstance(seg.get("id"), str):
            errors.append("timeline: segment needs an id")
            continue
        sid = seg["id"]
        if sid in ids:
            errors.append(sid + ": duplicate segment id")
        ids.add(sid)
        if seg.get("clip_id") not in clips:
            errors.append(sid + ": unknown clip_id")
        start, end, rate = seg.get("source_in"), seg.get("source_out"), seg.get("rate", 1)
        if not all(number(v) for v in (start, end, rate)) or not 0 <= start < end or not 0.1 <= rate <= 8:
            errors.append(sid + ": invalid half-open source window or rate")
            continue
        if seg.get("source_audio", "mute") not in {"mute", "retime", "preserve"}:
            errors.append(sid + ": source_audio must be mute/retime/preserve")
        if rate != 1 and seg.get("source_audio") == "preserve":
            errors.append(sid + ": retimed video needs independent natural-speed speech on an audio track")
        if not seg.get("cut_reason"):
            errors.append(sid + ": cut_reason required")
        cursor += (end-start)/rate
    track_ids = set()
    for track in timeline.get("audio_tracks", []):
        if not isinstance(track, dict) or not isinstance(track.get("id"), str):
            errors.append("timeline.audio_tracks: each event needs an id")
            continue
        if track["id"] in track_ids:
            errors.append("timeline.audio_tracks: duplicate id")
        track_ids.add(track["id"])
        if track.get("kind") not in {"dialogue", "ambience", "music", "effect"}:
            errors.append(track["id"] + ": unknown audio track kind")
        values = (track.get("source_in"), track.get("source_out"), track.get("timeline_start"))
        if not all(number(v) for v in values) or not 0 <= values[0] < values[1] or values[2] < 0:
            errors.append(track["id"] + ": invalid audio window")
        elif values[2] + values[1] - values[0] > cursor + 0.05:
            errors.append(track["id"] + ": audio extends beyond picture; extend the final picture explicitly")
        if not track.get("clip_id") and not track.get("path"):
            errors.append(track["id"] + ": audio source is required")
        if track.get("clip_id") and track["clip_id"] not in clips:
            errors.append(track["id"] + ": unknown audio clip")
        if not number(track.get("gain_db", 0)) or abs(track.get("gain_db", 0)) > 60:
            errors.append(track["id"] + ": invalid gain_db")
    for cue in timeline.get("subtitles", []):
        if not isinstance(cue, dict) or not isinstance(cue.get("text"), str):
            errors.append("timeline.subtitles: invalid cue")
            continue
        if "segment_id" in cue:
            if cue["segment_id"] not in ids or not number(cue.get("source_start")) or not number(cue.get("source_end")):
                errors.append("timeline.subtitles: source cue needs known segment and numeric range")
            else:
                seg = next(s for s in segments if s["id"] == cue["segment_id"])
                if not seg["source_in"] <= cue["source_start"] < cue["source_end"] <= seg["source_out"]:
                    errors.append("timeline.subtitles: cue is cut by the retained source window")
        elif not all(number(cue.get(k)) for k in ("start", "end")) or not 0 <= cue["start"] < cue["end"] <= cursor + 0.001:
            errors.append("timeline.subtitles: invalid timeline cue")
    overlay_ids = set()
    for item in timeline.get("overlays", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in overlay_ids:
            errors.append("timeline.overlays: unique id required")
            continue
        overlay_ids.add(item["id"])
        if bool(item.get("text")) == bool(item.get("path")):
            errors.append(item["id"] + ": overlay needs exactly one of text or image path")
        if any(not isinstance(item[k], str) for k in ("text", "path") if k in item):
            errors.append(item["id"] + ": text/path must be strings")
        if not all(number(item.get(k)) for k in ("start", "end")) or not 0 <= item["start"] < item["end"] <= cursor+.001:
            errors.append(item["id"] + ": overlay interval outside timeline")
        if item.get("position", "bottom") not in {"top", "center", "bottom"}:
            errors.append(item["id"] + ": invalid overlay position")
    return errors


def mapping(timeline: dict[str, Any]) -> dict[str, Any]:
    errors = validate_timeline(timeline)
    if errors:
        raise ValueError("; ".join(errors))
    cursor, segments = 0.0, []
    for segment in timeline["segments"]:
        duration = (segment["source_out"]-segment["source_in"])/segment.get("rate", 1)
        segments.append({**segment, "timeline_start": cursor, "timeline_end": cursor + duration, "duration": duration})
        cursor += duration
    by_id = {s["id"]: s for s in segments}
    cues = []
    for cue in timeline.get("subtitles", []):
        if "segment_id" in cue:
            seg = by_id[cue["segment_id"]]
            cue = {**cue, "start": source_to_timeline(seg, cue["source_start"]), "end": source_to_timeline(seg, cue["source_end"])}
        cues.append(cue)
    return {"timebase": "seconds; source and timeline intervals are half-open", "fps": timeline["fps"],
            "duration": cursor, "segments": segments, "subtitles": cues, "audio_tracks": timeline.get("audio_tracks", [])}


def source_to_timeline(segment: dict[str, Any], source_time: float) -> float:
    if not segment["source_in"] <= source_time <= segment["source_out"]:
        raise ValueError("Time is outside retained source window")
    return segment["timeline_start"] + (source_time-segment["source_in"])/segment.get("rate", 1)
