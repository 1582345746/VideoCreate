from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config.storage import ConfigError, atomic_json

MAX_GIF_BYTES = 48 * 1024 * 1024
MAX_GIF_PIXELS = 100_000_000
MAX_GIF_FRAMES = 3000
MAX_GIF_SUBBLOCKS = 100_000


def inspect_gif(data: bytes) -> dict[str, Any]:
    if len(data) < 14 or len(data) > MAX_GIF_BYTES or data[:6] not in {b"GIF87a", b"GIF89a"}:
        raise ConfigError("GIF header or file size is invalid")
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    screen_flags = data[10]
    if not width or not height or width * height > MAX_GIF_PIXELS:
        raise ConfigError("GIF dimensions are invalid or exceed the pixel safety limit")
    cursor = 13
    if screen_flags & 0x80:
        cursor += 3 * (2 ** ((screen_flags & 0x07) + 1))
    if cursor > len(data):
        raise ConfigError("GIF global color table is truncated")

    frame_delays: list[int] = []
    pending_delay = 0
    loop_count: int | None = None
    trailer = False

    def skip_subblocks(index: int, *, capture_limit: int = 0) -> tuple[int, bytes]:
        content = bytearray()
        blocks = 0
        while index < len(data):
            size = data[index]
            index += 1
            if size == 0:
                return index, bytes(content)
            end = index + size
            if end > len(data):
                raise ConfigError("GIF data block is truncated")
            if capture_limit and len(content) < capture_limit:
                content.extend(data[index:min(end, index + capture_limit - len(content))])
            blocks += 1
            if blocks > MAX_GIF_SUBBLOCKS:
                raise ConfigError("GIF contains too many data subblocks")
            index = end
        raise ConfigError("GIF data blocks have no terminator")

    while cursor < len(data):
        marker = data[cursor]
        cursor += 1
        if marker == 0x3B:
            trailer = True
            break
        if marker == 0x21:
            if cursor >= len(data):
                raise ConfigError("GIF extension is truncated")
            label = data[cursor]
            cursor += 1
            if label == 0xF9:
                if cursor >= len(data) or data[cursor] != 4 or cursor + 6 > len(data) or data[cursor + 5] != 0:
                    raise ConfigError("GIF graphic control extension is invalid")
                pending_delay = int.from_bytes(data[cursor + 2:cursor + 4], "little")
                cursor += 6
            elif label == 0xFF:
                if cursor >= len(data):
                    raise ConfigError("GIF application extension is truncated")
                block_size = data[cursor]
                end = cursor + 1 + block_size
                if end > len(data):
                    raise ConfigError("GIF application identifier is truncated")
                application = data[cursor + 1:end]
                cursor, blocks = skip_subblocks(end, capture_limit=3)
                if application.startswith((b"NETSCAPE2.0", b"ANIMEXTS1.0")) and len(blocks) >= 3 and blocks[0] == 1:
                    loop_count = int.from_bytes(blocks[1:3], "little")
            else:
                cursor, _ = skip_subblocks(cursor)
            continue
        if marker == 0x2C:
            if cursor + 9 > len(data):
                raise ConfigError("GIF image descriptor is truncated")
            frame_width = int.from_bytes(data[cursor + 4:cursor + 6], "little")
            frame_height = int.from_bytes(data[cursor + 6:cursor + 8], "little")
            flags = data[cursor + 8]
            if not frame_width or not frame_height or frame_width * frame_height > MAX_GIF_PIXELS:
                raise ConfigError("GIF frame dimensions are invalid")
            cursor += 9
            if flags & 0x80:
                cursor += 3 * (2 ** ((flags & 0x07) + 1))
            if cursor >= len(data):
                raise ConfigError("GIF image data is missing")
            cursor += 1
            cursor, _ = skip_subblocks(cursor)
            frame_delays.append(pending_delay)
            pending_delay = 0
            if len(frame_delays) > MAX_GIF_FRAMES:
                raise ConfigError("GIF exceeds the frame safety limit")
            continue
        raise ConfigError("GIF contains an invalid block marker")

    if not trailer or not frame_delays:
        raise ConfigError("GIF has no complete image frames or trailer")
    return {"format": "gif", "mime_type": "image/gif", "width": width, "height": height,
            "frame_count": len(frame_delays), "animated": len(frame_delays) > 1,
            "frame_durations_ms": [delay * 10 for delay in frame_delays],
            "duration_ms": sum(frame_delays) * 10, "loop": loop_count,
            "sha256": hashlib.sha256(data).hexdigest()}


def probe_image(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ConfigError("Image file is missing or empty")
    if path.stat().st_size > MAX_GIF_BYTES:
        raise ConfigError("Image file exceeds the 48 MB inspection limit")
    data = path.read_bytes()
    if data.startswith((b"GIF87a", b"GIF89a")):
        if path.suffix.lower() != ".gif":
            raise ConfigError("Image extension does not match GIF file contents")
        return inspect_gif(data)
    suffixes = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
    image_format = suffixes.get(path.suffix.lower())
    if not image_format:
        raise ConfigError("Supported image formats are PNG, JPEG, WebP and GIF")
    actual_extension = (".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else
        ".jpg" if data.startswith(b"\xff\xd8\xff") else
        ".webp" if data.startswith(b"RIFF") and data[8:12] == b"WEBP" else "")
    expected_extension = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}[image_format]
    if actual_extension != expected_extension:
        raise ConfigError("Image extension does not match its file contents")
    return {"format": image_format, "mime_type": f"image/{'jpeg' if image_format == 'jpeg' else image_format}",
            "width": None, "height": None, "frame_count": 1, "animated": False,
            "frame_durations_ms": [], "duration_ms": 0, "loop": None,
            "sha256": hashlib.sha256(data).hexdigest()}


