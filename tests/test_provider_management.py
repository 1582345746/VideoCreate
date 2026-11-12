import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_v3_config import config
from videocreate.config import management as m
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.config.schema import validate_config
from videocreate.catalog.bindings import configured_binding, route_bindings, validate_request
from videocreate.config.bridge import engine_settings
from videocreate.runtime.budget import estimate
from videocreate.runtime.jobs import pinned_binding, generate
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.runtime.state import read_state
from videocreate import selection


class ManagementFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'videocreate.config.json'
        self.value = m.migrate(config())
        atomic_json(self.path, self.value)


class ProviderManagementTests(ManagementFixture):
    def test_migration_is_pure_and_keeps_old_fields_and_defaults(self):
        old = config()
        before = copy.deepcopy(old)
        migrated = m.migrate(old)
        self.assertEqual(old, before)
        self.assertEqual(migrated['defaults'], old['defaults'])
        self.assertEqual(migrated['selection']['video']['when_unspecified'], 'ask')
        self.assertEqual(validate_config(old), [])
        self.assertEqual(validate_config(migrated), [])

    def test_draft_with_declared_reference_capability_does_not_enable_generation(self):
        v = m.add_binding(self.value, identity='wan-draft', upstream='primary-sub2api',
                          model='wan-private', remote_model='Wan-Exact', family='wan')
        b = v['bindings']['wan-draft']
        b['notes'] = '30 图、10 视频、10 音频'
        b['declared_capabilities'] = {'references': {'images': 30, 'videos': 10, 'audios': 10, 'combined_total': None}}
        self.assertEqual(validate_config(v), [])
        self.assertNotIn('wan-draft', engine_settings(v)['video_upstreams'])
        with self.assertRaises(ConfigError):
            route_bindings(v, 'wan-private', operation='text-to-video', store_root=self.root)
        b['enabled'] = True
        self.assertTrue(validate_config(v))

    def test_unknown_schema_is_preserved_and_new_fields_need_v4(self):
        v = config()
        v['bindings']['grok-on-sub2api']['notes'] = 'note'
        self.assertTrue(validate_config(v))
        v['schema_version'] = 99
        self.assertTrue(validate_config(v))
        with self.assertRaises(ConfigError):
            m.migrate(v)

    def test_conflicting_editor_cannot_overwrite_new_revision(self):
        first = m.load(self.path)
        v = copy.deepcopy(first['config'])
        v['bindings']['grok-on-sub2api']['notes'] = 'new note'
        result = m.save(self.path, v, expected_token=first['token'])
        self.assertEqual(load_json(Path(result['backup'])), first['config'])
        with self.assertRaisesRegex(ConfigError, 'another editor'):
            m.save(self.path, first['config'], expected_token=first['token'])
        self.assertEqual(load_json(self.path)['bindings']['grok-on-sub2api']['notes'], 'new note')

    def test_address_account_and_delete_need_new_identity_or_archive(self):
        record = m.load(self.path)
        for field, value in [('base_url', 'https://another.example.test'), ('account_id', 'another-account')]:
            v = copy.deepcopy(self.value)
            v['upstreams']['primary-sub2api'][field] = value
            with self.assertRaisesRegex(ConfigError, 'new upstream ID'):
                m.save(self.path, v, expected_token=record['token'])
        archived = m.archive(self.value, 'upstreams', 'primary-sub2api')
        self.assertTrue(all(not b['enabled'] for b in archived['bindings'].values() if b['upstream'] == 'primary-sub2api'))
        self.assertEqual(archived['upstreams']['primary-sub2api']['auth'], self.value['upstreams']['primary-sub2api']['auth'])

    def test_restore_preserves_post_backup_identities_disabled(self):
        before = m.load(self.path)
        added = m.add_binding(self.value, identity='later', upstream='primary-sub2api',
                             model='later-model', remote_model='later-remote', family='wan')
        saved = m.save(self.path, added, expected_token=before['token'])
        m.restore(self.path, saved['backup'], expected_token=saved['token'])
        result = load_json(self.path)
        self.assertIn('later', result['bindings'])
        self.assertFalse(result['bindings']['later']['enabled'])
        self.assertEqual(validate_config(result), [])

    def test_price_and_notes_do_not_change_protocol_identity(self):
        before = configured_binding(self.value, 'grok-on-sub2api').snapshot()
        b = self.value['bindings']['grok-on-sub2api']
        b['notes'] = 'note changed'
        b['pricing'] = {'currency': 'USD', 'per_request': 4.9, 'version': '2'}
        after = configured_binding(self.value, 'grok-on-sub2api').snapshot()
        self.assertEqual(before['fingerprint'], after['fingerprint'])
        b['remote_model'] = 'a different remote model'
        self.assertNotEqual(after['fingerprint'], configured_binding(self.value, 'grok-on-sub2api').snapshot()['fingerprint'])

    def test_character_limit_counts_unicode_without_old_4096_byte_cap(self):
        self.value['bindings']['grok-on-sub2api']['capability_overrides'] = {
            'prompt_limit': {'maximum': 15000, 'counting_rule': 'unicode-codepoints'}}
        b = configured_binding(self.value, 'grok-on-sub2api')
        self.assertTrue(validate_request(b, {'operation': 'text-to-video', 'prompt': '水' * 15000})['ok'])
        self.assertFalse(validate_request(b, {'operation': 'text-to-video', 'prompt': '水' * 15001})['ok'])
        self.value['bindings']['grok-on-sub2api']['capability_overrides']['prompt_limit'] = {
            'maximum': 3, 'counting_rule': 'utf16-code-units'}
        b = configured_binding(self.value, 'grok-on-sub2api')
        self.assertTrue(validate_request(b, {'operation': 'text-to-video', 'prompt': '😀a'})['ok'])
        self.assertFalse(validate_request(b, {'operation': 'text-to-video', 'prompt': '😀😀'})['ok'])

    def test_listed_price_is_not_a_confirmed_budget_and_rounding_is_explicit(self):
        b = self.value['bindings']['grok-on-sub2api']
        b.pop('pricing', None)
        b['listed_pricing'] = {'amount': 4.9, 'display_symbol': '$', 'currency': None, 'unit': 'request'}
        self.assertIsNone(estimate(configured_binding(self.value, 'grok-on-sub2api'), 30, 'USD'))
        b['pricing'] = {'currency': 'USD', 'per_request': 1, 'per_second': .22, 'round_seconds': 5}
        self.assertEqual(estimate(configured_binding(self.value, 'grok-on-sub2api'), 6, 'USD'), 3.2)
        b['pricing']['status'] = 'unverified'
        self.assertIsNone(estimate(configured_binding(self.value, 'grok-on-sub2api'), 6, 'USD'))

    def test_v4_resume_rejects_changed_account_but_accepts_same_account_key_rotation(self):
        snap = configured_binding(self.value, 'grok-on-sub2api').snapshot()
        self.value['upstreams']['primary-sub2api']['auth'] = {'type': 'bearer', 'api_key': 'rotated-test-only'}
        self.assertEqual(pinned_binding(self.value, snap, self.root).key, 'rotated-test-only')
        self.value['upstreams']['primary-sub2api']['account_id'] = 'other'
        with self.assertRaisesRegex(ConfigError, 'account changed'):
            pinned_binding(self.value, snap, self.root)

    def test_shared_capacity_uses_one_gate_and_strictest_member_limit(self):
        from videocreate.runtime.limits import capacity, submission_slot
        for uid in ('primary-sub2api', 'backup-newapi'):
            self.value['upstreams'][uid]['capacity_group'] = 'same-account'
        self.value['upstreams']['primary-sub2api']['max_concurrent_submissions'] = 4
        self.value['upstreams']['backup-newapi']['max_concurrent_submissions'] = 1
        a, limit = capacity(self.value, 'primary-sub2api')
        b, other_limit = capacity(self.value, 'backup-newapi')
        self.assertEqual((a,limit), (b,other_limit))
        with submission_slot(self.root, a, limit):
            with self.assertRaises(ConfigError):
                with submission_slot(self.root, b, other_limit):
                    self.fail('Shared capacity was bypassed')

    def test_tier_prices_need_unique_match_and_correct_currency(self):
        from videocreate.runtime.budget import reserve, summary
        item = self.value['bindings']['grok-on-sub2api']
        item['pricing'] = {'currency':'USD','tiers':[
            {'when':{'resolution':'720p','maximum_seconds':10},'per_request':2},
            {'when':{'resolution':'1080p'},'per_second':.5}]}
        self.assertEqual(validate_config(self.value), [])
        b = configured_binding(self.value, 'grok-on-sub2api')
        self.assertIsNone(estimate(b,6,'USD'))
        self.assertEqual(estimate(b,6,'USD',parameters={'resolution':'720p'}),2)
        self.assertEqual(estimate(b,6,'USD',parameters={'resolution':'1080p'}),3)
        state={'ledger':[{'attempt_id':'a','kind':'video','estimated':2,'actual':None,'currency':'USD'}]}
        with self.assertRaisesRegex(ConfigError,'different currency'):
            reserve(state,{'currency':'CNY','max_total':100},attempt_id='b',job_id='j',kind='video',estimated=3)
        state['ledger'].append({'attempt_id':'b','kind':'video','estimated':3,'actual':None,'currency':'CNY'})
        self.assertIsNone(summary(state)['estimated_known_total'])
        self.assertEqual(summary(state)['by_currency']['USD']['estimated_known_total'],2)


