import copy
import tempfile
import unittest
from pathlib import Path

from videocreate.production_metrics import report
from videocreate.config.storage import atomic_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.review import receipts
from videocreate.runtime.state import save_state


class ProductionMetricTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = smart_car()
        self.bundle['timeline']['clips'] = self.bundle['timeline']['clips'][:1]
        segment = self.bundle['timeline']['segments'][0]
        segment.update(source_in=1, source_out=3, rate=1, source_audio='mute')
        self.bundle['timeline']['segments'] = [segment, {**segment, 'id': 'repeat', 'source_in': 2, 'source_out': 4, 'rate': .5}]
        self.bundle['timeline']['subtitles'] = []
        self.bundle['timeline']['audio_tracks'] = []
        save_bundle(self.root, self.bundle)
        source = self.root / 'source.mp4'
        source.write_bytes(b'synthetic source contract fixture')
        old = self.root / 'old.mp4'
        old.write_bytes(b'synthetic old candidate fixture')
        self.state = {'schema_version': 3, 'jobs': {'job-001': {'attempt_id': 'new', 'status': 'completed',
            'artifact': {'path': 'source.mp4', 'sha256': receipts.file_hash(source), 'media': {'duration': 6}},
            'history': [{'attempt_id': 'old', 'status': 'completed', 'artifact': {
                'path': 'old.mp4', 'sha256': receipts.file_hash(old), 'media': {'duration': 5}}}]}},
            'ledger': [{'attempt_id': 'old', 'job_id': 'job-001', 'kind': 'video', 'currency': 'USD', 'estimated': 2, 'actual': None},
                       {'attempt_id': 'new', 'job_id': 'job-001', 'kind': 'video', 'currency': 'USD', 'estimated': 2, 'actual': 2}]}
        save_state(self.root, self.state)

    def approve_fixture(self, status='pass'):
        receipt = receipts.template(self.root, self.bundle)
        receipt['reviewer_id'] = 'fixture-only'
        asset = receipt['assets']['job-001']
        for layer in asset['required_layers']:
            asset['layers'][layer].update(status=status, method='human-listening' if layer == 'audio' else 'human-video',
                observations=['synthetic contract observation, not media quality evidence'],
                evidence=[{'path': asset['path'], 'sha256': asset['sha256'], 'start': 0, 'end': asset['duration'], 'kind': 'video'}])
        receipts.apply(self.root, self.bundle, receipt)

    def test_measured_candidates_unique_source_and_playback_are_separate(self):
        result = report(self.root)
        self.assertEqual(result['seconds']['generated_known'], 11)
        self.assertEqual(result['seconds']['retained_available_playback'], 6)
        self.assertEqual(result['seconds']['retained_unique_source'], 3)
        self.assertEqual(result['seconds']['reviewed_usable_playback'], 0)
        self.assertEqual(result['rates']['retry_attempts'], 1)
        self.assertEqual(result['rates']['retried_jobs_over_submitted_video_jobs'], 1)
        self.assertIsNone(result['costs_by_currency']['USD']['project_actual_cost_per_reviewed_playback_second'])

    def test_current_receipts_required_and_defects_dominate_stale_cached_status(self):
        self.approve_fixture()
        result = report(self.root)
        self.assertEqual(result['seconds']['reviewed_usable_playback'], 6)
        self.assertEqual(result['seconds']['reviewed_unique_source'], 3)
        self.assertNotEqual(result['delivery_status'], 'accepted_delivery')
        self.approve_fixture('fail')
        self.assertEqual(report(self.root)['seconds']['reviewed_usable_playback'], 0)
        self.assertEqual(report(self.root)['sample']['rejected_source_jobs'], 1)

    def test_changed_candidate_or_window_does_not_inherit_review(self):
        self.approve_fixture()
        self.state['jobs']['job-001']['selection'] = {'attempt_id': 'old', 'sha256': self.state['jobs']['job-001']['history'][0]['artifact']['sha256']}
        save_state(self.root, self.state)
        self.assertEqual(report(self.root)['seconds']['reviewed_usable_playback'], 0)
        self.state['jobs']['job-001'].pop('selection')
        save_state(self.root, self.state)
        self.bundle['timeline']['segments'][0]['source_in'] = .5
        atomic_json(self.root / 'timeline.json', self.bundle['timeline'])
        self.assertEqual(report(self.root)['seconds']['reviewed_usable_playback'], 0)

    def test_mixed_costs_are_separate_and_unknowns_never_zero_unit_cost(self):
        self.approve_fixture()
        self.state['ledger'][0]['actual'] = 2
        self.state['ledger'].append({'attempt_id': 'image', 'job_id': 'image', 'kind': 'image', 'currency': 'CNY', 'estimated': None, 'actual': None})
        save_state(self.root, self.state)
        result = report(self.root)
        self.assertEqual(set(result['costs_by_currency']), {'USD', 'CNY'})
        self.assertAlmostEqual(result['costs_by_currency']['USD']['project_actual_cost_per_reviewed_playback_second'], 4 / 6)
        self.assertIsNone(result['costs_by_currency']['CNY']['project_actual_cost_per_reviewed_source_job'])

    def test_changed_bytes_count_as_missing_and_review_unavailable_not_pass(self):
        self.approve_fixture()
        (self.root / 'source.mp4').write_bytes(b'changed')
        result = report(self.root)
        self.assertEqual(result['seconds']['generated_known'], 5)
        self.assertEqual(result['seconds']['completed_artifact_missing_or_changed'], 1)
        self.assertIsNone(result['seconds']['reviewed_usable_playback'])
        self.assertEqual(result['delivery_status'], 'unavailable')

    def test_read_is_offline_and_does_not_rewrite_project(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report(self.root)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_explicit_different_clip_cannot_use_job_approval(self):
        self.approve_fixture()
        self.bundle['timeline']['clips'][0]['path'] = 'old.mp4'
        atomic_json(self.root / 'timeline.json', self.bundle['timeline'])
        result = report(self.root)
        self.assertEqual(result['seconds']['reviewed_usable_playback'], 0)
        self.assertTrue(result['explicit_clip_segments_not_matched_to_candidate'])
