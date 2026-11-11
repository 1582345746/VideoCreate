"""Portable themes contain descriptions, never credentials or user media."""
import re
from pathlib import Path
from ..cli import skill_root
from ..config.storage import ConfigError, load_json
from .schema import errors, theme_schema


def validate(theme):
    problems = errors(theme, theme_schema())
    if problems:
        raise ConfigError("; ".join(problems))
    ids = set()
    for character in theme["characters"]:
        cid = character["id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", cid) or cid in ids:
            raise ConfigError("Theme character IDs must be unique safe IDs")
        ids.add(cid)
        variants = [v["id"] for v in character["variants"]]
        if len(variants) != len(set(variants)) or not character["description"].strip() or not character["invariants"]:
            raise ConfigError("Theme needs identity descriptions, invariants and unique variants")
    return theme


def load(name="lulu-lumei", path=None):
    if path is None:
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ConfigError("Invalid built-in theme name")
        path = skill_root() / "assets/animation/themes" / (name + ".json")
    return validate(load_json(Path(path)))


def catalog():
    return [{"id": value["id"], "version": value["version"], "title": value["title"],
             "characters": [c["id"] for c in value["characters"]], "identity_status": "description-only"}
            for path in sorted((skill_root() / "assets/animation/themes").glob("*.json"))
            for value in [load(path=path)]]
