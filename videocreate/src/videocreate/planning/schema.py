"""Bounded authoring format; free text stays text and extra fields are errors."""
from ..config.schema import BOOL, POS, STR, STRING_LIST, _walk, enum, obj


def plan_schema():
    number = {"type": "number", "minimum": 0}
    state = {"type": "object"}
    line = obj({"speaker": STR, "text": STR, "on_screen": BOOL, "start": number, "end": number,
                "voice_asset_id": STR}, ("speaker", "text", "on_screen", "start", "end"))
    asset = obj({"id": STR, "kind": enum("character", "prop", "scene", "voice"), "description": STR,
                 "references": {"type": "array", "items": STR}, "identity_origin": STR,
                 "invariants": STRING_LIST}, ("id", "kind", "description"))
    scene = obj({"id": STR, "map": STR, "axis": STR, "positions": state}, ("id", "map", "axis"))
    shot = obj({
        "id": STR, "beat_id": STR, "scene_id": STR, "role": STR, "information_goal": STR, "framing": STR,
        "camera_position": STR, "camera_motion": STR, "screen_direction": STR, "eyeline": STR,
        "asset_ids": STRING_LIST, "actors": STRING_LIST,
        "actions": {"type": "array", "items": obj({"kind": enum("physical", "reaction", "camera", "hold"),
            "description": STR}, ("kind", "description")), "minItems": 1},
        "performance": obj({key: STR for key in ("trigger", "attention", "visible_response", "decision")}),
        "visible_evidence": STRING_LIST, "planned_seconds": {"type": "number", "exclusiveMinimum": 0},
        "entry_state": {"type": ["string", "object"]}, "exit_state": {"type": ["string", "object"]},
        "cut_motivation": STR,
        "action_phases": {"type": "array", "items": obj({"phase": enum("prepare", "anticipation", "action", "contact", "recovery", "settle"),
            "start": number, "end": number, "description": STR}, ("phase", "start", "end", "description"))},
        "claim_ids": STRING_LIST, "visual_purpose": enum("illustration", "evidence", "map", "graphic"),
        "contacts": {"type": "array", "items": obj({"subject": STR, "object": STR, "relation": STR}, ("subject", "object", "relation"))},
        "audio": obj({"mode": enum("native-dialogue", "offscreen", "ambience", "mute", "independent-voice"),
            "ambience": STR, "lines": {"type": "array", "items": line}}, ("mode",)),
        "state_transition": obj({"cause_beat_id": STR, "evidence_shot_ids": STRING_LIST}, ("cause_beat_id", "evidence_shot_ids")),
    }, ("id", "scene_id", "information_goal", "framing", "planned_seconds", "actions", "cut_motivation"))
    job = obj({"id": STR, "shot_ids": {**STRING_LIST, "minItems": 1}, "operation": enum("text-to-video", "image-to-video"),
        "seconds": {"type": "number", "exclusiveMinimum": 0}, "model": STR, "binding_id": STR,
        "references": {"type": "array", "items": obj({"path": STR, "sha256": STR,
            "role": enum("opening-frame", "identity", "prop", "scene")}, ("path", "sha256", "role"))},
        "depends_on": STRING_LIST, "required_quality_checks": STRING_LIST}, ("id", "shot_ids", "operation", "seconds"))
    segment = obj({"id": STR, "shot_id": STR, "clip_id": STR, "source_in": number, "source_out": number,
        "rate": {"type": "number", "exclusiveMinimum": 0}, "source_audio": enum("mute", "retime", "preserve"),
        "cut_reason": STR}, ("id", "shot_id", "clip_id", "source_in", "source_out", "cut_reason"))
    track = obj({"id": STR, "kind": enum("dialogue", "ambience", "music", "effect"), "clip_id": STR, "path": STR,
        "source_in": number, "source_out": number, "timeline_start": number, "gain_db": {"type": "number"}},
        ("id", "kind", "source_in", "source_out", "timeline_start"))
    cue = obj({"text": STR, "segment_id": STR, "source_start": number, "source_end": number, "start": number, "end": number}, ("text",))
    def array(items):
        return {"type": "array", "items": items}
    schema = obj({
        "project": obj({"schema_version": {"const": 3}, "product": {"const": "VideoCreate"}, "title": STR,
            "files": obj({name: STR for name in ("brief", "story", "director", "generation-plan", "timeline", "research")}),
            "status": STR}, ("schema_version", "product", "title")),
        "brief": obj({"intent": enum("narrative", "demonstration", "montage", "single-shot"), "genre": STR, "pace_profile": STR,
            "audience": STR, "aspect_ratio": STR, "resolution": STR, "visual_style": STR,
            "allowed_elements": STRING_LIST, "forbidden_elements": STRING_LIST,
            "workflow_profile": enum("portrait", "action-insert", "scenic", "explainer", "series-episode"),
            "audio_policy": enum("silent", "ambience", "voiceover", "dialogue", "native-experimental"),
            "target_seconds": {"type": "number", "exclusiveMinimum": 0},
            "reference_profiles": array(obj({"path": STR, "sha256": STR}, ("path", "sha256"))),
            "product": obj({key: STR for key in ("function", "enables_choice", "visible_result", "removal_breaks_story")},
                ("function", "enables_choice", "visible_result", "removal_breaks_story"))},
            ("intent", "pace_profile", "aspect_ratio", "resolution")),
        "story": obj({**{key: STR for key in ("logline", "goal", "obstacle", "choice", "consequence", "payoff")}, "initial_state": state,
            "beats": array(obj({"id": STR, "requires": state, "effects": state, "causes": STRING_LIST,
                "audience_learns": STR, "visible_evidence_needed": STRING_LIST},
                ("id", "requires", "effects", "causes", "audience_learns", "visible_evidence_needed")))}, ("beats", "initial_state")),
        "director": obj({"assets": array(asset), "scenes": array(scene), "shots": array(shot)}, ("assets", "scenes", "shots")),
        "generation-plan": obj({"jobs": array(job)}, ("jobs",)),
        "timeline": obj({"fps": STR, "width": POS, "height": POS,
            "clips": array(obj({"id": STR, "job_id": STR, "path": STR}, ("id", "job_id"))),
            "segments": array(segment), "audio_tracks": array(track), "subtitles": array(cue),
            "overlays": array(obj({"id": STR, "text": STR, "path": STR, "start": number, "end": number,
                "position": enum("top", "bottom", "center")}, ("id", "start", "end")))},
            ("fps", "clips", "segments")),
        "research": {"type": "object"},
    }, ("project", "brief", "story", "director", "generation-plan", "timeline"))
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "VideoCreate v3 production plan", **schema}


def schema_errors(bundle):
    errors = []
    _walk(bundle, plan_schema(), "$", errors)
    return errors
