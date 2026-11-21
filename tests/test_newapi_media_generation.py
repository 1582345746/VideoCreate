"""Same runtime guarantees as XingAPI, with NewAPI's distinct wire contract."""
import copy
import json
import shutil
from unittest import mock

import test_typed_media_generation as typed
from videocreate.adapters.newapi_references import NewAPIReferenceVideoClient
from videocreate.catalog.bindings import configured_binding, validate_request
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.runtime.state import read_state


class NewAPIMediaGenerationTests(typed.TypedMediaGenerationTests):
    adapter = 'newapi-json-v2'
    legacy_adapter = 'newapi-json-v1'
    client_class = NewAPIReferenceVideoClient
    remote_model = '官渠sd2.5-flash(20参任选/10-5-5/5-30秒/720P)'
    duration_field = 'seconds'
    ratio_field = 'aspect_ratio'
    create_endpoint = '/v1/videos'

    def test_inline_transmits_exact_files_without_urls_and_redacts_saved_echo(self):
        import base64
        self.config['bindings'][self.bid]['adapter_options'] = {'reference_transport': 'data-uri'}
        self.assertEqual(validate_config(self.config), [])
        send = self.mock_generation()
        def response(method, url, **kwargs):
            body = kwargs['value']
            return {'task_id': 'inline-task', 'echo': body,
                    'message': 'received ' + body['videos'][0]}
        send.side_effect = response
        with mock.patch.object(typed.refs, 'resolve_transports', side_effect=AssertionError('Inline must not fetch URLs')):
            self.assertTrue(self.run_job()['ok'])
        body = send.call_args.kwargs['value']
        for ref, field in zip(self.references, ['images', 'videos', 'audios']):
            value = body[field][0]
            self.assertTrue(value.startswith('data:'))
            self.assertEqual(base64.b64decode(value.split(',', 1)[1]), (self.root / ref['path']).read_bytes())
        persisted = '\n'.join(p.read_text('utf-8') for p in self.root.rglob('*.json'))
        for field in ['images', 'videos', 'audios']:
            self.assertNotIn(body[field][0], persisted)
        self.assertNotIn('inline_path', persisted)
        self.assertEqual(read_state(self.root)['jobs']['job-001']['task_id'], 'inline-task')

    def test_inline_unknown_submission_never_recreates_and_redacts_error(self):
        self.config['bindings'][self.bid]['adapter_options'] = {'reference_transport': 'data-uri'}
        send = self.mock_generation()
        def fail(method, url, **kwargs):
            raise TimeoutError('echo ' + kwargs['value']['videos'][0])
        send.side_effect = fail
        with self.assertRaises(ConfigError):
            self.run_job()
        with self.assertRaises(ConfigError):
            self.run_job(retry='network', reason='Resume only')
        send.assert_called_once()
        self.assertEqual(read_state(self.root)['jobs']['job-001']['status'], 'submission_unknown')
        self.assertNotIn('data:video/mp4;base64,', (self.root / 'state.json').read_text('utf-8'))

    def test_inline_modified_reference_rejected_before_create(self):
        from videocreate.adapters.inline_media import prepare_inline
        self.config['bindings'][self.bid]['adapter_options'] = {'reference_transport': 'data-uri'}
        binding = configured_binding(self.config, self.bid)
        media = prepare_inline(self.root, self.references)
        video = self.root / self.references[1]['path']
        video.write_bytes(video.read_bytes() + b'changed')
        send = self.mock_generation()
        client = self.client_class(binding)
        with self.assertRaisesRegex(ConfigError, 'changed'):
            client.fields('prompt', {'seconds': 15, 'media_references': media})
        send.assert_not_called()
        self.assertFalse(read_state(self.root)['ledger'])

    def test_inline_transport_is_explicit_and_newapi_v2_only(self):
        self.config['bindings'][self.bid]['adapter_options'] = {'reference_transport': 'data-uri'}
        self.assertEqual(validate_config(self.config), [])
        self.config['bindings'][self.bid]['adapter'] = 'xingapi-video-v2'
        self.assertTrue(any('reference transport requires' in e for e in validate_config(self.config)))

    def test_inline_total_bound_rejects_without_file_reads(self):
        from videocreate.adapters.inline_media import MAX_INLINE_BYTES
        self.config['bindings'][self.bid]['adapter_options'] = {'reference_transport': 'data-uri'}
        client = self.client_class(configured_binding(self.config, self.bid))
        with self.assertRaisesRegex(ConfigError, '32 MiB'):
            client.fields('prompt', {'seconds': 15, 'media_references': [{'bytes': MAX_INLINE_BYTES + 1}]})

    def test_documented_image_fetch_rejection_never_automatically_resubmits(self):
        from vc_common import APIError
        from test_reference_fetch_rejection import MESSAGE
        self.config['upstreams'][self.config['bindings'][self.bid]['upstream']]['base_url'] = 'https://suanliai.top/v1'
        send = self.mock_generation()
        send.side_effect = APIError(400, MESSAGE, 'actual-trace')
        with self.assertRaises(ConfigError):
            self.run_job()
        state = read_state(self.root)
        self.assertEqual(state['jobs']['job-001']['status'], 'rejected')
        self.assertEqual(state['jobs']['job-001']['submission_receipt']['trace_ids']['request_id'], 'actual-trace')
        self.assertIsNone(state['ledger'][0]['actual'])
        with self.assertRaisesRegex(ConfigError, 'explicit retry'):
            self.run_job()
        send.assert_called_once()

    def test_flash_requires_image_and_count_bounds(self):
        binding = configured_binding(self.config, self.bid)
        limits = binding.capabilities['media_reference_limits']
        limits.update(maximum_total_count=20, allowed_combinations=[['image'], ['image', 'video'],
            ['image', 'audio'], ['image', 'video', 'audio']])
        for kind, count in [('image', 10), ('video', 5), ('audio', 5)]:
            limits[kind]['maximum_count'] = count
        media = self.transport_refs()
        request = dict(operation='reference-to-video', prompt='test', seconds=30, resolution='720p',
                       aspect_ratio='16:9', media_references=media)
        self.assertTrue(validate_request(binding, request)['ok'])
        self.assertFalse(validate_request(binding, {**request, 'media_references': media[1:]})['ok'])
        for index, count in [(0, 11), (1, 6), (2, 6)]:
            items = [r for i, r in enumerate(media) if i != index] + [media[index]] * count
            self.assertFalse(validate_request(binding, {**request, 'media_references': items})['ok'])

    def test_reader_poll_download_and_recovery_preserve_output_not_input_urls(self):
        import media_client
        output = 'https://results.example.test/final.mp4?signature=output-access'
        payload = {'status': 'completed', 'video_url': output,
                   'request': {'videos': list(self.urls.values())}, 'message': next(iter(self.urls.values()))}
        def request(method, url, **kwargs):
            if method == 'POST':
                return {'task_id': 'task/with-prefix', 'echo': {'videos': list(self.urls.values())}}
            self.assertTrue(url.endswith('/v1/videos/task%2Fwith-prefix'))
            return copy.deepcopy(payload)
        def download(url, destination, **kwargs):
            if url.endswith('/content'):
                from vc_common import SkillError
                raise SkillError('content endpoint unavailable')
            self.assertEqual(url, output)
            self.assertFalse(kwargs.get('key'))
            shutil.copyfile(self.fixture / 'video.mp4', destination)
        with mock.patch.object(media_client, 'request_json', side_effect=request) as send, \
                mock.patch.object(media_client, 'download_file', side_effect=download):
            self.assertTrue(self.run_job()['ok'])
        self.assertEqual([c.args[0] for c in send.call_args_list], ['POST', 'GET'])
        persisted = '\n'.join(p.read_text('utf-8') for p in self.root.rglob('*.json')
                              if p.name in {'state.json', 'request.json', 'provider-result.json'})
        self.assertNotIn('private-signature', persisted)
        self.assertNotIn('https://media.example.test', persisted)
        self.assertIn(output, persisted)

    def test_trace_only_response_never_becomes_task_id_or_reposts(self):
        send = self.mock_generation()
        send.return_value = {'request_id': 'trace-only'}
        with self.assertRaises(ConfigError):
            self.run_job()
        self.assertEqual(read_state(self.root)['jobs']['job-001']['status'], 'submission_unknown')
        with self.assertRaises(ConfigError):
            self.run_job(retry='network', reason='Resume')
        send.assert_called_once()

    def test_empty_arrays_omitted_and_model_audio_switch_omitted(self):
        self.job['references'] = [self.references[0]]
        atomic_json(self.root / 'generation-plan.json', self.bundle['generation-plan'])
        self.config['bindings'][self.bid]['adapter_options'] = {'include_generate_audio_field': False}
        self.assertEqual(validate_config(self.config), [])
        send = self.mock_generation()
        self.assertTrue(self.run_job()['ok'])
        fields = send.call_args.kwargs['value']
        for name in ['videos', 'audios', 'generate_audio', 'reference_videos', 'duration', 'ratio']:
            self.assertNotIn(name, fields)
        self.assertEqual(len(fields['images']), 1)
