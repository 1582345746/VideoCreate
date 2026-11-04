from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..config.storage import ConfigError, resolve_key


ADAPTER_ALIASES = {"sub2api-json-v1": "sub2api-json", "newapi-json-v1": "newapi-json",
                   "newapi-multipart-v1": "newapi-multipart", "openai-images-v1": "openai-images"}
MUSE_VIDEO_MAX_SECONDS = 10


def _is_muse_video(binding: dict[str, Any]) -> bool:
    return any(str(binding.get(key, "")).strip().casefold() == "muse-video"
               for key in ("model", "remote_model"))


@dataclass(frozen=True)
class Binding:
    id: str
    model: str
    remote_model: str
    upstream_id: str
    base_url: str
    adapter: str
    key: str = field(repr=False, compare=False)
    capabilities: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        public = {"binding_id": self.id, "model": self.model, "remote_model": self.remote_model,
                  "upstream_id": self.upstream_id, "base_url": self.base_url.rstrip("/"),
                  "adapter": self.adapter, "adapter_version": 1, "capabilities": self.capabilities,
                  "adapter_options": self.options}
        public["fingerprint"] = hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return public


def capabilities(config: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Known adapter contract, not a claim of successful remote generation."""
    video = config["models"][binding["model"]]["kind"] == "video"
    adapter = binding["adapter"]
    result: dict[str, Any] = {
        "verification_level": "configured", "operations": list(binding["operations"]),
        "max_prompt_bytes": 4096, "max_reference_images": 1,
        "reference_mime_types": ["image/jpeg", "image/png", "image/webp"],
        "audio_control": "model-default" if adapter == "sub2api-json-v1" else "explicit" if video else "not-applicable",
        "native_fps": None, "idempotency": "unknown", "cancel": "unsupported",
    }
    if video:
        result.update(duration={"minimum": 1, "maximum": 15, "step": 1},
                      resolutions=["480p", "720p", "1080p"], aspect_ratios=["16:9", "9:16", "1:1", "4:3", "3:4", "2:3", "3:2"],
                      conditions=[], video_reference="unknown", audio_reference="unknown", last_frame="unknown")
    overrides = binding.get("capability_overrides", {})
    allowed = set(result) - {"verification_level"}
    if set(overrides) - allowed:
        raise ConfigError("capability_overrides: unknown capability field or read-only verification level")
    result.update(copy.deepcopy(overrides))
    if video and _is_muse_video(binding):
        duration = result["duration"]
        if duration["minimum"] > MUSE_VIDEO_MAX_SECONDS:
            raise ConfigError("Muse Video duration minimum cannot exceed its 10-second request limit")
        duration["maximum"] = min(duration["maximum"], MUSE_VIDEO_MAX_SECONDS)
    if binding.get("adapter_options", {}).get("include_generate_audio_field") is False:
        result["audio_control"] = "model-default"
    return result


def configured_binding(config: dict, bid: str, *, key: str = "") -> Binding:
    item = config["bindings"].get(bid)
    if not item:
        raise ConfigError("Unknown binding")
    upstream = config["upstreams"][item["upstream"]]
    return Binding(bid, item["model"], item["remote_model"], item["upstream"], upstream["base_url"],
        item["adapter"], key, capabilities(config, item), {
            "request_timeout_seconds": upstream.get("request_timeout_seconds", 120),
            **item.get("adapter_options", {}), **({"pricing": item["pricing"]} if item.get("pricing") else {})})


def route_bindings(config: dict[str, Any], model: str, *, operation: str,
                   preferred: str | None = None, policy: str | None = None, require_key: bool = True,
                   store_root=None) -> list[Binding]:
    route = config["routes"].get(model)
    if not route:
        raise ConfigError("Selected model has no configured route")
    requested = preferred or route["preferred_binding"]
    if requested not in route["candidates"]:
        raise ConfigError("Selected binding is not a candidate for this model")
    selected_policy = policy or ("fixed" if preferred else route["policy"])
    if selected_policy not in {"fixed", "automatic-same-model"}:
        raise ConfigError("Unknown routing policy")
    ordered = [requested] + [bid for bid in route["candidates"] if bid != requested]
    if selected_policy == "fixed":
        ordered = [requested]
    result: list[Binding] = []
    for bid in ordered:
        item = config["bindings"][bid]
        if not item["enabled"] or operation not in item["operations"]:
            continue
        upstream = config["upstreams"][item["upstream"]]
        key = resolve_key(upstream["auth"], store_root=store_root)
        if require_key and not key:
            continue
        result.append(configured_binding(config, bid, key=key))
    if not result:
        raise ConfigError("No enabled binding supports the selected model/operation with available credentials")
    return result


def validate_request(binding: Binding, request: dict[str, Any]) -> dict[str, Any]:
    caps = binding.capabilities
    errors: list[str] = []
    warnings: list[str] = []
    if request["operation"] not in caps["operations"]:
        errors.append("Operation is unsupported by this binding")
    maximum = caps.get("max_prompt_bytes")
    if not isinstance(maximum, int) or maximum < 1:
        errors.append("Prompt byte limit is unknown or invalid")
    elif len(request.get("prompt", "").encode("utf-8")) > maximum:
        errors.append("Prompt exceeds this binding's byte limit")
    duration = caps.get("duration", {})
    seconds = request.get("seconds")
    if seconds is not None:
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not duration:
            errors.append("Duration constraint is unknown or invalid")
        else:
            maximum = duration["maximum"]
            if _is_muse_video({"model": binding.model, "remote_model": binding.remote_model}):
                maximum = min(maximum, MUSE_VIDEO_MAX_SECONDS)
            if (not duration["minimum"] <= seconds <= maximum
                    or abs((seconds-duration["minimum"])/duration["step"]-round((seconds-duration["minimum"])/duration["step"])) > 1e-6):
                errors.append("Duration is outside this binding's supported range/step")
    for field, plural in (("resolution", "resolutions"), ("aspect_ratio", "aspect_ratios")):
        if field in request and request[field] not in caps.get(plural, []):
            errors.append(f"Unsupported {field} for this binding")
    for condition in caps.get("conditions", []):
        if all(request.get(k) == v for k, v in condition.get("when", {}).items()):
            if "max_seconds" in condition and seconds is not None and seconds > condition["max_seconds"]:
                errors.append("Duration exceeds this resolution/operation condition")
    if "generate_audio" in request and caps.get("audio_control") == "unknown":
        errors.append("Audio control capability is unknown")
    if request.get("generate_audio") and caps.get("audio_control") == "unsupported":
        errors.append("Audio generation is unsupported")
    elif caps.get("audio_control") == "model-default":
        warnings.append("Audio switch is not transmitted: provider/model default controls the output; review actual audio")
    refs = request.get("references", [])
    if len(refs) > caps.get("max_reference_images", 0):
        errors.append("Too many reference images for this binding")
    for field in ("video_reference", "audio_reference", "last_frame", "native_fps"):
        if request.get(field) and caps.get(field) in {None, "unknown", "unsupported"}:
            errors.append(f"{field} has not been verified for this binding")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "verification_level": caps.get("verification_level", "configured"), "binding": binding.snapshot()}
