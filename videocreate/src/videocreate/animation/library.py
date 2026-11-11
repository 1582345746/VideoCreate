"""Local interaction exemplars backed by current source playback reviews."""
import math
import re
from pathlib import Path
from ..config.storage import ConfigError, atomic_json, load_json
from ..media.gif import extract_frame
from ..planning.project import content_hash, within
from ..references import digest
from ..review import receipts
from ..runtime.state import state_lock
from .pipeline import checked

FILENAME = "animation-library.json"


def read(root):
    path = root / FILENAME
    value = load_json(path) if path.exists() else {"schema_version": 1, "items": {}}
    if value.get("schema_version") != 1 or not isinstance(value.get("items"), dict):
        raise ConfigError("Requires an animation interaction library")
    return value


def current(root, job_id, start, end, *, contact=False, output_name="preview.mp4"):
    bundle = checked(root)
    contract = receipts.contracts(root, bundle, output_name=output_name).get(job_id)
    if not contract or job_id == "final":
        raise ConfigError("Choose an actual completed source video job")
    if (not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end))
            or not any(a <= start < end <= b for a, b in contract["windows"])):
        raise ConfigError("Interaction interval must lie inside a retained, reviewed source window")
    job = next(j for j in bundle["generation-plan"]["jobs"] if j["id"] == job_id)
    shots = [s for s in bundle["director"]["shots"] if s["id"] in job["shot_ids"]]
    contact = contact or any(s.get("contacts") for s in shots)
    required = ["performance_motion", "identity", "clean_frame"]
    if contact or "spatial_continuity" in contract["required_layers"]:
        required.append("spatial_continuity")
    status = receipts.summary(root, bundle, output_name=output_name)["assets"][job_id]
    if any(status.get(layer) != "pass" for layer in required):
        raise ConfigError("Interaction needs current playback passes for " + ", ".join(required))
    return bundle, contract, status, required, bool(contact)


def add(root, library_root, *, item_id, job_id, start, end, description, opening_conditions, contact=False,
        output_name="preview.mp4"):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", item_id)
            or not description.strip() or not opening_conditions.strip()):
        raise ConfigError("Interaction needs a safe ID, observed description and opening conditions")
    root, library_root = root.resolve(), library_root.resolve()
    bundle, contract, status, required, contact = current(root, job_id, start, end, contact=contact, output_name=output_name)
    with state_lock(library_root):
        library = read(library_root)
        if item_id in library["items"]:
            raise ConfigError("Interaction ID already exists; preserve it and choose a new versioned ID")
        opening = extract_frame(library_root, source=within(root, contract["path"]), job_id=item_id, at=start)
        item = {"source_project": str(root), "job_id": job_id, "source_path": contract["path"],
            "source_sha256": contract["sha256"], "contract_hash": contract["contract_hash"],
            "interval": [start, end], "description": description, "opening_conditions": opening_conditions,
            "contact": contact, "required_layers": required, "observed_layers": status, "review_output_name": output_name,
            "theme_id": bundle["animation"]["theme"]["id"],
            "theme_hash": content_hash(bundle["animation"]["theme"]), "opening_frame": opening["artifact"],
            "reuse": "performance-reference-only", "full_story_approval": False}
        item["item_hash"] = content_hash(item)
        library["items"][item_id] = item
        atomic_json(library_root / FILENAME, library)
    return {"ok": True, "item_id": item_id, "item": item, "paid_creates": 0}


def catalog(root):
    items = []
    for item_id, item in read(root)["items"].items():
        status, error = "playback-reviewed", ""
        try:
            if content_hash({k: v for k, v in item.items() if k != "item_hash"}) != item["item_hash"]:
                raise ConfigError("Interaction metadata changed")
            opening = item["opening_frame"]
            if digest(within(root, opening["path"])) != opening["sha256"]:
                raise ConfigError("Interaction opening frame changed")
            bundle, contract, _, required, _ = current(Path(item["source_project"]), item["job_id"],
                *item["interval"], contact=item["contact"], output_name=item["review_output_name"])
            if (contract["sha256"] != item["source_sha256"] or contract["contract_hash"] != item["contract_hash"]
                    or required != item["required_layers"]
                    or content_hash(bundle["animation"]["theme"]) != item["theme_hash"]):
                raise ConfigError("Interaction source, scope or theme changed")
        except (ConfigError, OSError, KeyError, TypeError, ValueError) as exc:
            status, error = "unavailable", str(exc)
        items.append({"id": item_id, **item, "status": status, "error": error})
    return {"ok": True, "items": items, "paid_creates": 0}
