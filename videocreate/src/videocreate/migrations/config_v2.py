from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

from ..config.storage import ConfigError, atomic_json, config_root, load_json
from ..config.schema import validate_config, configuration_schema


LEGACY_PRODUCT = "GrokVideoSkill"
LEGACY_SKILL = "grok-video-studio"


def legacy_root() -> Path:
    override = os.environ.get("GVS_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / LEGACY_PRODUCT
    return Path.home() / ".config" / LEGACY_PRODUCT


def convert_config(old: dict[str, Any]) -> dict[str, Any]:
    old = copy.deepcopy(old)
    # Historical public field aliases never escape this migration boundary.
    for target, alternatives in {
        "image_base_url": ("quickai_image_base_url", "quickai_base_url"),
        "sub2api_video_base_url": ("quickai_video_base_url", "quickai_base_url"),
        "newapi_video_base_url": ("quickainew_video_base_url", "quickainew_base_url"),
    }.items():
        if not old.get(target):
            old[target] = next((old.get(name) for name in alternatives if old.get(name)), "")
    old["default_video_provider"] = {"quickai": "sub2api", "quickainew": "newapi"}.get(old.get("default_video_provider"), old.get("default_video_provider", "sub2api"))
    model_default = old.get("default_video_model", old.get("video_model", "grok-imagine-video-1.5"))
    image_model = old.get("image_model", "gpt-image-2.5")
    result: dict[str, Any] = {"schema_version": 3, "product": "VideoCreate", "defaults": {
        "video_model": model_default, "image_model": image_model, "resolution": "720p", "aspect_ratio": "9:16",
        "audio_mode": "native-dialogue", "subtitle_source": "none", "pace_profile": "story-adaptive"},
        "models": {}, "upstreams": {}, "bindings": {}, "routes": {},
        "execution": {"allow_cross_model_fallback": False, "unknown_submission": "hold-and-reconcile",
                      "read_retry_attempts": 3, "max_create_attempts_per_task": 3,
                      "require_binding_snapshot": True, "paid_probe_on_install": False}}
    upstreams = copy.deepcopy(old.get("video_upstreams", {}))
    for uid, url_fields, key_ref, adapter in (
        ("sub2api", ("sub2api_video_base_url", "sub2api_base_url"), "sub2api_video_key", "sub2api-json"),
        ("newapi", ("newapi_video_base_url", "newapi_base_url"), "newapi_video_key", "newapi-multipart"),
    ):
        url = next((old.get(k) for k in url_fields if old.get(k)), "")
        if url:
            upstreams.setdefault(uid, {"base_url": url, "adapter": adapter, "provider_kind": uid})
    adapter_map = {"sub2api": "sub2api-json-v1", "sub2api-json": "sub2api-json-v1", "xingapi-json": "sub2api-json-v1",
                   "openai-video-json": "sub2api-json-v1", "newapi-json": "newapi-json-v1", "newapi": "newapi-multipart-v1",
                   "newapi-multipart": "newapi-multipart-v1", "openai-video-multipart": "newapi-multipart-v1"}
    routes = copy.deepcopy(old.get("video_model_routes", {}))
    for mid in dict.fromkeys([model_default, "grok-imagine-video-1.5", "seedance-2.0-mini-720p"]):
        routes.setdefault(mid, {"upstreams": list(upstreams), "default_upstream": old.get("default_video_provider", "sub2api")})
    for uid, raw in upstreams.items():
        key_ref = {"sub2api": "sub2api_video_key", "newapi": "newapi_video_key"}.get(uid, "video_upstream_keys." + uid)
        result["upstreams"][uid] = {"platform": raw.get("provider_kind", uid), "display_name": raw.get("title", uid),
            "base_url": raw.get("base_url", ""), "auth": {"type": "bearer", "secret_ref": key_ref},
            "max_concurrent_submissions": 1, "request_timeout_seconds": 120}
    for mid, route in routes.items():
        result["models"][mid] = {"kind": "video", "family": "seedance" if "seedance" in mid.lower() else "grok" if "grok" in mid.lower() else "custom"}
        ids: list[str] = []
        for uid in route.get("upstreams", []):
            if uid not in upstreams:
                continue
            raw = upstreams[uid]
            mapping = raw.get("model_map", {})
            if mapping and mid not in mapping:
                continue
            bid = re.sub(r"[^A-Za-z0-9_.-]", "-", mid + "--" + uid)[:128]
            ids.append(bid)
            adapter = adapter_map.get(raw.get("adapter", "sub2api-json"))
            if not adapter:
                raise ConfigError("Cannot migrate an unknown adapter; keep original configuration")
            result["bindings"][bid] = {"enabled": bool(raw.get("enabled", True)), "model": mid, "upstream": uid,
                "remote_model": mapping.get(mid, mid), "adapter": adapter,
                "operations": ["text-to-video", "image-to-video"], "capability_overrides": {}, "adapter_options": {}}
        preferred = next((bid for bid in ids if result["bindings"][bid]["upstream"] == route.get("default_upstream")), ids[0] if ids else None)
        if preferred:
            result["routes"][mid] = {"policy": "fixed", "preferred_binding": preferred, "candidates": ids}
    image_url = old.get("image_base_url", old.get("sub2api_base_url", ""))
    if image_url:
        result["models"][image_model] = {"kind": "image", "family": "gpt-image"}
        result["upstreams"]["image-service"] = {"platform": "image", "base_url": image_url,
            "auth": {"type": "bearer", "secret_ref": "sub2api_image_key"}}
        result["bindings"]["image-primary"] = {"enabled": True, "model": image_model, "upstream": "image-service",
            "remote_model": image_model, "adapter": "openai-images-v1", "operations": ["text-to-image", "image-edit"]}
        result["routes"][image_model] = {"policy": "fixed", "preferred_binding": "image-primary", "candidates": ["image-primary"]}
    else:
        result["defaults"].pop("image_model", None)
    errors = validate_config(result)
    if errors:
        raise ConfigError("Legacy configuration needs review before migration: " + "; ".join(errors))
    return result


def migrate_config(source: Path | None = None, destination: Path | None = None, *, apply: bool = False) -> dict[str, Any]:
    source = (source or legacy_root()).expanduser().resolve()
    destination = (destination or config_root()).expanduser().resolve()
    if source == destination:
        raise ConfigError("Source and destination configuration directories must differ")
    old_path = source / "config.json"
    converted = convert_config(load_json(old_path))
    if not (source / "secrets.dpapi").exists():
        for uid, upstream in converted["upstreams"].items():
            ref = upstream["auth"].get("secret_ref", "")
            suffix = uid.upper().replace("-", "_")
            names = {
                "sub2api_image_key": ["VIDEOCREATE_IMAGE_API_KEY", "VIDEOCREATE_SUB2API_IMAGE_KEY", "GVS_IMAGE_API_KEY", "GVS_SUB2API_IMAGE_KEY"],
                "sub2api_video_key": ["VIDEOCREATE_VIDEO_API_KEY", "VIDEOCREATE_SUB2API_VIDEO_KEY", "GVS_VIDEO_API_KEY", "GVS_SUB2API_VIDEO_KEY"],
                "newapi_video_key": ["VIDEOCREATE_NEWAPI_VIDEO_KEY", "GVS_NEWAPI_VIDEO_KEY"],
            }.get(ref, [f"VIDEOCREATE_VIDEO_UPSTREAM_{suffix}_KEY", f"GVS_VIDEO_UPSTREAM_{suffix}_KEY"])
            found = next((name for name in names if os.environ.get(name)), None)
            if found:
                upstream["auth"] = {"type": "bearer", "env": found}
    target = destination / "videocreate.config.json"
    if target.exists():
        raise ConfigError("Destination already has a v3 configuration; refusing to overwrite it")
    public = {"source": str(source), "destination": str(destination), "models": len(converted["models"]),
              "bindings": len(converted["bindings"]), "credentials": "preserved-as-local-references",
              "applied": False, "creates_remote_tasks": False}
    if not apply:
        return public
    support = [item for item in source.iterdir() if item.is_file() and item.suffix in {".json", ".dpapi"}]
    for item in support:
        dest = destination / item.name
        if dest.exists() and dest.read_bytes() != item.read_bytes():
            raise ConfigError("A destination support file conflicts with migration; original files preserved")
    destination.mkdir(parents=True, exist_ok=True)
    # Preserve encrypted bytes and optional-service paths without decrypting or logging them.
    created = []
    try:
        for item in support:
            dest = destination / item.name
            if dest.exists():
                continue
            shutil.copy2(item, dest)
            created.append(dest)
            os.chmod(dest, 0o600)
        schema = destination / "videocreate.config.schema.json"
        if not schema.exists():
            atomic_json(schema, configuration_schema())
            created.append(schema)
        converted["$schema"] = str(schema)
        atomic_json(target, converted)
        created.append(target)
        atomic_json(destination / "migration-v2-receipt.json", {**public, "applied": True,
            "source_config_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
            "target_config_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    except Exception:
        for path in reversed(created):
            if path.parent.resolve() == destination:
                path.unlink(missing_ok=True)
        raise
    return {**public, "applied": True, "config": str(target)}
