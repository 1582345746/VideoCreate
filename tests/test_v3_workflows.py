from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_v3_config import ROOT, config
from videocreate.config.schema import configuration_schema, validate_config
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.workflows import describe, prepare

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = config()
        save_bundle(self.root, smart_car())

    def test_published_schema_matches_runtime_and_old_configs_are_compatible(self):
        self.assertEqual(configuration_schema(), load_json(ROOT / 'videocreate/assets/schemas/videocreate.config.schema.json'))
        self.assertEqual(validate_config(self.config), [])
        del self.config['browser_services'], self.config['workflows'], self.config['defaults']['workflow']
        self.assertEqual(validate_config(self.config, ready=True), [])

    def test_browser_services_reject_secrets_and_fake_capability_flags(self):
        for key in ('cookies', 'password', 'api_key', 'verified', 'supports_video'):
            changed = copy.deepcopy(self.config)
            changed['browser_services']['museai'][key] = 'do-not-print-this'
            errors = validate_config(changed)
            self.assertTrue(errors)
            self.assertNotIn('do-not-print-this', str(errors))

    def test_service_requires_exact_allowed_origin_and_secure_url(self):
        for url in ('https://elsewhere.test/', 'http://muse.ai/', 'https://u:p@muse.ai/',
                    'https://muse.ai/?token=secret', 'https://muse.ai:bad/', 'https://muse.ai/#secret'):
            changed = copy.deepcopy(self.config)
            changed['browser_services']['museai']['base_url'] = url
            self.assertTrue(validate_config(changed), url)
        self.config['browser_services']['museai']['base_url'] = 'https://muse.ai/create'
        self.assertEqual(validate_config(self.config), [])

    def test_cannot_attach_external_profile_to_builtin_browser(self):
        self.config['browser_services']['museai']['profile_directory'] = 'dedicated-profile'
        self.assertTrue(validate_config(self.config))
        self.config['browser_services']['museai']['driver'] = 'playwright-local'
        self.assertEqual(validate_config(self.config), [])

    def test_workflow_rejects_cycles_forward_references_and_duplicate_stages(self):
        for change in ('forward', 'wrong-kind', 'duplicate'):
            changed = copy.deepcopy(self.config)
            stages = changed['workflows']['muse-image-video']['stages']
            if change == 'forward':
                stages[0]['input_from'] = 'video'
            elif change == 'wrong-kind':
                stages[1]['input_from'] = 'video'
            else:
                stages[1]['id'] = 'image'
            self.assertTrue(validate_config(changed))

    def test_api_and_browser_targets_cannot_be_mixed(self):
        for change in ('model', 'service', 'binding', 'operation'):
            changed = copy.deepcopy(self.config)
            stages = changed['workflows']['api-image-muse-video']['stages']
            if change == 'model':
                stages[1]['model'] = 'grok-imagine-video-1.5'
            elif change == 'service':
                stages[0]['service'] = 'museai'
            elif change == 'binding':
                stages[0]['binding'] = 'grok-on-sub2api'
            else:
                changed['browser_services']['museai']['requested_operations'] = ['text-to-image']
            self.assertTrue(validate_config(changed))

    def test_describe_resolves_api_selection_and_never_reads_keys(self):
        self.config['defaults']['image_model'] = 'gpt-image-2'
        with mock.patch('videocreate.config.storage.resolve_key', side_effect=AssertionError('credential read')):
            result = describe(self.config, 'api-image-muse-video')
        self.assertEqual(result['stages'][0]['binding'], 'image-primary')
        self.assertEqual(result['stages'][1]['driver'], 'codex-browser')
        self.assertEqual(result['stages'][1]['generation'], 'unverified')
        self.assertNotIn('test-only-value', json.dumps(result))
        self.assertFalse(result['automatic_workflow_runner'])

    def test_enabled_browser_is_not_verified_and_needs_no_api_credentials(self):
        for upstream in self.config['upstreams'].values():
            upstream['auth']['api_key'] = ''
        for binding in self.config['bindings'].values():
            binding['enabled'] = False
        self.config['browser_services']['museai']['enabled'] = True
        with mock.patch('socket.socket', side_effect=AssertionError('network')):
            result = prepare(self.root, self.config, 'muse-video', 'video', job_id='job-002')
        packet = load_json(Path(result['packet']))
        self.assertEqual(packet['status'], 'prepared_only')
        self.assertFalse(packet['can_execute'])
        self.assertFalse(packet['budget_reserved'])
        self.assertEqual(packet['submission'], {'status': 'not_submitted', 'task_id': None})
        self.assertIn('generation_capability_unverified', packet['live_checks_required'])
        self.assertIn('Current shot shot-002:', packet['prompt'])
        self.assertNotIn('Current shot shot-010:', packet['prompt'])
        self.assertFalse((self.root / 'state.json').exists())

    def test_prepare_is_idempotent_and_keeps_api_state_unchanged(self):
        atomic_json(self.root / 'state.json', {'existing': 'unknown-submission'})
        before = (self.root / 'state.json').read_bytes()
        first = prepare(self.root, self.config, 'muse-video', 'video', job_id='job-001')
        second = prepare(self.root, self.config, 'muse-video', 'video', job_id='job-001')
        self.assertEqual(first['packet'], second['packet'])
        self.assertEqual((self.root / 'state.json').read_bytes(), before)
        self.assertEqual(len(list((self.root / 'browser-handoffs').rglob('*.json'))), 1)
        self.assertNotIn('test-only-value', Path(first['packet']).read_text(encoding='utf-8'))

    def test_tampered_packet_cannot_be_silently_overwritten(self):
        result = prepare(self.root, self.config, 'muse-video', 'video', job_id='job-001')
        path = Path(result['packet'])
        changed = load_json(path)
        changed['submission']['status'] = 'completed'
        atomic_json(path, changed)
        with self.assertRaisesRegex(ConfigError, 'differs'):
            prepare(self.root, self.config, 'muse-video', 'video', job_id='job-001')

    def test_image_packet_supports_standalone_image_and_actual_reference_edit(self):
        prompt = self.root / 'opening.txt'
        prompt.write_text('A thoughtful strategist beside a small alarm clock.', encoding='utf-8')
        result = prepare(self.root, self.config, 'muse-image', 'image', prompt_file=Path('opening.txt'))
        self.assertEqual(load_json(Path(result['packet']))['prompt'], prompt.read_text(encoding='utf-8'))
        self.config['workflows']['muse-image']['stages'][0]['operation'] = 'image-edit'
        with self.assertRaisesRegex(ConfigError, 'actual local reference'):
            prepare(self.root, self.config, 'muse-image', 'image', prompt_file=prompt)
        (self.root / 'ref.png').write_bytes(PNG)
        result = prepare(self.root, self.config, 'muse-image', 'image', prompt_file=prompt, references=[Path('ref.png')])
        self.assertEqual(load_json(Path(result['packet']))['references'][0]['sha256'], hashlib.sha256(PNG).hexdigest())

    def test_standalone_image_does_not_require_video_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / 'prompt.txt'
            prompt.write_text('A strategist checks a silent alarm clock.', encoding='utf-8')
            result = prepare(root, self.config, 'muse-image', 'image', prompt_file=Path('prompt.txt'))
            packet = load_json(Path(result['packet']))
            self.assertEqual(packet['source']['input_kind'], 'standalone-image')
            self.assertEqual(packet['source']['prompt_sha256'], hashlib.sha256(prompt.read_bytes()).hexdigest())
            self.assertEqual(packet['source']['reference_sha256'], [])
            self.assertEqual(packet['requested_parameters'], {})

    def test_reference_image_must_be_decodable_before_handoff(self):
        prompt = self.root / 'opening.txt'
        prompt.write_text('Repair the supplied portrait.', encoding='utf-8')
        self.config['workflows']['muse-image']['stages'][0]['operation'] = 'image-edit'
        (self.root / 'truncated.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        with self.assertRaisesRegex(ConfigError, 'truncated|decodable|invalid'):
            prepare(self.root, self.config, 'muse-image', 'image', prompt_file=prompt,
                    references=[Path('truncated.png')])

    def test_mixed_video_needs_explicit_image_job_and_hash_verified_reference(self):
        with self.assertRaisesRegex(ConfigError, 'operation differs'):
            prepare(self.root, self.config, 'api-image-muse-video', 'video', job_id='job-001')
        (self.root / 'ref.png').write_bytes(PNG)
        generation = load_json(self.root / 'generation-plan.json')
        generation['jobs'][0].update(operation='image-to-video', references=[
            {'role': 'opening-frame', 'path': 'ref.png', 'sha256': hashlib.sha256(PNG).hexdigest()}])
        atomic_json(self.root / 'generation-plan.json', generation)
        result = prepare(self.root, self.config, 'api-image-muse-video', 'video', job_id='job-001')
        packet = load_json(Path(result['packet']))
        self.assertEqual(packet['references'][0]['role'], 'opening-frame')
        self.assertIn('source_stage_output_provenance_check_required', packet['live_checks_required'])
        (self.root / 'ref.png').write_bytes(PNG + b'changed')
        with self.assertRaisesRegex(ConfigError, 'stale'):
            prepare(self.root, self.config, 'api-image-muse-video', 'video', job_id='job-001')

    def test_text_only_operation_does_not_silently_upload_images(self):
        (self.root / 'ref.png').write_bytes(PNG)
        with self.assertRaisesRegex(ConfigError, 'Text-only'):
            prepare(self.root, self.config, 'muse-video', 'video', job_id='job-001', references=[Path('ref.png')])

    def test_bad_input_does_not_create_packet(self):
        (self.root / 'empty.txt').write_text('', encoding='utf-8')
        with self.assertRaises(ConfigError):
            prepare(self.root, self.config, 'muse-image', 'image', prompt_file=Path('empty.txt'))
        with self.assertRaises(ConfigError):
            prepare(self.root, self.config, 'muse-image', 'image', prompt_file=Path('../outside.txt'))
        self.assertFalse((self.root / 'browser-handoffs').exists())

    def test_cli_lists_and_prepares_workflow_without_network(self):
        path = self.root / 'config.json'
        atomic_json(path, self.config)
        cli = [sys.executable, str(ROOT / 'videocreate/scripts/videocreate.py'), 'workflow']
        result = subprocess.run(cli + ['list', '--config', str(path)], capture_output=True, text=True, check=True)
        self.assertEqual(len(json.loads(result.stdout)['workflows']), 5)
        result = subprocess.run(cli + ['prepare', str(self.root), '--config', str(path), '--workflow', 'muse-video',
                                      '--stage', 'video', '--job', 'job-001'], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['status'], 'prepared_only')


if __name__ == '__main__':
    unittest.main()
