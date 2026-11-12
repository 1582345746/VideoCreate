import hashlib
import http.client
import io
import os
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.error
import wave
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config.management import migrate
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate import media_references as refs
from videocreate import media_server as host


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / 'private name.wav'
        with wave.open(str(self.audio), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b'\x12\x34' * 16000)
        self.server = host.MediaHTTPServer(self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.publication = host.publish(self.root, self.audio, kind='audio',
            public_base_url='https://media.example.test', lifetime_seconds=600)
        self.url_path = urllib.parse.urlsplit(self.publication['url']).path

    def request(self, method='GET', path=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path or self.url_path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_exact_file_head_and_ranges(self):
        expected = self.audio.read_bytes()
        status, headers, body = self.request()
        self.assertEqual((status, body), (200, expected))
        self.assertEqual(headers['Content-Type'], 'audio/wav')
        self.assertEqual(headers['Content-Length'], str(len(expected)))
        status, headers, body = self.request('HEAD')
        self.assertEqual((status, body), (200, b''))
        self.assertEqual(headers['Content-Length'], str(len(expected)))
        for value, wanted in [('bytes=0-63', expected[:64]), ('bytes=-13', expected[-13:]),
                               ('bytes=32000-', expected[32000:])]:
            status, headers, body = self.request(headers={'Range': value})
            self.assertEqual((status, body), (206, wanted))
            self.assertEqual(int(headers['Content-Length']), len(wanted))
        self.assertEqual(self.request(headers={'Range': 'bytes=999999-'})[0], 416)
        self.assertEqual(self.request(headers={'Range': 'bytes=0-1,4-5'})[0], 416)

    def test_no_listing_arbitrary_path_upload_or_token_in_registry(self):
        for path in ('/', '/published.json', '/objects/', '/m/../published.json',
                     self.url_path.replace('reference.wav', '%2e%2e%2fsecret'),
                     self.url_path + '?extra=1', '/m/' + 'a' * 43 + '/reference.wav'):
            self.assertEqual(self.request(path=path)[0], 404)
        for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            self.assertEqual(self.request(method)[0], 405)
        self.assertNotIn(self.url_path.split('/')[2], (self.root/'local-media/published.json').read_text('utf-8'))

    def test_expiry_and_revocation_preserve_source(self):
        with mock.patch('videocreate.media_server.time.time', return_value=self.publication['expires_at'] + 1):
            self.assertEqual(self.request()[0], 404)
        self.assertEqual(self.request()[0], 200)
        host.revoke(self.root, self.publication['publication_id'])
        self.assertEqual(self.request()[0], 404)
        self.assertTrue(self.audio.is_file())

    def test_copy_is_immutable_and_tampered_snapshot_is_not_served(self):
        expected = self.audio.read_bytes()
        self.audio.write_bytes(b'changed original')
        self.assertEqual(self.request()[2], expected)
        snapshot = next((self.root/'local-media/objects').glob('*.wav'))
        snapshot.write_bytes(b'changed snapshot')
        self.assertEqual(self.request()[0], 409)

    def test_reference_kind_hash_and_url_boundaries(self):
        project = self.root/'project'
        reference = refs.register(project, self.audio, kind='audio', role='sound')
        self.assertEqual(refs.prepare_references(project, [reference])[0]['duration_seconds'], 1)
        with self.assertRaises(ConfigError):
            refs.register(project, self.audio, kind='image', role='identity')
        (project/reference['path']).write_bytes(b'not a wave')
        with self.assertRaises(ConfigError):
            refs.prepare_references(project, [reference])
        for url in ('http://media.example.test/a', 'https://localhost/a', 'https://127.0.0.1/a',
                    'https://192.168.1.1/a', 'https://user:password@example.test/a', 'file:///C:/file.mp4'):
            with self.assertRaises(ConfigError):
                refs.public_url(url)

    def test_full_link_hash_check_without_auth_and_reject_wrong_bytes(self):
        # Local HTTP fixture exercises the real GET reader; production URLs still require HTTPS/public DNS.
        url = 'http://127.0.0.1:' + str(self.server.server_port) + self.url_path
        with mock.patch.object(refs, 'public_url'):
            result = refs.verify_url(url, self.publication['media'])
            self.assertEqual(result['sha256'], hashlib.sha256(self.audio.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ConfigError, 'differ'):
                refs.verify_url(url, {**self.publication['media'], 'sha256': '0' * 64})
            with self.assertRaisesRegex(ConfigError, 'HTTP 404'):
                refs.verify_url(url + '/page', self.publication['media'])

    def test_link_refresh_account_scope_and_expiry_do_not_change_reference(self):
        project = self.root/'project'
        reference = refs.register(project, self.audio, kind='audio', role='sound')
        before = dict(reference)
        with mock.patch.dict(os.environ, {'VC_TEST_MEDIA_URL': self.publication['url']}), \
                mock.patch.object(refs, 'verify_url', return_value={'verified_at': time.time()}):
            refs.bind_url(project, reference, upstream_id='one', account_id='account', store_root=self.root,
                          url_env='VC_TEST_MEDIA_URL', expires_at=time.time()+10000)
            self.assertEqual(refs.resolve_transports(project, [reference], upstream_id='one', account_id='account',
                             store_root=self.root)[0]['url'], self.publication['url'])
            for upstream, account in [('two', 'account'), ('one', 'other')]:
                with self.assertRaises(ConfigError):
                    refs.resolve_transports(project, [reference], upstream_id=upstream, account_id=account, store_root=self.root)
            with self.assertRaisesRegex(ConfigError, 'expires'):
                refs.resolve_transports(project, [reference], upstream_id='one', account_id='account',
                                        store_root=self.root, minimum_validity=20000)
        self.assertEqual(reference, before)
        self.assertNotIn(self.publication['url'], (project/'references/transports.json').read_text('utf-8'))

    def test_configuration_remains_optional_and_rejects_bad_domain(self):
        value = migrate(config())
        self.assertEqual(validate_config(value), [])
        value['local_media_server'] = {'port': 8765, 'public_base_url': 'https://media.example.test', 'max_link_seconds':604800}
        self.assertEqual(validate_config(value), [])
        for url in ('http://media.example.test', 'https://media.example.test/path', 'https://media.example.test?key=private'):
            value['local_media_server']['public_base_url'] = url
            self.assertTrue(validate_config(value))

    def test_redirect_to_private_address_is_rejected_before_fetch(self):
        opener = mock.Mock()
        error = urllib.error.HTTPError('https://media.example.test/file', 302, 'redirect',
            {'Location': 'https://127.0.0.1/private'}, io.BytesIO())
        opener.open.side_effect = error
        with mock.patch.object(refs.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]), \
                mock.patch.object(refs.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(ConfigError, 'private'):
                refs.verify_url('https://media.example.test/file', self.publication['media'])
        self.assertEqual(opener.open.call_count, 1)
        request = opener.open.call_args[0][0]
        self.assertNotIn('Authorization', request.headers)
        self.assertNotIn('Cookie', request.headers)

    def test_network_and_incomplete_response_errors_hide_private_url(self):
        url = 'https://media.example.test/private-capability?signature=secret'
        for error in (OSError(url), http.client.IncompleteRead(b'secret-response')):
            with mock.patch.object(refs, 'public_url'), \
                    mock.patch.object(refs.urllib.request, 'build_opener') as builder:
                builder.return_value.open.side_effect = error
                with self.assertRaises(ConfigError) as raised:
                    refs.verify_url(url, self.publication['media'])
            self.assertNotIn('secret', str(raised.exception))
            self.assertNotIn('private-capability', str(raised.exception))

    def test_host_failed_public_verification_revokes_publication(self):
        from videocreate.media_reference_commands import command
        project = self.root/'project'
        project.mkdir()
        atomic_json(project/'project.json', {})
        value = migrate(config())
        upstream = next(iter(value['upstreams']))
        value['local_media_server'] = {'port': 8765, 'public_base_url':'https://media.example.test'}
        config_path = self.root/'config.json'
        atomic_json(config_path, value)
        with mock.patch.object(host, 'status', return_value={'running': True}), \
                mock.patch('videocreate.media_reference_commands.bind_url', side_effect=ConfigError('Public check failed')):
            with self.assertRaisesRegex(ConfigError, 'Public check failed'):
                command(['host', str(project), '--source', str(self.audio), '--kind', 'audio', '--role', 'sound',
                         '--upstream', upstream, '--config', str(config_path)])
        # Only the newly attempted host is revoked; the independent setup publication remains active.
        items = host.published(self.root)
        self.assertEqual(sum(i['revoked'] for i in items), 1)
        self.assertEqual(sum(not i['revoked'] for i in items), 1)
        self.assertEqual(load_json(project/'project.json'), {})
        self.assertFalse((project/'state.json').exists())


class ServiceLifecycleTests(unittest.TestCase):
    def test_unrelated_service_cannot_be_reused_or_stopped(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class OtherHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.send_header('X-VideoCreate-Instance', 'different-instance')
                self.end_headers()
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            server = ThreadingHTTPServer(('127.0.0.1', 0), OtherHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                atomic_json(root/'local-media/server.json', {'status':'serving', 'port':server.server_port,
                    'instance_id':'old-instance', 'pid':os.getpid()})
                self.assertFalse(host.status(root)['running'])
                self.assertFalse(host.stop(root)['stopped'])
                self.assertFalse((root/'local-media/stop.json').exists())
            finally:
                server.shutdown()
                server.server_close()

    def test_background_start_reuse_and_local_stop(self):
        import socket
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            value = migrate(config())
            value['local_media_server'] = {'port': port, 'public_base_url':'https://media.example.test'}
            path = root/'config.json'
            atomic_json(path, value)
            try:
                first = host.start(path)
                self.assertTrue(first['running'])
                second = host.start(path)
                self.assertEqual(second['pid'], first['pid'])
                self.assertTrue(second['reused'])
                self.assertTrue(host.stop(root)['stopped'])
                self.assertFalse(host.status(root)['running'])
            finally:
                host.stop(root)


if __name__ == '__main__':
    unittest.main()
