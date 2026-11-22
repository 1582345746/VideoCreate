from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "videocreate/src"))
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import content_hash, save_bundle
from videocreate.review import receipts
from videocreate.runtime.state import save_state
from videocreate.timeline.render import probe, render


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = smart_car()
        save_bundle(self.root, self.bundle)
        raw = self.root / "jobs/job-001/attempt/source.mp4"
        raw.parent.mkdir(parents=True)
        raw.write_bytes(b"synthetic contract fixture only")
        save_state(self.root, {"schema_version": 3, "jobs": {"job-001": {"status": "completed", "artifact": {
            "path": raw.relative_to(self.root).as_posix(), "sha256": receipts.file_hash(raw), "media": {"duration": 4}}}}, "ledger": []})
        final = self.root / "deliverables/preview.mp4"
        final.parent.mkdir()
        final.write_bytes(b"synthetic final contract fixture")
        # This contract-only fixture represents all source clips using the same
        # local bytes. A final manifest must account for every timeline input.
        for clip in self.bundle["timeline"]["clips"]:
            clip["path"] = raw.relative_to(self.root).as_posix()
        atomic_json(final.with_suffix(".manifest.json"), {"sha256": receipts.file_hash(final),
            "timeline_hash": content_hash(self.bundle["timeline"]), "media": {"duration": 30},
            "source_hashes": {clip["id"]: receipts.file_hash(raw) for clip in self.bundle["timeline"]["clips"]}})
        self.receipt = receipts.template(self.root, self.bundle)
        self.receipt["reviewer_id"] = "fixture-reviewer"
        for asset in self.receipt["assets"].values():
            for layer, item in asset["layers"].items():
                if layer not in asset["required_layers"]:
                    item["status"] = "not_applicable"
                    continue
                item.update(status="pass", method="human-listening" if layer == "audio" else "human-video",
                    observations=["Synthetic observation for contract validation only"],
                    evidence=[{"path": asset["path"], "sha256": asset["sha256"], "start": 0, "end": asset["duration"], "kind": "video"}])
        self.receipt["assets"]["final"]["blind_understanding"] = {
            k: "Synthetic viewer answer" for k in ("goal", "obstacle", "choice", "result", "product_role", "payoff")}

    def test_structurally_valid_plan_with_no_review_stays_pending(self):
        result = receipts.summary(self.root, self.bundle)
        self.assertEqual(result["status"], "review_pending")
        self.assertEqual(result["assets"]["final"]["narrative"], "unverified")

    def test_event_comparison_is_bound_to_media_intervals_and_separate_from_approval(self):
        from unittest.mock import patch
        from videocreate.review.comparison import export_comparison, record_observations
        source = self.root / 'jobs/job-001/attempt/source.mp4'
        candidate = self.root / 'deliverables/preview.mp4'
        spec = {'schema_version': 1, 'events': [{'id': 'beat', 'label': '</script>',
                'source': [0, 1], 'candidate': [1, 2]}]}
        for key, path in (('source', source), ('candidate', candidate)):
            spec[key] = {'path': path.relative_to(self.root).as_posix(), 'sha256': receipts.file_hash(path)}
        with patch('videocreate.review.comparison.probe', return_value={'duration': 3, 'has_audio': False}):
            page = export_comparison(self.root, self.bundle, spec)
            self.assertNotIn('"label": "</script>"', Path(page['page']).read_text(encoding='utf-8'))
            receipt = {'schema_version': 1, 'comparison_hash': page['comparison_hash'], 'reviewer': 'test',
                       'observations': {'beat': {'status': 'fail', 'note': 'One second late in fixture'}}}
            report = record_observations(self.root, self.bundle, spec, receipt)
            self.assertEqual(record_observations(self.root, self.bundle, spec, receipt), report)
            self.assertTrue(Path(report['observations']).is_file())
            self.assertEqual(receipts.summary(self.root, self.bundle)['status'], 'review_pending')
            spec['events'][0]['candidate'] = [0, 2]
            with self.assertRaisesRegex(ConfigError, 'current comparison'):
                record_observations(self.root, self.bundle, spec, receipt)
            spec['events'][0]['candidate'] = [0, 4]
            with self.assertRaisesRegex(ConfigError, 'interval'):
                export_comparison(self.root, self.bundle, spec)
            candidate.write_bytes(b'changed')
            with self.assertRaisesRegex(ConfigError, 'bytes changed'):
                record_observations(self.root, self.bundle, spec, receipt)

    def test_playable_page_uses_real_media_and_does_not_approve_it(self):
        import json, re
        from videocreate.review.page import export
        atomic_json(self.root / 'timeline.json', self.bundle['timeline'])
        result = export(self.root)
        html = Path(result['page']).read_text(encoding='utf-8')
        data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(data['receipt']['assets']['final']['sha256'], self.receipt['assets']['final']['sha256'])
        self.assertEqual(data['media']['final'], '../deliverables/preview.mp4')
        self.assertEqual(receipts.summary(self.root,self.bundle)['status'],'review_pending')

    def test_scoped_event_failure_tracks_selected_contract_and_trim(self):
        from unittest.mock import patch
        from videocreate.review.comparison import comparison, record_observations
        artifact = self.receipt['assets']['job-001']
        media = {key: artifact[key] for key in ('path', 'sha256')}
        spec = {'schema_version': 1, 'review_asset_id': 'job-001', 'source': media, 'candidate': media,
                'events': [{'id': 'hat', 'label': 'Hat disappears', 'source': [0, 1], 'candidate': [1, 2]}]}
        with patch('videocreate.review.comparison.probe', return_value={'duration': 4, 'has_audio': False}):
            review = comparison(self.root, self.bundle, spec)
            record_observations(self.root, self.bundle, spec, {'schema_version': 1,
                'comparison_hash': content_hash(review), 'reviewer': 'fixture',
                'observations': {'hat': {'status': 'fail', 'note': 'The hat is absent.'}}})
        receipts.apply(self.root, self.bundle, self.receipt)
        segment = self.bundle['timeline']['segments'][0]
        for start, expected, status in [(0, 'full', 'rejected'), (1.5, 'partial', 'review_pending'),
                                        (2, 'trimmed', 'review_pending')]:
            with self.subTest(start=start):
                segment['source_in'] = start
                report = receipts.summary(self.root, self.bundle)
                self.assertEqual(report['status'], status)
                self.assertEqual(report['event_observations'][0]['events'][0]['retained_defect'], expected)
        segment['source_in'] = 0
        self.bundle['director']['shots'][0]['framing'] = 'Changed review requirement'
        report = receipts.summary(self.root, self.bundle)
        self.assertNotIn('retained_defect', report['event_observations'][0]['events'][0])

    def test_review_contract_resolves_project_root_before_recording_relative_paths(self):
        (self.root / "alias-parent").mkdir()
        alias_root = self.root / "alias-parent" / ".."
        self.assertEqual(receipts.contracts(alias_root, self.bundle),
            receipts.contracts(self.root, self.bundle))

    def test_full_contract_can_be_accepted_only_with_observed_evidence(self):
        self.assertEqual(receipts.validate_receipt(self.root, self.bundle, self.receipt), [])
        result = receipts.apply(self.root, self.bundle, self.receipt)
        self.assertEqual(result["summary"]["status"], "accepted_delivery")

    def test_three_frames_cannot_certify_motion_or_clean_whole_clip(self):
        for layer in ("performance_motion", "clean_frame"):
            receipt = copy.deepcopy(self.receipt)
            item = receipt["assets"]["final"]["layers"][layer]
            item["method"] = "codex-vision"
            item["evidence"][0]["kind"] = "frames"
            self.assertTrue(receipts.validate_receipt(self.root, self.bundle, receipt))

    def test_short_video_sample_cannot_certify_the_entire_performance(self):
        self.receipt["assets"]["final"]["layers"]["performance_motion"]["evidence"][0]["end"] = 2
        self.assertTrue(any("full temporal" in e for e in receipts.validate_receipt(self.root, self.bundle, self.receipt)))

    def test_logo_defect_overrides_old_or_new_pass_on_same_bytes(self):
        receipts.apply(self.root, self.bundle, self.receipt)
        rejected = copy.deepcopy(self.receipt)
        rejected["assets"]["final"]["layers"]["clean_frame"].update(status="fail", observations=["Logo visibly remains around 7.56s"])
        receipts.apply(self.root, self.bundle, rejected)
        receipts.apply(self.root, self.bundle, self.receipt)
        self.assertEqual(receipts.summary(self.root, self.bundle)["status"], "rejected")

    def test_changed_title_keeps_reviews_but_changed_visual_contract_does_not(self):
        receipts.apply(self.root, self.bundle, self.receipt)
        self.bundle["project"]["title"] = "Metadata title changed"
        self.assertEqual(receipts.summary(self.root, self.bundle)["status"], "accepted_delivery")
        self.bundle["director"]["shots"][0]["framing"] = "Changed required visual evidence"
        self.assertEqual(receipts.summary(self.root, self.bundle)["status"], "review_pending")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local FFmpeg required")
