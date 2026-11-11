"""Optional v3 bridge to the retained local CosyVoice client; no model downloads."""
from pathlib import Path
from ..cli import legacy_engine
from ..config.storage import ConfigError, atomic_json, load_json
from ..planning.project import content_hash, within
from ..references import digest
from .pipeline import checked


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
            if (record.get("speaker") != line["speaker"] or record.get("text") != line["text"]
                    or record.get("voice_id") != voices.get("characters", {}).get(line["speaker"])
                    or record.get("path") != track.get("path") or not record.get("path")
                    or digest(within(root, record["path"])) != record.get("sha256")):
                raise ConfigError(shot["id"] + ": voice/text contract changed; replace this line's audio, then rerender")


def synthesize(root, sid, line_index, *, service_url, voice_id, instruct=""):
    bundle = checked(root)
    shot = next((s for s in bundle["director"]["shots"] if s["id"] == sid), None)
    if shot is None or shot.get("audio", {}).get("mode") != "independent-voice":
        raise ConfigError("Synthesis needs an independent-voice shot")
    lines = shot["audio"].get("lines", [])
    if not 0 <= line_index < len(lines) or not voice_id.strip():
        raise ConfigError("Choose a line and a stable local service voice ID")
    line = lines[line_index]
    legacy_engine()
    from audio_client import CosyVoiceClient
    client = CosyVoiceClient(service_url)  # Retained adapter enforces loopback URLs.
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
    client.synthesize(line["text"], output, voice_id=voice_id, instruct_text=instruct)
    record = {"input_hash": fingerprint, "path": output.relative_to(root).as_posix(), "sha256": digest(output),
        "request": request, "lip_sync": "unverified-nonhuman-face"}
    atomic_json(receipt, record)
    return {"ok": True, **record, "status": "listening_required", "paid_creates": 0}
