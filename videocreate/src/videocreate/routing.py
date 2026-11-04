"""Route only within explicitly chosen models and independently observed checks."""
from __future__ import annotations

from .catalog.bindings import route_bindings, validate_request
from .catalog.evidence import verified_evidence, verify_quality_task
from .config.storage import ConfigError, load_json


def quality_checks(store_root, binding, operation):
    folder = store_root / "binding-evidence" / binding.snapshot()["fingerprint"]
    passed, failed, receipts = set(), set(), []
    for path in sorted(folder.glob("*.json")):
        try:
            r = load_json(path)
            if r.get("stage") != "quality" or r.get("operation") != operation or r.get("binding_fingerprint") != binding.snapshot()["fingerprint"]:
                continue
            verified_evidence(r["evidence"])
            verify_quality_task(binding.snapshot()["fingerprint"], r)
            if not r.get("attempt_id") or not r.get("task_id") or not r.get("reviewer_id") or not isinstance(r.get("checks"), dict):
                continue
            from .catalog.evidence import quality_method_errors
            if quality_method_errors(r):
                continue
            for key, value in r.get("checks", {}).items():
                if value is False:
                    failed.add(key)
                elif value is True and r.get("result") == "pass":
                    passed.add(key)
            receipts.append(str(path))
        except (ConfigError, OSError, KeyError, TypeError, ValueError):
            continue
    return {"passed": sorted(passed - failed), "failed": sorted(failed), "receipts": receipts}


def require_quality(store_root, binding, job):
    required = set(job.get("required_quality_checks", []))
    if required:
        checks = quality_checks(store_root, binding, job["operation"])
        if required - set(checks["passed"]):
            raise ConfigError("Binding lacks observed quality checks for this operation: " + ", ".join(sorted(required - set(checks["passed"]))))


def recommend(bundle, config, *, store_root):
    rows = []
    for job in bundle["generation-plan"]["jobs"]:
        model = job.get("model", config["defaults"]["video_model"])
        bindings = route_bindings(config, model, operation=job["operation"], preferred=job.get("binding_id"),
                                  require_key=False, store_root=store_root)
        candidates = []
        for binding in bindings:
            checks = quality_checks(store_root, binding, job["operation"])
            missing = sorted(set(job.get("required_quality_checks", [])) - set(checks["passed"]))
            shots = [shot for shot in bundle["director"]["shots"] if shot["id"] in job["shot_ids"]]
            references = job.get("references", [])
            request = validate_request(binding, {"operation": job["operation"], "prompt": "", "seconds": job["seconds"],
                "resolution": bundle["brief"]["resolution"], "aspect_ratio": bundle["brief"]["aspect_ratio"],
                "generate_audio": any(shot.get("audio", {}).get("mode", "ambience") in {"native-dialogue", "offscreen", "ambience"} for shot in shots),
                "primary_reference": object() if any(ref["role"] == "opening-frame" for ref in references) else None,
                "reference_images": [object() for ref in references if ref["role"] != "opening-frame"]})
            candidates.append({"binding": binding.id, "fingerprint": binding.snapshot()["fingerprint"],
                "missing_quality_checks": missing, "request_errors": request["errors"], "quality": checks,
                "eligible": not missing and request["ok"],
                "capability_status": "configured, not proof of output quality"})
        rows.append({"job": job["id"], "model": model, "candidates": candidates,
                     "recommended": next((r["binding"] for r in candidates if r["eligible"]), None)})
    return {"ok": True, "jobs": rows, "cross_model_selection": False, "paid_creates": 0}
