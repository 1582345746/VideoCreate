from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
sys.path.insert(0, str(ROOT / "videocreate/scripts"))

from test_v3_config import config
from videocreate.adapters.video import BindingVideoClient
from videocreate.catalog.bindings import route_bindings
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json
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
        for override in ({"duration": {"minimum": 1, "maximum": 15, "step": 0}}, {"max_reference_images": -1}, {"last_frame": "supported"}, {"made_up": True}):
            value = config()
            value["bindings"]["grok-on-sub2api"]["capability_overrides"] = override
            self.assertTrue(validate_config(value))


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

    def test_bad_shapes_and_path_ids_report_errors(self):
        for mutate in (lambda b: b["director"].update(shots="wrong"), lambda b: b["director"]["shots"][0].update(id="../escape"),
                       lambda b: b["generation-plan"]["jobs"][0].update(unknown_option=True)):
            bundle = smart_car()
            mutate(bundle)
            self.assertFalse(validate_plan(bundle)["ok"])

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
        self.run_job()
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