class SelectionTests(ManagementFixture):
    def setUp(self):
        super().setUp()
        self.project = self.root / 'project'
        save_bundle(self.project, smart_car())

    def test_menu_choice_is_stable_and_scoped_to_project(self):
        packet = selection.menu(self.project, self.value, kind='video', store_root=self.root)
        result = selection.choose(self.project, self.value, selection_id=packet['selection_id'], number=1, store_root=self.root)
        self.assertEqual(result['binding_id'], packet['choices'][0]['id'])
        choice = selection.resolve(self.project, self.value, kind='video', store_root=self.root)
        self.assertEqual(choice, (result['model'], result['binding_id']))
        self.assertIsNone(selection.project_choice(self.root / 'other', 'video'))

    def test_stale_number_and_tampered_packet_are_rejected(self):
        packet = selection.menu(self.project, self.value, kind='video', store_root=self.root)
        changed = copy.deepcopy(self.value)
        changed['revision'] += 1
        with self.assertRaisesRegex(ConfigError, 'Configuration changed'):
            selection.choose(self.project, changed, selection_id=packet['selection_id'], number=1, store_root=self.root)
        path = self.project / 'selections' / (packet['selection_id'] + '.json')
        v = load_json(path)
        v['choices'][0]['id'] = 'another'
        atomic_json(path, v)
        with self.assertRaisesRegex(ConfigError, 'packet was changed'):
            selection.choose(self.project, self.value, selection_id=packet['selection_id'], number=1, store_root=self.root)

    def test_unspecified_needs_choice_while_unique_explicit_pair_does_not(self):
        with self.assertRaises(selection.SelectionRequired):
            selection.resolve(self.project, self.value, kind='video', store_root=self.root)
        self.assertEqual(selection.resolve(self.project, self.value, kind='video', store_root=self.root,
            model='grok-imagine-video-1.5', upstream='primary-sub2api'), ('grok-imagine-video-1.5', 'grok-on-sub2api'))

    def test_no_headless_create_or_budget_when_selection_is_missing(self):
        with mock.patch('videocreate.runtime.jobs.client') as factory:
            with self.assertRaises(selection.SelectionRequired):
                generate(self.project, self.value, store_root=self.root, job_ids=['job-001'])
            factory.assert_not_called()
        self.assertEqual(read_state(self.project)['ledger'], [])

    def test_once_choice_does_not_change_project_or_global_defaults(self):
        before = copy.deepcopy(self.value)
        packet = selection.menu(self.project, self.value, kind='video', store_root=self.root)
        selection.choose(self.project, self.value, selection_id=packet['selection_id'], number=1, store_root=self.root, scope='once')
        self.assertIsNone(selection.project_choice(self.project, 'video'))
        self.assertEqual(before, self.value)

    def test_unrelated_bad_credential_does_not_block_explicit_binding(self):
        self.value['upstreams']['backup-newapi']['auth'] = {'type': 'bearer', 'env': 'VIDEOCREATE_TEST_MISSING_KEY'}
        self.assertEqual(validate_config(self.value), [])
        bindings = route_bindings(self.value, 'grok-imagine-video-1.5', operation='text-to-video',
            preferred='grok-on-sub2api', store_root=self.root)
        self.assertEqual([b.id for b in bindings], ['grok-on-sub2api'])

    def test_disabled_project_selection_is_not_silently_replaced(self):
        packet = selection.menu(self.project, self.value, kind='video', store_root=self.root)
        choice = selection.choose(self.project, self.value, selection_id=packet['selection_id'], number=1, store_root=self.root)
        self.value['bindings'][choice['binding_id']]['enabled'] = False
        model, bid = selection.resolve(self.project, self.value, kind='video', store_root=self.root)
        with self.assertRaises(ConfigError):
            route_bindings(self.value, model, preferred=bid, operation='text-to-video', store_root=self.root)

    def test_switch_preserves_all_previous_attempts_unless_explicit_terminal_retry(self):
        from videocreate.runtime.state import save_state
        from videocreate.runtime.jobs import _prepare_job
        bundle = smart_car()
        snapshot = configured_binding(self.value, 'grok-on-sub2api').snapshot()
        for status in ('submitting', 'submission_unknown', 'queued', 'in_progress', 'read_pending', 'completed', 'failed'):
            record = {'status': status, 'task_id': 'original-task', 'binding_snapshot': snapshot}
            save_state(self.project, {'schema_version': 3, 'jobs': {'job-001': record}, 'ledger': []})
            self.assertEqual(selection.video_overrides(self.project, self.value, store_root=self.root,
                job_ids=['job-001'], binding='grok-on-newapi'), {})
            with mock.patch('videocreate.runtime.jobs.client'):
                binding = _prepare_job(self.project, bundle, bundle['generation-plan']['jobs'][0],
                    self.value, self.root, record, retry=None, explicit_jobs={'job-001'},
                    binding_override={'job-001': 'grok-on-newapi'})[0]
            self.assertEqual(binding.id, 'grok-on-sub2api')
        self.assertEqual(selection.video_overrides(self.project, self.value, store_root=self.root,
            job_ids=['job-001'], retry='content', binding='grok-on-newapi'), {'job-001': 'grok-on-newapi'})

    def test_image_unknown_precedes_missing_selection(self):
        from videocreate.assets import generate_image
        from videocreate.runtime.state import save_state
        save_state(self.project, {'schema_version': 3, 'jobs': {'image-a': {'status': 'submission_unknown'}}, 'ledger': []})
        with mock.patch('videocreate.selection.resolve') as resolve:
            with self.assertRaisesRegex(ConfigError, 'original attempt'):
                generate_image(self.project, self.value, store_root=self.root, job_id='image-a',
                    prompt='a blue square', references=[])
        resolve.assert_not_called()


