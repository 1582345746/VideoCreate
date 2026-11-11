"""Optional v3 bridge to retained local voice providers; no model downloads."""
from pathlib import Path
from ..cli import legacy_engine
from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash, within
from ..references import digest
from .pipeline import checked


def profiles_hash(root, bundle):
    from .voice_cast import read
    cast = read(root)
    if not cast:
        return None
    speakers = {line["speaker"] for shot in bundle["director"]["shots"]
        if shot.get("audio", {}).get("mode") == "independent-voice" for line in shot["audio"].get("lines", [])}
    used = {cid: profile for cid, profile in cast["characters"].items() if cid in speakers}
    return content_hash(used) if used else None


def validate_tracks(root, bundle):
    independent = [s for s in bundle["director"]["shots"] if s.get("audio", {}).get("mode") == "independent-voice" and s["audio"].get("lines")]
    if not independent:
        return
    path = root / "animation-voices.json"
    if not path.exists():
        raise ConfigError("Import and listen to independent voice tracks before rendering")
    voices = load_json(path)
    tracks = {t["id"]: t for t in bundle["timeline"].get("audio_tracks", [])}
    for shot in independent:
        for i, line in enumerate(shot["audio"]["lines"]):
            record = voices.get("lines", {}).get(f"{shot['id']}:{i}", {})
            track = tracks.get(f"voice-{shot['id']}-{i}", {})
            from .voice_cast import select
            profile = select(root, line["speaker"])
            if (record.get("speaker") != line["speaker"] or record.get("text") != line["text"]
                    or record.get("voice_id") != voices.get("characters", {}).get(line["speaker"])
                    or record.get("path") != track.get("path") or not record.get("path")
                    or digest(within(root, record["path"])) != record.get("sha256")
                    or record.get("profile_hash") != (content_hash(profile) if profile else None)):
                raise ConfigError(shot["id"] + ": voice/text contract changed; replace this line's audio, then rerender")


def synthesize(root, sid, line_index, *, service_url=None, voice_id=None, instruct=""):
    legacy_engine()
    from vc_common import SkillError
    try:
        return _synthesize(root, sid, line_index, service_url=service_url, voice_id=voice_id, instruct=instruct)
    except SkillError as error:
        raise ConfigError(str(error)) from error


def _synthesize(root, sid, line_index, *, service_url, voice_id, instruct):
    bundle = checked(root)
    shot = next((s for s in bundle["director"]["shots"] if s["id"] == sid), None)
    if shot is None or shot.get("audio", {}).get("mode") != "independent-voice":
        raise ConfigError("Synthesis needs an independent-voice shot")
    lines = shot["audio"].get("lines", [])
    if not 0 <= line_index < len(lines):
        raise ConfigError("Choose a valid dialogue line")
    line = lines[line_index]
    legacy_engine()
    from .voice_cast import identity, select
    profile = select(root, line["speaker"])
    if profile:
        if (service_url and service_url.rstrip("/") != profile["service_url"]
                or voice_id and voice_id != identity(profile)):
            raise ConfigError("Synthesis overrides differ from the character voice cast; revise its version explicitly")
        from tts_providers import create_tts_provider
        provider = create_tts_provider(profile["provider"], {}, service_url=profile["service_url"])
        request = {"profile": profile, "profile_hash": content_hash(profile), "text": line["text"],
            "speaker": line["speaker"], "voice_id": identity(profile), "instruct": instruct}
    else:
        if not service_url or not voice_id or not voice_id.strip():
            raise ConfigError("Configure a voice cast or supply a local service URL and stable voice ID")
        from audio_client import CosyVoiceClient
        client = CosyVoiceClient(service_url)
        request = {"provider": "cosyvoice-local", "service_url": client.base_url, "text": line["text"],
            "speaker": line["speaker"], "voice_id": voice_id, "instruct": instruct}
    fingerprint = content_hash(request)
    output = root / "audio/generated" / (fingerprint + ".wav")
    receipt = output.with_suffix(".json")
    if receipt.exists() and output.exists():
        prior = load_json(receipt)
        if prior.get("input_hash") == fingerprint and prior.get("sha256") == digest(output):
            return {"ok": True, "skipped": True, **prior, "status": "listening_required", "paid_creates": 0}
        raise ConfigError("Cached local voice bytes changed; preserve and reconcile the candidate")
    output.parent.mkdir(parents=True, exist_ok=True)
    if profile:
        provider.synthesize(line["text"], output, voice=profile["voice"], reference_audio=None,
            language=profile["language"], emotion=instruct, profile_name=line["speaker"] + "-" + profile["version"])
    else:
        client.synthesize(line["text"], output, voice_id=voice_id, instruct_text=instruct)
    record = {"input_hash": fingerprint, "path": output.relative_to(root).as_posix(), "sha256": digest(output),
        "request": request, "lip_sync": "unverified-nonhuman-face"}
    atomic_json(receipt, record)
    return {"ok": True, **record, "status": "listening_required", "paid_creates": 0}
