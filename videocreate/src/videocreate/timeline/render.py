from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config.storage import ConfigError, atomic_json
from ..planning.project import content_hash, within
from .model import mapping


def run(arguments: list[str]) -> None:
    result = subprocess.run(arguments, capture_output=True)
    if result.returncode:
        # No credentials are passed to local media tools.
        raise ConfigError("Local media command failed: " + result.stderr.decode("utf-8", errors="replace")[-2000:])


def probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ConfigError("FFprobe is required; no automatic download was attempted")
    result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, check=True)
    value = json.loads(result.stdout)
    video = next((s for s in value.get("streams", []) if s["codec_type"] == "video"), None)
    if not video:
        raise ConfigError("Source has no decodable video stream")
    return {"duration": float(value["format"]["duration"]), "width": video["width"], "height": video["height"],
            "fps": video.get("avg_frame_rate", "0/0"), "source_fps": video.get("r_frame_rate", "0/0"),
            "frame_count": video.get("nb_frames"), "has_audio": any(s["codec_type"] == "audio" for s in value["streams"]),
            "codec": video.get("codec_name")}


def atempo(rate: float) -> str:
    values = []
    while rate < 0.5:
        values.append(0.5)
        rate /= 0.5
    while rate > 2:
        values.append(2)
        rate /= 2
    values.append(rate)
    return ",".join("atempo=" + str(v) for v in values)


