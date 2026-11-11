"""Pilot edits preserve production plans, speech and final-review boundaries."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
from videocreate.animation import examples, pipeline, previews
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.project import content_hash, load_project, validate_plan
from videocreate.references import digest
from videocreate.review import receipts
from videocreate.runtime.jobs import current_inputs
from videocreate.runtime.state import read_state, save_state
from videocreate.timeline.model import mapping


class AnimationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "story"
        examples.create(self.root)
        self.bundle = load_project(self.root)

    def test_trim_rebases_independent_events_without_changing_the_plan(self):
        bundle = self.bundle
        timeline = bundle["timeline"]
        first, second = timeline["segments"][:2]
        boundary = first["source_out"] - first["source_in"]
        timeline["audio_tracks"] = [
            {"id": "line", "kind": "dialogue", "path": "voice.wav", "source_in": 0,
             "source_out": .5, "timeline_start": boundary + .1},
            {"id": "music", "kind": "music", "path": "music.wav", "source_in": 0,
             "source_out": bundle["brief"]["target_seconds"], "timeline_start": 0}]
        timeline["subtitles"] = [{"text": "Intact line", "start": boundary + .1, "end": boundary + .6}]
        before = content_hash(bundle)
        derived = previews.prepare(bundle, {"reason": "Remove duplicate action", "segments": {first["id"]: {"source_out": 2}}})
        self.assertEqual(content_hash(bundle), before)
        self.assertEqual([s["shot_id"] for s in derived["segments"]], bundle["animation"]["adaptation"]["pilot_shot_ids"])
        self.assertEqual(len(derived["clips"]), 2)
        line = next(t for t in derived["audio_tracks"] if t["id"] == "line")
        self.assertAlmostEqual(line["timeline_start"], 2.1)
        self.assertAlmostEqual(line["source_out"] - line["source_in"], .5)
        self.assertAlmostEqual(derived["subtitles"][0]["start"], 2.1)
        music = [t for t in derived["audio_tracks"] if t["kind"] == "music"]
        self.assertEqual(len(music), 2)
        self.assertAlmostEqual(music[1]["source_in"], boundary)
        self.assertAlmostEqual(music[1]["timeline_start"], 2)

    def test_trim_refuses_partial_speech_subtitles_and_nonpilot_changes(self):
        segment = self.bundle["timeline"]["segments"][0]
        edit = {"reason": "Trim", "segments": {segment["id"]: {"source_out": 1}}}
        for event in ("speech", "subtitle"):
            with self.subTest(event=event):
                bundle = copy.deepcopy(self.bundle)
                if event == "speech":
                    bundle["timeline"]["audio_tracks"] = [{"id": "line", "kind": "dialogue", "path": "voice.wav",
                        "source_in": 0, "source_out": 1, "timeline_start": .5}]
                else:
                    bundle["timeline"]["subtitles"] = [{"text": "Full phrase", "start": .5, "end": 1.5}]
                with self.assertRaisesRegex(ConfigError, "cut a spoken line or subtitle"):
                    previews.prepare(bundle, edit)
        with self.assertRaisesRegex(ConfigError, "non-pilot"):
            previews.prepare(self.bundle, {"reason": "Wrong shot", "segments": {"seg-003": {"source_out": 1}}})
        with self.assertRaisesRegex(ConfigError, "inside"):
            previews.prepare(self.bundle, {"reason": "Beyond retained window", "segments": {segment["id"]: {"source_out": 100}}})

    def completed_pilot(self, bundle):
        path = self.root / "fixture.mp4"
        duration = max(j["seconds"] for j in bundle["generation-plan"]["jobs"])
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=blue:s=180x320:d={duration}",
            "-c:v", "libx264", "-y", str(path)], check=True)
        state = read_state(self.root)
        pilot = bundle["animation"]["adaptation"]["pilot_shot_ids"]
        for job in bundle["generation-plan"]["jobs"]:
            if not set(job["shot_ids"]) & set(pilot):
                continue
            state["jobs"][job["id"]] = {"status": "completed",
                "input_hash": current_inputs(self.root, bundle, job, {}),
                "artifact": {"path": path.name, "sha256": digest(path), "media": {"duration": duration}}}
        save_state(self.root, state)
        return path

    def test_watched_edit_evidence_checks_source_and_view_time_and_audio_policy(self):
        # Contract fixture only: no claim that these bytes contain animation.
        state = read_state(self.root)
        timeline = previews.prepare(self.bundle)
        sources = {}
        for i, job in enumerate(self.bundle["generation-plan"]["jobs"][:2]):
            source = self.root / (job["id"] + ".mp4")
            source.write_bytes(b"synthetic source " + str(i).encode())
            sources[timeline["clips"][i]["id"]] = digest(source)
            state["jobs"][job["id"]] = {"status": "completed", "artifact": {
                "path": source.name, "sha256": digest(source), "media": {"duration": job["seconds"]}}}
        save_state(self.root, state)
        watched = self.root / "watched.mp4"
        watched.write_bytes(b"synthetic edit contract fixture")
        def write_manifest():
            atomic_json(self.root / "watched.timeline.json", timeline)
            atomic_json(self.root / "watched.manifest.json", {"sha256": digest(watched), "technical_decode": "pass",
                "timeline_hash": content_hash(timeline), "mapping": mapping(timeline), "source_hashes": sources,
                "media": {"duration": mapping(timeline)["duration"]}})
        write_manifest()
        receipt = receipts.template(self.root, self.bundle)
        receipt["reviewer_id"] = "contract-test"
        receipt["assets"] = {"job-002": receipt["assets"]["job-002"]}
        contract = receipt["assets"]["job-002"]
        segment = mapping(timeline)["segments"][1]
        evidence = {"path": watched.name, "sha256": digest(watched), "start": segment["source_in"],
            "end": segment["source_out"], "kind": "video", "mapped_view": {
                "manifest": "watched.manifest.json", "timeline": "watched.timeline.json",
                "start": segment["timeline_start"], "end": segment["timeline_end"]}}
        contract["layers"] = {"audio": {"status": "pass", "method": "human-listening",
            "observations": ["Synthetic test only"], "evidence": [evidence]}}
        self.assertEqual(receipts.validate_receipt(self.root, self.bundle, receipt), [])
        wrong = copy.deepcopy(receipt)
        wrong["assets"]["job-002"]["layers"]["audio"]["evidence"][0]["mapped_view"]["start"] = 0
        self.assertTrue(receipts.validate_receipt(self.root, self.bundle, wrong))
        sources[segment["clip_id"]] = "0" * 64
        write_manifest()
        self.assertTrue(receipts.validate_receipt(self.root, self.bundle, receipt))
        sources[segment["clip_id"]] = contract["sha256"]
        timeline["segments"][1]["source_audio"] = "mute"
        write_manifest()
        self.assertTrue(receipts.validate_receipt(self.root, self.bundle, receipt))
        timeline["segments"][1]["source_audio"] = "preserve"
        timeline["audio_tracks"] = [{"id": "mix", "path": "new.wav", "kind": "music", "source_in": 0,
            "source_out": 1, "timeline_start": 0}]
        write_manifest()
        self.assertTrue(receipts.validate_receipt(self.root, self.bundle, receipt))
        timeline["audio_tracks"] = []
        write_manifest()
        watched.write_bytes(b"changed watched edit")
        self.assertTrue(receipts.validate_receipt(self.root, self.bundle, receipt))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media tools required")
    def test_real_cli_pilot_edit_preserves_state_and_cannot_be_final_delivery(self):
        source = self.completed_pilot(self.bundle)
        before = {p.name: p.read_bytes() for p in self.root.glob("*.json")}
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "videocreate/scripts/videocreate.py"), "animation", "preview", str(self.root)],
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = json.loads(result.stdout)
        self.assertFalse(result["full_story_delivery"])
        self.assertEqual(result["scope"], "animation-pilot")
        self.assertEqual(result["paid_creates"], 0)
        self.assertTrue(Path(result["path"]).is_file())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.glob("*.json")})
        self.assertTrue(validate_plan(load_project(self.root), self.root)["ok"])
        self.assertTrue(all(row["reuse"] for row in pipeline.status(self.root)["jobs"][:2]))
        contracts = receipts.contracts(self.root, self.bundle, output_name="animation-pilot.mp4")
        self.assertEqual(set(contracts), {"job-001", "job-002"})
        with self.assertRaisesRegex(ConfigError, "actual final"):
            pipeline.review(self.root, output_name="animation-pilot.mp4")
        self.assertNotEqual(receipts.summary(self.root, self.bundle, output_name="animation-pilot.mp4")["status"], "accepted_delivery")
        state = read_state(self.root)
        state["jobs"]["job-001"]["input_hash"] = "stale"
        save_state(self.root, state)
        with self.assertRaisesRegex(ConfigError, "current generation inputs"):
            previews.render(self.root)
        with self.assertRaisesRegex(ConfigError, "separate"):
            previews.render(self.root, output_name="preview.mp4")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media tools required")
    def test_pilot_voice_does_not_require_the_unproduced_third_shot(self):
        dialogue = self.root.parent / "dialogue"
        examples.create(dialogue, scenario="dialogue")
        self.root = dialogue
        bundle = load_project(self.root)
        voice = self.root / "tone.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4", "-y", str(voice)], check=True)
        for shot in bundle["director"]["shots"][:2]:
            speaker = shot["audio"]["lines"][0]["speaker"]
            pipeline.import_voice(self.root, shot["id"], 0, voice, voice_id="fixture-" + speaker,
                reviewer="synthetic-test", notes="Test tone only; no voice quality assertion")
        bundle = load_project(self.root)
        self.completed_pilot(bundle)
        result = previews.render(self.root)
        timeline = load_json(Path(result["path"]).with_suffix(".timeline.json"))
        self.assertEqual(len(timeline["audio_tracks"]), 2)
        self.assertNotIn("voice-shot-3-0", {t["id"] for t in timeline["audio_tracks"]})
        self.assertEqual(result["audio_content"], "unverified")


if __name__ == "__main__":
    unittest.main()
