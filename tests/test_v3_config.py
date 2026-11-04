from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
sys.path.insert(0, str(ROOT / "videocreate/scripts"))

from videocreate.catalog.bindings import route_bindings, validate_request
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json, load_json, redact_config, resolve_key
from videocreate.config.bridge import engine_settings
from videocreate.migrations.config_v2 import convert_config, migrate_config


def config() -> dict:
    value = load_json(ROOT / "videocreate/assets/config/videocreate.config.example.json")
    for upstream in value["upstreams"].values():
        upstream["base_url"] = "https://provider.example.test/v1"
        upstream["auth"]["api_key"] = "test-only-value"
    for binding in value["bindings"].values():
        binding["enabled"] = True
        if "REPLACE_" in binding["remote_model"]:
            binding["remote_model"] = "Channel Model / Preserve Exact CASE"
    return value


class ConfigurationTests(unittest.TestCase):
    def test_sample_concurrency_matches_documented_fifty_upstream_and_six_worker_defaults(self):
        sample = load_json(ROOT / "videocreate/assets/config/videocreate.config.example.json")
        self.assertEqual({item["max_concurrent_submissions"] for item in sample["upstreams"].values()}, {50})
        self.assertEqual(sample["execution"]["max_concurrent_image_tasks"], 6)
        self.assertEqual(sample["execution"]["max_concurrent_video_tasks"], 6)

    def test_example_and_enabled_four_combinations_validate(self):
        self.assertEqual(validate_config(config(), ready=True), [])
        for mid in ("grok-imagine-video-1.5", "seedance-2.0-mini-720p"):
            bindings = route_bindings(config(), mid, operation="image-to-video", policy="automatic-same-model")
            self.assertEqual(len(bindings), 2)
            self.assertEqual({b.model for b in bindings}, {mid})

    def test_fixed_route_does_not_switch_to_backup(self):
        value = config()
        value["bindings"]["grok-on-sub2api"]["enabled"] = False
        with self.assertRaises(ConfigError):
            route_bindings(value, "grok-imagine-video-1.5", operation="image-to-video")

    def test_different_models_on_same_upstream_keep_different_adapters(self):
        value = config()
        value["bindings"]["grok-on-newapi"]["adapter"] = "newapi-multipart-v1"
        value["bindings"]["seedance-on-newapi"]["adapter"] = "newapi-json-v1"
        settings = engine_settings(value)
        self.assertEqual(settings["video_upstreams"]["grok-on-newapi"]["adapter"], "newapi-multipart")
        self.assertEqual(settings["video_upstreams"]["seedance-on-newapi"]["adapter"], "newapi-json")

    def test_unknown_property_and_cross_model_route_are_actionable(self):
        value = config()
        value["defaults"]["resoluton"] = "720p"
        self.assertIn("$.defaults.resoluton: unknown field", validate_config(value))
        del value["defaults"]["resoluton"]
        value["routes"]["grok-imagine-video-1.5"]["candidates"].append("seedance-on-newapi")
        self.assertTrue(any("cross-model" in e for e in validate_config(value)))

    def test_duplicate_json_keys_and_invalid_json_do_not_expose_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"api_key":"private-value","api_key":"second-value"}', encoding="utf-8")
            with self.assertRaises(ConfigError) as error:
                load_json(path)
            self.assertNotIn("private-value", str(error.exception))
            path.write_text('{"api_key":"private-value",}', encoding="utf-8")
            with self.assertRaises(ConfigError) as error:
                load_json(path)
            self.assertNotIn("private-value", str(error.exception))

    def test_auth_sources_are_mutually_exclusive(self):
        value = config()
        value["upstreams"]["primary-sub2api"]["auth"]["env"] = "EXAMPLE_KEY"
        self.assertTrue(any("choose exactly one" in e for e in validate_config(value)))
        with mock.patch.dict(os.environ, {"EXAMPLE_KEY": "value"}):
            self.assertEqual(resolve_key({"type": "bearer", "env": "EXAMPLE_KEY"}), "value")

    def test_redaction_and_binding_repr_never_include_secrets(self):
        value = config()
        self.assertNotIn("test-only-value", json.dumps(redact_config(value)))
        binding = route_bindings(value, "grok-imagine-video-1.5", operation="image-to-video")[0]
        self.assertNotIn("test-only-value", repr(binding))
        self.assertNotIn("test-only-value", json.dumps(binding.snapshot()))

    def test_channel_duration_conditions_and_unknown_reference_block(self):
        value = config()
        value["bindings"]["grok-on-sub2api"]["capability_overrides"] = {"conditions": [{"when": {"resolution": "720p"}, "max_seconds": 12}]}
        binding = route_bindings(value, "grok-imagine-video-1.5", operation="image-to-video")[0]
        request = {"operation": "image-to-video", "prompt": "a", "seconds": 15, "resolution": "720p", "aspect_ratio": "9:16", "references": []}
        self.assertFalse(validate_request(binding, request)["ok"])
        request["seconds"] = 5
        request["video_reference"] = True
        self.assertFalse(validate_request(binding, request)["ok"])

    def test_sub2api_audio_switch_is_reported_as_model_default(self):
        binding = route_bindings(config(), "grok-imagine-video-1.5", operation="image-to-video")[0]
        result = validate_request(binding, {"operation": "image-to-video", "prompt": "a", "generate_audio": True})
        self.assertTrue(result["ok"])
        self.assertTrue(any("not transmitted" in w for w in result["warnings"]))

    def test_image_credentials_are_independent_of_video_route(self):
        value = config()
        before = engine_settings(value)
        value["defaults"]["video_model"] = "seedance-2.0-mini-720p"
        value["routes"]["seedance-2.0-mini-720p"]["preferred_binding"] = "seedance-on-newapi"
        after = engine_settings(value)
        for key in ("image_base_url", "image_model", "sub2api_image_key"):
            self.assertEqual(before[key], after[key])

    def test_cli_init_is_idempotent_and_show_is_always_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "videocreate.config.json"
            cli = [sys.executable, str(ROOT / "videocreate/scripts/videocreate.py"), "config"]
            first = subprocess.run(cli + ["init", "--config", str(path)], capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(first.stdout)["created"])
            atomic_json(path, config())
            before = path.read_bytes()
            subprocess.run(cli + ["init", "--config", str(path)], capture_output=True, check=True)
            self.assertEqual(path.read_bytes(), before)
            shown = subprocess.run(cli + ["show", "--config", str(path)], capture_output=True, text=True, check=True)
            self.assertNotIn("test-only-value", shown.stdout + shown.stderr)

    def test_imports_perform_no_network_or_configuration_writes(self):
        script = "import socket; socket.socket=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('network')); import videocreate; from videocreate.config import schema; from videocreate.catalog import bindings"
        env = {**os.environ, "PYTHONPATH": str(ROOT / "videocreate/src")}
        subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, check=True)