def resolve_clips(root: Path, timeline: dict, state: dict) -> dict[str, Path]:
    paths = {}
    for clip in timeline["clips"]:
        if clip.get("path"):
            paths[clip["id"]] = within(root, clip["path"])
        else:
            from ..runtime.candidates import selected
            record = selected(state.get("jobs", {}).get(clip["job_id"], {}))
            artifact = record.get("artifact", {})
            if record.get("status") != "completed" or not artifact.get("path"):
                raise ConfigError("Clip job is not completed: " + clip["job_id"])
            path = within(root, artifact["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
                raise ConfigError("Raw clip bytes changed; preserve source and register a derived clip explicitly")
            paths[clip["id"]] = path
    return paths


def subtitle_file(path: Path, cues: list[dict]) -> None:
    def stamp(seconds):
        ms = round(seconds * 1000)
        return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
    path.write_text("\n\n".join(f"{i}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{cue['text']}" for i, cue in enumerate(cues, 1)) + "\n", encoding="utf-8")


def auxiliary_hashes(root: Path, timeline: dict) -> dict:
    return {entry["path"]: hashlib.sha256(within(root, entry["path"]).read_bytes()).hexdigest()
        for group in ("audio_tracks", "overlays") for entry in timeline.get(group, []) if entry.get("path")}


def render(root: Path, bundle: dict, state: dict, *, output_name: str = "preview.mp4", scope: str = "project-timeline") -> dict:
    if scope not in {"project-timeline", "animation-pilot"}:
        raise ConfigError("Unknown edit scope")
    if "animation" in bundle:
        from ..animation.voices import validate_tracks
        validate_tracks(root, bundle)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("FFmpeg is required; no automatic download was attempted")
    if Path(output_name).name != output_name or not output_name.endswith(".mp4"):
        raise ConfigError("Output must be a plain MP4 filename in deliverables")
    timeline = bundle["timeline"]
    plan = mapping(timeline)
    clips = resolve_clips(root, timeline, state)
    auxiliary = auxiliary_hashes(root, timeline)
    media = {cid: probe(path) for cid, path in clips.items()}
    width, height = timeline.get("width", 720), timeline.get("height", 1280)
    if not isinstance(width, int) or not isinstance(height, int) or width % 2 or height % 2 or not 64 <= width <= 4096 or not 64 <= height <= 4096:
        raise ConfigError("Timeline canvas must be even integer dimensions from 64 to 4096")
    for seg in plan["segments"]:
        if seg["source_out"] > media[seg["clip_id"]]["duration"] + 0.04:
            raise ConfigError(seg["id"] + ": retained source window exceeds actual downloaded duration")
    target_dir = root / "deliverables"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / output_name
    if any(target.resolve() == path.resolve() for path in clips.values()):
        raise ConfigError("Output cannot overwrite a source clip")
    fps_notes = []
    with tempfile.TemporaryDirectory(prefix="videocreate-edit-", dir=target_dir) as temp:
        folder, parts = Path(temp), []
        for i, seg in enumerate(plan["segments"]):
            path, rate = clips[seg["clip_id"]], seg.get("rate", 1)
            source = media[seg["clip_id"]]
            duration = seg["source_out"] - seg["source_in"]
            part = folder / f"segment-{i:03}.mp4"
            args = [ffmpeg, "-nostdin", "-filter_threads", "1", "-v", "error", "-y", "-ss", str(seg["source_in"]), "-t", str(duration), "-i", str(path)]
            filters = f"setpts=(PTS-STARTPTS)/{rate},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={timeline['fps']}"
            if source["has_audio"] and seg.get("source_audio", "mute") != "mute":
                args += ["-af", "asetpts=PTS-STARTPTS," + atempo(rate)
                    + f",apad=whole_dur={seg['duration']},atrim=duration={seg['duration']}", "-map", "0:a:0"]
            else:
                args += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seg['duration']}", "-map", "1:a:0"]
            args += ["-map", "0:v:0", "-vf", filters, "-t", str(seg["duration"]), "-c:v", "libx264",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(part)]
            run(args)
            parts.append(part)
            from fractions import Fraction
            try:
                unique = float(Fraction(source["fps"])) * rate
            except (ValueError, ZeroDivisionError):
                unique = None
            fps_notes.append({"segment_id": seg["id"], "source_fps": source["fps"], "playback_rate": rate,
                "source_frame_samples_per_timeline_second": unique, "output_fps": timeline["fps"],
                "interpolation": "none", "note": "fps conversion resamples/repeats frames; it does not prove high-frame-rate capture"})
        concat = folder / "concat.txt"
        concat.write_text("\n".join("file '" + part.name + "'" for part in parts), encoding="utf-8")
        base = folder / "picture.mp4"
        run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(base)])
        final_temp = folder / "output.mp4"
        audio = plan["audio_tracks"]
        if audio:
            args = [ffmpeg, "-v", "error", "-y", "-i", str(base)]
            graph, labels = [], ["[0:a]"]
            for i, event in enumerate(audio, 1):
                source = clips[event["clip_id"]] if event.get("clip_id") else within(root, event["path"])
                args += ["-i", str(source)]
                delay = round(event["timeline_start"] * 48000)
                graph.append(f"[{i}:a]atrim=start={event['source_in']}:end={event['source_out']},asetpts=PTS-STARTPTS,aresample=48000,volume={event.get('gain_db',0)}dB,adelay={delay}S:all=1[a{i}]")
                labels.append(f"[a{i}]")
            graph.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,alimiter=limit=0.95[mix]")
            args += ["-filter_complex", ";".join(graph), "-map", "0:v", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac",
                     "-t", str(plan["duration"]), "-movflags", "+faststart", str(final_temp)]
            run(args)
        else:
            run([ffmpeg, "-v", "error", "-y", "-i", str(base), "-c", "copy", "-movflags", "+faststart", str(final_temp)])
        if timeline.get("overlays"):
            from .overlays import composite
            composite(root, timeline, final_temp, folder / "composited.mp4", folder, ffmpeg, plan["duration"])
            final_temp = folder / "composited.mp4"
        final_media = probe(final_temp)
        run([ffmpeg, "-v", "error", "-i", str(final_temp), "-f", "null", "-"])
        final_temp.replace(target)
    subtitle_file(target.with_suffix(".srt"), plan["subtitles"])
    manifest = {"schema_version": 3, "status": "draft_preview", "scope": scope, "path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "timeline_hash": content_hash(timeline), "mapping": plan, "media": final_media,
        "source_hashes": {cid: hashlib.sha256(path.read_bytes()).hexdigest() for cid, path in clips.items()},
        "auxiliary_hashes": auxiliary,
        "fps_report": fps_notes, "technical_decode": "pass", "audio_content": "unverified", "content": "unverified", "paid_creates": 0}
    atomic_json(target.with_suffix(".manifest.json"), manifest)
    return {"ok": True, **manifest}
