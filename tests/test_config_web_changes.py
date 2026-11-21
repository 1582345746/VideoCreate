"""Config/credential commit boundaries, replay and interruption recovery."""
import json
import os
import tempfile
import unittest
import concurrent.futures
import threading
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config import management as m
from videocreate.config.storage import atomic_json, load_json, resolve_key
from videocreate.config_web.changes import Changes
from videocreate.config_web.errors import WebError
from videocreate.config_web.service import ConfigService


@unittest.skipUnless(os.name == 'nt', 'DPAPI write tests require Windows')
class ConfigWebChangeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'config.json'
        self.value = m.migrate(config())
        atomic_json(self.path, self.value)
        self.changes = Changes(ConfigService(self.path, read_only=False))
        self.session = 'synthetic-browser-session'
        self.key = 'new-private-key-only-for-isolated-fixture'

    def preview(self, operation='upstream.create', values=None, identity=None):
        return self.changes.preview({'operation': operation, 'id': identity,
                                    'values': values if values is not None else {'url':'https://new.example.test/v1'},
                                    'expected_token': m.load(self.path)['token']}, session=self.session)

    def commit(self, p, key=True):
        return self.changes.commit({'preview_token':p['preview_token'], **({'credential':self.key} if key else {})}, session=self.session)

    def test_three_url_key_saves_are_readable_by_existing_core_without_network(self):
        with mock.patch('urllib.request.build_opener', side_effect=AssertionError('No network')):
            for index in range(3):
                p = self.preview(values={'url':'https://provider' + str(index) + '.example.test/v1'})
                self.assertNotIn(self.key, json.dumps(p))
                result = self.commit(p)
                row = load_json(self.path)['upstreams'][result['id']]
                self.assertEqual(resolve_key(row['auth'], store_root=self.path.parent), self.key)
                self.assertEqual(row['display_name'], 'provider' + str(index) + '.example.test')
        self.assertEqual(len(load_json(self.path)['upstreams']), len(self.value['upstreams'])+3)
        for file in self.path.parent.rglob('*.json'):
            self.assertNotIn(self.key, file.read_text(encoding='utf-8'))

    def test_duplicate_commit_returns_one_receipt_and_one_new_upstream(self):
        p = self.preview()
        first = self.commit(p)
        raw = self.path.read_bytes()
        second = self.commit(p)
        self.assertEqual(first, second)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(load_json(self.path)['revision'], 1)

    def test_other_editor_conflict_does_not_even_stage_credentials(self):
        p = self.preview()
        record = m.load(self.path); newer = record['config']; newer['defaults']['resolution'] = '1080p'
        m.save(self.path, newer, expected_token=record['token'])
        raw = self.path.read_bytes()
        with mock.patch('videocreate.config_web.changes.store_credential') as store:
            with self.assertRaises(WebError) as error: self.commit(p)
            self.assertEqual(error.exception.status, 409); store.assert_not_called()
        self.assertEqual(self.path.read_bytes(), raw)

    def test_encryption_failure_preserves_old_config_and_reference(self):
        p = self.preview(); raw = self.path.read_bytes()
        with mock.patch('videocreate.config.secrets.protect', side_effect=OSError('synthetic encryption failure')):
            with self.assertRaises(OSError): self.commit(p)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse((self.path.parent/'secrets.dpapi').exists())

    def test_failure_before_replace_leaves_old_config_and_can_retry_staged_key(self):
        p = self.preview(); raw = self.path.read_bytes()
        real = m.save
        def fail(*args, **kwargs):
            def stop(after):
                kwargs['on_prepared'](after)
                raise OSError('fixture power loss before replace')
            return real(*args, **{**kwargs, 'on_prepared':stop})
        with mock.patch('videocreate.config_web.changes.m.save', side_effect=fail):
            with self.assertRaises(OSError): self.commit(p)
        self.assertEqual(self.path.read_bytes(), raw)
        with mock.patch('videocreate.config_web.changes.store_credential', side_effect=AssertionError('Already staged')):
            result = self.commit(p, key=False)
        self.assertTrue(result['ok'])

    def test_lost_response_after_replace_reconciles_across_new_server_session(self):
        p = self.preview(); real = m.save
        def lost(*args, **kwargs):
            real(*args, **kwargs)
            raise OSError('fixture response lost after committed write')
        with mock.patch('videocreate.config_web.changes.m.save', side_effect=lost):
            with self.assertRaises(OSError): self.commit(p)
        raw = self.path.read_bytes()
        restarted = Changes(ConfigService(self.path, read_only=False))
        with mock.patch('videocreate.config_web.changes.store_credential', side_effect=AssertionError('No replay')):
            result = restarted.commit({'preview_token':p['preview_token']}, session='new-browser-session')
        self.assertTrue(result['recovered'])
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(load_json(self.path)['revision'], 1)

    def test_rotation_preserves_old_version_and_original_upstream_identity(self):
        created = self.commit(self.preview()); uid = created['id']
        old = load_json(self.path)['upstreams'][uid]
        p = self.preview('upstream.rotate', {'same_account':True}, uid)
        self.key = 'rotated-new-test-key'
        self.commit(p)
        new = load_json(self.path)['upstreams'][uid]
        self.assertEqual(old['base_url'], new['base_url'])
        self.assertEqual(old['account_id'], new['account_id'])
        self.assertEqual(resolve_key(old['auth'], store_root=self.path.parent), 'new-private-key-only-for-isolated-fixture')
        self.assertEqual(resolve_key(new['auth'], store_root=self.path.parent), self.key)

    def test_unconfirmed_rotation_address_patch_and_raw_auth_are_rejected(self):
        uid = next(iter(self.value['upstreams']))
        for op, values in [('upstream.rotate', {'same_account':False}),
                           ('upstream.update', {'url':'https://another.example.test'}),
                           ('upstream.update', {'auth':{'api_key':self.key}})]:
            with self.assertRaises(WebError): self.preview(op, values, uid)
        self.assertEqual(load_json(self.path), self.value)

    def test_foreign_or_expired_preview_and_read_only_service_cannot_write(self):
        p = self.preview()
        with self.assertRaises(WebError):
            self.changes.commit({'preview_token':p['preview_token'],'credential':self.key},session='other')
        self.changes.previews[p['preview_token']]['expires'] = 0
        with self.assertRaises(WebError): self.commit(p)
        readonly = Changes(ConfigService(self.path), read_only=True)
        with self.assertRaises(WebError): readonly.preview({}, session=self.session)

    def test_archive_and_metadata_keep_unrelated_fields_and_do_not_touch_jobs(self):
        uid = next(iter(self.value['upstreams']))
        p = self.preview('upstream.update', {'name':'中文名称','notes':'用途记录'}, uid)
        self.commit(p, key=False)
        changed = load_json(self.path)
        self.assertEqual(changed['upstreams'][uid]['auth'], self.value['upstreams'][uid]['auth'])
        self.assertEqual(changed['execution'], self.value['execution'])
        self.commit(self.preview('upstream.archive', {}, uid), key=False)
        final = load_json(self.path)
        self.assertTrue(final['upstreams'][uid]['archived'])
        self.assertTrue(all(not b['enabled'] for b in final['bindings'].values() if b['upstream']==uid))

    def test_status_waits_for_in_flight_commit_before_reporting_no_submission(self):
        uid=next(iter(self.value['upstreams']))
        p=self.preview('upstream.update',{'name':'single committed name'},uid)
        entered=threading.Event();release=threading.Event();real=m.save
        def held(*args,**kwargs):
            entered.set();release.wait(5);return real(*args,**kwargs)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            with mock.patch('videocreate.config_web.changes.m.save',side_effect=held):
                first=pool.submit(self.commit,p,False);self.assertTrue(entered.wait(3))
                status=pool.submit(self.changes.status,{'preview_token':p['preview_token']})
                try:
                    with self.assertRaises(concurrent.futures.TimeoutError):status.result(timeout=.1)
                finally:release.set()
                self.assertTrue(first.result(timeout=5)['ok'])
                self.assertEqual(status.result(timeout=5)['status'],'committed')


if __name__ == '__main__': unittest.main()
