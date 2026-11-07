"""Dependency-free validation of the published, deliberately bounded schema."""
from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlsplit

from .storage import ConfigError


def obj(properties: dict[str, Any], required: tuple[str, ...] = (), *, extra: Any = False) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": extra}


def enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


STR = {"type": "string"}
BOOL = {"type": "boolean"}
POS = {"type": "integer", "minimum": 1}
STRING_LIST = {"type": "array", "items": STR, "uniqueItems": True}
OPEN_OBJECT = {"type": "object"}
OPERATIONS = ("text-to-video", "image-to-video", "text-to-image", "image-edit", "video-edit", "video-extend")
WORKFLOW_OPERATIONS = ("text-to-video", "image-to-video", "text-to-image", "image-edit")
ADAPTERS = ("sub2api-json-v1", "newapi-json-v1", "newapi-multipart-v1", "openai-images-v1")


def capability_schema() -> dict[str, Any]:
    positive = {"type": "number", "exclusiveMinimum": 0}
    return obj({
        "max_prompt_bytes": POS, "max_reference_images": {"type": "integer", "minimum": 0},
        "max_additional_reference_images": {"type": "integer", "minimum": 0},
        "image_to_video_requires_primary": BOOL,
        "reference_mime_types": STRING_LIST,
        "output_formats": {**STRING_LIST, "minItems": 1},
        "image_sizes": {**STRING_LIST, "minItems": 1},
        "image_quality_values": {**STRING_LIST, "minItems": 1},
        "animated_input": enum("unknown", "supported", "unsupported"),
        "animated_output": enum("unknown", "supported", "unsupported"),
        "max_animation_frames": POS,
        "max_animation_duration_seconds": {"type": "number", "exclusiveMinimum": 0},
        "duration": obj({"minimum": positive, "maximum": positive, "step": positive}, ("minimum", "maximum", "step")),
        "resolutions": STRING_LIST, "aspect_ratios": STRING_LIST,
        "conditions": {"type": "array", "items": obj({
            "when": obj({"resolution": STR, "aspect_ratio": STR, "operation": enum(*OPERATIONS)}, extra=False),
            "max_seconds": positive}, ("when", "max_seconds"))},
        "audio_control": enum("explicit", "model-default", "unsupported", "unknown", "not-applicable"),
        "native_fps": {"type": ["number", "null"], "exclusiveMinimum": 0},
        "video_reference": enum("unknown", "unsupported"), "audio_reference": enum("unknown", "unsupported"),
        "last_frame": enum("unknown", "unsupported"), "idempotency": enum("unknown", "unsupported"),
        "cancel": enum("unsupported", "unknown"),
    })


