from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_v3_config import ROOT, config
from videocreate.adapters.image import BindingImageClient
from videocreate.assets import generate_image, generate_images, recover_image
from videocreate.catalog.bindings import configured_binding
from videocreate.catalog.evidence import record, status
from videocreate.config.effective import effective
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json, config_root
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.planning.project import validate_plan, compile_job
from videocreate.runtime.budget import reserve
from videocreate.runtime.limits import submission_slot
from videocreate.runtime.settlement import settle
from videocreate.runtime.state import read_state, save_state
from videocreate.review.receipts import inbox, review_image


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = config()

    def evidence(self, name="evidence.json", data=b"observed upstream receipt"):
        path = self.root / name
        path.write_bytes(data)
        return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}

    def test_config_explains_project_and_explicit_binding_precedence_without_keys(self):
        bundle = smart_car()
        bundle["brief"]["resolution"] = "1080p"
        bundle["generation-plan"]["jobs"][0]["binding_id"] = "grok-on-newapi"
        with mock.patch("videocreate.config.storage.resolve_key", side_effect=AssertionError("secret was read")):
            result = effective(self.config, self.root / "config.json", bundle=bundle, job_id="job-001")
            self.assertEqual(result["values"]["binding_id"], "grok-on-newapi")
            self.assertEqual(result["values"]["resolution"], "1080p")
            self.assertEqual(result["sources"]["resolution"], "project.brief.resolution")
            explicit = effective(self.config, self.root / "config.json", bundle=bundle, job_id="job-001", binding_id="grok-on-sub2api")
            self.assertEqual(explicit["values"]["binding_id"], "grok-on-sub2api")
        self.assertNotIn("test-only-value", json.dumps(result))

    def test_new_user_is_setup_required_and_xdg_path_needs_no_dpapi(self):
        for binding in self.config["bindings"].values():
            binding["enabled"] = False
        self.assertTrue(any("setup_required" in e for e in validate_config(self.config, ready=True)))
        with mock.patch("videocreate.config.storage.os.name", "posix"), mock.patch("videocreate.config.storage.Path", type(self.root)), mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)}, clear=True):
            self.assertEqual(str(config_root()), str(self.root / "VideoCreate"))

    def test_catalog_receipt_cannot_certify_smoke_or_quality_and_changed_bytes_expire(self):
        binding = configured_binding(self.config, "grok-on-sub2api")
        evidence = self.evidence()
        receipt = {"binding_fingerprint": binding.snapshot()["fingerprint"], "stage": "catalog", "result": "pass",
            "operation": "text-to-video", "reviewer_id": "observer", "method": "models-list",
            "checks": {"exact_name": True}, "evidence": [evidence]}
        record(self.root, binding, receipt)
        stages = status(self.root, binding)["stages"]
        self.assertEqual(stages["catalog"]["status"], "reported_pass")
        self.assertEqual(stages["smoke"]["status"], "unverified")
        self.assertEqual(stages["quality"]["status"], "unverified")
        receipt.update(stage="smoke")
        with self.assertRaisesRegex(ConfigError, "attempt_id"):
            record(self.root, binding, receipt)
        Path(evidence["path"]).write_bytes(b"changed")
        result = status(self.root, binding)
        self.assertEqual(result["stages"]["catalog"]["status"], "unverified")
        self.assertTrue(result["stale_receipts"])

    def test_billing_settlement_matches_attempt_and_prevents_double_adjustment(self):
        state = read_state(self.root)
        reserve(state, {"currency": "CNY"}, attempt_id="a1", job_id="j1", kind="video", estimated=3)
        save_state(self.root, state)
        receipt = {"attempt_id": "a1", "job_id": "j1", "currency": "CNY", "amount": 2,
            "reviewer_id": "billing-observer", "upstream_record_id": "invoice-1", "evidence": [self.evidence()]}
        settle(self.root, receipt)
        self.assertEqual(read_state(self.root)["ledger"][0]["actual"], 2)
        self.assertTrue(settle(self.root, receipt)["unchanged"])
        with self.assertRaises(ConfigError):
            settle(self.root, {**receipt, "amount": 0})

    def test_image_wire_is_independent_and_unknown_output_recovers_without_create(self):
        import base64
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5S8AAAAASUVORK5CYII=")
        save_bundle(self.root, smart_car())
        self.config["defaults"]["video_model"] = "seedance-2.0-mini-720p"
        self.config["upstreams"]["image-service"]["base_url"] = "https://images.example.test/v1"
        binding = configured_binding(self.config, "image-primary", key="image-only-credential")
        with mock.patch("media_client.request_json", return_value={"data": [{"b64_json": base64.b64encode(png).decode()}]}) as post:
            result = BindingImageClient(binding).create("Opening composition", [], size="1024x1024", quality="auto")
        self.assertEqual(result, png)
        self.assertEqual(post.call_args.args[1], "https://images.example.test/v1/images/generations")
        self.assertEqual(post.call_args.kwargs["key"], "image-only-credential")
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload", side_effect=TimeoutError("unknown")) as create:
            with self.assertRaises(ConfigError):
                generate_image(self.root, self.config, store_root=self.root, job_id="image-1", prompt="Opening", references=[])
            with self.assertRaises(ConfigError):
                generate_image(self.root, self.config, store_root=self.root, job_id="image-1", prompt="Opening", references=[])
            create.assert_called_once()
        current = read_state(self.root)["jobs"]["image-1"]
        output = self.evidence("recovered.png", png)
        receipt = {"attempt_id": current["attempt_id"], "binding_fingerprint": current["binding_snapshot"]["fingerprint"],
            "method": "upstream-result", "reviewer_id": "operator", "upstream_record_id": "original-result-1",
            "output_sha256": output["sha256"], "evidence": [self.evidence()]}
        with mock.patch("media_client.request_json", side_effect=AssertionError("network")):
            recover_image(self.root, "image-1", Path(output["path"]), receipt)
        self.assertEqual(read_state(self.root)["jobs"]["image-1"]["status"], "completed")
        self.assertEqual(len(read_state(self.root)["ledger"]), 1)

    def test_saturated_image_instance_reserves_no_attempt(self):
        save_bundle(self.root, smart_car())
        self.config["upstreams"]["image-service"]["max_concurrent_submissions"] = 1
        with submission_slot(self.root, "image-service", 1):
            with self.assertRaisesRegex(ConfigError, "concurrency"):
                generate_image(self.root, self.config, store_root=self.root, job_id="image-busy", prompt="Opening", references=[])
        self.assertFalse(read_state(self.root)["ledger"])

    def test_image_batch_prevalidates_then_runs_with_configured_parallelism(self):
        import base64
        save_bundle(self.root, smart_car())
        self.config["execution"]["max_concurrent_image_tasks"] = 2
        self.config["upstreams"]["image-service"]["max_concurrent_submissions"] = 2
        png = base64.b64encode(b"not-a-real-png").decode()
        active = 0
        peak = 0
        guard = threading.Lock()
        def create_payload(*args, **kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.08)
            with guard:
                active -= 1
            return {"data": [{"b64_json": png}]}
        items = [{"job_id": f"image-{index}", "prompt": f"Frame {index}", "references": []} for index in range(3)]
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload", side_effect=create_payload), \
             mock.patch("media_client._extract_image", return_value=b"fake-image-bytes"), \
             mock.patch("media_client.save_image_bytes", side_effect=lambda data, target: target.with_suffix(".png")):
            result = generate_images(self.root, self.config, store_root=self.root, items=items)
        self.assertTrue(result["ok"], result)
        self.assertEqual(peak, 2)
        self.assertEqual(len(read_state(self.root)["ledger"]), 3)
        invalid = [{"job_id": "image-4", "prompt": "valid", "references": []},
                   {"job_id": "image-5", "prompt": "   ", "references": []}]
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload") as create:
            with self.assertRaises(ConfigError):
                generate_images(self.root, self.config, store_root=self.root, items=invalid)
            create.assert_not_called()

    def test_review_inbox_orders_completed_assets_and_image_receipt_updates_state(self):
        image = self.root / "assets" / "generated" / "image-1.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"reviewable image")
        state = read_state(self.root)
        state["jobs"] = {
            "image-1": {"kind": "image", "status": "completed", "completed_at": 20,
                "content_status": "unverified", "artifact": {"path": image.relative_to(self.root).as_posix(),
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}},
            "video-1": {"kind": "video", "status": "completed", "completed_at": 10,
                "content_status": "unverified", "artifact": {"path": "jobs/video-1/source.mp4", "sha256": "x"}},
            "video-2": {"kind": "video", "status": "queued", "created_at": 1}}
        save_state(self.root, state)
        self.assertEqual([item["job_id"] for item in inbox(self.root)["items"]], ["video-1", "image-1"])
        result = review_image(self.root, job_id="image-1", status="pass", reviewer_id="reviewer",
            observation="The image has the intended subject and no visible artifact")
        self.assertEqual(result["status"], "reviewed")
        self.assertEqual([item["job_id"] for item in inbox(self.root, pending_only=True)["items"]], ["video-1"])

    def test_modern_product_exception_and_independent_voice_do_not_conflict(self):
        bundle = smart_car()
        bundle["brief"].update(allowed_elements=["智能汽车"], forbidden_elements=["智能汽车", "广告水印"])
        compiled = compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=4096)
        self.assertIn("Explicitly allowed story objects/marks: 智能汽车", compiled["prompt"])
        self.assertIn("广告水印", compiled["prompt"])
        bundle["brief"]["visual_style"] = "no modern objects"
        self.assertTrue(any("conflicts" in e for e in validate_plan(bundle)["errors"]))
        shot = bundle["director"]["shots"][0]
        shot["audio"] = {"mode": "independent-voice", "lines": [{"speaker": "strategist", "text": "这句由独立声音轨播放", "start": 0, "end": 1, "on_screen": False}]}
        prompt = compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=4096)["prompt"]
        self.assertIn("independent soundtrack", prompt)
        self.assertNotIn("这句由独立声音轨播放", prompt)


@unittest.skipUnless(os.name == "nt", "Windows installer rollback")
class InstallerRollbackTests(unittest.TestCase):
    def test_failed_upgrade_restores_the_previous_skill_and_user_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / "skills" / "videocreate"
            destination.mkdir(parents=True)
            (destination / "previous-install.txt").write_text("restore-me")
            config_dir = root / "config"
            atomic_json(config_dir / "videocreate.config.json", config())
            before = (config_dir / "videocreate.config.json").read_bytes()
            # Fail the version check after the replacement has been copied.
            failing = root / "fail-python.cmd"
            failing.write_text("@exit /b 29\r\n", encoding="ascii")
            env = {**os.environ, "VIDEOCREATE_CONFIG_DIR": str(config_dir)}
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "install.ps1"),
                "-Destination", str(destination), "-Python", str(failing), "-Force"], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / "previous-install.txt").read_text(), "restore-me")
            self.assertFalse((destination / "SKILL.md").exists())
            self.assertEqual((config_dir / "videocreate.config.json").read_bytes(), before)
