from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))

from videocreate.config.storage import ConfigError, load_json
from videocreate.media.gif import export_video_to_gif, export_frames_to_gif, extract_frame, inspect_gif, probe_image


def gif_fixture(delays=(5,), *, loop=0) -> bytes:
    data = bytearray(b"GIF89a" + struct.pack("<HHBBB", 1, 1, 0x80, 0, 0))
    data.extend(b"\x00\x00\x00\xff\xff\xff")
    if loop is not None:
        data.extend(b"!\xff\x0bNETSCAPE2.0\x03\x01" + struct.pack("<H", loop) + b"\x00")
    for delay in delays:
        data.extend(b"!\xf9\x04\x00" + struct.pack("<H", delay) + b"\x00\x00")
        data.extend(b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00")
    data.append(0x3B)
    return bytes(data)


class GifInspectionTests(unittest.TestCase):
    def test_static_and_animated_gif_metadata_are_distinguished(self):
        static = inspect_gif(gif_fixture())
        self.assertEqual(static["frame_count"], 1)
        self.assertFalse(static["animated"])
        animated = inspect_gif(gif_fixture((5, 12), loop=3))
        self.assertEqual(animated["frame_count"], 2)
        self.assertTrue(animated["animated"])
        self.assertEqual(animated["frame_durations_ms"], [50, 120])
        self.assertEqual(animated["duration_ms"], 170)
        self.assertEqual(animated["loop"], 3)

    def test_truncated_or_non_gif_bytes_are_rejected(self):
        with self.assertRaises(ConfigError):
            inspect_gif(gif_fixture()[:-2])
        with self.assertRaises(ConfigError):
            inspect_gif(b"not a gif")

    def test_inspect_reads_actual_gif_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "animation.gif"
            payload = gif_fixture((2, 3))
            path.write_bytes(payload)
            report = probe_image(path)
        self.assertTrue(report["animated"])
        self.assertEqual(report["sha256"], hashlib.sha256(payload).hexdigest())

    def test_gif_bytes_with_non_gif_extension_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image.png"
            path.write_bytes(gif_fixture((2, 3)))
            with self.assertRaisesRegex(ConfigError, "extension"):
                probe_image(path)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for the conversion integration test")
    def test_video_export_creates_a_traceable_animated_gif_without_paid_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=size=128x72:rate=10", "-t", "1", "-pix_fmt", "yuv420p", "-y", str(source)],
                check=True, capture_output=True, timeout=60)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = export_video_to_gif(root, source=source, job_id="gif-preview-001",
                duration=1, fps=10, width=96)
            artifact = root / result["artifact"]["path"]
            self.assertTrue(result["ok"])
            self.assertEqual(result["paid_creates"], 0)
            self.assertTrue(result["artifact"]["animated"])
            self.assertGreater(result["artifact"]["frame_count"], 1)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            self.assertTrue(artifact.with_suffix(".gif.json").is_file())
            with self.assertRaises(ConfigError):
                export_video_to_gif(root, source=source, job_id="gif-preview-001", duration=1)
            first = extract_frame(root, source=artifact, job_id="gif-first", at=0)
            second = extract_frame(root, source=artifact, job_id="gif-second", at=0.4)
            self.assertNotEqual(first["artifact"]["sha256"], second["artifact"]["sha256"])
            frames = [root / r["artifact"]["path"] for r in (first, second)]
            animation = export_frames_to_gif(root, frames=frames, job_id="frames-animation", fps=5, width=96)
            self.assertEqual(animation["paid_creates"], 0)
            self.assertEqual(animation["kind"], "frames-to-gif")
            self.assertEqual(animation["artifact"]["frame_count"], 2)
            self.assertEqual(len(animation["source_frames"]), 2)
            self.assertNotIn("source", animation)


if __name__ == "__main__":
    unittest.main()
