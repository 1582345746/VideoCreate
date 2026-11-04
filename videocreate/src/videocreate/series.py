"""Version 3 series continuity inherits observed accepted endings, never draft scripts."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config.storage import ConfigError, atomic_json, load_json
from .planning.project import content_hash, load_project, save_bundle, within


def initialize(root: Path, title: str, episodes: int = 20) -> dict:
    if isinstance(episodes, bool) or not isinstance(episodes, int) or not 1 <= episodes <= 100:
        raise ConfigError("Episode count must be 1–100")
    if (root / "series.json").exists():
        raise ConfigError("Series already exists; edit its bible in place")
    atomic_json(root / "series.json", {"schema_version": 3, "product": "VideoCreate", "title": title,
        "characters": [], "reference_hashes": {}, "world_rules": [], "initial_state": {},
        "episodes": [{"number": i, "goal": "", "obstacle": "", "choice": "", "result": "", "hook": ""} for i in range(1, episodes+1)]})
    return {"ok": True, "bible": str(root / "series.json"), "status": "authoring_required", "paid_creates": 0}


def _bible(root):
    bible = load_json(root / "series.json")
    if bible.get("schema_version") != 3 or bible.get("product") != "VideoCreate":
        raise ConfigError("Requires a v3 series bible")
    if not isinstance(bible.get("episodes"), list) or any(not isinstance(e, dict) or e.get("number") != i for i,e in enumerate(bible["episodes"], 1)):
        raise ConfigError("Episode numbers must be consecutive from 1")
    if not isinstance(bible.get("characters"), list) or not isinstance(bible.get("initial_state"), dict):
        raise ConfigError("Series characters must be an array and initial_state an object")
    return bible


def _accepted(root, number):
    path = root / "accepted" / f"episode-{number:03}.json"
    if not path.is_file():
        raise ConfigError("Previous episode has no accepted ending receipt")
    receipt = load_json(path)
    payload = {k:v for k,v in receipt.items() if k != "receipt_hash"}
    if content_hash(payload) != receipt.get("receipt_hash"):
        raise ConfigError("Accepted episode receipt changed")
    episode = root / "episodes" / f"episode-{number:03}"
    bundle = load_project(episode)
    from .review.receipts import contracts, summary
    final = contracts(episode, bundle, output_name=receipt["output_name"]).get("final", {})
    if final.get("sha256") != receipt.get("final_sha256") or final.get("contract_hash") != receipt.get("contract_hash"):
        raise ConfigError("Previously accepted episode changed; continuity needs a new reviewed version")
    if summary(episode, bundle, output_name=receipt["output_name"])["status"] != "accepted_delivery":
        raise ConfigError("Previous episode no longer has accepted content reviews")
    if receipt.get("bible_hash") != content_hash(_bible(root)):
        raise ConfigError("Series bible changed after acceptance; reconcile continuity explicitly")
    return receipt


def prepare(root: Path, number: int, seconds=60) -> dict:
    bible = _bible(root)
    if not 1 <= number <= len(bible["episodes"]):
        raise ConfigError("Unknown episode number")
    previous = _accepted(root, number-1) if number > 1 else None
    from .planning.profiles import create
    bundle = create("series-episode", title=f"{bible['title']} · {number:02}", seconds=seconds)
    arc = bible["episodes"][number-1]
    bundle["story"].update({k:arc.get(k, "") for k in ("goal", "obstacle", "choice")})
    bundle["story"]["consequence"] = arc.get("result", "")
    bundle["story"]["initial_state"] = previous["observed_exit_state"] if previous else bible["initial_state"]
    bundle["director"]["assets"] = bible["characters"]
    destination = root / "episodes" / f"episode-{number:03}"
    # Copy canonical reference bytes into the episode, keeping hash provenance.
    import copy, shutil
    bundle["director"]["assets"] = copy.deepcopy(bundle["director"]["assets"])
    refs, reference_hashes = [], {}
    for character in bundle["director"]["assets"]:
        for i, ref in enumerate(character.get("references", [])):
            if not isinstance(ref, str):
                raise ConfigError("Character references must be project-relative paths")
            source = within(root, ref)
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            if sha != bible.get("reference_hashes", {}).get(ref):
                raise ConfigError("Canonical reference needs its SHA-256 in bible.reference_hashes")
            relative = "assets/canonical/" + sha + source.suffix.lower()
            refs.append((source, relative))
            character["references"][i] = relative
            reference_hashes[relative] = sha
    save_bundle(destination, bundle)
    for source, relative in refs:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    atomic_json(destination / "series-context.json", {"schema_version": 3, "series_root": str(root.resolve()),
        "number": number, "bible_hash": content_hash(bible),
        "previous_receipt_hash": previous["receipt_hash"] if previous else None,
        "initial_state": bundle["story"]["initial_state"], "canonical_assets_hash": content_hash(bundle["director"]["assets"]),
        "reference_hashes": reference_hashes})
    return {"ok": True, "project": str(destination), "status": "author_story_and_coverage", "paid_creates": 0}


def check_episode_context(root: Path, bundle: dict) -> None:
    path = root / "series-context.json"
    if not path.exists():
        if bundle["brief"].get("workflow_profile") == "series-episode":
            raise ConfigError("Series episode needs series prepare context before generation")
        return
    context = load_json(path)
    series_root = Path(context["series_root"])
    bible = _bible(series_root)
    if context.get("bible_hash") != content_hash(bible):
        raise ConfigError("Series bible changed; explicitly reconcile episode context before generation")
    expected = bible["initial_state"]
    if context["number"] > 1:
        previous = _accepted(series_root, context["number"]-1)
        if previous["receipt_hash"] != context["previous_receipt_hash"]:
            raise ConfigError("Previous accepted ending changed")
        expected = previous["observed_exit_state"]
    if context["initial_state"] != expected or bundle["story"].get("initial_state") != expected:
        raise ConfigError("Episode entry state differs from accepted continuity")
    # Extra props/guests are allowed; canonical character requirements stay fixed.
    canonical_ids = {a["id"] for a in bible["characters"]}
    actual = [a for a in bundle["director"]["assets"] if a["id"] in canonical_ids]
    if content_hash(actual) != context["canonical_assets_hash"]:
        raise ConfigError("Canonical identity/voice reference contract changed")
    for relative, sha in context.get("reference_hashes", {}).items():
        if hashlib.sha256(within(root, relative).read_bytes()).hexdigest() != sha:
            raise ConfigError("Episode canonical reference bytes changed")
    for relative, sha in bible.get("reference_hashes", {}).items():
        if hashlib.sha256(within(series_root, relative).read_bytes()).hexdigest() != sha:
            raise ConfigError("Series canonical reference bytes changed")


def accept(root: Path, number: int, observation: dict, output_name="preview.mp4") -> dict:
    destination = root / "accepted" / f"episode-{number:03}.json"
    if destination.exists():
        raise ConfigError("Accepted ending is immutable; create a new series version to revise it")
    episode = root / "episodes" / f"episode-{number:03}"
    bundle = load_project(episode)
    check_episode_context(episode, bundle)
    from .review.receipts import contracts, summary
    if summary(episode, bundle, output_name=output_name)["status"] != "accepted_delivery":
        raise ConfigError("Episode requires accepted source and final content reviews")
    final = contracts(episode, bundle, output_name=output_name)["final"]
    if not isinstance(observation.get("observed_exit_state"), dict) or not observation["observed_exit_state"]:
        raise ConfigError("Record the observed nonempty exit state, not the planned ending")
    if not observation.get("reviewer_id") or not observation.get("observations") or observation.get("method") not in {"human-video", "model-audio-video"}:
        raise ConfigError("Ending requires actual video observation/reviewer")
    interval = observation.get("interval", [])
    if observation.get("final_sha256") != final["sha256"] or not isinstance(interval, list) or len(interval) != 2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in interval) or not 0 <= interval[0] < interval[1] <= final["duration"] + .001 or interval[1] < final["duration"]-.1:
        raise ConfigError("Ending observation must cover the actual final interval and bytes")
    receipt = {"schema_version": 3, "number": number, "bible_hash": content_hash(_bible(root)),
        "output_name": output_name, "final_sha256": final["sha256"], "contract_hash": final["contract_hash"],
        **{k: observation[k] for k in ("observed_exit_state", "reviewer_id", "observations", "method", "interval")}}
    receipt["receipt_hash"] = content_hash(receipt)
    atomic_json(destination, receipt)
    return {"ok": True, "accepted": str(destination), "paid_creates": 0}
