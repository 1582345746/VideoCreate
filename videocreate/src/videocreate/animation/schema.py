"""Versioned, bounded animation authoring contract, independent of provider APIs."""
from ..config.schema import STR, STRING_LIST, _walk, enum, obj
from ..planning.schema import plan_schema


def array(item, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum}


def theme_schema():
    return obj({"id": STR, "version": STR, "title": STR, "style": STR,
        "characters": array(obj({"id": STR, "name": STR, "species": STR, "description": STR,
            "invariants": STRING_LIST, "personality": STR,
            "variants": array(obj({"id": STR, "description": STR}, ("id", "description")), 1)},
            ("id", "name", "species", "description", "invariants", "personality", "variants")), 1),
        "world_suggestions": STRING_LIST, "performance_rules": STRING_LIST,
        "interactions": array(obj({"id": STR, "description": STR,
            "contact": {"type": "boolean"}, "status": enum("description-only")},
            ("id", "description", "contact", "status")))},
        ("id", "version", "title", "style", "characters", "world_suggestions", "performance_rules", "interactions"))


def animation_schema(v3=None):
    number = {"type": "number", "minimum": 0}
    v3 = v3 or plan_schema()["properties"]
    point = obj({"id": STR, "description": STR, "origin": enum("source", "original", "user"),
        "observation_ids": STRING_LIST}, ("id", "description", "origin", "observation_ids"))
    return obj({"schema_version": {"const": 1}, "product": {"const": "VideoCreate-animation"},
        "title": STR, "theme": theme_schema(),
        "sources": array(obj({"id": STR, "path": STR, "sha256": STR,
            "purpose": enum("story", "character", "art"), "duration": {"type": "number", "exclusiveMinimum": 0},
            "report": STR, "report_sha256": STR},
            ("id", "path", "sha256", "purpose", "duration", "report", "report_sha256"))),
        "study": obj({"analyst": STR, "observations": array(obj({"id": STR, "source_id": STR,
            "start": number, "end": number,
            "kind": enum("visible-state", "action", "overlay", "dialogue", "sound", "interpretation"),
            "method": enum("frames", "ocr", "human-video", "model-audio-video", "asr", "human-listening"),
            "certainty": enum("observed", "inferred"), "notes": STR, "evidence_ids": STRING_LIST},
            ("id", "source_id", "start", "end", "kind", "method", "certainty", "notes", "evidence_ids"))),
            "segments": array(obj({"id": STR, "source_id": STR, "start": number, "end": number, "label": STR},
                ("id", "source_id", "start", "end", "label")))}, ("analyst", "observations", "segments")),
        "outline": obj({key: STR for key in ("premise", "goal", "obstacle", "choice", "result", "payoff")}
            | {"roles": STRING_LIST, "emotion_curve": STRING_LIST, "core_points": array(point, 1)},
            ("premise", "goal", "obstacle", "choice", "result", "payoff", "roles", "emotion_curve", "core_points")),
        "adaptation": obj({"design_origin": {"const": "newly-designed"}, "rationale": STR,
            "casting": {"type": "object", "additionalProperties": STR},
            "variants": array(obj({"character_id": STR, "variant_id": STR}, ("character_id", "variant_id"))),
            "scene_designs": array(obj({key: STR for key in ("scene_id", "description", "layout", "scale", "lighting")},
                ("scene_id", "description", "layout", "scale", "lighting")), 1),
            "point_map": array(obj({"point_id": STR, "beat_ids": STRING_LIST, "shot_ids": STRING_LIST, "explanation": STR},
                ("point_id", "beat_ids", "shot_ids", "explanation")), 1),
            "pilot_shot_ids": {**STRING_LIST, "minItems": 1, "maxItems": 2},
            "brief": v3["brief"], "story": v3["story"], "director": v3["director"]},
            ("design_origin", "rationale", "casting", "variants", "scene_designs", "point_map", "pilot_shot_ids", "brief", "story", "director"))},
        ("schema_version", "product", "title", "theme", "sources", "study"))


def errors(value, schema=None):
    result = []
    _walk(value, schema or animation_schema(), "$animation", result)
    return result
