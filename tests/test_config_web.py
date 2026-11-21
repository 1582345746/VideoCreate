"""Local HTTP boundary and browser DTO privacy; synthetic files only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from test_v3_config import config
from videocreate.config import management
from videocreate.config.storage import atomic_json
from videocreate.config_web.app import create_app
from videocreate.config_web.service import ConfigService


class ConfigWebTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'config.json'
        self.value = management.migrate(config())
        self.secret = 'private-browser-sentinel-DO-NOT-RETURN'
        for u in self.value['upstreams'].values():
            u['auth'] = {'type': 'bearer', 'api_key': self.secret}
            u['notes'] = 'legacy accidental paste ' + self.secret
        self.uid = next(iter(self.value['upstreams']))
        self.bid = next(iter(self.value['bindings']))
        self.value['bindings'][self.bid]['notes'] = '普通中文 <script>alert(1)</script> ' + self.secret
        atomic_json(self.path, self.value)
        self.before = self.path.read_bytes()
        self.app = create_app(self.path, port=18787)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:18787', raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def connect(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.client.headers['X-VC-Client'] = '1'
        session = self.client.get('/api/session')
        self.assertEqual(session.status_code, 200)
        self.client.headers['Origin'] = 'http://127.0.0.1:18787'
        self.client.headers['X-VC-CSRF'] = session.json()['csrf_token']
        return response

    def test_cookie_bootstrap_and_static_csp(self):
        response = self.connect()
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie)
        self.assertIn('samesite=strict', cookie)
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('csrf_token', response.text)

    def test_second_tab_keeps_current_cookie_and_csrf_instead_of_invalidating_first_tab(self):
        self.connect();before=self.client.get('/api/session').json()['csrf_token']
        response=self.client.get('/')
        self.assertNotIn('set-cookie',response.headers)
        self.assertEqual(self.client.get('/api/session').json()['csrf_token'],before)

    def test_authenticated_context_is_path_bound_and_stable_across_restart(self):
        self.connect()
        identity = self.client.get('/api/session').json()['config_id']
        self.assertEqual(identity, self.app.state.identity['config_id'])
        self.assertEqual(identity, ConfigService(self.path).identity)
        same = create_app(self.path, port=18787).state.identity['config_id']
        other_path = self.path.with_name('identical-copy.json')
        other_path.write_bytes(self.before)
        other = create_app(other_path, port=18787).state.identity['config_id']
        self.assertEqual(identity, same)
        self.assertNotEqual(identity, other)
        self.assertEqual(ConfigService(other_path).summary()['token'], ConfigService(self.path).summary()['token'])

    def test_foreign_browser_context_cannot_read_or_write_even_with_valid_session(self):
        self.connect()
        identity = self.client.get('/api/session').json()['config_id']
        foreign = '0' * 64 if identity != '0' * 64 else '1' * 64
        with mock.patch.object(self.app.state.service, 'catalog', side_effect=AssertionError('No foreign read')), \
             mock.patch.object(self.app.state.changes, 'preview', side_effect=AssertionError('No foreign preview')), \
             mock.patch.object(self.app.state.changes, 'status', side_effect=AssertionError('No foreign reconciliation')):
            for route, body in [('catalog', None), ('changes/preview', {}), ('changes/status', {})]:
                response = (self.client.get('/api/' + route, headers={'X-VC-Config': foreign}) if body is None else
                            self.client.post('/api/' + route, json=body, headers={'X-VC-Config': foreign}))
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()['error']['code'], 'config_changed')
                self.assertTrue(response.json()['error']['reload_required'])
                for sentinel in (foreign, identity, self.secret, str(self.path)):
                    self.assertNotIn(sentinel, response.text)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_matching_context_keeps_existing_csrf_origin_and_read_only_boundaries(self):
        self.connect()
        self.client.headers['X-VC-Config'] = self.client.get('/api/session').json()['config_id']
        self.assertEqual(self.client.get('/api/catalog').status_code, 200)
        for headers in ({'X-VC-CSRF':'bad'}, {'Origin':'https://foreign.test'}):
            self.assertEqual(self.client.post('/api/changes/preview', json={}, headers=headers).status_code, 403)
        response = self.client.post('/api/changes/preview', json={'operation':'upstream.archive',
            'id':self.uid, 'values':{}, 'expected_token':ConfigService(self.path).summary()['token']})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error']['code'], 'read_only')
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_future_version_with_corrupt_tail_is_also_read_only(self):
        self.path.write_bytes(b'{"schema_version":99,"tail":')
        self.assertEqual(ConfigService(self.path).summary()['status'],'unsupported-version')

    def test_anonymous_reads_and_simple_cross_site_requests_are_rejected(self):
        self.assertEqual(self.client.get('/api/catalog').status_code, 401)
        self.connect()
        self.assertEqual(self.client.get('/api/catalog', headers={'Origin': 'https://attacker.test'}).status_code, 403)
        self.assertEqual(self.client.get('/api/catalog', headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
        self.assertEqual(self.client.get('/api/catalog', headers={'Host': 'attacker.test:18787'}).status_code, 403)
        self.client.headers.pop('X-VC-Client')
        self.assertEqual(self.client.get('/api/catalog').status_code, 401)

    def test_reads_do_not_resolve_keys_or_mutate_config(self):
        self.connect()
        with mock.patch('videocreate.config.storage.resolve_key', side_effect=AssertionError('No credentials')), \
             mock.patch('urllib.request.build_opener', side_effect=AssertionError('No network')):
            response = self.client.get('/api/catalog')
        self.assertEqual(response.status_code, 200)
        text = response.text
        for forbidden in (self.secret, 'secret_ref', 'api_key', 'test-only-value', 'provider_accounts.'):
            self.assertNotIn(forbidden, text)
        data = response.json()
        self.assertEqual(data['summary']['config_path'], str(self.path.resolve()))
        self.assertEqual(len(data['bindings']), len(self.value['bindings']))
        row = next(b for b in data['bindings'] if b['id'] == self.bid)
        self.assertIn('<script>', row['notes'])  # Browser renders ordinary text, not HTML.
        self.assertIn('[已隐藏]', row['notes'])
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_secret_refs_and_environment_names_never_leave_server(self):
        self.value['upstreams'][self.uid]['auth'] = {'type':'bearer', 'secret_ref':'provider_accounts.private-account.7'}
        other = next(uid for uid in self.value['upstreams'] if uid != self.uid)
        self.value['upstreams'][other]['auth'] = {'type':'bearer', 'env':'MY_PRIVATE_KEY_ENV'}
        atomic_json(self.path, self.value)
        self.connect()
        response = self.client.get('/api/catalog')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('private-account', response.text)
        self.assertNotIn('MY_PRIVATE_KEY_ENV', response.text)

    def test_failed_catalog_http_keeps_only_address_matched_documents_and_safe_error(self):
        from videocreate.config.storage import ConfigError
        self.connect()
        for address,expected in [('https://xingapi.top/v1',1),('https://other.example.test/v1',0)]:
            with self.subTest(address=address):
                self.value['upstreams'][self.uid]['base_url']=address
                atomic_json(self.path,self.value);original=self.path.read_bytes()
                with mock.patch('videocreate.config_web.checks.discovery.models',
                                side_effect=ConfigError('HTTP 404 '+self.secret+' private-error')):
                    response=self.client.post('/api/catalog/check',json={'upstream':self.uid})
                self.assertEqual(response.status_code,200)
                packet=response.json()
                self.assertEqual(packet['status'],'not-supported')
                self.assertEqual(len(packet.get('contracts',[])),expected)
                self.assertEqual(packet.get('rows'),[])
                for forbidden in (self.secret,'private-error','api_key','secret_ref','provider_accounts.'):
                    self.assertNotIn(forbidden,response.text)
                self.assertEqual(self.path.read_bytes(),original)

    def test_missing_corrupt_and_future_files_are_preserved(self):
        service = ConfigService(self.path)
        for raw, status in [(b'{"schema_version":4,"api_key":"private-malformed",', 'invalid-json'),
                            (b'{"schema_version":99,"api_key":"private-future"}', 'unsupported-version'),
                            (b'\xff\xfe', 'unreadable')]:
            self.path.write_bytes(raw)
            packet = service.catalog()
            self.assertEqual(packet['summary']['status'], status)
            self.assertEqual(packet['bindings'], [])
            self.assertNotIn('private-', json.dumps(packet))
            self.assertEqual(self.path.read_bytes(), raw)
        self.path.unlink()
        self.assertEqual(service.summary()['status'], 'missing')
        self.assertFalse(self.path.exists())

    def test_write_csrf_content_type_and_size_are_checked_before_routes(self):
        self.connect()
        self.assertEqual(self.client.post('/api/unknown', json={}).status_code, 404)
        self.assertEqual(self.client.post('/api/unknown', json={}, headers={'X-VC-CSRF':'bad'}).status_code, 403)
        self.assertEqual(self.client.post('/api/unknown', content='text').status_code, 415)
        self.assertEqual(self.client.post('/api/unknown', content='x' * (256*1024+1), headers={'Content-Type':'application/json'}).status_code, 413)

    def test_session_expiry_and_method_boundary(self):
        self.connect()
        self.assertEqual(self.client.delete('/api/catalog').status_code, 405)
        self.app.state.sessions.values.clear()
        self.assertEqual(self.client.get('/api/catalog').status_code, 401)

    def test_no_jobs_shell_file_proxy_or_openapi_routes(self):
        self.connect()
        for path in ['/docs', '/openapi.json', '/api/jobs/run', '/api/shell', '/api/files', '/api/proxy']:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        health = self.client.get('/health').json()
        self.assertNotIn('config_path', health)
        self.assertNotIn(str(self.path), json.dumps(health))

    def test_unexpected_exception_response_is_redacted(self):
        self.connect()
        with mock.patch.object(self.app.state.service, 'catalog', side_effect=RuntimeError(self.secret)):
            response = self.client.get('/api/catalog')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(self.secret, response.text)


if __name__ == '__main__':
    unittest.main()
