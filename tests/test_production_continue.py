"""Continuation uses saved evidence and exposes no implicit generation route."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from videocreate import production, production_continue as continuation
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.profiles import create
from videocreate.planning.project import save_bundle
from videocreate.production_commands import production_command
from videocreate.runtime.state import save_state


class ProductionContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '项目'
        save_bundle(self.root, smart_car())

    def test_authoring_describes_exact_stage_without_writes_or_provider_access(self):
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('No network')), \
                mock.patch('videocreate.cli.read_config', side_effect=AssertionError('No provider config')):
            result = continuation.describe(self.root)
        self.assertEqual(result['action'], 'inspect-authoring')
        self.assertEqual(result['stage'], 'theme')
        self.assertEqual(result['value']['brief'], load_json(self.root / 'brief.json'))
        self.assertFalse(result['executable'])
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertFalse((self.root / 'production').exists())
        self.assertFalse((self.root / 'state.json').exists())

    def test_checkpoint_advances_plan_only_and_later_edit_invalidates_snapshot(self):
        result = continuation.describe(self.root)
        production.checkpoint(self.root, result['stage'], reason='Checked audience and theme', expected_hash=result['input_hash'])
        self.assertEqual(continuation.describe(self.root)['stage'], 'outline')
        with self.assertRaisesRegex(ConfigError, 'Next step changed'):
            continuation.execute(self.root, expected_token=result['token'])
        self.assertEqual(production.status(self.root)['review']['status'], 'draft_preview')

    def test_generation_and_unknown_submissions_are_explanations_never_dispatches(self):
        production.policy(self.root, 'auto-within-authorization', 'Continue current authorized plan')
        for state, action in [({}, 'generation'), ({'job-001':{'status':'submission_unknown'}}, 'reconcile'),
                ({'job-001':{'status':'queued', 'task_id':'videoprep_original',
                    'binding_snapshot':{'binding_id':'original-account'}}}, 'generation')]:
            save_state(self.root, {'schema_version':3, 'jobs':state, 'ledger':[]})
            before = (self.root / 'state.json').read_bytes()
            with mock.patch('videocreate.runtime.jobs.client', side_effect=AssertionError('No dispatcher')):
                decision = continuation.describe(self.root)
                self.assertEqual(decision['action'], action)
                with self.assertRaisesRegex(ConfigError, 'explicit entry'):
                    continuation.execute(self.root, expected_token=decision['token'])
            self.assertEqual(before, (self.root / 'state.json').read_bytes())
            if action == 'reconcile':self.assertEqual(decision['blocked_jobs'], ['job-001'])

    def test_all_profiles_choose_their_real_import_or_authoring_route(self):
        for profile, action in [('edit-only','import-video'), ('mixed-video','choose-mixed-sources'),
                ('gif-local','import-gif'), ('image-only','inspect-authoring'),
                ('gif-only','inspect-authoring'), ('scenic','inspect-authoring')]:
            root = Path(self.temp.name) / profile
            save_bundle(root, create(profile, title='Continuation', topic='Actual planned subject'))
            self.assertEqual(continuation.describe(root)['action'], action, profile)

    def test_invalid_plan_is_repairable_and_not_executed(self):
        value = load_json(self.root / 'director.json')
        value['shots'][0]['beat_id'] = 'missing-beat'
        atomic_json(self.root / 'director.json', value)
        decision = continuation.describe(self.root)
        self.assertEqual(decision['action'], 'repair-plan')
        self.assertTrue(decision['errors'])
        with self.assertRaisesRegex(ConfigError, 'explicit entry'):
            continuation.execute(self.root, expected_token=decision['token'])

    def test_changed_plan_or_task_rejects_old_executable_token_before_action(self):
        # A current status fixture isolates decision-to-action freshness from rendering.
        current = production.status(self.root)
        current['next'] = {'id':'editing', 'name':'剪辑与声音'}
        with mock.patch('videocreate.production.status', return_value=current):
            decision = continuation.describe(self.root)
            value = load_json(self.root / 'brief.json');value['audience'] = 'changed audience'
            atomic_json(self.root / 'brief.json', value)
            with mock.patch('videocreate.timeline.render.render', side_effect=AssertionError('Stale render')):
                with self.assertRaisesRegex(ConfigError, 'Next step changed'):
                    continuation.execute(self.root, expected_token=decision['token'])
            decision = continuation.describe(self.root)
            save_state(self.root, {'schema_version':3, 'jobs':{'job-001':{'status':'queued'}}, 'ledger':[]})
            with self.assertRaisesRegex(ConfigError, 'Next step changed'):
                continuation.execute(self.root, expected_token=decision['token'])

    def test_animation_authoring_points_to_original_source(self):
        decision = continuation.describe(self.root)
        bundle = production.load_project(self.root)
        bundle['animation'] = {'owned':'sidecar'}
        status = production.status(self.root)
        status['next'] = next(s for s in status['stages'] if s['id']=='script')
        with mock.patch('videocreate.production_continue.load_project', return_value=bundle), \
                mock.patch('videocreate.production.status', return_value=status):
            result = continuation.describe(self.root)
        self.assertEqual(result['stage'], 'script')
        self.assertIsNone(result['edit_layer'])
        self.assertFalse(result['executable'])

    def test_cli_describes_and_requires_token_and_explicit_action(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(production_command(['continue-local', str(self.root)]), 0)
        self.assertEqual(json.loads(output.getvalue())['stage'], 'theme')
        with self.assertRaisesRegex(ConfigError, 'Next step changed'):
            production_command(['continue-local', str(self.root), '--execute'])
        with self.assertRaisesRegex(ConfigError, 'only consumed'):
            production_command(['status', str(self.root), '--execute'])

    def test_local_gif_uses_collection_review_delivery_and_explicit_rebuild(self):
        from PIL import Image
        from videocreate import local_gifs
        root = Path(self.temp.name) / 'local-gif'
        save_bundle(root, create('gif-local', title='Local GIF steps'))
        frames = []
        for number, color in enumerate(('red', 'green', 'blue')):
            path = Path(self.temp.name) / ('frame-'+str(number)+'.png')
            Image.new('RGB', (96, 64), color).save(path);frames.append(path)
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('No network')), \
                mock.patch('videocreate.cli.read_config', side_effect=AssertionError('No provider config')):
            local_gifs.build(root, gif_id='gif-001', frames=frames, fps=10, width=96)
            production.policy(root, 'auto-within-authorization', 'Continue local GIF recipe')
            decision = continuation.describe(root)
            self.assertEqual(decision['action'], 'review-page')
            page = continuation.execute(root, expected_token=decision['token'])
            self.assertTrue(Path(page['page']).is_file())
            self.assertEqual(production.status(root)['review']['status'], 'review_pending')
            # This is an explicitly synthetic receipt used only to exercise the route.
            local_gifs.review(root, gif_id='gif-001', status='pass', reviewer_id='fixture-reviewer',
                observation='Synthetic frame-sequence fixture', temporal_observation=True)
            decision = continuation.describe(root)
            self.assertEqual(decision['action'], 'deliver')
            result = continuation.execute(root, expected_token=decision['token'])
            self.assertEqual(result['status'], 'accepted_delivery')
            generation = load_json(root / 'generation-plan.json')
            generation['local_gifs'][0]['recipe']['width'] = 128
            atomic_json(root / 'generation-plan.json', generation)
            decision = continuation.describe(root)
            self.assertEqual(decision['action'], 'repair-gif')
            with self.assertRaisesRegex(ConfigError, 'explicit entry'):
                continuation.execute(root, expected_token=decision['token'])


if __name__ == '__main__':
    unittest.main()
