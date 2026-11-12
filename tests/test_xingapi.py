import copy
import tempfile
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.cli import legacy_engine
from videocreate.catalog.bindings import configured_binding
from videocreate.config.management import migrate
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError
from videocreate.runtime.jobs import client

legacy_engine()
import media_client as wire
from provider_contracts import SubmissionUnknownError, ProviderTaskFailedError
from vc_common import APIError, SkillError


class XingAPIContractTests(unittest.TestCase):
    def setUp(self):
        self.config = migrate(config())
        bid = next(bid for bid, b in self.config['bindings'].items() if b['adapter'] == 'sub2api-json-v1')
        b = self.config['bindings'][bid]
        b.update(adapter='xingapi-video-v1', remote_model='seedance2.5-V', operations=['text-to-video'],
                 capability_overrides={'duration': {'minimum': 5, 'maximum': 30, 'step': 1},
                    'resolutions': ['720p'], 'aspect_ratios': ['16:9'], 'audio_control': 'model-default',
                    'max_reference_images': 0, 'max_additional_reference_images': 0})
        self.binding = configured_binding(self.config, bid)
        self.client = client(self.binding)
        self.kwargs = {'seconds': 5, 'size': 'auto', 'resolution': '720p', 'aspect_ratio': '16:9', 'generate_audio': False}

    def test_exact_wire_fields_nested_task_id_and_no_optional_audio(self):
        self.assertEqual(validate_config(self.config), [])
        with mock.patch.object(wire, 'request_json', return_value={'data': {'request_id': 'videoprep_exact', 'status': 'queued'}}) as send:
            self.assertEqual(self.client.create('Five second fixture', **self.kwargs), 'videoprep_exact')
        self.assertEqual(send.call_args.args[0], 'POST')
        self.assertTrue(send.call_args.args[1].endswith('/v1/videos/generations'))
        self.assertEqual(send.call_args.kwargs['value'], {'model': 'seedance2.5-V', 'prompt': 'Five second fixture',
            'duration': 5, 'ratio': '16:9', 'resolution': '720p'})
        self.assertEqual(self.client.last_submission['create_response']['data']['request_id'], 'videoprep_exact')

    def test_empty_task_does_not_retry_and_retains_redacted_response(self):
        self.binding.key  # Key remains in memory only.
        with mock.patch.object(wire, 'request_json', return_value={'status': 'queued', 'api_key': 'secret'}) as send:
            with self.assertRaises(SubmissionUnknownError):
                self.client.create('Fixture prompt', **self.kwargs)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.client.last_submission['create_response']['api_key'], '***')

    def test_local_reference_and_fractional_duration_fail_before_send(self):
        with mock.patch.object(wire, 'request_json') as send:
            with self.assertRaisesRegex(ConfigError, 'HTTPS'):
                self.client.create('Fixture prompt', **self.kwargs, primary_reference=Path('local.png'))
            with self.assertRaises(ConfigError):
                self.client.create('Fixture prompt', **{**self.kwargs, 'seconds': 5.5})
            send.assert_not_called()

    def test_query_encodes_complete_id_and_normalizes_case(self):
        with mock.patch.object(wire, 'request_json', return_value={'data': {'status': 'SuCcEeDeD', 'model': 'seedance2.5-V'}}) as query:
            status, payload = self.client.query('videoprep_a/b')
        self.assertEqual(status, 'succeeded')
        self.assertTrue(query.call_args.args[1].endswith('/videos/videoprep_a%2Fb'))
        self.assertEqual(payload['model'], 'seedance2.5-V')

    def test_retry_after_and_invalid_json_read_never_recreate(self):
        with mock.patch.object(self.client, 'query', side_effect=[APIError(429, 'later', retry_after='47'),
                SkillError('provider returned invalid JSON'), ('completed', {'status': 'completed'})]), \
                mock.patch('videocreate.adapters.xingapi.time.sleep') as sleep, mock.patch.object(self.client, 'create') as create:
            self.client.poll('videoprep_one', timeout_seconds=600)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [47, 30])
        create.assert_not_called()

    def test_terminal_failed_http_200_stops_polling(self):
        with mock.patch.object(self.client, 'query', return_value=('failed', {'status': 'failed', 'error': {'message': 'fixture rejection'}})), \
                mock.patch('videocreate.adapters.xingapi.time.sleep') as sleep:
            with self.assertRaises(ProviderTaskFailedError):
                self.client.poll('videoprep_one', timeout_seconds=600)
        sleep.assert_not_called()

    def test_python39_socket_timeout_resumes_same_task(self):
        with mock.patch.object(self.client, 'query', side_effect=[socket.timeout('read timeout'),
                ('completed', {'status': 'completed'})]) as query, mock.patch('videocreate.adapters.xingapi.time.sleep'):
            self.client.poll('videoprep_same', timeout_seconds=600)
        self.assertEqual([c.args[0] for c in query.call_args_list], ['videoprep_same', 'videoprep_same'])

    def test_download_uses_original_authenticated_endpoint_and_rejects_noncompleted(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'source.mp4'
            with mock.patch.object(wire, 'download_file') as download, mock.patch.object(wire, 'assert_mp4'):
                with self.assertRaises(ConfigError):
                    self.client.download('videoprep_a', {'status': 'queued'}, target)
                download.assert_not_called()
                self.client.download('videoprep_a', {'status': 'completed', 'video_url': 'https://storage.invalid/signed'}, target)
            self.assertTrue(download.call_args.args[0].endswith('/videos/videoprep_a/content'))
            self.assertEqual(download.call_args.kwargs['key'], self.binding.key)
            self.assertIn('video/', download.call_args.kwargs['expected_content_types'])


class XingAPITransportTests(unittest.TestCase):
    def test_redirect_does_not_forward_key_and_json_is_never_saved_as_video(self):
        observed = []
        class Storage(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append(('storage', self.headers.get('Authorization')))
                self.send_response(200); self.send_header('Content-Type', 'video/mp4'); self.end_headers()
                self.wfile.write(b'\0\0\0\x18ftypisom' + b'\0' * 32)
            def log_message(self, *_):
                pass
        storage = ThreadingHTTPServer(('127.0.0.1', 0), Storage)
        self.addCleanup(storage.server_close); self.addCleanup(storage.shutdown)
        threading.Thread(target=storage.serve_forever, daemon=True).start()
        class Gateway(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append(('gateway', self.headers.get('Authorization')))
                if self.path == '/json':
                    self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                    self.wfile.write(b'{"error":"not complete"}')
                elif self.path == '/rate':
                    self.send_response(429); self.send_header('Retry-After', '37'); self.end_headers()
                    self.wfile.write(b'{"error":"wait"}')
                else:
                    self.send_response(302)
                    self.send_header('Location', f'http://127.0.0.1:{storage.server_port}/file')
                    self.end_headers()
            def log_message(self, *_):
                pass
        gateway = ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
        self.addCleanup(gateway.server_close); self.addCleanup(gateway.shutdown)
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{gateway.server_port}'
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'video.mp4'
            wire.download_file(url + '/redirect', target, key='fixture-token', expected_content_types=('video/', 'application/octet-stream'))
            wire.assert_mp4(target)
            self.assertEqual(observed, [('gateway', 'Bearer fixture-token'), ('storage', None)])
            before = target.read_bytes()
            with self.assertRaisesRegex(SkillError, 'Content-Type'):
                wire.download_file(url + '/json', target, key='fixture-token', expected_content_types=('video/',))
            self.assertEqual(target.read_bytes(), before)
            with self.assertRaises(APIError) as raised:
                wire.request_json('GET', url + '/rate', key='fixture-token')
            self.assertEqual(raised.exception.retry_after, '37')
