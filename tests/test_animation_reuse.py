"""Reusable voice contracts and playback-backed exemplars; fixtures incur no requests."""
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "videocreate/src"))
from videocreate.animation import examples, library, pipeline, series, voice_cast, voices
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.project import load_project
from videocreate.references import digest
from videocreate.review import receipts
from videocreate.runtime.jobs import current_inputs
from videocreate.runtime.state import read_state, save_state


class AnimationReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "story"
        examples.create(self.project, scenario="dialogue", audio_mode="independent-voice")
        self.cast = {"schema_version": 1, "characters": {cid: {"version": "1", "provider": "cosyvoice",
            "service_url": "http://127.0.0.1:9880", "language": "zh-CN", "voice": {"voice_id": cid + "-fixture"}}
            for cid in ("lulu", "lumei")}}

    def audio(self):
        path = self.root / "test-silence.wav"
        with wave.open(str(path), "wb") as out:
            out.setparams((1, 2, 16000, 16000, "NONE", "not compressed"))
            out.writeframes(b"\0\0" * 16000)
        return path

    def test_voice_cast_rejects_unknown_character_remote_url_and_unversioned_change(self):
        voice_cast.configure(self.project, self.cast)
        changed = copy.deepcopy(self.cast)
        changed["characters"]["lulu"]["voice"]["voice_id"] = "replacement"
        with self.assertRaisesRegex(ConfigError, "reason"):
            voice_cast.configure(self.project, changed)
        with self.assertRaisesRegex(ConfigError, "version"):
            voice_cast.configure(self.project, changed, reason="fixture voice change")
        self.assertEqual(voice_cast.read(self.project), self.cast)
        for bad in ("not-a-character", "lulu"):
            invalid = copy.deepcopy(self.cast)
            invalid["characters"] = {bad: invalid["characters"]["lulu"]}
            if bad == "lulu":
                invalid["characters"][bad]["service_url"] = "https://example.com"
            with self.assertRaises(ConfigError):
                voice_cast.configure(self.project, invalid)

    def test_episode_voices_are_independent_snapshots_without_video_invalidation(self):
        root = self.root / "series"
        series.initialize(root, title="Fixtures", episodes=2)
        voice_cast.configure(root, self.cast)
        episode1 = Path(series.prepare(root, 1, self.project / "animation.authoring.json")["project"])
        b1 = load_project(episode1)
        before = current_inputs(episode1, b1, b1["generation-plan"]["jobs"][0], {})
        changed = copy.deepcopy(self.cast)
        changed["characters"]["lulu"].update(version="2")
        changed["characters"]["lulu"]["voice"]["voice_id"] = "new-preset"
        voice_cast.configure(root, changed, reason="Choose a replacement voice for future episodes")
        episode2 = Path(series.prepare(root, 2, self.project / "animation.authoring.json")["project"])
        self.assertEqual(voice_cast.read(episode1), self.cast)
        self.assertEqual(voice_cast.read(episode2), changed)
        from videocreate.series import check_episode_context
        check_episode_context(episode1, b1)
        self.assertEqual(current_inputs(episode1, b1, b1["generation-plan"]["jobs"][0], {}), before)

    def test_profile_synthesis_reuses_provider_and_cache_and_preserves_other_voice(self):
        voice_cast.configure(self.project, self.cast)
        from videocreate.cli import legacy_engine
        legacy_engine()
        def write_audio(text, output, **kwargs):
            shutil.copy2(self.audio(), output)
        with patch("tts_providers.CosyVoiceProvider.synthesize", side_effect=write_audio) as service:
            first = voices.synthesize(self.project, "shot-1", 0)
            same = voices.synthesize(self.project, "shot-1", 0)
            other = voices.synthesize(self.project, "shot-2", 0)
            self.assertTrue(same["skipped"])
            self.assertEqual(service.call_count, 2)
            changed = copy.deepcopy(self.cast)
            changed["characters"]["lulu"]["version"] = "2"
            changed["characters"]["lulu"]["voice"]["voice_id"] = "replacement"
            voice_cast.configure(self.project, changed, reason="Fixture replacement")
            with self.assertRaisesRegex(ConfigError, "Generated voice candidate"):
                pipeline.import_voice(self.project, "shot-1", 0, self.project / first["path"], voice_id=None,
                    reviewer="synthetic-fixture", notes="An old candidate must not inherit a new profile")
            replacement = voices.synthesize(self.project, "shot-1", 0)
            self.assertNotEqual(first["path"], replacement["path"])
            self.assertEqual(voices.synthesize(self.project, "shot-2", 0)["path"], other["path"])
            self.assertEqual(service.call_count, 3)
            self.assertTrue((self.project / first["path"]).is_file())
        self.assertEqual(read_state(self.project)["ledger"], [])

    def test_voicebox_uses_the_declared_preset_model_language_and_instruction(self):
        profile = self.cast["characters"]["lulu"]
        profile.update(provider="voicebox", service_url="http://127.0.0.1:17493", language="zh-CN")
        profile["voice"] = {"preset_voice_id": "fixture-preset", "preset_engine": "qwen_custom_voice",
            "model_size": "0.6B", "model_revision": "fixture-revision", "seed": 42}
        voice_cast.configure(self.project, self.cast)
        from videocreate.cli import legacy_engine
        legacy_engine()
        def write_audio(text, output, **kwargs):
            shutil.copy2(self.audio(), output)
        with patch("tts_providers.VoiceboxProvider.synthesize", side_effect=write_audio) as service:
            result = voices.synthesize(self.project, "shot-1", 0, instruct="轻声，关心但嘴硬")
            self.assertEqual(service.call_args.kwargs["voice"], profile["voice"])
            self.assertEqual(service.call_args.kwargs["language"], "zh-CN")
            self.assertEqual(service.call_args.kwargs["emotion"], "轻声，关心但嘴硬")
            self.assertEqual(result["status"], "listening_required")
            self.assertEqual(result["lip_sync"], "unverified-nonhuman-face")
        with self.assertRaisesRegex(ConfigError, "overrides"):
            voices.synthesize(self.project, "shot-1", 0, voice_id="a-different-voice")

    @unittest.skipUnless(shutil.which("ffprobe"), "FFprobe required")
    def test_replacing_one_profile_invalidates_only_its_audio_and_keeps_history(self):
        voice_cast.configure(self.project, self.cast)
        audio = self.audio()
        for sid in ("shot-1", "shot-2", "shot-3"):
            pipeline.import_voice(self.project, sid, 0, audio, voice_id=None,
                reviewer="synthetic-fixture", notes="Silence fixture; not a voice quality review")
        voices.validate_tracks(self.project, load_project(self.project))
        before = load_json(self.project / "animation-voices.json")["lines"]
        changed = copy.deepcopy(self.cast)
        changed["characters"]["lulu"]["version"] = "2"
        voice_cast.configure(self.project, changed, reason="Version changed even though preset ID remains")
        with self.assertRaisesRegex(ConfigError, "voice/text contract"):
            voices.validate_tracks(self.project, load_project(self.project))
        for sid in ("shot-1", "shot-3"):
            pipeline.import_voice(self.project, sid, 0, audio, voice_id=None,
                reviewer="synthetic-fixture", notes="New version; silence fixture")
        voices.validate_tracks(self.project, load_project(self.project))
        after = load_json(self.project / "animation-voices.json")["lines"]
        self.assertEqual(before["shot-2:0"], after["shot-2:0"])
        self.assertNotEqual(before["shot-1:0"]["profile_hash"], after["shot-1:0"]["profile_hash"])
        self.assertTrue(list((self.project / "audio/voice-line-history").glob("*.json")))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media tools required")
    def test_voice_revision_invalidates_final_review_without_invalidating_video_sources(self):
        voice_cast.configure(self.project, self.cast)
        for sid in ("shot-1", "shot-2", "shot-3"):
            pipeline.import_voice(self.project, sid, 0, self.audio(), voice_id=None,
                reviewer="synthetic-fixture", notes="Silence fixture only")
        path = self.project / "fixture.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=90x160:d=4",
            "-c:v", "libx264", "-y", str(path)], check=True, timeout=60)
        bundle = load_project(self.project)
        state = read_state(self.project)
        for job in bundle["generation-plan"]["jobs"]:
            state["jobs"][job["id"]] = {"status": "completed", "artifact": {"path": path.name,
                "sha256": digest(path), "media": {"duration": 4}}}
        save_state(self.project, state)
        before = current_inputs(self.project, bundle, bundle["generation-plan"]["jobs"][0], {})
        from videocreate.timeline.render import render
        render(self.project, bundle, state)
        original = receipts.contracts(self.project, bundle)
        self.assertIn("final", original)
        changed = copy.deepcopy(self.cast)
        changed["characters"]["lulu"]["version"] = "2"
        voice_cast.configure(self.project, changed, reason="Fixture voice revision")
        with self.assertRaisesRegex(ConfigError, "Final edit voice cast changed"):
            receipts.contracts(self.project, bundle)
        self.assertEqual(current_inputs(self.project, bundle, bundle["generation-plan"]["jobs"][0], {}), before)
        self.assertEqual(read_state(self.project)["ledger"], [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media tools required")
    def test_library_requires_playback_and_later_failure_revokes_exemplar(self):
        path = self.project / "fixture.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=90x160:d=4",
            "-c:v", "libx264", "-y", str(path)], check=True, timeout=60)
        state = read_state(self.project)
        state["jobs"]["job-001"] = {"status": "completed", "artifact": {"path": path.name,
            "sha256": digest(path), "media": {"duration": 4}}}
        save_state(self.project, state)
        bundle = load_project(self.project)
        destination = self.root / "library"
        def add(**kwargs):
            return library.add(self.project, destination, item_id="example-1", job_id="job-001", start=0, end=4,
                description="Synthetic exemplar of validation only", opening_conditions="Blue frame fixture", **kwargs)
        with self.assertRaisesRegex(ConfigError, "playback"):
            add()
        receipt = receipts.template(self.project, bundle)
        receipt["reviewer_id"] = "synthetic-workflow-fixture"
        source = receipt["assets"]["job-001"]
        for layer in ("performance_motion", "identity", "clean_frame"):
            source["layers"][layer] = {"status": "pass", "method": "human-video",
                "observations": ["Synthetic test receipt; no actual character quality claim"],
                "evidence": [{"path": path.name, "sha256": digest(path), "kind": "video", "start": 0, "end": 4}]}
        receipts.apply(self.project, bundle, receipt)
        with self.assertRaisesRegex(ConfigError, "spatial_continuity"):
            add(contact=True)
        add()
        self.assertEqual(library.catalog(destination)["items"][0]["status"], "playback-reviewed")
        self.assertFalse(library.catalog(destination)["items"][0]["full_story_approval"])
        source["layers"]["performance_motion"]["status"] = "fail"
        receipts.apply(self.project, bundle, receipt)
        self.assertEqual(library.catalog(destination)["items"][0]["status"], "unavailable")
        self.assertEqual(read_state(self.project)["ledger"], [])


if __name__ == "__main__":
    unittest.main()
