from __future__ import annotations

import base64
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
sys.path.insert(0, str(ROOT / "videocreate/scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_v3_config import config
from videocreate.assets import _select_image_route, generate_image
from videocreate.config.storage import ConfigError
from videocreate.config.schema import validate_config
from videocreate.catalog.bindings import configured_binding
from videocreate.adapters.image import BindingImageClient
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.runtime.state import read_state
from vc_common import APIError


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==")


class ImageModelSelectionTests(unittest.TestCase):
    def test_cooldown_is_shared_for_new_automatic_routes_but_explicit_binding_stays_fixed(self):
        from videocreate.runtime.health import observe
        from videocreate.catalog.bindings import route_bindings
        value = config()
        route = value["routes"]["gpt-image-2.5"]
        route.update(policy="automatic-same-model", preferred_binding="image-primary")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binding = configured_binding(value, "image-primary", key="test-only-value")
            observe(root, binding, failed=True)
            with self.assertRaises(ConfigError):
                route_bindings(value, "gpt-image-2.5", operation="text-to-image", store_root=root)
            fixed = route_bindings(value, "gpt-image-2.5", operation="text-to-image", preferred="image-primary", store_root=root)
            self.assertEqual(fixed[0].id, "image-primary")
            observe(root, binding, failed=False)
            self.assertTrue(route_bindings(value, "gpt-image-2.5", operation="text-to-image", store_root=root))

    def test_image_readiness_does_not_require_video_credentials(self):
        value = config()
        value["defaults"]["image_model"] = "gpt-image-2.5"
        for b in value["bindings"].values():
            if value["models"][b["model"]]["kind"] == "video":
                b["enabled"] = False
        self.assertEqual(validate_config(value, ready=True, kind="image"), [])
        self.assertTrue(validate_config(value, ready=True))

    def test_binding_omits_unaccepted_image_fields_and_preserves_remote_model(self):
        value = config()
        value["bindings"]["image-primary"]["adapter_options"] = {"image_request_fields": ["n", "size"]}
        binding = configured_binding(value, "image-primary", key="test-key")
        with mock.patch("media_client.request_json", return_value={"data": []}) as send:
            BindingImageClient(binding).create_payload("A boat", [], size="1024x1024", quality="auto")
        payload = send.call_args.kwargs["value"]
        self.assertEqual(payload, {"model": binding.remote_model, "prompt": "A boat", "n": 1, "size": "1024x1024"})
        with mock.patch("media_client.request_json") as send:
            with self.assertRaises(ConfigError):
                BindingImageClient(binding).create_payload("A boat", [], size="999x999", quality="auto")
            send.assert_not_called()

    def test_first_compatible_selection_uses_request_operation_and_preserves_model_boundary(self):
        value = config()
        value["models"]["gpt-image-2.6-flare"] = {"kind": "image", "family": "gpt-image"}
        value["bindings"]["flare-text-only"] = copy.deepcopy(value["bindings"]["image-primary"])
        value["bindings"]["flare-text-only"].update(model="gpt-image-2.6-flare", remote_model="gpt-image-2.6-flare",
            operations=["text-to-image"])
        value["routes"]["gpt-image-2.6-flare"] = {"policy": "fixed", "preferred_binding": "flare-text-only",
            "candidates": ["flare-text-only"]}
        value["model_selection"] = {"image": {"policy": "first-compatible",
            "candidates": ["gpt-image-2.6-flare", "gpt-image-2.5"]}}
        with tempfile.TemporaryDirectory() as folder:
            reference = Path(folder) / "edit.png"
            reference.write_bytes(PNG)
            model, bindings, selection = _select_image_route(value, requested_model=None, binding_id=None,
                prompt="Keep the silhouette and change the background", references=[reference],
                size="1024x1024", quality="auto", output_format="png", store_root=Path(folder))
        self.assertEqual(model, "gpt-image-2.5")
        self.assertEqual(bindings[0].id, "image-primary")
        self.assertEqual(selection["decisions"][0]["eligible"], False)
        self.assertEqual(selection["decisions"][1]["eligible"], True)


class ImageUpstreamFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        save_bundle(self.root, smart_car())
        self.config = config()
        self.config["defaults"]["image_model"] = "gpt-image-2.5"
        self.config["upstreams"]["image-backup"] = copy.deepcopy(self.config["upstreams"]["image-service"])
        self.config["upstreams"]["image-backup"]["base_url"] = "https://backup.example.test/v1"
        self.config["bindings"]["image-backup"] = copy.deepcopy(self.config["bindings"]["image-primary"])
        self.config["bindings"]["image-backup"].update(upstream="image-backup", remote_model="gpt-image-2.5")
        self.config["bindings"]["image-primary"]["adapter_options"] = {"confirmed_rejection_http_statuses": [400]}
        self.config["routes"]["gpt-image-2.5"] = {"policy": "automatic-same-model", "preferred_binding": "image-primary",
            "candidates": ["image-primary", "image-backup"]}

    def test_confirmed_rejection_uses_next_same_model_binding_and_accounts_for_both_creates(self):
        response = {"data": [{"b64_json": base64.b64encode(PNG).decode("ascii")}]}
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload",
                side_effect=[APIError(400, "model rejected"), response]) as create:
            result = generate_image(self.root, self.config, store_root=self.root, job_id="image-failover-001",
                prompt="A blue paper kite", references=[], model="gpt-image-2.5")
        self.assertTrue(result["ok"])
        self.assertEqual(result["binding"], "image-backup")
        self.assertEqual(result["model"], "gpt-image-2.5")
        self.assertEqual(result["paid_creates"], 2)
        self.assertEqual(create.call_count, 2)
        record = read_state(self.root)["jobs"]["image-failover-001"]
        self.assertEqual(record["history"][0]["status"], "rejected")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(len(read_state(self.root)["ledger"]), 2)

    def test_ambiguous_transport_failure_is_held_without_backup_create(self):
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload",
                side_effect=TimeoutError("connection lost")) as create:
            with self.assertRaises(ConfigError):
                generate_image(self.root, self.config, store_root=self.root, job_id="image-unknown-001",
                    prompt="A blue paper kite", references=[], model="gpt-image-2.5")
        self.assertEqual(create.call_count, 1)
        record = read_state(self.root)["jobs"]["image-unknown-001"]
        self.assertEqual(record["status"], "submission_unknown")

    def test_content_rejection_never_creates_on_a_backup(self):
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload",
                side_effect=APIError(400, "content policy moderation")) as create:
            with self.assertRaises(ConfigError):
                generate_image(self.root, self.config, store_root=self.root, job_id="content-rejected",
                    prompt="A blue paper kite", references=[], model="gpt-image-2.5")
        self.assertEqual(create.call_count, 1)

    def test_completed_image_is_reused_when_defaults_change_and_original_binding_is_disabled(self):
        payload = {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload", return_value=payload):
            generate_image(self.root, self.config, store_root=self.root, job_id="cached",
                prompt="A blue paper kite", references=[], model="gpt-image-2.5")
        self.config["defaults"]["image_model"] = "gpt-image-2.6"
        self.config["bindings"]["image-primary"]["enabled"] = False
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload") as create:
            result = generate_image(self.root, self.config, store_root=self.root, job_id="cached",
                prompt="A blue paper kite", references=[])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["model"], "gpt-image-2.5")
        self.assertEqual(result["paid_creates"], 0)
        create.assert_not_called()

    def test_native_gif_static_output_stays_invalid_when_reprocessed(self):
        self.config["bindings"]["image-primary"]["capability_overrides"] = {
            "output_formats": ["png", "gif"], "animated_output": "supported"}
        payload = {"data": [{"b64_json": base64.b64encode(PNG).decode()}]}
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload", return_value=payload):
            with self.assertRaisesRegex(ConfigError, "multi-frame"):
                generate_image(self.root, self.config, store_root=self.root, job_id="static-for-gif",
                    prompt="A moving boat", references=[], binding_id="image-primary", output_format="gif")
        from videocreate.assets import reprocess_image
        result = reprocess_image(self.root, "static-for-gif")
        self.assertFalse(result["ok"])
        self.assertEqual(read_state(self.root)["jobs"]["static-for-gif"]["status"], "output_invalid")

    def test_animated_gif_review_requires_temporal_observation(self):
        from test_gif_media import gif_fixture
        from videocreate.review.receipts import review_image
        self.config["bindings"]["image-primary"]["capability_overrides"] = {
            "output_formats": ["png", "gif"], "animated_output": "supported"}
        payload = {"data": [{"b64_json": base64.b64encode(gif_fixture((10, 10))).decode()}]}
        with mock.patch("videocreate.adapters.image.BindingImageClient.create_payload", return_value=payload):
            generate_image(self.root, self.config, store_root=self.root, job_id="animation",
                prompt="A boat rocks", references=[], binding_id="image-primary", output_format="gif")
        with self.assertRaisesRegex(ConfigError, "playback"):
            review_image(self.root, job_id="animation", status="pass", reviewer_id="test", observation="First frame inspected")
        result = review_image(self.root, job_id="animation", status="pass", reviewer_id="test",
            observation="Full playback observed", temporal_observation=True)
        self.assertEqual(result["status"], "reviewed")


if __name__ == "__main__":
    unittest.main()
