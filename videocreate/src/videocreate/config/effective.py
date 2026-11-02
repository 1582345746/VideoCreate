"""Explain configuration without resolving or printing credential values."""
from __future__ import annotations

from pathlib import Path

from .storage import ConfigError, redact_config


def effective(config: dict, path: Path, *, bundle: dict | None = None,
              job_id: str | None = None, binding_id: str | None = None) -> dict:
    from ..catalog.bindings import capabilities
    values, sources = {}, {}

    def put(name, value, source):
        values[name], sources[name] = value, source

    for name, value in config["defaults"].items():
        put(name, value, "config.defaults." + name)
    job = None
    if bundle is not None:
        for name in ("aspect_ratio", "resolution", "pace_profile"):
            if name in bundle["brief"]:
                put(name, bundle["brief"][name], "project.brief." + name)
        if job_id:
            job = next((j for j in bundle["generation-plan"]["jobs"] if j["id"] == job_id), None)
            if not job:
                raise ConfigError("Unknown project job")
            if job.get("model"):
                put("video_model", job["model"], "project.generation-plan.jobs." + job_id + ".model")
            for name in ("seconds", "operation"):
                put(name, job[name], "project.generation-plan.jobs." + job_id + "." + name)
    mid = values["video_model"]
    route = config["routes"][mid]
    bid = binding_id or (job or {}).get("binding_id") or route["preferred_binding"]
    binding = config["bindings"].get(bid)
    if not binding or binding["model"] != mid or bid not in route["candidates"]:
        raise ConfigError("Effective binding must be a candidate for the selected model")
    put("binding_id", bid, "CLI --binding" if binding_id else
        "project.generation-plan.jobs." + str(job_id) + ".binding_id" if (job or {}).get("binding_id") else
        "config.routes." + mid + ".preferred_binding")
    for name in ("remote_model", "adapter", "enabled", "upstream"):
        put(name, binding[name], "config.bindings." + bid + "." + name)
    upstream = config["upstreams"][binding["upstream"]]
    put("base_url", upstream["base_url"], "config.upstreams." + binding["upstream"] + ".base_url")
    put("route_policy", "fixed" if binding_id or (job or {}).get("binding_id") else route["policy"],
        "explicit binding selection" if binding_id or (job or {}).get("binding_id") else "config.routes." + mid + ".policy")
    auth = upstream["auth"]
    put("credential_source", next(k for k in ("api_key", "env", "secret_ref") if k in auth),
        "config.upstreams." + binding["upstream"] + ".auth")
    return {"ok": True, "config": str(path), "values": redact_config(values), "sources": sources,
            "capabilities": capabilities(config, binding), "network_requests": 0,
            "note": "Existing task snapshots pin URL/model/adapter. This report describes new attempts; no credentials were read."}
