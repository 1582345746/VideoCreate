"""Private snapshots must never write config or expose raw credentials on disk."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config import drafts, management, secrets
from videocreate.config.storage import ConfigError, atomic_json


@unittest.skipUnless(os.name == 'nt', 'DPAPI requires Windows')
class ConfigDraftTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name);self.path = self.root/'config.json'
        self.value = management.migrate(config());atomic_json(self.path,self.value)
        self.before = self.path.read_bytes();self.token = management.load(self.path)['token']
        self.store = drafts.DraftStore(self.path)

    def save(self, **kwargs):
        self.store.save(self.token,self.value,kwargs.get('forms',[]));return self.store.session

    def test_real_dpapi_roundtrip_never_writes_plaintext_or_configuration(self):
        self.value['bindings']['grok-on-sub2api']['notes']='private-draft-canary-密钥'
        session=self.save(forms=[{'invalid_raw':'{broken JSON'}])
        self.assertEqual(self.store.read(session)['value'],self.value)
        self.assertEqual(self.path.read_bytes(),self.before)
        data=self.store.target.read_bytes()
        for marker in ['private-draft-canary','test-only-value','invalid_raw']:
            self.assertNotIn(marker.encode(),data)
        self.assertEqual(list(self.store.directory.glob('*.tmp')),[])

    def test_active_and_unknown_owner_never_recover_or_discard(self):
        session=self.save();other=drafts.DraftStore(self.path)
        for status in ('active','unknown'):
            with mock.patch.object(drafts,'owner_status',return_value=status):
                self.assertEqual(other.inventory()[0]['status'],status)
                with self.assertRaises(ConfigError):other.recover(session)
                with self.assertRaises(ConfigError):other.discard(session)
        self.assertTrue(self.store.target.exists())

    def test_stopped_recovery_is_read_only_and_scoped_to_exact_configuration(self):
        session=self.save();other=drafts.DraftStore(self.path)
        with mock.patch.object(drafts,'owner_status',return_value='stopped'):
            value=other.recover(session)
            self.assertEqual(value['base_token'],self.token)
            self.assertEqual(other.inventory()[0]['status'],'stopped')
        self.assertTrue(self.store.target.exists());self.assertEqual(self.path.read_bytes(),self.before)
        second=drafts.DraftStore(self.root/'other.json');self.assertNotEqual(second.directory,other.directory)

    def test_configuration_conflict_preserves_encrypted_original(self):
        session=self.save();self.value['revision']+=1;atomic_json(self.path,self.value)
        other=drafts.DraftStore(self.path)
        with mock.patch.object(drafts,'owner_status',return_value='stopped'):
            self.assertEqual(other.inventory()[0]['status'],'conflict')
            with self.assertRaises(ConfigError):other.recover(session)
        self.assertTrue(self.store.target.exists())

    def test_other_version_and_corruption_are_retained_without_plaintext_error(self):
        session=self.save();data=self.store.read(session);data['manager_version']='future'
        import json
        self.store.target.write_bytes(secrets.protect(json.dumps(data).encode()))
        other=drafts.DraftStore(self.path)
        with mock.patch.object(drafts,'owner_status',return_value='stopped'):
            self.assertEqual(other.inventory()[0]['status'],'other-version')
            with self.assertRaises(ConfigError):other.recover(session)
        self.store.target.write_bytes(b'corrupt-private-draft')
        self.assertEqual(other.inventory()[0]['status'],'unreadable')
        with self.assertRaises(ConfigError) as error:other.recover(session)
        self.assertNotIn('private-draft',str(error.exception));self.assertTrue(self.store.target.exists())

    def test_encryption_and_atomic_replace_failure_retain_last_snapshot(self):
        self.save();before=self.store.target.read_bytes()
        with mock.patch.object(secrets,'protect',side_effect=ConfigError('encryption unavailable')):
            with self.assertRaises(ConfigError):self.save()
        with mock.patch.object(drafts.os,'replace',side_effect=OSError('replace unavailable')):
            with self.assertRaises(OSError):self.save()
        self.assertEqual(self.store.target.read_bytes(),before)
        self.assertEqual(list(self.store.directory.glob('*.tmp')),[])

    def test_sessions_do_not_overwrite_and_discard_requires_stopped_owner(self):
        session=self.save();other=drafts.DraftStore(self.path);other.save(self.token,self.value,[])
        self.assertEqual(len(list(self.store.directory.glob('*.dpapi'))),2)
        other.discard();self.assertTrue(self.store.target.exists())
        with mock.patch.object(drafts,'owner_status',return_value='stopped'):other.discard(session)
        self.assertFalse(self.store.target.exists());self.assertEqual(self.path.read_bytes(),self.before)

    def test_invalid_identity_size_and_unsupported_platform_never_write_plaintext(self):
        for session in ('../escape','0'*31,'x'*32):
            with self.assertRaises(ConfigError):self.store.read(session)
        with mock.patch.object(drafts,'MAX_BYTES',10):
            with self.assertRaises(ConfigError):self.save()
        self.assertFalse(self.store.target.exists())


if __name__=='__main__':unittest.main()