class NativeTimelineTests(unittest.TestCase):
    def test_real_24fps_half_speed_with_natural_speed_audio_bridge_and_subtitle_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "fixture.mp4"
            subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                "testsrc2=size=160x120:rate=24:duration=2", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
                check=True, capture_output=True)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            bundle = {"timeline": {"fps": "30/1", "width": 160, "height": 120,
                "clips": [{"id": "clip-1", "job_id": "job-1", "path": "fixture.mp4"}],
                "segments": [{"id": "seg-1", "shot_id": "shot-1", "clip_id": "clip-1", "source_in": 0, "source_out": 1,
                    "rate": 0.5, "source_audio": "mute", "cut_reason": "Slow physical detail"}, {
                    "id": "seg-2", "shot_id": "shot-2", "clip_id": "clip-1", "source_in": 1, "source_out": 2,
                    "rate": 1, "source_audio": "mute", "cut_reason": "Return to real time"}],
                "audio_tracks": [{"id": "bridge", "kind": "dialogue", "clip_id": "clip-1", "source_in": 0, "source_out": 2,
                    "timeline_start": 0.5, "gain_db": -6}],
                "subtitles": [{"segment_id": "seg-1", "source_start": 0.2, "source_end": 0.6, "text": "Mapped cue"}]}}
            report = render(root, bundle, {"jobs": {}})
            self.assertEqual(report["fps_report"][0]["source_fps"], "24/1")
            self.assertEqual(report["fps_report"][0]["source_frame_samples_per_timeline_second"], 12)
            self.assertEqual(report["fps_report"][0]["interpolation"], "none")
            self.assertAlmostEqual(report["media"]["duration"], 3, delta=0.15)
            self.assertTrue(report["media"]["has_audio"])
            self.assertEqual(report["content"], "unverified")
            self.assertIn("00:00:00,400 --> 00:00:01,200", (root / "deliverables/preview.srt").read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