class DiscoveryTests(ManagementFixture):
    def test_catalog_preserves_case_and_import_never_enables_or_erases_notes(self):
        from videocreate.catalog.discovery import models, import_models
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'data': [
            {'id': 'seedance2.5-V'}, {'id': 'seedance2.5-s'}, {'id': 'seedance2.5-V'}]}).encode()
        with mock.patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = response
            catalog = models(self.value, 'primary-sub2api', store_root=self.root)
        self.assertEqual(catalog['ids'], ['seedance2.5-V', 'seedance2.5-s'])
        value, added = import_models(self.value, 'primary-sub2api', catalog['ids'], family='seedance')
        self.assertEqual(len(added), 2)
        self.assertEqual(validate_config(value), [])
        for bid in added:
            self.assertFalse(value['bindings'][bid]['enabled'])
        value['bindings'][added[0]]['notes'] = 'keep my note'
        again, new = import_models(value, 'primary-sub2api', catalog['ids'])
        self.assertEqual(new, [])
        self.assertEqual(value, again)

    def test_catalog_error_does_not_echo_remote_secrets(self):
        from videocreate.catalog.discovery import models
        from urllib.error import HTTPError
        with mock.patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = HTTPError('https://example.test', 401, 'private content', {}, None)
            with self.assertRaisesRegex(ConfigError, 'HTTP 401') as caught:
                models(self.value, 'primary-sub2api', store_root=self.root)
        self.assertNotIn('private content', str(caught.exception))

    def test_gui_and_file_use_same_strict_json_parser(self):
        from videocreate.config.storage import parse_json
        for raw in ('{"a": 1, "a": 2}', '{"a": NaN}', '[]'):
            with self.assertRaises(ConfigError):
                parse_json(raw)
