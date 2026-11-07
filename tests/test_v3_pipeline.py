from __future__ import annotations

import copy
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
sys.path.insert(0, str(ROOT / "videocreate/scripts"))

from test_v3_config import config
from videocreate.adapters.video import BindingVideoClient
from videocreate.catalog.bindings import route_bindings, validate_request
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.assets import generate_image, reprocess_image
from videocreate.planning.examples import smart_car
from videocreate.planning.project import compile_job, content_hash, save_bundle, validate_plan
from videocreate.runtime import jobs
from videocreate.runtime.budget import reserve, summary
from videocreate.runtime.reconcile import reconcile
from videocreate.runtime.state import read_state, save_state, state_lock
from videocreate.timeline.model import mapping, validate_timeline
from videocreate.review import receipts
from provider_contracts import SubmissionUnknownError
import media_client


class BindingWireTests(unittest.TestCase):
    def test_unified_json_first_frame_contract_and_default_images_field(self):
        for field in ("images", "first_frame"):
            value = config()
            item = value["bindings"]["grok-on-newapi"]
            item["adapter"] = "newapi-json-v1"
            item["adapter_options"] = {"primary_image_field": field}
            self.assertEqual(validate_config(value), [])
            binding = route_bindings(value, item["model"], operation="image-to-video", preferred="grok-on-newapi")[0]
            with tempfile.TemporaryDirectory() as folder:
                image = Path(folder)/"opening.jpg"
                image.write_bytes(b"jpeg-placeholder")
                client = BindingVideoClient(binding, mock.Mock())
                with mock.patch("media_client._prepare_sub2api_reference", side_effect=lambda path, *args: path), \
                     mock.patch("media_client.request_json", return_value={"id": "video-known"}) as post:
                    self.assertEqual(client.create("A mother recognizes a voice", seconds=8, size="auto",
                        resolution="720p", aspect_ratio="9:16", generate_audio=True, primary_reference=image), "video-known")
                body = post.call_args.kwargs["value"]
                self.assertTrue(post.call_args.args[1].endswith("/v1/videos"))
                self.assertEqual(body["seconds"], 8)
                self.assertTrue(body["generate_audio"])
                encoded = body[field] if field == "first_frame" else body[field][0]
                self.assertEqual(base64.b64decode(encoded.split(",",1)[1]), image.read_bytes())
                self.assertNotIn("images" if field == "first_frame" else "first_frame", body)

    def test_first_frame_rejects_extra_guidance_before_network(self):
        value = config()
        item = value["bindings"]["grok-on-newapi"]
        item.update(adapter="newapi-json-v1", adapter_options={"primary_image_field": "first_frame"},
            capability_overrides={"max_reference_images": 2, "max_additional_reference_images": 1})
        binding = route_bindings(value, item["model"], operation="image-to-video", preferred="grok-on-newapi")[0]
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder)/"reference.jpg"
            image.write_bytes(b"jpeg-placeholder")
            with mock.patch("media_client.request_json") as post:
                with self.assertRaisesRegex(ConfigError, "additional guidance"):
                    BindingVideoClient(binding, mock.Mock()).create("A moving subject", seconds=4, size="auto",
                        resolution="720p", primary_reference=image, reference_images=[image])
            post.assert_not_called()

    @staticmethod
    def muse_config():
        value = config()
        value["models"]["muse-video"] = copy.deepcopy(value["models"]["grok-imagine-video-1.5"])
        value["models"]["muse-video"].update(family="muse-video", display_name="Muse Video")
        binding = copy.deepcopy(value["bindings"]["grok-on-sub2api"])
        binding.update(model="muse-video", remote_model="muse-video",
            operations=["text-to-video", "image-to-video"],
            capability_overrides={"duration": {"minimum": 1, "maximum": 10, "step": 1},
                "max_reference_images": 7, "max_additional_reference_images": 6,
                "image_to_video_requires_primary": True})
        value["bindings"]["muse-video-on-sub2api"] = binding
        value["routes"]["muse-video"] = {"policy": "fixed", "preferred_binding": "muse-video-on-sub2api",
            "candidates": ["muse-video-on-sub2api"]}
        return value

    def test_four_combinations_use_exact_model_and_distinct_wire_contract(self):
        value = config()
        for bid in ("grok-on-sub2api", "grok-on-newapi", "seedance-on-sub2api", "seedance-on-newapi"):
            with self.subTest(binding=bid):
                item = value["bindings"][bid]
                binding = route_bindings(value, item["model"], operation="text-to-video", preferred=bid)[0]
                reader_type = media_client.Sub2ApiVideoClient if "sub2api" in bid else media_client.NewApiVideoClient
                client = BindingVideoClient(binding, reader_type(binding.base_url, binding.key, binding.remote_model))
                with mock.patch("media_client.request_json", return_value={"data": {"task_id": "known"}, "request_id": "trace"}) as post:
                    self.assertEqual(client.create("A moving subject", seconds=4, size="auto", resolution="720p", aspect_ratio="9:16", generate_audio=True, references=[]), "known")
                self.assertIn("/v1/videos", post.call_args.args[1])
                self.assertNotIn("/v1/v1", post.call_args.args[1])
                kwargs = post.call_args.kwargs
                if "value" in kwargs:
                    body = kwargs["value"]
                    self.assertEqual(body["model"], item["remote_model"])
                    if "sub2api" in bid:
                        self.assertEqual(body["duration"], 4)
                        self.assertNotIn("generate_audio", body)
                    else:
                        self.assertEqual(body["seconds"], 4)
                        self.assertTrue(body["generate_audio"])
                else:
                    self.assertIn(item["remote_model"].encode(), kwargs["body"])
                self.assertNotIn("test-only-value", json.dumps(client.last_submission))

    def test_trace_only_is_unknown_unless_this_protocol_declares_it_as_task(self):
        value = config()
        bid = "grok-on-sub2api"
        for allowed in (False, True):
            value["bindings"][bid]["adapter_options"] = {"task_id_fields": ["request_id"]} if allowed else {}
            binding = route_bindings(value, "grok-imagine-video-1.5", operation="text-to-video")[0]
            client = BindingVideoClient(binding, mock.Mock())
            with mock.patch("media_client.request_json", return_value={"request_id": "trace-only"}) as post:
                args = dict(seconds=4, size="auto", resolution="720p", aspect_ratio="9:16", references=[])
                if allowed:
                    self.assertEqual(client.create("Current action", **args), "trace-only")
                else:
                    with self.assertRaises(SubmissionUnknownError):
                        client.create("Current action", **args)
                post.assert_called_once()

    def test_capability_violation_sends_zero_requests(self):
        value = config()
        value["bindings"]["grok-on-sub2api"]["capability_overrides"] = {"conditions": [{"when": {"resolution": "720p"}, "max_seconds": 3}]}
        binding = route_bindings(value, "grok-imagine-video-1.5", operation="text-to-video")[0]
        with mock.patch("media_client.request_json") as post:
            with self.assertRaises(ConfigError):
                BindingVideoClient(binding, mock.Mock()).create("Current action", seconds=4, size="auto", resolution="720p", references=[])
        post.assert_not_called()

    def test_invalid_capability_types_and_zero_step_fail_configuration(self):
        for override in ({"duration": {"minimum": 1, "maximum": 15, "step": 0}}, {"max_reference_images": -1},
                         {"max_additional_reference_images": -1}, {"last_frame": "supported"}, {"made_up": True}):
            value = config()
            value["bindings"]["grok-on-sub2api"]["capability_overrides"] = override
            self.assertTrue(validate_config(value))

    def test_muse_primary_and_six_guidance_images_use_distinct_sub2api_fields(self):
        value = self.muse_config()
        binding = route_bindings(value, "muse-video", operation="image-to-video")[0]
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index in range(7):
                path = Path(folder) / f"reference-{index}.jpg"
                path.write_bytes(f"jpeg-placeholder-{index}".encode())
                paths.append(path)
            client = BindingVideoClient(binding, mock.Mock())
            with mock.patch("media_client._prepare_sub2api_reference", side_effect=lambda path, *args: path), \
                 mock.patch("media_client.request_json", return_value={"data": {"task_id": "known"}}) as post:
                task_id = client.create("A quiet spring station portrait", seconds=10, size="auto",
                    resolution="720p", aspect_ratio="9:16", primary_reference=paths[0],
                    reference_images=paths[1:])
            self.assertEqual(task_id, "known")
            body = post.call_args.kwargs["value"]
            self.assertEqual(body["duration"], 10)
            self.assertTrue(body["image"]["url"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(len(body["reference_images"]), 6)
            self.assertTrue(all(item["url"].startswith("data:image/jpeg;base64,") for item in body["reference_images"]))

    def test_muse_accepts_one_primary_and_rejects_missing_primary_or_eight_total(self):
        value = self.muse_config()
        binding = route_bindings(value, "muse-video", operation="image-to-video")[0]
        report = validate_request(binding, {"operation": "image-to-video", "prompt": "move",
            "seconds": 10, "resolution": "1080p", "aspect_ratio": "9:16",
            "primary_reference": object(), "reference_images": []})
        self.assertTrue(report["ok"], report["errors"])
        missing_primary = validate_request(binding, {"operation": "image-to-video", "prompt": "move",
            "seconds": 10, "resolution": "480p", "aspect_ratio": "9:16",
            "primary_reference": None, "reference_images": [object()]})
        self.assertTrue(any("primary image" in error for error in missing_primary["errors"]))
        too_many = validate_request(binding, {"operation": "image-to-video", "prompt": "move",
            "seconds": 10, "resolution": "720p", "aspect_ratio": "9:16",
            "primary_reference": object(), "reference_images": [object()] * 7})
        self.assertTrue(any("Too many reference images" in error for error in too_many["errors"]))

    def test_muse_additional_images_are_rejected_before_submission_when_over_limit(self):
        value = self.muse_config()
        binding = route_bindings(value, "muse-video", operation="image-to-video")[0]
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index in range(8):
                path = Path(folder) / f"reference-{index}.jpg"
                path.write_bytes(b"jpeg-placeholder")
                paths.append(path)
            client = BindingVideoClient(binding, mock.Mock())
            with mock.patch("media_client._prepare_sub2api_reference", side_effect=lambda path, *args: path), \
                 mock.patch("media_client.request_json") as post:
                with self.assertRaisesRegex(ConfigError, "Too many reference images"):
                    client.create("A quiet spring station portrait", seconds=10, size="auto",
                        resolution="720p", aspect_ratio="9:16", primary_reference=paths[0],
                        reference_images=paths[1:])
            post.assert_not_called()

    def test_result_download_resolves_relative_paths_and_keeps_key_on_gateway(self):
        from vc_common import APIError
        for reader_type in (media_client.Sub2ApiVideoClient, media_client.NewApiVideoClient):
            for result_url, expected_url, expected_key in (
                ("/media/result.mp4", "https://gateway.test/media/result.mp4", "gateway-key"),
                ("https://cdn.test/result.mp4", "https://cdn.test/result.mp4", ""),
                ("//cdn.test/result.mp4", "https://cdn.test/result.mp4", ""),
            ):
                with self.subTest(reader=reader_type.__name__, result=result_url), tempfile.TemporaryDirectory() as folder:
                    reader = reader_type("https://gateway.test/v1", "gateway-key", "configured-model")
                    with mock.patch("media_client.download_file", side_effect=[APIError(404, "not available"), None]) as download, \
                         mock.patch("media_client.assert_mp4"):
                        reader.download("task-known", {"video": {"url": result_url}}, Path(folder)/"source.mp4")
                    self.assertEqual(download.call_args.args[0], expected_url)
                    self.assertEqual(download.call_args.kwargs.get("key"), expected_key)


class ImageResponseTests(unittest.TestCase):
    def test_multiple_image_edit_references_do_not_inherit_video_guidance_limit(self):
        from videocreate.adapters.image import BindingImageClient
        value = config()
        bid = next(bid for bid, item in value["bindings"].items() if item["adapter"] == "openai-images-v1")
        value["bindings"][bid]["capability_overrides"] = {"max_reference_images": 2}
        binding = route_bindings(value, value["bindings"][bid]["model"], operation="image-edit", preferred=bid)[0]
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("costume.png", "composition.png", "extra.png")]
            for path in paths:
                path.write_bytes(b"image-placeholder")
            client = BindingImageClient(binding)
            with mock.patch("media_client.request_json", return_value={"data": []}) as post:
                client.create_payload("Keep costume from first, composition from second", paths[:2], size="1536x1024", quality="high")
            self.assertEqual(post.call_args.kwargs["body"].count(b'filename="'), 2)
            with mock.patch("media_client.request_json") as post:
                with self.assertRaisesRegex(ConfigError, "Too many reference images"):
                    client.create_payload("Too many inputs", paths, size="1536x1024", quality="high")
            post.assert_not_called()

    def test_b64_json_accepts_data_url_and_wrapped_whitespace(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==")
        encoded = base64.b64encode(png).decode("ascii")
        self.assertEqual(media_client._extract_image({"data": [{"b64_json": "data:image/png;base64," + encoded}]}), png)
        self.assertEqual(media_client._extract_image({"data": [{"b64_json": encoded[:12] + "\n" + encoded[12:]}]}), png)

    def test_decode_failure_preserves_provider_response_for_recovery(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        save_bundle(root, smart_car())
        reference = root / "lead.png"
        reference.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="))
        response = {"request_id": "diagnostic-trace", "data": [{"b64_json": "not-valid-base64"}]}
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload", return_value=response):
            with self.assertRaisesRegex(ConfigError, "invalid base64"):
                generate_image(root, config(), store_root=root, job_id="character-sheet-001",
                    prompt="A three-view character reference sheet", references=[reference],
                    size="1536x1024", quality="high")
        state = read_state(root)
        record = state["jobs"]["character-sheet-001"]
        self.assertEqual(record["status"], "output_invalid")
        saved = root / "jobs" / "character-sheet-001" / record["attempt_id"] / "provider-response.json"
        self.assertTrue(saved.is_file())
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), response)
        self.assertEqual(record["provider_response"], saved.relative_to(root).as_posix())
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload") as create:
            self.assertFalse(reprocess_image(root, "character-sheet-001")["ok"])
            create.assert_not_called()
        png = reference.read_bytes()
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload",
                return_value={"data": [{"b64_json": base64.b64encode(png).decode()}]}) as create:
            result = generate_image(root, config(), store_root=root, job_id="character-sheet-001",
                prompt="A three-view character reference sheet", references=[reference], size="1536x1024",
                quality="high", retry="content", reason="Saved upstream image response contains corrupt base64")
            self.assertTrue(result["ok"])
            create.assert_called_once()
        current = read_state(root)["jobs"]["character-sheet-001"]
        self.assertEqual(len(current["history"]), 1)
        self.assertEqual(current["history"][0]["status"], "output_invalid")


