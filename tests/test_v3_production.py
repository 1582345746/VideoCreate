"""Production regressions use synthetic local media; no paid/network calls."""
import copy
import hashlib
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
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.profiles import create
from videocreate.planning.project import content_hash, load_project, save_bundle, validate_plan
from videocreate.planning.schema import plan_schema
from videocreate.runtime.state import read_state, save_state
from videocreate.runtime.candidates import select, selected, handoff
from videocreate.review.receipts import contracts
from videocreate import education, references, series


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_published_plan_schema_matches_runtime_and_cli_export(self):
        published = load_json(ROOT / "videocreate/assets/schemas/videocreate.plan.schema.json")
        self.assertEqual(published, plan_schema())
        self.assertIn("research", published["properties"])
        self.assertIn("workflow_profile", published["properties"]["brief"]["properties"])
        output = self.root / "exported-plan.schema.json"
        from videocreate.cli import main
        from contextlib import redirect_stdout
        from io import StringIO
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["plan", "schema", "--output", str(output)]), 0)
        self.assertEqual(load_json(output), published)

    def test_profiles_have_different_coverage_and_exact_duration(self):
        for profile in ("portrait", "action-insert", "scenic", "explainer"):
            bundle = create(profile, seconds=15.5)
            self.assertTrue(validate_plan(bundle)["ok"], validate_plan(bundle))
            self.assertAlmostEqual(sum(s["source_out"]-s["source_in"] for s in bundle["timeline"]["segments"]), 15.5)
            for job in bundle["generation-plan"]["jobs"]:
                self.assertLessEqual(job["seconds"], 10)
                shot = next(s for s in bundle["director"]["shots"] if s["id"] == job["shot_ids"][0])
                self.assertEqual(shot["planned_seconds"], job["seconds"])
        portrait = create("portrait", seconds=16)
        self.assertNotEqual(portrait["director"]["shots"][0]["framing"], portrait["director"]["shots"][1]["framing"])
        action = create("action-insert")
        shot = action["director"]["shots"][0]
        self.assertEqual(len(action["generation-plan"]["jobs"]), 1)
        self.assertEqual(action["generation-plan"]["jobs"][0]["seconds"], 10)
        self.assertIn("target", shot["asset_ids"])
        self.assertIn("training jacket", action["director"]["assets"][0]["description"])
        self.assertEqual(len(shot["contacts"]), 1)
        self.assertEqual([phase["phase"] for phase in shot["action_phases"]], ["prepare", "action", "contact", "recovery", "settle"])
        self.assertIn("locked tripod", shot["camera_motion"])
        extended = create("action-insert", seconds=12)
        self.assertTrue(validate_plan(extended)["ok"], validate_plan(extended))
        self.assertEqual([job["seconds"] for job in extended["generation-plan"]["jobs"]], [10, 2])
        self.assertEqual(extended["director"]["shots"][1]["contacts"], [])
        self.assertTrue(all(job["seconds"] <= 10 for job in extended["generation-plan"]["jobs"]))
        self.assertFalse(validate_plan(create("series-episode"))["ok"])

    def test_binding_duration_override_blocks_oversized_requests(self):
        from videocreate.catalog.bindings import configured_binding, validate_request
        config = load_json(ROOT / "videocreate/assets/config/videocreate.config.example.json")
        bid = next(k for k, value in config["bindings"].items() if value["adapter"] == "sub2api-json-v1")
        config["bindings"][bid]["capability_overrides"] = {"duration": {"minimum": 1, "maximum": 10, "step": 1}}
        binding = configured_binding(config, bid)
        common = {"operation": "text-to-video", "prompt": "Synthetic duration preflight", "resolution": "720p",
            "aspect_ratio": "16:9", "generate_audio": False, "references": []}
        self.assertTrue(validate_request(binding, {**common, "seconds": 10})["ok"])
        self.assertIn("Duration is outside", "; ".join(validate_request(binding, {**common, "seconds": 11})["errors"]))

    def muse_video_config(self):
        config = load_json(ROOT / "videocreate/assets/config/videocreate.config.example.json")
        config["models"]["muse-video"] = {"kind": "video", "family": "muse"}
        config["upstreams"]["muse-test"] = {"platform": "sub2api", "base_url": "https://muse.example.test/v1",
            "auth": {"type": "bearer", "api_key": "synthetic-test-key"}}
        config["bindings"]["muse-test"] = {"enabled": True, "model": "muse-video", "upstream": "muse-test",
            "remote_model": "muse-video", "adapter": "sub2api-json-v1", "operations": ["text-to-video"]}
        config["routes"]["muse-video"] = {"policy": "fixed", "preferred_binding": "muse-test", "candidates": ["muse-test"]}
        config["defaults"]["video_model"] = "muse-video"
        return config

    def test_muse_video_defaults_to_hard_10_second_limit(self):
        from videocreate.catalog.bindings import configured_binding, validate_request
        config = self.muse_video_config()
        binding = configured_binding(config, "muse-test")
        self.assertEqual(binding.capabilities["duration"]["maximum"], 10)
        request = {"operation": "text-to-video", "prompt": "synthetic", "resolution": "720p",
            "aspect_ratio": "16:9", "seconds": 10, "references": []}
        self.assertTrue(validate_request(binding, request)["ok"])
        request["seconds"] = 11
        self.assertFalse(validate_request(binding, request)["ok"])
        config["bindings"]["muse-test"]["capability_overrides"] = {
            "duration": {"minimum": 1, "maximum": 15, "step": 1}}
        binding = configured_binding(config, "muse-test")
        self.assertEqual(binding.capabilities["duration"]["maximum"], 10,
            "a capability override cannot raise the confirmed Muse Video limit")
        binding = configured_binding(config, "muse-test")
        binding.capabilities["duration"]["maximum"] = 15
        self.assertFalse(validate_request(binding, request)["ok"], "old task snapshots cannot bypass the Muse limit")

    def test_route_marks_over_duration_job_ineligible_before_generation(self):
        from videocreate.routing import recommend
        config = self.muse_video_config()
        bundle = create("action-insert", seconds=10)
        bundle["generation-plan"]["jobs"][0]["model"] = "muse-video"
        bundle["generation-plan"]["jobs"][0]["seconds"] = 11
        result = recommend(bundle, config, store_root=self.root)
        candidate = result["jobs"][0]["candidates"][0]
        self.assertFalse(candidate["eligible"])
        self.assertTrue(any("Duration is outside" in error for error in candidate["request_errors"]))

    def test_jobs_run_rejects_over_limit_before_client_or_budget_reservation(self):
        from videocreate.runtime.jobs import generate
        config = self.muse_video_config()
        bundle = create("action-insert", seconds=10)
        bundle["generation-plan"]["jobs"][0].update(model="muse-video", seconds=11)
        save_bundle(self.root, bundle)
        with patch("videocreate.runtime.jobs.client", side_effect=AssertionError("client construction must not occur")) as make_client:
            with self.assertRaisesRegex(ConfigError, "Duration is outside"):
                generate(self.root, config, store_root=self.root, job_ids=["job-001"])
        make_client.assert_not_called()
        self.assertFalse((self.root / "state.json").exists())

    def test_observed_reference_profile_reaches_compiled_job_prompt(self):
        from videocreate.planning.project import compile_job
        save_bundle(self.root, create("portrait", seconds=10))
        source = self.root / "source.mp4"
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=blue:size=160x120:rate=24:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
        report = references.analyze(source, self.root / "study", max_frames=3)
        study = load_json(Path(report["report"]))
        fid = study["frames"][0]["id"]
        observation = {"reviewer_id": "test", "observations": [{"category": "framing", "method": "frames",
            "start": 0, "end": 2, "notes": "Subject sits in the left third with headroom", "frame_ids": [fid]}]}
        profile = references.profile(Path(report["report"]), observation)
        references.attach(self.root, Path(profile["profile"]))
        bundle = load_project(self.root)
        compiled = compile_job(bundle, bundle["generation-plan"]["jobs"][0], max_bytes=4096, root=self.root)
        self.assertIn("Observed reference style", compiled["prompt"])
        self.assertIn(observation["observations"][0]["notes"], compiled["prompt"])

    def test_invalid_phases_and_audio_policy_cannot_pass(self):
        bundle = create("portrait")
        bundle["director"]["shots"][0]["action_phases"][1]["start"] = 1
        self.assertFalse(validate_plan(bundle)["ok"])
        bundle = create("portrait")
        bundle["director"]["shots"][0]["audio"]["mode"] = "native-dialogue"
        self.assertFalse(validate_plan(bundle)["ok"])

    def candidate(self, attempt, value):
        path = self.root / (attempt + ".mp4")
        path.write_bytes(value)
        return {"attempt_id": attempt, "task_id": "synthetic-"+attempt, "status": "completed", "artifact": {
            "path": path.name, "sha256": hashlib.sha256(value).hexdigest(), "media": {"duration": 10}}}

    def test_select_history_survives_current_failure_and_detects_changed_bytes(self):
        save_bundle(self.root, create("portrait", seconds=10))
        old = self.candidate("old", b"old fixture")
        record = {"attempt_id": "new", "status": "failed", "history": [old]}
        save_state(self.root, {"schema_version": 3, "jobs": {"job-001": record}, "ledger": []})
        select(self.root, "job-001", "old", "Fixture verifies recovered candidate")
        current = read_state(self.root)["jobs"]["job-001"]
        self.assertEqual(current["status"], "failed")
        self.assertEqual(selected(current)["attempt_id"], "old")
        (self.root / "old.mp4").write_bytes(b"changed")
        with self.assertRaises(ConfigError):
            select(self.root, "job-001", "old", "same reason")

    def test_selected_candidate_change_invalidates_final_manifest(self):
        bundle = create("portrait", seconds=10)
        save_bundle(self.root, bundle)
        old, new = self.candidate("old", b"a"), self.candidate("new", b"b")
        new["history"] = [old]
        save_state(self.root, {"schema_version": 3, "jobs": {"job-001": new}, "ledger": []})
        final = self.root / "deliverables/preview.mp4"
        final.parent.mkdir()
        final.write_bytes(b"synthetic final")
        atomic_json(final.with_suffix(".manifest.json"), {"sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
            "timeline_hash": content_hash(bundle["timeline"]), "source_hashes": {"clip-001": new["artifact"]["sha256"]}, "media": {"duration": 10}})
        self.assertIn("final", contracts(self.root, bundle))
        select(self.root, "job-001", "old", "Different bytes")
        with self.assertRaisesRegex(ConfigError, "different candidate"):
            contracts(self.root, bundle)

    def researched(self):
        bundle = create("explainer", seconds=10, topic="Source fixture")
        save_bundle(self.root, bundle)
        source = self.root / "source.txt"
        source.write_text("Example population was 100 in 2020. Synthetic test data only.", encoding="utf-8")
        record = education.add_source(self.root, "s1", source, url="https://example.org/data", title="Test source", publisher="Test publisher")["source"]
        bundle = load_project(self.root)
        bundle["research"]["claims"] = [{"id":"c1", "kind":"statistic", "text":"Example population was 100 in 2020.", "status":"verified", "source_ids":["s1"],
            "review":{"reviewer_id":"test", "source_id":"s1", "source_sha256":record["sha256"], "excerpt":"Example population was 100 in 2020."},
            "metric":{"name":"population", "value":100, "unit":"people", "year":"2020", "geography":"example", "definition":"test residents"}}]
        bundle["research"]["narration"] = [{"id":"n1", "text":"Example population was 100 in 2020.", "claim_ids":["c1"], "start":0,"end":9}]
        bundle["director"]["shots"][0]["claim_ids"] = ["c1"]
        return bundle

    def test_fact_requires_matching_excerpt_and_preserved_snapshot(self):
        bundle = self.researched()
        self.assertTrue(education.validate_research(bundle, root=self.root, ready=True)["ok"])
        bundle["research"]["claims"][0]["review"]["excerpt"] = "Unsupported invented fact"
        self.assertFalse(education.validate_research(bundle, root=self.root, ready=True)["ok"])
        path = self.root / bundle["research"]["sources"][0]["path"]
        path.write_text("Modified bytes", encoding="utf-8")
        self.assertTrue(any("bytes changed" in e for e in education.validate_research(bundle, root=self.root)["errors"]))

    def test_ranking_requires_comparable_universe_year_and_coverage(self):
        bundle = self.researched()
        bundle["research"]["claims"][0]["comparison"] = {"universe":"all countries"}
        self.assertFalse(education.validate_research(bundle, root=self.root, ready=True)["ok"])

    def test_malformed_claim_ids_return_diagnostics_and_no_crash(self):
        bundle = self.researched()
        bundle["research"]["claims"][0]["source_ids"] = [{}]
        bundle["research"]["narration"][0]["claim_ids"] = [{}]
        bundle["director"]["shots"][0]["claim_ids"] = [{}]
        self.assertFalse(education.validate_research(bundle, root=self.root, ready=True)["ok"])

    def test_unverified_fact_generated_evidence_and_overlapping_narration_block(self):
        bundle = self.researched()
        bundle["research"]["claims"][0]["status"] = "draft"
        bundle["director"]["shots"][0]["visual_purpose"] = "evidence"
        bundle["research"]["narration"].append({**bundle["research"]["narration"][0],"id":"n2"})
        report = education.validate_research(bundle, root=self.root, ready=True)
        self.assertGreaterEqual(len(report["errors"]),3)

    def test_explainer_apply_preserves_existing_subtitles_and_rejects_conflicts(self):
        bundle = self.researched()
        bundle["timeline"]["subtitles"] = [{"text": "Existing title", "start": 9.2, "end": 9.8}]
        atomic_json(self.root / bundle["project"]["files"]["research"], bundle["research"])
        atomic_json(self.root / bundle["project"]["files"]["director"], bundle["director"])
        atomic_json(self.root / bundle["project"]["files"]["timeline"], bundle["timeline"])
        education.export(self.root, apply=True)
        applied = load_project(self.root)["timeline"]["subtitles"]
        self.assertEqual({cue["text"] for cue in applied}, {"Existing title", "Example population was 100 in 2020."})
        bundle = load_project(self.root)
        bundle["timeline"]["subtitles"].append({"text": "Conflicting line", "start": 3, "end": 4})
        atomic_json(self.root / bundle["project"]["files"]["timeline"], bundle["timeline"])
        with self.assertRaisesRegex(ConfigError, "overlaps an existing cue"):
            education.export(self.root, apply=True)

    def test_series_cannot_inherit_unaccepted_script(self):
        series.initialize(self.root, "Test", 20)
        result = series.prepare(self.root, 1)
        episode = Path(result["project"])
        series.check_episode_context(episode, load_project(episode))
        with self.assertRaises(ConfigError):
            series.prepare(self.root, 2)
        bible = load_json(self.root/"series.json")
        bible["world_rules"] = ["Changed rule"]
        atomic_json(self.root/"series.json", bible)
        with self.assertRaisesRegex(ConfigError,"bible changed"):
            series.check_episode_context(episode,load_project(episode))

    def test_series_ending_requires_real_review_and_final_interval(self):
        series.initialize(self.root,"Test",2)
        series.prepare(self.root,1)
        with patch("videocreate.review.receipts.summary", return_value={"status":"review_pending"}):
            with self.assertRaisesRegex(ConfigError,"accepted source"):
                series.accept(self.root,1,{})
        with patch("videocreate.review.receipts.summary",return_value={"status":"accepted_delivery"}), patch("videocreate.review.receipts.contracts",return_value={"final":{"sha256":"fixture","contract_hash":"c","duration":60}}):
            observation={"observed_exit_state":{"door":"open"},"reviewer_id":"test","method":"human-video","observations":["synthetic test"],"final_sha256":"fixture","interval":[0,2]}
            with self.assertRaisesRegex(ConfigError,"final interval"):
                series.accept(self.root,1,observation)
            observation["interval"]=[55,60]
            observation["bible_hash"]="attempted override"
            series.accept(self.root,1,observation)
            accepted=load_json(self.root/"accepted/episode-001.json")
            self.assertNotEqual(accepted["bible_hash"],"attempted override")
            second = Path(series.prepare(self.root, 2)["project"])
            second_bundle = load_project(second)
            self.assertEqual(second_bundle["story"]["initial_state"], observation["observed_exit_state"])
            series.check_episode_context(second, second_bundle)

    def test_map_provenance_and_source_preservation(self):
        source=self.root/"geography.geojson"
        atomic_json(source,{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]}})
        before=source.read_bytes()
        result=education.draw_map(source,self.root/"map.svg",source_url="https://example.org/geo")
        self.assertEqual(source.read_bytes(),before)
        self.assertTrue(Path(result["raster"]).is_file())
        with self.assertRaises(ConfigError):
            education.draw_map(source,source,source_url="https://example.org/geo")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Quality evidence requires FFmpeg")
    def test_quality_routing_binds_observation_to_completed_video_task(self):
        from videocreate.catalog.bindings import configured_binding
        from videocreate.catalog.evidence import record
        from videocreate.routing import quality_checks, require_quality
        config=load_json(ROOT/"videocreate/assets/config/videocreate.config.example.json")
        bid=next(k for k,v in config["bindings"].items() if v["adapter"]=="sub2api-json-v1")
        binding=configured_binding(config,bid)
        project = self.root / "completed-project"
        project.mkdir()
        evidence=project/"source.mp4"
        subprocess.run([shutil.which("ffmpeg"),"-v","error","-y","-f","lavfi","-i",
            "color=c=blue:size=64x64:rate=24:duration=1","-c:v","libx264","-pix_fmt","yuv420p",str(evidence)],check=True,capture_output=True)
        artifact_hash=hashlib.sha256(evidence.read_bytes()).hexdigest()
        save_state(project,{"schema_version":3,"jobs":{"job-001":{"status":"completed","attempt_id":"attempt-1","task_id":"task-1",
            "binding_snapshot":binding.snapshot(),"artifact":{"path":"source.mp4","sha256":artifact_hash}}},"ledger":[]})
        receipt={"stage":"quality","result":"pass","binding_fingerprint":binding.snapshot()["fingerprint"],
            "operation":"text-to-video","attempt_id":"attempt-1","task_id":"task-1","project_root":str(project),"reviewer_id":"test", "method":"human-video",
            "checks":{"natural_motion":True},"evidence":[{"path":str(evidence),"sha256":artifact_hash}]}
        with self.assertRaises(ConfigError):
            record(self.root,binding,{**receipt,"method":"codex-vision"})
        with self.assertRaisesRegex(ConfigError,"do not match a completed task"):
            record(self.root,binding,{**receipt,"task_id":"forged-task"})
        text_evidence=self.root/"not-a-video.txt"
        text_evidence.write_text("Synthetic observed video result for contract testing")
        with self.assertRaisesRegex(ConfigError,"exact downloaded video artifact"):
            record(self.root,binding,{**receipt,"evidence":[{"path":str(text_evidence),"sha256":hashlib.sha256(text_evidence.read_bytes()).hexdigest()}]})
        record(self.root,binding,receipt)
        require_quality(self.root,binding,{"operation":"text-to-video","required_quality_checks":["natural_motion"]})
        with self.assertRaises(ConfigError):
            require_quality(self.root,binding,{"operation":"image-to-video","required_quality_checks":["natural_motion"]})
        record(self.root,binding,{**receipt,"result":"fail","checks":{"natural_motion":False}})
        self.assertNotIn("natural_motion",quality_checks(self.root,binding,"text-to-video")["passed"])
        evidence.write_text("Modified evidence")
        self.assertEqual(quality_checks(self.root,binding,"text-to-video")["receipts"],[])

    def test_series_preserves_canonical_reference_bytes_in_episode(self):
        series.initialize(self.root,"Test",2)
        reference=self.root/"face.png"
        reference.write_bytes(b"synthetic reference")
        bible=load_json(self.root/"series.json")
        bible["characters"]=[{"id":"lead","kind":"character","description":"Fictional test adult","references":["face.png"]}]
        bible["reference_hashes"]={"face.png":hashlib.sha256(reference.read_bytes()).hexdigest()}
        atomic_json(self.root/"series.json",bible)
        episode=Path(series.prepare(self.root,1)["project"])
        bundle=load_project(episode)
        copied=episode/bundle["director"]["assets"][0]["references"][0]
        self.assertEqual(copied.read_bytes(),reference.read_bytes())
        series.check_episode_context(episode,bundle)
        copied.write_bytes(b"wrong reference")
        with self.assertRaisesRegex(ConfigError,"reference bytes changed"):
            series.check_episode_context(episode,bundle)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"Requires FFmpeg")
