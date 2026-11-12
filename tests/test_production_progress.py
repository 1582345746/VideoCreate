import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from videocreate import production as p
from videocreate.config.storage import atomic_json, load_json, ConfigError
from videocreate.planning.project import save_bundle, compile_job, load_project
from videocreate.planning.examples import smart_car
from videocreate.runtime.jobs import generation_inputs
from videocreate.runtime.state import save_state


class ProductionProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '项目'
        self.bundle = smart_car()
        save_bundle(self.root, self.bundle)

    def test_status_is_derived_offline_and_does_not_create_stage_or_job_state(self):
        result = p.status(self.root)
        self.assertTrue(result['ok'])
        self.assertEqual(result['next']['id'], 'theme')
        self.assertFalse((self.root / 'state.json').exists())
        self.assertFalse((self.root / 'production').exists())
        self.assertNotIn('accepted_delivery', str(result))

    def test_checkpoint_is_version_bound_and_plan_edits_invalidate_it(self):
        stage = p.status(self.root)['stages'][0]
        p.checkpoint(self.root, 'theme', reason='Audience and intent approved', expected_hash=stage['input_hash'])
        self.assertEqual(p.status(self.root)['stages'][0]['status'], 'complete')
        value = load_json(self.root / 'brief.json')
        value['audience'] = 'new audience'
        atomic_json(self.root / 'brief.json', value)
        self.assertEqual(p.status(self.root)['stages'][0]['status'], 'stale')
        with self.assertRaisesRegex(ConfigError, 'content changed'):
            p.checkpoint(self.root, 'theme', reason='old reply', expected_hash=stage['input_hash'])
        with self.assertRaises(ConfigError):
            p.checkpoint(self.root, 'review', reason='cannot shortcut', expected_hash='x')

    def test_script_roundtrip_has_single_source_and_rejects_stale_exchange(self):
        exported = p.script_export(self.root)
        value = load_json(Path(exported['script']))
        value['shots'][0]['actions'][0]['description'] += ' The hand stops naturally.'
        result = p.import_script(self.root, value)
        self.assertTrue(Path(result['backup']).is_file())
        self.assertEqual(load_project(self.root)['director']['shots'], value['shots'])
        with self.assertRaisesRegex(ConfigError, 'source changed'):
            p.import_script(self.root, value)

    def test_subtitles_do_not_invalidate_generation_but_local_action_does(self):
        job = self.bundle['generation-plan']['jobs'][0]
        compilation = compile_job(self.bundle, job, max_bytes=4096, root=self.root)
        record = {'status': 'queued', 'task_id': 'original', 'input_hash': generation_inputs(self.root, self.bundle, job, compilation)}
        save_state(self.root, {'schema_version': 3, 'jobs': {job['id']: record}, 'ledger': []})
        changed = copy.deepcopy(self.bundle)
        changed['timeline']['subtitles'] = [{'text': 'new subtitle', 'start': 0, 'end': 1}]
        self.assertEqual(p.impact(self.root, changed)['changed_job_inputs'], [])
        changed['director']['shots'][0]['actions'][0]['description'] += ' He waves twice.'
        self.assertEqual(p.impact(self.root, changed)['changed_job_inputs'], [job['id']])

    def test_ambiguous_submission_takes_precedence_over_creative_stage(self):
        save_state(self.root, {'schema_version': 3, 'jobs': {'job-001': {'status': 'submission_unknown'}}, 'ledger': []})
        self.assertEqual(p.status(self.root)['next']['id'], 'reconcile')

    def test_policy_guides_next_without_approving_media(self):
        p.policy(self.root, 'auto-within-authorization', 'User asked to proceed through existing plan')
        result = p.status(self.root)
        self.assertEqual(result['next']['id'], 'generation')
        self.assertEqual(result['review']['status'], 'draft_preview')
        self.assertEqual(result['stages'][0]['status'], 'ready')

    def test_index_rebuilds_from_source_and_reports_missing_projects(self):
        store = Path(self.temp.name) / 'index'
        self.assertEqual(len(p.project_index(store, self.root)['projects']), 1)
        project = load_json(self.root / 'project.json')
        project['title'] = 'changed title'
        atomic_json(self.root / 'project.json', project)
        self.assertEqual(p.project_index(store)['projects'][0]['title'], 'changed title')
        (self.root / 'project.json').unlink()
        self.assertIn('unavailable', p.project_index(store)['projects'][0])