def configuration_schema() -> dict[str, Any]:
    defaults = obj({
        "video_model": STR, "image_model": STR, "aspect_ratio": STR, "resolution": STR,
        "audio_mode": enum("native-dialogue", "preserve", "mute", "narration", "local-voice", "local-lipsync", "local-narration"),
        "subtitle_source": enum("none", "project", "upstream"), "pace_profile": STR, "workflow": STR,
    }, ("video_model",))
    auth = obj({"type": enum("bearer"), "api_key": STR, "env": STR, "secret_ref": STR}, ("type",))
    model = obj({"kind": enum("video", "image"), "family": STR, "display_name": STR, "prompt_profile": STR}, ("kind", "family"))
    upstream = obj({"display_name": STR, "platform": STR, "base_url": STR, "auth": auth,
                    "max_concurrent_submissions": POS, "request_timeout_seconds": POS}, ("base_url", "auth"))
    binding = obj({
        "enabled": BOOL, "setup_status": STR, "model": STR, "upstream": STR, "remote_model": STR,
        "adapter": enum(*ADAPTERS),
        "operations": {"type": "array", "items": enum(*OPERATIONS), "minItems": 1, "uniqueItems": True},
        "capability_profile": STR, "capability_overrides": capability_schema(),
        "adapter_options": obj({"task_id_fields": {**STRING_LIST, "minItems": 1},
            "include_generate_audio_field": BOOL,
            "primary_image_field": enum("images", "first_frame"),
            "image_request_fields": {"type": "array", "items": enum("n", "size", "quality", "response_format", "output_format"), "uniqueItems": True},
            "image_response_format": enum("b64_json", "url"),
            "confirmed_rejection_http_statuses": {"type": "array", "items": {"type": "integer", "minimum": 400, "maximum": 499}, "uniqueItems": True}}),
        "pricing": obj({"currency": STR, "per_request": {"type": "number", "minimum": 0},
            "per_second": {"type": "number", "minimum": 0}}, ("currency",)),
    }, ("enabled", "model", "upstream", "remote_model", "adapter", "operations"))
    route = obj({"policy": enum("fixed", "automatic-same-model"), "preferred_binding": STR,
                 "candidates": {**STRING_LIST, "minItems": 1}}, ("policy", "preferred_binding", "candidates"))
    model_selector = obj({"policy": enum("fixed", "first-compatible"),
                          "candidates": {**STRING_LIST, "minItems": 1}}, ("policy", "candidates"))
    result = obj({
        "$schema": STR, "schema_version": {"const": 3}, "product": {"const": "VideoCreate"},
        "defaults": defaults,
        "models": {"type": "object", "additionalProperties": model, "minProperties": 1},
        "upstreams": {"type": "object", "additionalProperties": upstream},
        "bindings": {"type": "object", "additionalProperties": binding},
        "routes": {"type": "object", "additionalProperties": route},
        "model_selection": obj({"image": model_selector}, extra=False),
        "browser_services": {"type": "object", "additionalProperties": obj({
            "enabled": BOOL, "display_name": STR, "driver": enum("codex-browser", "playwright-local"),
            "base_url": STR, "allowed_origins": {**STRING_LIST, "minItems": 1},
            "requested_operations": {"type": "array", "items": enum(*WORKFLOW_OPERATIONS), "minItems": 1, "uniqueItems": True},
            "profile_directory": STR, "max_prompt_bytes": POS,
        }, ("enabled", "driver", "base_url", "allowed_origins", "requested_operations"))},
        "workflows": {"type": "object", "additionalProperties": obj({
            "description": STR,
            "stages": {"type": "array", "minItems": 1, "items": obj({
                "id": STR, "executor": enum("api", "browser"), "operation": enum(*WORKFLOW_OPERATIONS),
                "model": STR, "binding": STR, "service": STR, "input_from": STR,
            }, ("id", "executor", "operation"))},
        }, ("stages",))},
        "execution": obj({"max_concurrent_image_tasks": {"type": "integer", "minimum": 1, "maximum": 50},
            "max_concurrent_video_tasks": {"type": "integer", "minimum": 1, "maximum": 50},
            "allow_cross_model_fallback": {"const": False}, "unknown_submission": {"const": "hold-and-reconcile"},
            "read_retry_attempts": POS, "max_create_attempts_per_task": POS, "require_binding_snapshot": {"const": True},
            "paid_probe_on_install": {"const": False}}),
        "budget": obj({"currency": STR, "max_total": {"type": ["number", "null"], "minimum": 0},
            "max_image_requests": POS, "max_video_requests": POS, "default_candidates_per_task": POS,
            "unknown_price_policy": enum("report-unknown-and-apply-request-limit", "block")}),
        "review": obj({"structural_is_content_approval": {"const": False},
            "require_narrative_understanding_for_story": BOOL, "require_temporal_review_for_motion": BOOL,
            "require_audio_review_for_speech": BOOL, "unverified_output_label": {"const": "draft_preview"}}),
    }, ("schema_version", "defaults", "models", "upstreams", "bindings", "routes"))
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "VideoCreate user configuration", **result}


def _matches(value: Any, kind: str) -> bool:
    return {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
            "boolean": isinstance(value, bool), "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
            "null": value is None}.get(kind, False)


