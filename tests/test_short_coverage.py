"""Offline regressions for action readability and distinct generation/edit timing."""
import copy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
from videocreate.cli import main
from videocreate.config.storage import ConfigError, load_json
from videocreate.planning.profiles import create
from videocreate.planning.project import compile_job, load_project, save_bundle, validate_plan
from videocreate.planning.creative_audit import audit


class ShortCoverageTests(unittest.TestCase):
    def test_short_plans_have_exact_rate_one_duration_causal_coverage_and_source_handles(self):
        for profile in ("action-montage", "animal-comedy"):
            for seconds in (10, 15.5, 20):
                with self.subTest(profile=profile, seconds=seconds):
                    b = create(profile, seconds=seconds)
                    self.assertTrue(validate_plan(b)["ok"], validate_plan(b))
                    self.assertEqual(audit(b)["content"], "unverified")
                    self.assertEqual(audit(b)["findings"], [])
                    shots = b["director"]["shots"]
                    self.assertEqual(len(shots), 7)
                    self.assertTrue({"setup", "action", "result", "reaction", "payoff"} <= {s["role"] for s in shots})
                    segments = b["timeline"]["segments"]
                    self.assertAlmostEqual(sum(s["source_out"]-s["source_in"] for s in segments), seconds, places=5)
                    self.assertTrue(all(s["rate"] == 1 for s in segments))
                    for shot, job, segment in zip(shots, b["generation-plan"]["jobs"], segments):
                        self.assertLessEqual(job["seconds"], 10)
                        self.assertEqual(shot["planned_seconds"], job["seconds"])
                        self.assertGreater(segment["source_in"], 0)
                        self.assertLess(segment["source_out"], job["seconds"])
                        self.assertEqual(len(shot["actions"]), 1)
                        compiled = compile_job(b, job, max_bytes=12000)
                        if "lead" not in shot["asset_ids"]:
                            self.assertNotIn("Visible lead:", compiled["prompt"])
                    contact = next(s for s in shots if s["role"] == "action")
                    phases = {p["phase"]: p for p in contact["action_phases"]}
                    self.assertLessEqual(phases["contact"]["end"]-phases["contact"]["start"], .3)
                    self.assertLessEqual(phases["contact"]["end"], 1.2)
                    self.assertTrue(b["story"]["beats"][-1]["causes"])

    def test_old_slow_profile_is_not_forced_to_be_an_action_montage(self):
        portrait = create("portrait", seconds=20)
        self.assertEqual(audit(portrait)["findings"], [])
        self.assertEqual(portrait["brief"]["pace_profile"], "slow-cinema")
        for p in ("animal-comedy", "action-montage"):
            with self.assertRaises(ConfigError):
                create(p, seconds=60)
        b = create("action-montage")
        b["director"]["shots"][0]["camera_motion"] = "Locked camera; no slow motion; 不使用慢镜头"
        self.assertEqual(audit(b)["findings"], [])
        b["director"]["shots"][0]["camera_motion"] = "slow push toward the face"
        self.assertIn("slow-camera-in-action", {f["code"] for f in audit(b)["findings"]})

    def test_audit_catches_observed_long_take_and_late_contact_risks_without_approval(self):
        b = create("action-insert", seconds=10)
        original = copy.deepcopy(b)
        self.assertIn("late-contact", {f["code"] for f in audit(b)["findings"]})
        self.assertEqual(b, original)
        b = create("action-montage")
        for seg, job in zip(b["timeline"]["segments"], b["generation-plan"]["jobs"]):
            job["seconds"] = 10
            seg.update(source_in=0, source_out=10)
        for shot in b["director"]["shots"]:
            shot.update(framing="first-person POV close-up", role="action")
        report = audit(b)
        codes = {f["code"] for f in report["findings"]}
        self.assertTrue({"full-long-takes", "missing-spatial-coverage", "missing-result-coverage", "independent-pov-continuity"} <= codes)
        self.assertEqual(report["content"], "unverified")
        self.assertEqual(report["paid_creates"], 0)

    def test_cli_initializes_and_audits_new_profile_without_reading_network_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cat"
            output = Path(tmp) / "advisory.json"
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["plan", "init", str(root), "--profile", "animal-comedy", "--seconds", "18"]), 0)
                self.assertEqual(main(["plan", "validate", str(root)]), 0)
                self.assertEqual(main(["plan", "audit", str(root), "--output", str(output)]), 0)
            self.assertEqual(load_json(output)["evidence_kind"], "declared-plan-advisory")
            self.assertEqual(load_project(root)["brief"]["target_seconds"], 18)


if __name__ == "__main__":
    unittest.main()