class MigrationTests(unittest.TestCase):
    def legacy(self):
        return {"version": 4, "image_model": "gpt-image-2", "default_video_model": "grok-imagine-video-1.5",
                "image_base_url": "https://image.example.test", "sub2api_video_base_url": "https://video.example.test",
                "newapi_video_base_url": "", "video_upstreams": {}, "video_model_routes": {}}

    def test_conversion_is_pure_and_contains_no_key_values(self):
        old = self.legacy()
        before = copy.deepcopy(old)
        converted = convert_config(old)
        self.assertEqual(old, before)
        self.assertEqual(validate_config(converted), [])
        self.assertEqual(converted["upstreams"]["sub2api"]["auth"]["secret_ref"], "sub2api_video_key")

    def test_migration_preserves_encrypted_bytes_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "old"
            target = Path(folder) / "new"
            atomic_json(source / "config.json", self.legacy())
            (source / "secrets.dpapi").write_bytes(b"encrypted-original")
            preview = migrate_config(source, target)
            self.assertFalse(preview["applied"])
            self.assertFalse(target.exists())
            result = migrate_config(source, target, apply=True)
            self.assertTrue(result["applied"])
            self.assertEqual((target / "secrets.dpapi").read_bytes(), b"encrypted-original")
            with self.assertRaises(ConfigError):
                migrate_config(source, target, apply=True)

    def test_old_environment_names_still_find_v2_config(self):
        import vc_common
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {"GVS_CONFIG_DIR": folder}, clear=True):
            self.assertEqual(vc_common.config_dir(), Path(folder).resolve())
