"""Independent animated shorts share a versioned theme, not prior episode state."""
import copy
from pathlib import Path
import shutil
from .. import series as base
from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash, save_bundle, within
from ..references import digest
from . import themes
from .project import project_bundle, validate_document


def initialize(root, *, title, theme="lulu-lumei", episodes=20):
    result = base.initialize(root, title, episodes, mode="independent")
    bible = load_json(root / "series.json")
    bible["animation_theme"] = themes.load(theme)
    atomic_json(root / "series.json", bible)
    return result


def prepare(root, number, source, *, model=None, binding=None):
    bible = base._bible(root)
    if bible.get("mode") != "independent" or "animation_theme" not in bible:
        raise ConfigError("Use animation series-init for independent animated shorts")
    if not 1 <= number <= len(bible["episodes"]):
        raise ConfigError("Unknown episode number")
    document = load_json(source)
    report = validate_document(document, source.parent, ready=True)
    if not report["ok"]:
        raise ConfigError("; ".join(report["errors"]))
    if content_hash(document["theme"]) != content_hash(bible["animation_theme"]):
        raise ConfigError("Episode theme version differs from series; create a new series version explicitly")
    bundle = project_bundle(document, model=model, binding=binding)
    expected = bible["episodes"][number-1].get("initial_state", bundle["story"]["initial_state"])
    if bundle["story"]["initial_state"] != expected:
        raise ConfigError("Authored story entry contradicts this independent episode's initial state")
    destination = root / "episodes" / f"episode-{number:03}"
    if (destination / "project.json").exists():
        raise ConfigError("Episode already exists; preserve its attempts and repair locally")
    copies, reference_hashes = [], {}
    canonical = {a["id"]: a for a in bible["characters"]}
    for asset in bundle["director"]["assets"]:
        for relative in canonical.get(asset["id"], {}).get("references", []):
            path = within(root, relative)
            sha = digest(path)
            if sha != bible.get("reference_hashes", {}).get(relative):
                raise ConfigError("Shared character reference needs a matching canonical SHA-256")
            target = "assets/canonical/" + sha + path.suffix.lower()
            asset.setdefault("references", []).append(target)
            reference_hashes[target] = sha
            copies.append((path, target))
    for reference in document["sources"]:
        report_path = within(source.parent, reference["report"])
        copies.append((report_path, reference["report"]))
        for frame in load_json(report_path).get("frames", []):
            frame_path = within(report_path.parent, frame["path"])
            if digest(frame_path) != frame["sha256"]:
                raise ConfigError("Source study frame bytes changed")
            copies.append((frame_path, (Path(reference["report"]).parent / frame["path"]).as_posix()))
    save_bundle(destination, bundle)
    for source_path, relative in copies:
        target = within(destination, relative, exists=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    canonical_assets = [a for a in bundle["director"]["assets"] if a["id"] in canonical]
    atomic_json(destination / "series-context.json", {"schema_version": 3, "series_root": str(root.resolve()),
        "number": number, "bible_hash": content_hash(bible), "previous_receipt_hash": None,
        "initial_state": copy.deepcopy(expected), "canonical_assets_hash": content_hash(canonical_assets),
        "animation_theme_hash": content_hash(bible["animation_theme"]), "reference_hashes": reference_hashes})
    return {"ok": True, "project": str(destination), "mode": "independent", "paid_creates": 0}