class ProductionMediaTests(unittest.TestCase):
    def test_render_overlays_voice_review_handoff_and_reference_evidence(self):
        from videocreate.timeline.render import render,probe
        from videocreate.review.packet import packet
        from videocreate import references
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            bundle=create("portrait",seconds=10)
            bundle["timeline"].update(width=160,height=120)
            bundle["timeline"]["segments"][0].update(source_in=0,source_out=2)
            bundle["brief"]["target_seconds"]=2
            save_bundle(root,bundle)
            source=root/"source.mp4"
            subprocess.run([shutil.which("ffmpeg"),"-v","error","-y","-f","lavfi","-i","color=c=blue:size=160x120:rate=24:duration=2","-f","lavfi","-i","sine=frequency=440:duration=2","-c:v","libx264","-c:a","aac","-shortest",str(source)],check=True,capture_output=True)
            artifact={"path":source.name,"sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"media":probe(source)}
            state={"schema_version":3,"jobs":{"job-001":{"status":"completed","attempt_id":"fixture","task_id":"fixture","artifact":artifact}},"ledger":[]}
            save_state(root,state)
            bundle["timeline"]["overlays"]=[{"id":"title","text":"Test 100", "start":0,"end":1,"position":"center"}]
            bundle["timeline"]["audio_tracks"]=[{"id":"voice","kind":"dialogue","path":"source.mp4","source_in":0,"source_out":2,"timeline_start":0}]
            result=render(root,bundle,state)
            self.assertAlmostEqual(result["media"]["duration"],2,delta=.1)
            self.assertIn("audio",contracts(root,bundle)["final"]["required_layers"])
            self.assertIn("source.mp4",result["auxiliary_hashes"])
            page=packet(root,bundle)
            self.assertTrue(Path(page["review_page"]).is_file())
            obs=load_json(Path(page["observations"]))
            self.assertIn("sha256",obs["assets"]["final"]["samples"][0])
            frame=handoff(root,"job-001",1.5)
            self.assertTrue((root/frame["reference"]["path"]).is_file())
            (root/frame["reference"]["path"]).write_bytes(b"wrong handoff")
            with self.assertRaisesRegex(ConfigError,"handoff bytes changed"):
                handoff(root,"job-001",1.5)
            with self.assertRaises(ConfigError):
                handoff(root,"job-001",2.5)
            with self.assertRaises(ConfigError):
                handoff(root,"job-001",1,next_job="job-001")
            report=references.analyze(source,root/"reference",max_frames=6)
            study=load_json(Path(report["report"]))
            fid=study["frames"][0]["id"]
            observation={"reviewer_id":"test","observations":[{"category":"camera","method":"frames","start":0,"end":2,"notes":"Cannot certify from stills","frame_ids":[fid]}]}
            with self.assertRaisesRegex(ConfigError,"Static frames"):
                references.profile(Path(report["report"]),observation)
            observation["observations"][0]["category"]="framing"
            profile=references.profile(Path(report["report"]),observation)
            references.attach(root,Path(profile["profile"]))
            self.assertTrue(load_project(root)["brief"]["reference_profiles"])
            value=load_json(Path(profile["profile"]))
            value["observations"][0]["category"]="camera"
            value["profile_hash"]=content_hash({k:v for k,v in value.items() if k!="profile_hash"})
            atomic_json(Path(profile["profile"]),value)
            self.assertTrue(references.validate_profile(Path(profile["profile"])))


if __name__ == "__main__":
    unittest.main()