class PlanningTests(unittest.TestCase):
    def test_example_exposes_causality_and_does_not_certify_content(self):
        result = validate_plan(smart_car())
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["content"], "unverified")
        self.assertEqual(len(result["coverage"]), 10)
        self.assertEqual(mapping(smart_car()["timeline"])["duration"], 30)

    def test_overloaded_driving_shot_and_fake_reaction_are_rejected(self):
        bundle = smart_car()
        shot = bundle["director"]["shots"][5]
        shot["role"] = "reaction"
        shot["actions"] = [{"kind": "physical", "description": action} for action in ("drive", "detour", "grain follows", "talk", "arrive")]
        shot["planned_seconds"] = 5
        errors = validate_plan(bundle)["errors"]
        self.assertTrue(any("action load" in e for e in errors))
        self.assertTrue(any("reaction tag" in e for e in errors))

    def test_product_without_visible_result_and_missing_coverage_are_rejected(self):
        bundle = smart_car()
        bundle["brief"]["product"]["visible_result"] = "missing"
        bundle["director"]["shots"][4]["visible_evidence"] = []
        errors = validate_plan(bundle)["errors"]
        self.assertTrue(any("Product choice/result" in e for e in errors))
        self.assertTrue(any("missing visual coverage" in e for e in errors))

    def test_slow_cinema_has_no_forced_speech_or_fast_cut_limit(self):
        bundle = smart_car()
        bundle["brief"]["pace_profile"] = "slow-cinema"
        for shot in bundle["director"]["shots"]:
            shot["planned_seconds"] = 12
            shot["audio"] = {"mode": "ambience"}
        self.assertTrue(validate_plan(bundle)["ok"])

    def test_prompt_excludes_later_cast_and_ending_and_never_silently_compresses(self):
        bundle = smart_car()
        bundle["story"]["payoff"] = "FUTURE-ENDING-SECRET"
        bundle["director"]["assets"].append({"id": "future", "kind": "character", "description": "FUTURE-CAST-SECRET"})
        compiled = compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=4096)
        self.assertNotIn("FUTURE", compiled["prompt"])
        self.assertNotIn("no modern objects", compiled["prompt"])
        self.assertEqual(compiled["dropped_essential_fields"], [])
        with self.assertRaises(ConfigError):
            compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=100)

    def test_first_person_camera_gets_hard_viewpoint_continuity_lock(self):
        bundle = smart_car()
        shot = bundle["director"]["shots"][0]
        shot["camera_position"] = "First-person camera at chest level"
        compiled = compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=4096)
        self.assertIn("POV continuity lock", compiled["prompt"])
        self.assertIn("never cut to third-person", compiled["prompt"])
        self.assertIn(shot["id"] + ".pov_continuity_lock", compiled["retained"])
        for view in ("POV camera", "第一人称，眼部高度"):
            shot["camera_position"] = view
            self.assertIn("POV continuity lock", compile_job(bundle,
                bundle["generation-plan"]["jobs"][0], max_bytes=4096)["prompt"])
        shot["camera_position"] = "Eye-level observer camera above an impoverished village"
        external = compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=4096)
        self.assertNotIn("POV continuity lock", external["prompt"])

    def test_dialogue_compilation_preserves_location_sound_and_voice_direction(self):
        bundle = smart_car()
        shot = bundle["director"]["shots"][0]
        shot["audio"].update(mode="offscreen", ambience="River water, soft cloth; one calm Mandarin voice, no music.",
            lines=[{"speaker": "narrator", "text": "Hold the line.", "on_screen": False, "start": 1, "end": 3}])
        compiled = compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=4096)
        self.assertIn(shot["audio"]["ambience"], compiled["prompt"])
        self.assertIn(shot["audio"]["lines"][0]["text"], compiled["prompt"])

    def test_bad_shapes_and_path_ids_report_errors(self):
        for mutate in (lambda b: b["director"].update(shots="wrong"), lambda b: b["director"]["shots"][0].update(id="../escape"),
                       lambda b: b["generation-plan"]["jobs"][0].update(unknown_option=True)):
            bundle = smart_car()
            mutate(bundle)
            self.assertFalse(validate_plan(bundle)["ok"])

    def test_image_to_video_plan_allows_guidance_roles_but_requires_one_primary(self):
        bundle = smart_car()
        job = bundle["generation-plan"]["jobs"][0]
        job.update(operation="image-to-video", references=[
            {"path": "opening.jpg", "sha256": "a" * 64, "role": "opening-frame"},
            {"path": "identity.jpg", "sha256": "b" * 64, "role": "identity"},
            {"path": "station.jpg", "sha256": "c" * 64, "role": "scene"},
        ])
        self.assertTrue(validate_plan(bundle)["ok"], validate_plan(bundle)["errors"])
        job["references"].pop(0)
        self.assertTrue(any("exactly one opening-frame primary" in error for error in validate_plan(bundle)["errors"]))

    def test_cycle_and_state_mismatch_block_plan(self):
        bundle = smart_car()
        bundle["generation-plan"]["jobs"][0]["depends_on"] = ["job-002"]
        bundle["generation-plan"]["jobs"][1]["depends_on"] = ["job-001"]
        bundle["story"]["beats"][1]["requires"]["grain"] = "camp"
        errors = validate_plan(bundle)["errors"]
        self.assertTrue(any("cyclic" in e for e in errors))
        self.assertTrue(any("input state" in e for e in errors))

    def test_arbitrary_transition_reason_cannot_explain_spatial_change(self):
        bundle = smart_car()
        bundle["director"]["shots"][0]["exit_state"] = {"kongming": "outside"}
        bundle["director"]["shots"][1]["entry_state"] = {"kongming": "inside-car"}
        self.assertTrue(any("spatial state" in e for e in validate_plan(bundle)["errors"]))

    def test_half_speed_maps_subtitles_but_keeps_audio_track_at_real_time(self):
        timeline = smart_car()["timeline"]
        timeline["segments"][0].update(rate=0.5, source_audio="mute")
        timeline["subtitles"] = [{"segment_id": "segment-001", "source_start": 0.5, "source_end": 1, "text": "Mapped"}]
        timeline["audio_tracks"] = [{"id": "j-cut", "kind": "dialogue", "clip_id": "clip-002", "source_in": 0, "source_out": 2, "timeline_start": 4.5}]
        result = mapping(timeline)
        self.assertEqual(result["subtitles"][0]["start"], 0.5)
        self.assertEqual(result["subtitles"][0]["end"], 1.5)
        self.assertEqual(result["audio_tracks"][0]["timeline_start"], 4.5)
        self.assertEqual(result["duration"], 32.5)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = smart_car()
        save_bundle(self.root, self.bundle)
        self.config = config()
        self.calls = 0
        self.poll_failure = False
        outer = self
        class FakeClient:
            def __init__(self, binding):
                self.binding = binding
                self.last_submission = {}
            def prepare(self, prompt, **kwargs):
                return {"binding_snapshot": self.binding.snapshot(), "prompt": prompt}
            def create(self, prompt, **kwargs):
                outer.calls += 1
                state = read_state(outer.root)
                assert state["jobs"]["job-001"]["status"] == "submitting"
                assert state["ledger"][-1]["status"] == "reserved"
                return "task-known"
            def poll(self, task_id, *, timeout_seconds, on_status):
                if outer.poll_failure:
                    raise TimeoutError("read timeout")
                return {"status": "completed"}
            def query(self, task_id):
                return "queued", {}
            def download(self, task_id, payload, destination):
                destination.write_bytes(b"original source bytes")
        self.factory = mock.patch("videocreate.runtime.jobs.client", side_effect=FakeClient)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.probe = mock.patch("videocreate.timeline.render.probe", return_value={"duration": 6, "fps": "24/1"})
        self.probe.start()
        self.addCleanup(self.probe.stop)

    def run_job(self, **kwargs):
        return jobs.generate(self.root, self.config, store_root=self.root, job_ids=["job-001"], **kwargs)

    def test_persist_before_create_and_skip_after_subtitle_change(self):
        self.run_job()
        timeline = self.bundle["timeline"]
        timeline["subtitles"] = [{"start": 0, "end": 1, "text": "Only subtitles changed"}]
        atomic_json(self.root / "timeline.json", timeline)
        self.run_job()
        self.assertEqual(self.calls, 1)
        self.assertEqual(summary(read_state(self.root))["unknown_price_requests"], 1)

    def test_completed_payload_survives_download_failure_and_known_task_resumes(self):
        with mock.patch("videocreate.runtime.jobs.client") as factory:
            fake = factory.return_value
            fake.prepare.return_value = {}
            fake.last_submission = {}
            fake.create.return_value = "task-known"
            payload = {"status": "completed", "video": {"url": "/media/result.mp4"}}
            fake.poll.return_value = payload
            fake.download.side_effect = TimeoutError("download timeout")
            with self.assertRaises(ConfigError):
                self.run_job()
            record = read_state(self.root)["jobs"]["job-001"]
            self.assertEqual(record["status"], "read_pending")
            saved = self.root/"jobs/job-001"/record["attempt_id"]/"provider-result.json"
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), payload)
            self.assertIn("provider_completed_at", record)
            fake.poll.side_effect = AssertionError("Resume the saved completed result without querying again")
            def resumed_download(task_id, result, destination):
                self.assertEqual(read_state(self.root)["jobs"]["job-001"]["status"], "downloading")
                destination.write_bytes(b"source")
            fake.download.side_effect = resumed_download
            self.run_job(retry="network", reason="resume known task download")
            fake.create.assert_called_once()
            fake.poll.assert_called_once()

    def test_corrupt_saved_result_recovers_by_reading_known_task_without_recreating(self):
        with mock.patch("videocreate.runtime.jobs.client") as factory:
            fake = factory.return_value
            fake.prepare.return_value = {}
            fake.last_submission = {}
            fake.create.return_value = "task-known"
            fake.poll.return_value = {"status": "completed"}
            fake.download.side_effect = TimeoutError("download timeout")
            with self.assertRaises(ConfigError):
                self.run_job()
            record = read_state(self.root)["jobs"]["job-001"]
            saved = self.root / "jobs" / "job-001" / record["attempt_id"] / "provider-result.json"
            saved.write_bytes(b"\xff\xfe")
            fake.download.side_effect = lambda task_id, payload, path: path.write_bytes(b"source")
            result = self.run_job(retry="network", reason="Recover damaged local result from the known task")
            self.assertTrue(result["ok"])
            fake.create.assert_called_once()
            self.assertEqual(fake.poll.call_count, 2)

    def test_known_task_read_timeout_pins_original_endpoint_after_defaults_change(self):
        self.poll_failure = True
        with self.assertRaises(ConfigError):
            self.run_job()
        self.assertEqual(read_state(self.root)["jobs"]["job-001"]["task_id"], "task-known")
        self.config["upstreams"]["primary-sub2api"]["base_url"] = "https://new.invalid"
        self.config["defaults"]["video_model"] = "seedance-2.0-mini-720p"
        self.poll_failure = False
        with mock.patch("videocreate.runtime.jobs.pinned_binding", wraps=jobs.pinned_binding) as pin:
            self.run_job(retry="network", reason="retry the read")
        self.assertEqual(self.calls, 1)
        self.assertEqual(pin.call_args.args[1]["base_url"], "https://provider.example.test/v1")

    def test_create_timeout_is_held_and_cannot_automatically_retry(self):
        with mock.patch("videocreate.runtime.jobs.client") as factory:
            fake = factory.return_value
            fake.prepare.return_value = {}
            fake.last_submission = {"trace_ids": {"request_id": "trace"}}
            fake.create.side_effect = TimeoutError("create timeout")
            with self.assertRaises(ConfigError):
                self.run_job()
            fake.create.assert_called_once()
            with self.assertRaisesRegex(ConfigError, "submission unknown"):
                self.run_job(retry="network", reason="查不到")
            fake.create.assert_called_once()
        self.assertEqual(read_state(self.root)["jobs"]["job-001"]["status"], "submission_unknown")

    def test_unknown_price_never_counts_as_zero_under_hard_limit(self):
        self.config["budget"]["max_total"] = 5
        with self.assertRaisesRegex(ConfigError, "Price is unknown"):
            self.run_job()
        self.assertEqual(self.calls, 0)
        self.assertFalse(read_state(self.root)["ledger"])

    def test_replan_is_explicit_and_preserves_history(self):
        self.run_job()
        self.bundle["director"]["shots"][0]["actions"][0]["description"] = "New current action"
        atomic_json(self.root / "director.json", self.bundle["director"])
        with self.assertRaisesRegex(ConfigError, "inputs changed"):
            self.run_job()
        self.run_job(retry="replan", reason="Local action redesign")
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(read_state(self.root)["jobs"]["job-001"]["history"]), 1)

    def test_concurrent_budget_reservations_cannot_exceed_limit(self):
        def attempt(i):
            try:
                with state_lock(self.root):
                    state = read_state(self.root)
                    reserve(state, {"max_video_requests": 3, "max_total": 1, "currency": "CNY"}, attempt_id=str(i), job_id=str(i), kind="video", estimated=0.4)
                    save_state(self.root, state)
                return True
            except ConfigError:
                return False
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(results), 2)
        self.assertEqual(len(read_state(self.root)["ledger"]), 2)

    def test_video_jobs_submit_and_poll_concurrently_under_configured_limits(self):
        self.config["execution"]["max_concurrent_video_tasks"] = 3
        self.config["upstreams"]["primary-sub2api"]["max_concurrent_submissions"] = 3
        guard = threading.Lock()
        create_barrier = threading.Barrier(3)
        poll_barrier = threading.Barrier(3)
        active_create = active_poll = peak_create = peak_poll = create_calls = poll_calls = 0
        class ConcurrentClient:
            def __init__(this, binding):
                this.binding, this.last_submission = binding, {}
            def prepare(this, prompt, **kwargs):
                return {"prompt": prompt}
            def create(this, prompt, **kwargs):
                nonlocal active_create, peak_create, create_calls
                with guard:
                    active_create += 1
                    peak_create = max(peak_create, active_create)
                    create_calls += 1
                    wait_for_initial_group = create_calls <= 3
                if wait_for_initial_group:
                    create_barrier.wait(timeout=15)
                with guard:
                    active_create -= 1
                return "known-" + str(uuid.uuid4())
            def poll(this, task_id, *, timeout_seconds, on_status):
                nonlocal active_poll, peak_poll, poll_calls
                with guard:
                    active_poll += 1
                    peak_poll = max(peak_poll, active_poll)
                    poll_calls += 1
                    wait_for_initial_group = poll_calls <= 3
                if wait_for_initial_group:
                    poll_barrier.wait(timeout=15)
                with guard:
                    active_poll -= 1
                return {"status": "completed"}
            def query(this, task_id):
                return "queued", {}
            def download(this, task_id, payload, destination):
                destination.write_bytes(b"source-" + task_id.encode())
        with mock.patch("videocreate.runtime.jobs.client", side_effect=ConcurrentClient):
            result = jobs.generate(self.root, self.config, store_root=self.root, poll_timeout=10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["jobs"]), 10)
        self.assertEqual(peak_create, 3)
        self.assertEqual(peak_poll, 3)

    def test_dependency_waits_for_predecessor_and_blocks_after_ambiguous_failure(self):
        self.bundle["generation-plan"]["jobs"][1]["depends_on"] = ["job-001"]
        atomic_json(self.root / "generation-plan.json", self.bundle["generation-plan"])
        self.config["execution"]["max_concurrent_video_tasks"] = 3
        self.config["upstreams"]["primary-sub2api"]["max_concurrent_submissions"] = 3
        created = []
        first_prompt = compile_job(self.bundle, self.bundle["generation-plan"]["jobs"][0],
            max_bytes=4096)["prompt"]
        class DependencyClient:
            def __init__(this, binding):
                this.binding, this.last_submission = binding, {}
            def prepare(this, prompt, **kwargs):
                return {"prompt": prompt}
            def create(this, prompt, **kwargs):
                created.append(prompt)
                if prompt == first_prompt:
                    raise TimeoutError("ambiguous first create")
                return "task"
            def poll(this, task_id, **kwargs):
                return {"status": "completed"}
            def download(this, task_id, payload, destination):
                destination.write_bytes(b"dependent-source")
        with mock.patch("videocreate.runtime.jobs.client", side_effect=DependencyClient):
            result = jobs.generate(self.root, self.config, store_root=self.root, poll_timeout=1)
        statuses = {item["job_id"]: item["status"] for item in result["jobs"]}
        self.assertEqual(statuses["job-001"], "error")
        self.assertEqual(statuses["job-002"], "blocked")
        self.assertEqual(read_state(self.root)["jobs"].get("job-002", {}).get("task_id", ""), "")

    def test_content_retry_does_not_recreate_completed_dependency(self):
        self.bundle["generation-plan"]["jobs"][1]["depends_on"] = ["job-001"]
        atomic_json(self.root / "generation-plan.json", self.bundle["generation-plan"])
        with mock.patch("videocreate.runtime.jobs.client") as factory:
            factory.return_value.prepare.return_value = {}
            factory.return_value.last_submission = {}
            factory.return_value.create.return_value = "task-known"
            factory.return_value.poll.return_value = {"status": "completed"}
            factory.return_value.download.side_effect = lambda task, payload, path: path.write_bytes(b"source")
            jobs.generate(self.root, self.config, store_root=self.root, job_ids=["job-002"], poll_timeout=10)
            dependency_attempt = read_state(self.root)["jobs"]["job-001"]["attempt_id"]
            result = jobs.generate(self.root, self.config, store_root=self.root, job_ids=["job-002"],
                poll_timeout=10, retry="content", reason="Retry the selected shot after review")
            self.assertEqual(factory.return_value.create.call_count, 3)
        self.assertTrue(result["ok"])
        self.assertEqual(read_state(self.root)["jobs"]["job-001"]["attempt_id"], dependency_attempt)

    def test_configured_automatic_fallback_requires_protocol_rejection_evidence(self):
        from vc_common import APIError
        original = jobs.client
        seen = []
        factory = self.factory
        factory.stop()
        self.config["routes"]["grok-imagine-video-1.5"]["policy"] = "automatic-same-model"
        self.config["bindings"]["grok-on-sub2api"]["adapter_options"] = {"confirmed_rejection_http_statuses": [429]}
        # Reuse our offline successful client once the newapi binding is selected.
        class FallbackClient:
            def __init__(this, binding):
                this.binding, this.last_submission = binding, {}
            def prepare(this, prompt, **kwargs):
                return {}
            def create(this, prompt, **kwargs):
                seen.append(this.binding.id)
                if this.binding.id == "grok-on-sub2api":
                    raise APIError(429, "confirmed pre-submit rejection")
                return "fallback-task"
            def poll(this, task_id, **kwargs):
                return {"status": "completed"}
            def download(this, task_id, payload, destination):
                destination.write_bytes(b"fallback-source")
        with mock.patch("videocreate.runtime.jobs.client", side_effect=FallbackClient):
            self.run_job()
        self.assertEqual(seen, ["grok-on-sub2api", "grok-on-newapi"])
        self.assertEqual(len(read_state(self.root)["ledger"]), 2)
        self.assertEqual(len(read_state(self.root)["jobs"]["job-001"]["history"]), 1)

    def test_incompatible_primary_is_skipped_before_any_create(self):
        self.config["routes"]["grok-imagine-video-1.5"]["policy"] = "automatic-same-model"
        self.config["bindings"]["grok-on-sub2api"]["capability_overrides"] = {
            "conditions": [{"when": {"resolution": "720p"}, "max_seconds": 1}]}
        self.run_job()
        state = read_state(self.root)
        self.assertEqual(self.calls, 1)
        self.assertEqual(state["jobs"]["job-001"]["binding_snapshot"]["binding_id"], "grok-on-newapi")
        self.assertEqual(state["jobs"]["job-001"]["selection"]["decisions"][0]["eligible"], False)
        self.assertEqual(len(state["ledger"]), 1)

    def test_resolution_change_requires_local_replan(self):
        self.run_job()
        self.bundle["brief"]["resolution"] = "1080p"
        atomic_json(self.root / "brief.json", self.bundle["brief"])
        with self.assertRaisesRegex(ConfigError, "inputs changed"):
            self.run_job()

    def test_explicit_job_binding_remains_fixed_under_an_automatic_route(self):
        from vc_common import APIError
        self.config["routes"]["grok-imagine-video-1.5"]["policy"] = "automatic-same-model"
        self.config["bindings"]["grok-on-sub2api"]["adapter_options"] = {"confirmed_rejection_http_statuses": [429]}
        self.bundle["generation-plan"]["jobs"][0]["binding_id"] = "grok-on-sub2api"
        atomic_json(self.root / "generation-plan.json", self.bundle["generation-plan"])
        with mock.patch("videocreate.runtime.jobs.client") as factory:
            factory.return_value.prepare.return_value = {}
            factory.return_value.last_submission = {}
            factory.return_value.create.side_effect = APIError(429, "confirmed rejection")
            with self.assertRaises(ConfigError):
                self.run_job()
            self.assertEqual(factory.call_count, 1)
        self.assertEqual(len(read_state(self.root)["ledger"]), 1)

    def test_replaced_reference_requires_local_replan_even_when_filename_is_unchanged(self):
        path = self.root / "opening.png"
        path.write_bytes(b"first reference")
        job = self.bundle["generation-plan"]["jobs"][0]
        job.update(operation="image-to-video", references=[{"path": path.name, "role": "opening-frame", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}])
        atomic_json(self.root / "generation-plan.json", self.bundle["generation-plan"])
        (self.root / "alias-parent").mkdir()
        jobs.generate(self.root / "alias-parent" / "..", self.config,
            store_root=self.root, job_ids=["job-001"])
        path.write_bytes(b"changed reference")
        job["references"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        atomic_json(self.root / "generation-plan.json", self.bundle["generation-plan"])
        with self.assertRaisesRegex(ConfigError, "inputs changed"):
            self.run_job()
        self.assertEqual(self.calls, 1)

    def test_reconciliation_does_not_treat_absence_as_non_reception(self):
        self.test_create_timeout_is_held_and_cannot_automatically_retry()
        record = read_state(self.root)["jobs"]["job-001"]
        evidence = self.root / "upstream-evidence.txt"
        evidence.write_text("查不到", encoding="utf-8")
        receipt = {"job_id": "job-001", "attempt_id": record["attempt_id"], "binding_fingerprint": record["binding_snapshot"]["fingerprint"],
            "outcome": "not-received", "reviewer_id": "human", "method": "upstream-audit",
            "evidence": [{"path": evidence.name, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]}
        with self.assertRaisesRegex(ConfigError, "inconclusive"):
            reconcile(self.root, self.config, receipt, store_root=self.root)
        self.assertEqual(read_state(self.root)["jobs"]["job-001"]["status"], "submission_unknown")


if __name__ == "__main__":
    unittest.main()