def export_video_to_gif(root: Path, *, source: Path, job_id: str, start: float = 0,
                        duration: float = 3, fps: int = 15, width: int = 480,
                        loop: int = 0) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", job_id):
        raise ConfigError("GIF job ID is invalid")
    if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024 * 1024:
        raise ConfigError("Video source is missing or exceeds 2 GB")
    if not 0 <= start <= 86_400 or not 0.1 <= duration <= 30 or start + duration > 86_400:
        raise ConfigError("GIF source range must be positive and no longer than 30 seconds")
    if not 1 <= fps <= 60 or not 64 <= width <= 2048 or loop not in {-1, *range(0, 65536)}:
        raise ConfigError("GIF fps, width or loop value is outside the supported range")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("FFmpeg is required for video-to-GIF conversion")
    destination = root / "assets" / "generated" / job_id / "final.gif"
    if destination.exists():
        raise ConfigError("GIF output already exists; choose a new job ID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    palette = destination.with_name("palette.png")
    temporary = destination.with_name("final.tmp.gif")
    trim_filter = f"fps={fps},scale={width}:-1:flags=lanczos"
    try:
        palette_result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(start),
            "-t", str(duration), "-i", str(source), "-vf", trim_filter + ",palettegen=stats_mode=diff",
            "-frames:v", "1", "-y", str(palette)], capture_output=True, text=True, timeout=180)
        if palette_result.returncode:
            raise ConfigError("FFmpeg could not create a GIF palette")
        convert_result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(start),
            "-t", str(duration), "-i", str(source), "-i", str(palette), "-lavfi",
            f"{trim_filter}[x];[x][1:v]paletteuse=dither=sierra2_4a:diff_mode=rectangle", "-loop", str(loop),
            "-y", str(temporary)], capture_output=True, text=True, timeout=180)
        if convert_result.returncode or not temporary.is_file():
            raise ConfigError("FFmpeg could not encode the GIF output")
        if not temporary.is_file() or temporary.stat().st_size > MAX_GIF_BYTES:
            raise ConfigError("GIF output is missing or exceeds 48 MB")
        output = temporary.read_bytes()
        metadata = inspect_gif(output)
        temporary.replace(destination)
    finally:
        for path in (palette, temporary):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    source_hash = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            source_hash.update(chunk)
    source_digest = source_hash.hexdigest()
    output_digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "kind": "video-to-gif", "status": "draft_preview",
        "source": str(source.resolve()), "source_sha256": source_digest,
        "source_start_seconds": start, "source_duration_seconds": duration,
        "fps": fps, "width": width, "loop": loop,
        "artifact": {"path": destination.relative_to(root).as_posix(), "sha256": output_digest, **metadata},
        "paid_creates": 0}
    atomic_json(destination.with_suffix(".gif.json"), manifest)
    return {"ok": True, **manifest}


def export_frames_to_gif(root: Path, *, frames: list[Path], job_id: str, fps: int = 10,
                          width: int = 480, loop: int = 0) -> dict[str, Any]:
    if not frames or len(frames) > 1800 or not 1 <= fps <= 60 or not 0.1 <= len(frames) / fps <= 30:
        raise ConfigError("Frame animation needs 0.1–30 seconds and at most 1800 frames")
    metadata = [probe_image(path) for path in frames]
    if any(m["animated"] or m["format"] != metadata[0]["format"] for m in metadata):
        raise ConfigError("Use static frames of one image format for frame animation")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("FFmpeg is required for frame animation")
    root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="videocreate-frames-") as directory:
        work = Path(directory)
        suffix = frames[0].suffix.lower()
        for index, frame in enumerate(frames):
            shutil.copyfile(frame, work / f"frame-{index:05d}{suffix}")
        source = work / "frames.mkv"
        encoded = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
            "-i", str(work / ("frame-%05d" + suffix)), "-c:v", "ffv1", "-y", str(source)],
            capture_output=True, timeout=180)
        if encoded.returncode:
            raise ConfigError("FFmpeg could not read the frame sequence; use matching dimensions and image formats")
        result = export_video_to_gif(root, source=source, job_id=job_id, duration=len(frames) / fps,
            fps=fps, width=width, loop=loop)
    result.update(kind="frames-to-gif", source_frames=[{"path": str(p.resolve()), "sha256": m["sha256"]}
        for p, m in zip(frames, metadata)])
    for key in ("source", "source_sha256", "source_start_seconds"):
        result.pop(key, None)
    atomic_json((root / result["artifact"]["path"]).with_suffix(".gif.json"), {k: v for k, v in result.items() if k != "ok"})
    return result


def extract_frame(root: Path, *, source: Path, job_id: str, at: float = 0) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", job_id) or not 0 <= at <= 86_400:
        raise ConfigError("Frame ID or timestamp is invalid")
    if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024 * 1024:
        raise ConfigError("Frame source is missing or exceeds 2 GB")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("FFmpeg is required to extract a still frame")
    root = root.resolve()
    destination = root / "assets" / "generated" / job_id / "frame.png"
    if destination.exists():
        raise ConfigError("Frame output already exists; choose a new ID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(at),
        "-i", str(source), "-frames:v", "1", "-n", str(destination)], capture_output=True, timeout=180)
    if encoded.returncode or not destination.is_file():
        raise ConfigError("FFmpeg could not extract a frame at this timestamp")
    metadata = probe_image(destination)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    result = {"kind": "explicit-static-frame", "source": str(source.resolve()), "source_sha256": digest.hexdigest(),
        "at_seconds": at, "artifact": {"path": destination.relative_to(root).as_posix(), **metadata}, "paid_creates": 0}
    atomic_json(destination.with_suffix(".png.json"), result)
    return {"ok": True, **result}