def _walk(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    kinds = schema.get("type", [])
    if isinstance(kinds, str):
        kinds = [kinds]
    if kinds and not any(_matches(value, kind) for kind in kinds):
        errors.append(path + ": invalid type")
        return
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        errors.append(path + ": unsupported constant")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(path + ": unsupported selection")
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if not math.isfinite(value) or ("minimum" in schema and value < schema["minimum"]):
            errors.append(path + ": below minimum or non-finite")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(path + ": must be greater than minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(path + ": exceeds maximum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(path + "." + key + ": required")
        if len(value) < schema.get("minProperties", 0):
            errors.append(path + ": empty object is not allowed")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, child in value.items():
            if key in properties:
                _walk(child, properties[key], path + "." + key, errors)
            elif extra is False:
                errors.append(path + "." + key + ": unknown field")
            elif isinstance(extra, dict):
                _walk(child, extra, path + "." + key, errors)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(path + ": too few items")
        if schema.get("uniqueItems") and len({repr(item) for item in value}) != len(value):
            errors.append(path + ": duplicate items")
        if "items" in schema:
            for index, child in enumerate(value):
                _walk(child, schema["items"], f"{path}[{index}]", errors)


def validate_config(config: dict[str, Any], *, ready: bool = False, store_root=None, kind: str | None = None) -> list[str]:
    errors: list[str] = []
    _walk(config, configuration_schema(), "$", errors)
    if errors:
        return errors
    from ..workflows import validate_workflows
    errors.extend(validate_workflows(config))
    models, upstreams, bindings = config["models"], config["upstreams"], config["bindings"]
    for group_name, group in (("models", models), ("upstreams", upstreams), ("bindings", bindings)):
        for key in group:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", key):
                errors.append(f"$.{group_name}: invalid ID")
    for uid, upstream in upstreams.items():
        path = f"$.upstreams.{uid}"
        url = urlsplit(upstream["base_url"])
        try:
            port = url.port
        except ValueError:
            port = -1
        if not url.hostname or url.username or url.password or url.query or url.fragment or port == -1 or (
            url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
        ):
            errors.append(path + ".base_url: require HTTPS without credentials, query or fragment")
        auth = upstream["auth"]
        choices = [key for key in ("api_key", "env", "secret_ref") if key in auth]
        if len(choices) != 1:
            errors.append(path + ".auth: choose exactly one of api_key, env, secret_ref")
        elif choices[0] in {"env", "secret_ref"} and not auth[choices[0]].strip():
            errors.append(path + ".auth: credential reference must not be empty")
    for bid, binding in bindings.items():
        path = f"$.bindings.{bid}"
        if binding["model"] not in models:
            errors.append(path + ".model: unknown model reference")
        if binding["upstream"] not in upstreams:
            errors.append(path + ".upstream: unknown upstream reference")
        if not binding["remote_model"].strip() or (ready and binding["enabled"] and "REPLACE_" in binding["remote_model"]):
            errors.append(path + ".remote_model: exact remote model ID is required")
        binding_kind = models.get(binding["model"], {}).get("kind")
        if any((operation in {"text-to-image", "image-edit"}) != (binding_kind == "image") for operation in binding["operations"]):
            errors.append(path + ".operations: operation does not match model kind")
        if binding["adapter"] == "openai-images-v1" and binding_kind != "image":
            errors.append(path + ".adapter: image adapter requires an image model")
        if binding["adapter"] != "openai-images-v1" and binding_kind == "image":
            errors.append(path + ".adapter: video adapter cannot generate images")
        if set(binding["operations"]) & {"video-edit", "video-extend"}:
            errors.append(path + ".operations: no implemented adapter for video edit/extend yet")
        overrides = binding.get("capability_overrides", {})
        duration = overrides.get("duration", {})
        if duration and duration["minimum"] > duration["maximum"]:
            errors.append(path + ".capability_overrides.duration: minimum exceeds maximum")
        options = binding.get("adapter_options", {})
        if options.get("include_generate_audio_field") is False and overrides.get("audio_control") == "explicit":
            errors.append(path + ": explicit audio control conflicts with omitted audio field")
        if "include_generate_audio_field" in options and binding["adapter"] != "newapi-json-v1":
            errors.append(path + ".adapter_options: audio field option requires newapi-json-v1")
        if any(key in options for key in ("image_request_fields", "image_response_format")) and binding_kind != "image":
            errors.append(path + ".adapter_options: image options require an image model")
    for mid, route in config["routes"].items():
        path = f"$.routes.{mid}"
        if mid not in models:
            errors.append(path + ": unknown model")
        if route["preferred_binding"] not in route["candidates"]:
            errors.append(path + ".preferred_binding: must appear in candidates")
        for bid in route["candidates"]:
            if bid not in bindings or bindings[bid]["model"] != mid:
                errors.append(path + ".candidates: unknown binding or cross-model route")
    image_selector = config.get("model_selection", {}).get("image", {})
    for model_id in image_selector.get("candidates", []):
        if models.get(model_id, {}).get("kind") != "image":
            errors.append("$.model_selection.image.candidates: every candidate must be a configured image model")
    for key in ("video_model", "image_model"):
        mid = config["defaults"].get(key)
        if mid and (mid not in models or models[mid]["kind"] != ("video" if key == "video_model" else "image")):
            errors.append(f"$.defaults.{key}: model missing or wrong kind")
        if mid and mid not in config["routes"]:
            errors.append(f"$.defaults.{key}: model has no route")
    if ready:
        from .storage import resolve_key
        mid = config["defaults"].get("image_model" if kind == "image" else "video_model")
        route = config["routes"].get(mid, {})
        selected = [route.get("preferred_binding")] if route.get("policy") == "fixed" else route.get("candidates", [])
        if not any(bindings.get(bid, {}).get("enabled") for bid in selected):
            errors.append("$.defaults: setup_required; enable a binding on the selected route")
        for bid, binding in bindings.items():
            if not binding["enabled"] or binding["upstream"] not in upstreams:
                continue
            if kind and models[binding["model"]]["kind"] != kind:
                continue
            upstream = upstreams[binding["upstream"]]
            if (urlsplit(upstream["base_url"]).hostname or "").endswith(".example"):
                errors.append(f"$.upstreams.{binding['upstream']}.base_url: placeholder host")
            try:
                if not resolve_key(upstream["auth"], store_root=store_root):
                    errors.append(f"$.upstreams.{binding['upstream']}.auth: credential unavailable")
            except ConfigError as error:
                errors.append(f"$.upstreams.{binding['upstream']}.auth: {error}")
    return errors
