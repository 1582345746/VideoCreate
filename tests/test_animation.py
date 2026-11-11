"""Animation contracts and real local-media integration; no provider charges."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
from videocreate.animation import examples, pipeline, project, themes
from videocreate.animation.schema import animation_schema
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.project import compile_job, content_hash, load_project, validate_plan
from videocreate.references import digest
from videocreate.runtime.jobs import current_inputs
from videocreate.runtime.state import read_state, save_state
from videocreate.review import receipts
from videocreate import series


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def example(self, name="story", **kwargs):
        path = self.root / name
        examples.create(path, **kwargs)
        return path, load_project(path)

    def frame(self, root, bundle, sid="shot-1"):
        from PIL import Image
        path = root / (sid + ".png")
        Image.new("RGB", (180, 320), (230, 200, 90)).save(path)
        observation = {"sha256": digest(path), "input_hash": pipeline.keyframe_spec(root, bundle, sid)["input_hash"],
            "method": "human-image", "reviewer_id": "synthetic-test-fixture", "notes": "Fixture only; no claim about generated character quality",
            "checks": {k: "pass" for k in pipeline.FRAME_CHECKS}}
        pipeline.select_frame(root, sid, path, observation)
        return path, observation

    def test_three_story_types_and_second_theme_compile(self):
        for theme in ("lulu-lumei", "cloud-couriers"):
            for scenario in ("reaction", "dialogue", "contact"):
                with self.subTest(theme=theme, scenario=scenario):
                    root, bundle = self.example(theme + scenario, theme=theme, scenario=scenario)
                    self.assertTrue(validate_plan(bundle, root)["ok"])
                    for job in bundle["generation-plan"]["jobs"]:
                        compiled = compile_job(bundle, job, max_bytes=4096, root=root)
                        self.assertLessEqual(compiled["utf8_bytes"], 4096)
                        if theme == "cloud-couriers":
                            self.assertNotIn("黄色", compiled["prompt"])
                            self.assertNotIn("lulu", compiled["prompt"])
                            self.assertNotIn("噜", compiled["prompt"])
                    self.assertEqual(pipeline.status(root)["budget"]["requests"], 0)

    def test_missing_story_point_and_disconnected_mapping_rejected(self):
        root, bundle = self.example()
        document = bundle["animation"]
        document["adaptation"]["point_map"] = []
        self.assertFalse(project.validate_document(document, ready=True)["ok"])
        document = project.read(root)
        document["adaptation"]["point_map"][0]["beat_ids"] = ["beat-1"]
        self.assertFalse(project.validate_document(document, ready=True)["ok"])

    def test_native_dialogue_preserves_generated_audio_without_tts_or_unheard_captions(self):
        root, bundle = self.example(scenario="dialogue")
        self.assertEqual(bundle["timeline"]["audio_tracks"], [])
        self.assertEqual(bundle["timeline"]["subtitles"], [])
        self.assertTrue(all(s["source_audio"] == "preserve" for s in bundle["timeline"]["segments"]))
        self.assertTrue(all(s["audio"]["mode"] == "native-dialogue" for s in bundle["director"]["shots"]))
        from videocreate.animation.voices import validate_tracks
        validate_tracks(root, bundle)
        compiled = compile_job(bundle, bundle["generation-plan"]["jobs"][0], root=root, max_bytes=4096)
        self.assertIn("我才没等你。", compiled["prompt"])
        self.assertNotIn("Voice is supplied on an independent soundtrack", compiled["prompt"])

    def test_current_plan_cannot_drop_mapped_shot_or_change_identity(self):
        root, bundle = self.example()
        bundle["director"]["shots"].pop()
        self.assertFalse(validate_plan(bundle, root)["ok"])
        bundle = load_project(root)
        bundle["director"]["assets"][-1]["description"] = "A different character"
        self.assertFalse(validate_plan(bundle, root)["ok"])

    def test_pilot_pair_must_be_adjacent(self):
        root, bundle = self.example()
        doc = bundle["animation"]
        doc["adaptation"]["pilot_shot_ids"] = ["shot-1", "shot-3"]
        self.assertFalse(project.validate_document(doc, ready=True)["ok"])

    def test_static_frames_cannot_certify_audio_or_motion(self):
        root, bundle = self.example()
        doc = bundle["animation"]
        doc["sources"] = [{"id": "ref", "path": "/not-present.mp4", "sha256": "x", "purpose": "story", "duration": 12,
            "report": "report.json", "report_sha256": "x"}]
        doc["study"] = {"analyst": "fixture", "segments": [], "observations": [{"id": "obs", "source_id": "ref", "start": 0,
            "end": 3, "kind": "dialogue", "method": "frames", "certainty": "observed", "notes": "Caption seen", "evidence_ids": ["frame-1"]}]}
        result = project.validate_document(doc)
        self.assertFalse(result["ok"])
        doc["study"]["observations"][0]["kind"] = "overlay"
        self.assertTrue(project.validate_document(doc)["ok"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media tools required")
    def test_unicode_reference_import_dedup_and_provenance(self):
        root = self.root / "source-study"
        project.initialize(root)
        source = self.root / "中文 空格 # 🫣.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=96x128:d=2", "-c:v", "libx264", "-y", str(source)], check=True)
        alias_parent = self.root / "alias-parent"
        alias_parent.mkdir()
        # The analyzer resolves paths; callers may use aliases, including Windows 8.3 names.
        alternate_root = alias_parent / ".." / root.name
        first = project.inspect(alternate_root, [source, source], max_frames=4)
        self.assertTrue(first["sources"][1]["duplicate"])
        document = project.read(root)
        record = document["sources"][0]
        report = load_json(root / record["report"])
        frame = report["frames"][0]
        study = {"analyst": "fixture", "segments": [], "observations": [{"id": "seen", "source_id": record["id"],
            "start": 0, "end": 2, "kind": "visible-state", "method": "frames", "certainty": "observed", "notes": "Blue fixture",
            "evidence_ids": [frame["id"]]}]}
        self.assertTrue(project.author(root, {"study": study})["ok"])
        ranged = project.inspect(root, [source], max_frames=2, sample_start=.5, sample_end=1.5)
        self.assertFalse(ranged["sources"][0].get("duplicate", False))
        self.assertEqual(len(project.read(root)["sources"]), 2)
        duplicate = project.inspect(root, [source], sample_start=.5, sample_end=1.5)
        self.assertTrue(duplicate["sources"][0]["duplicate"])
        self.assertTrue(project.validate_document(project.read(root), root)["ok"])
        source.write_bytes(b"changed")
        self.assertFalse(project.validate_document(project.read(root), root)["ok"])

    def test_reference_purpose_is_not_silently_treated_as_story(self):
        root, bundle = self.example()
        document = bundle["animation"]
        document["sources"] = [{"id": "style", "path": "unknown.mp4", "sha256": "x", "purpose": "art", "duration": 10,
            "report": "report.json", "report_sha256": "x"}]
        document["study"] = {"analyst": "fixture", "segments": [], "observations": [{"id": "obs", "source_id": "style",
            "start": 0, "end": 2, "kind": "visible-state", "method": "frames", "certainty": "observed", "notes": "A state", "evidence_ids": ["frame-1"]}]}
        document["outline"]["core_points"][0].update(origin="source", observation_ids=["obs"])
        self.assertFalse(project.validate_document(document)["ok"])

    def test_unknown_fields_and_unversioned_theme_rejected(self):
        root, bundle = self.example()
        bundle["animation"]["automatic_understanding"] = True
        self.assertFalse(validate_plan(bundle)["ok"])
        theme = themes.load()
        theme["characters"][1]["id"] = theme["characters"][0]["id"]
        with self.assertRaises(ConfigError):
            themes.validate(theme)

    def test_keyframes_are_prepared_offline_then_hash_reviewed(self):
        root, bundle = self.example()
        with patch("videocreate.assets.generate_images") as generate:
            result = pipeline.keyframes(root)
            self.assertEqual(result["paid_creates"], 0)
            generate.assert_not_called()
        self.frame(root, bundle)
        updated = load_project(root)
        job = updated["generation-plan"]["jobs"][0]
        self.assertEqual(job["operation"], "image-to-video")
        self.assertTrue(validate_plan(updated, root)["ok"])
        updated["director"]["shots"][0]["framing"] = "Different opening"
        atomic_json(root / "director.json", updated["director"])
        with self.assertRaisesRegex(ConfigError, "no longer matches"):
            pipeline.execution_guard(root, load_project(root), [job["id"]])

    def test_later_shots_are_blocked_before_network_until_pilot_review(self):
        root, bundle = self.example()
        with patch("videocreate.runtime.jobs.client") as client:
            with self.assertRaisesRegex(ConfigError, "pilot"):
                pipeline.execution_guard(root, bundle, ["job-003"])
            client.assert_not_called()

    def test_only_local_video_inputs_invalidate_generation(self):
        root, bundle = self.example(scenario="dialogue", audio_mode="independent-voice")
        job = bundle["generation-plan"]["jobs"][0]
        def fingerprint(b):
            return current_inputs(root, b, job, {})
        initial = fingerprint(bundle)
        bundle["project"]["title"] = "New title"
        bundle["timeline"]["subtitles"][0]["text"] = "Corrected subtitle"
        bundle["timeline"]["audio_tracks"][0]["path"] = "new-voice.wav"
        bundle["director"]["shots"][0]["audio"]["lines"][0]["voice_asset_id"] = "new-voice"
        self.assertEqual(fingerprint(bundle), initial)
        bundle["director"]["shots"][1]["actions"][0]["description"] = "New action elsewhere"
        self.assertEqual(fingerprint(bundle), initial)
        bundle["brief"]["resolution"] = "1080p"
        self.assertNotEqual(fingerprint(bundle), initial)
        bundle["brief"]["resolution"] = "720p"
        initial = fingerprint(bundle)
        reference = root / "identity.png"
        reference.write_bytes(b"reference hash fixture")
        job["references"] = [{"path": reference.name, "role": "opening-frame"}]
        with_reference = fingerprint(bundle)
        self.assertEqual(current_inputs(root / ".." / root.name, bundle, job, {}), with_reference)
        reference.write_bytes(b"different reference bytes")
        self.assertNotEqual(fingerprint(bundle), with_reference)
        job.pop("references")
        self.assertEqual(fingerprint(bundle), initial)
        bundle["director"]["shots"][0]["actions"][0]["description"] = "Changed local action"
        self.assertNotEqual(fingerprint(bundle), initial)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media tools required")
    def test_import_voice_and_render_real_timeline_remains_unreviewed(self):
        root, bundle = self.example(scenario="dialogue", audio_mode="independent-voice")
        voice = self.root / "voice.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-y", str(voice)], check=True)
        before = pipeline.status(root)["jobs"][0]["input_hash"]
        for i in range(1,4):
            speaker = bundle["director"]["shots"][i-1]["audio"]["lines"][0]["speaker"]
            pipeline.import_voice(root, f"shot-{i}", 0, voice, voice_id="fixture-" + speaker, reviewer="synthetic", notes="test tone only")
        self.assertEqual(pipeline.status(root)["jobs"][0]["input_hash"], before)
        with self.assertRaisesRegex(ConfigError, "voice ID"):
            pipeline.import_voice(root, "shot-1", 0, voice, voice_id="different", reviewer="fixture", notes="test")
        state = read_state(root)
        media = root / "clips" / "fixture.mp4"
        media.parent.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=180x320:d=4", "-c:v", "libx264", "-y", str(media)], check=True)
        for job in bundle["generation-plan"]["jobs"]:
            state["jobs"][job["id"]] = {"status": "completed", "artifact": {"path": "clips/fixture.mp4", "sha256": digest(media), "media": {"duration": 4}}}
        save_state(root, state)
        from videocreate.timeline.render import render
        bundle = load_project(root)
        render(root, bundle, state)
        self.assertEqual(receipts.summary(root, bundle)["status"], "review_pending")
        template = pipeline.review(root)["template"]
        with self.assertRaises(ConfigError):
            pipeline.review(root, template)
        template.update(reviewer_id="synthetic-test", method="human-video")
        for c in [*template["points"].values(), template["theme_consistency"]]:
            c.update(status="fail", observation="Fixture has no acting; must fail")
        pipeline.review(root, template)
        self.assertEqual(receipts.summary(root, bundle)["status"], "rejected")
        bundle["timeline"]["subtitles"][0]["text"] = "Changed"
        atomic_json(root / "timeline.json", bundle["timeline"])
        with self.assertRaises(ConfigError):
            pipeline.review(root, template)

    def test_independent_episodes_do_not_require_or_inherit_previous_ending(self):
        root = self.root / "independent"
        series.initialize(root, "Independent stories", 3, mode="independent")
        bible = load_json(root / "series.json")
        bible["episodes"][1]["initial_state"] = {"place": "new-kitchen", "mood": "relaxed"}
        atomic_json(root / "series.json", bible)
        result = series.prepare(root, 2, 12)
        episode = Path(result["project"])
        bundle = load_project(episode)
        self.assertEqual(bundle["story"]["initial_state"], bible["episodes"][1]["initial_state"])
        series.check_episode_context(episode, bundle)
        serial = self.root / "serial"
        series.initialize(serial, "Serial stories", 3)
        with self.assertRaisesRegex(ConfigError, "Previous episode"):
            series.prepare(serial, 2)

    def test_source_story_never_becomes_camera_prompt(self):
        root, bundle = self.example()
        bundle["animation"]["outline"]["premise"] = "REAL_SOURCE_BEDROOM_CAMERA_123"
        for job in bundle["generation-plan"]["jobs"]:
            self.assertNotIn("REAL_SOURCE_BEDROOM_CAMERA_123", compile_job(bundle, job, max_bytes=4096)["prompt"])

    def test_character_references_are_cropped_and_packed_without_losing_cast(self):
        root, bundle = self.example()
        from PIL import Image
        from videocreate.animation.references import register
        image = self.root / "views.png"
        Image.new("RGB", (400, 400), "orange").save(image)
        register(root, "lulu", image, crop=[0,0,100,200])
        register(root, "lumei", image, crop=[100,0,150,250])
        bundle = load_project(root)
        spec = pipeline.keyframe_spec(root, bundle, "shot-1")
        self.assertEqual(len(spec["references"]), 1)
        sheet = root / spec["references"][0]
        with Image.open(sheet) as sheet_image:
            self.assertEqual(sheet_image.size, (1024,640))
        self.assertEqual(len(load_json(sheet.with_suffix(".json"))["inputs"]), 2)
        self.assertEqual(spec, pipeline.keyframe_spec(root, bundle, "shot-1"))
        self.assertIn(bundle["director"]["shots"][0]["opening_frame"], spec["prompt"])
        self.assertTrue(all(c["species"] == "capybara / 水豚" for c in bundle["animation"]["theme"]["characters"]))
        with self.assertRaises(ConfigError):
            register(root, "lulu", image, crop=[390,0,100,100])

    def test_independent_animation_series_pins_theme_and_accepts_different_story_state(self):
        from videocreate.animation import series as animated_series
        author_root, bundle = self.example()
        series_root = self.root / "animated-series"
        animated_series.initialize(series_root, title="Everyday stories", episodes=3)
        result = animated_series.prepare(series_root, 2, author_root / project.AUTHOR)
        episode = Path(result["project"])
        series.check_episode_context(episode, load_project(episode))
        self.assertFalse((series_root / "accepted/episode-001.json").exists())
        wrong_root, _ = self.example("other-cast", theme="cloud-couriers")
        with self.assertRaisesRegex(ConfigError, "theme"):
            animated_series.prepare(series_root, 3, wrong_root / project.AUTHOR)

    def test_optional_local_tts_cache_uses_voice_and_text_without_recreating_video(self):
        from videocreate.animation.voices import synthesize
        from videocreate.cli import legacy_engine
        legacy_engine()
        root, bundle = self.example(scenario="dialogue", audio_mode="independent-voice")
        def write_voice(text, output, **kwargs):
            output.write_bytes(b"local-voice-fixture")
        with patch("audio_client.CosyVoiceClient.synthesize", side_effect=write_voice) as client:
            first = synthesize(root, "shot-1", 0, service_url="http://127.0.0.1:9880", voice_id="fixed-lulu")
            second = synthesize(root, "shot-1", 0, service_url="http://127.0.0.1:9880", voice_id="fixed-lulu")
            self.assertEqual(client.call_count, 1)
            self.assertTrue(second["skipped"])
            third = synthesize(root, "shot-1", 0, service_url="http://127.0.0.1:9880", voice_id="new-lulu")
            self.assertNotEqual(first["path"], third["path"])
            self.assertEqual(third["status"], "listening_required")
            self.assertTrue((root / first["path"]).exists())
        self.assertEqual(read_state(root)["ledger"], [])

    def test_dependency_cannot_bypass_pilot_expansion_gate(self):
        root, bundle = self.example()
        bundle["generation-plan"]["jobs"][0]["depends_on"] = ["job-003"]
        with self.assertRaisesRegex(ConfigError, "pilot"):
            pipeline.execution_guard(root, bundle, ["job-001"])

    def test_unknown_animation_submission_cannot_create_again(self):
        root, bundle = self.example()
        self.frame(root, bundle)
        state = read_state(root)
        state["jobs"]["job-001"] = {"status": "submission_unknown", "attempt_id": "unknown-original", "task_id": ""}
        save_state(root, state)
        with patch("videocreate.runtime.jobs.client") as client:
            with self.assertRaisesRegex(ConfigError, "submission unknown"):
                pipeline.run(root, {}, store_root=self.root, job_ids=["job-001"])
            client.assert_not_called()
        self.assertEqual(read_state(root)["jobs"]["job-001"]["attempt_id"], "unknown-original")
        self.assertEqual(read_state(root)["ledger"], [])

    def test_missing_original_scene_reports_error_instead_of_crashing(self):
        root, bundle = self.example()
        bundle["director"]["scenes"][0]["id"] = "unexpected"
        self.assertFalse(validate_plan(bundle, root)["ok"])


if __name__ == "__main__":
    unittest.main()
