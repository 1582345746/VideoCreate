"""Adapt explicit v3 bindings to the retained v2 execution engine.

Each registry entry represents one model binding, so two models on the same
server can use different wire protocols. No secret is written to a project.
"""
from __future__ import annotations

from typing import Any

from ..catalog.bindings import ADAPTER_ALIASES, capabilities
from .storage import ConfigError, resolve_key


def engine_settings(config: dict[str, Any], *, require_secrets: bool = True, store_root=None) -> dict[str, Any]:
    defaults = config["defaults"]
    registry: dict[str, Any] = {}
    image: dict[str, Any] = {}
    for bid, item in config["bindings"].items():
        upstream = config["upstreams"][item["upstream"]]
        key = resolve_key(upstream["auth"], store_root=store_root)
        if config["models"][item["model"]]["kind"] == "image":
            route = config["routes"].get(item["model"], {})
            if item["enabled"] and bid == route.get("preferred_binding") and item["model"] == defaults.get("image_model"):
                image = {"image_base_url": upstream["base_url"], "sub2api_image_key": key, "image_model": item["remote_model"],
                         "image_binding_id": bid, "image_binding": item}
            continue
        registry[bid] = {
            "id": bid, "title": bid, "base_url": upstream["base_url"], "key": key,
            "enabled": item["enabled"], "adapter": ADAPTER_ALIASES[item["adapter"]],
            "provider_kind": upstream.get("platform", item["adapter"]), "upstream_id": item["upstream"],
            "model_map": {item["model"]: item["remote_model"]}, "models": [item["model"]],
            "capabilities": {"text_to_video": "text-to-video" in item["operations"], "image_to_video": "image-to-video" in item["operations"]},
            "binding_capabilities": capabilities(config, item), "adapter_options": {
                "request_timeout_seconds": upstream.get("request_timeout_seconds", 120), **item.get("adapter_options", {})},
        }
    routes = {mid: {"default_upstream": route["preferred_binding"], "upstreams": list(route["candidates"]),
                    "policy": "fixed" if route["policy"] == "fixed" else "automatic"}
              for mid, route in config["routes"].items() if config["models"][mid]["kind"] == "video"}
    model = defaults["video_model"]
    result = {"version": 4, "config_schema_version": 3, "video_model": model, "default_video_model": model,
              "default_video_provider": routes[model]["default_upstream"], "video_model_routes": routes,
              "video_upstreams": registry, "image_base_url": "", "image_model": defaults.get("image_model", "gpt-image-2"),
              "sub2api_image_key": "", "sub2api_video_key": "", "newapi_video_key": "",
              "sub2api_video_base_url": "", "newapi_video_base_url": "", "secret_provider": "user-config",
              "videocreate_defaults": defaults, "videocreate_budget": config.get("budget", {}),
              "videocreate_execution": config.get("execution", {}), **image}
    # Compatibility aliases are only used to find already-recorded v2 task IDs.
    # Client creation resolves the alias against the pinned model again.
    result["legacy_upstream_aliases"] = {}
    for bid, item in registry.items():
        platform = item["provider_kind"]
        result["legacy_upstream_aliases"].setdefault(platform, []).append(bid)
        if platform in {"sub2api", "newapi"} and item["enabled"]:
            result.setdefault("_legacy_candidates", {}).setdefault(platform, []).append(bid)
            result[platform + "_video_base_url"] = result[platform + "_video_base_url"] or item["base_url"]
            result[platform + "_video_key"] = result[platform + "_video_key"] or item["key"]
    if require_secrets and not (result["sub2api_image_key"] or any(v["enabled"] and v["key"] for v in registry.values())):
        raise ConfigError("No enabled binding has available credentials; edit videocreate.config.json")
    return result
