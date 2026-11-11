"""Local, versioned preset voices shared by independent shorts; no downloads."""
import copy
from ..cli import legacy_engine
from ..config.schema import STR, _walk, enum, obj
from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash
from ..runtime.state import state_lock

FILENAME = "animation-voice-cast.json"


def schema():
    voice = obj({key: STR for key in ("voice_id", "preset_voice_id", "provider_profile_id",
        "preset_engine", "model_size", "model", "model_revision", "instruct_text")}
        | {"seed": {"type": "integer", "minimum": 0}, "normalize": {"type": "boolean"}})
    profile = obj({"version": STR, "provider": enum("cosyvoice", "voicebox"), "service_url": STR,
        "language": STR, "voice": voice}, ("version", "provider", "service_url", "language", "voice"))
    return obj({"schema_version": {"const": 1}, "characters": {"type": "object", "additionalProperties": profile}},
        ("schema_version", "characters"))


def validate(value, character_ids):
    errors = []
    _walk(value, schema(), "$voice_cast", errors)
    if errors:
        raise ConfigError("; ".join(errors))
    if not value["characters"] or set(value["characters"]) - set(character_ids):
        raise ConfigError("Voice cast needs known theme character IDs")
    legacy_engine()
    from audio_client import _loopback_origin
    from vc_common import SkillError
    from voice_contracts import validate_voice_contract
    result = copy.deepcopy(value)
    for cid, profile in result["characters"].items():
        if not profile["version"].strip() or not profile["language"].strip():
            raise ConfigError("Voice profiles need a version and language")
        try:
            profile["service_url"] = _loopback_origin(profile["service_url"], profile["provider"])
        except SkillError as error:
            raise ConfigError(str(error)) from error
        errors = validate_voice_contract(profile["voice"], prefix=cid, default_provider=profile["provider"],
            require_approved=False)
        # Only preset identities have a stable wire contract in this bridge.
        if profile["provider"] == "cosyvoice" and (
                not profile["voice"].get("voice_id", "").strip()
                or set(profile["voice"]) - {"voice_id", "instruct_text"}):
            errors.append(cid + ": CosyVoice presets need voice_id and optional instruct_text")
        if profile["provider"] == "voicebox" and not profile["voice"].get("preset_voice_id", "").strip():
            errors.append(cid + ": Voicebox needs an explicit preset_voice_id")
        if profile["provider"] == "voicebox" and "voice_id" in profile["voice"]:
            errors.append(cid + ": use preset_voice_id for Voicebox")
        if errors:
            raise ConfigError("; ".join(errors))
    return result


def character_ids(root):
    if (root / "series.json").is_file():
        theme = load_json(root / "series.json").get("animation_theme", {})
    else:
        from .pipeline import checked
        theme = checked(root)["animation"]["theme"]
    return [c["id"] for c in theme.get("characters", [])]


def read(root):
    path = root / FILENAME
    return validate(load_json(path), character_ids(root)) if path.is_file() else None


def identity(profile):
    legacy_engine()
    from voice_contracts import voice_identity_key
    return voice_identity_key(profile["voice"], default_provider=profile["provider"])


def select(root, speaker):
    cast = read(root)
    return cast["characters"].get(speaker) if cast else None


def configure(root, value, *, reason=""):
    value = validate(value, character_ids(root))
    with state_lock(root):
        prior = read(root)
        changed = sorted(cid for cid in set((prior or {}).get("characters", {})) | set(value["characters"])
            if (prior or {}).get("characters", {}).get(cid) != value["characters"].get(cid))
        if prior and changed:
            if not reason.strip():
                raise ConfigError("Changing a voice cast requires an explicit reason; existing audio is retained")
            for cid in set(prior["characters"]) & set(value["characters"]):
                if prior["characters"][cid] != value["characters"][cid] and prior["characters"][cid]["version"] == value["characters"][cid]["version"]:
                    raise ConfigError(cid + ": increment the voice profile version when changing its contract")
            atomic_json(root / "audio/voice-cast-history" / (content_hash(prior) + ".json"),
                {"cast": prior, "replacement_reason": reason})
        atomic_json(root / FILENAME, value)
    return {"ok": True, "changed_characters": changed, "voice_cast_hash": content_hash(value),
        "status": "listening_required", "video_regeneration": False, "paid_creates": 0}


def describe(root, *, check_service=False):
    cast = read(root)
    result = {"ok": True, "cast": cast, "status": "configured" if cast else "not_configured",
        "quality": "requires-listening-and-separate-lip-sync-review", "paid_creates": 0}
    if check_service and cast:
        legacy_engine()
        from tts_providers import create_tts_provider
        result["services"] = []
        seen = set()
        for profile in cast["characters"].values():
            key = (profile["provider"], profile["service_url"])
            if key not in seen:
                seen.add(key)
                provider = create_tts_provider(key[0], {}, service_url=key[1])
                try:
                    health = provider.health()
                except Exception as error:
                    health = {"ok": False, "error": str(error)[:500]}
                result["services"].append({"provider": key[0], "service_url": key[1], "health": health})
    return result
