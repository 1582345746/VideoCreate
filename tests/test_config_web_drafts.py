"""Versioned per-form draft boundaries; recovery never applies configuration."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config import management as m, repair
from videocreate.config.storage import atomic_json, load_json
from videocreate.config_web.drafts import Drafts
from videocreate.config_web.errors import WebError
from videocreate.config_web.service import ConfigService


class WebFormDraftTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'config.json'
        self.value = m.migrate(config()); atomic_json(self.path, self.value)
        self.drafts = Drafts(ConfigService(self.path, read_only=False))
        self.source = m.fingerprint(self.value)

    def binding(self):
        return {'kind':'binding', 'id':next(iter(self.value['bindings'])),
                'display_name':'未保存中文名称', 'notes':'  保留空白\n第二行  ', 'favorite':True,
                'sort_order':'-', 'tags':'中文, pending', 'advanced':True, 'enabled':True,
                'remote_model':'Exact-CASE', 'adapter':'unconfigured', 'operations':[], 'setup_status':'draft',
                'sections':{'listed_pricing':'{\n "amount":0.25, "unit":"second", "currency":"USD"\n}',
                            'pricing':'{"per_second":'}}

    def defaults(self):
        return {'kind':'defaults', 'image':{'binding':'image-id', 'policy':'ask'},
                'video':{'binding':'stale-id', 'policy':'use-default'}}

    def save(self, form, source=None, token=None, version=None):
        return self.drafts.save({'source_token':source or self.source, 'form':form, 'draft_token':token, 'expected_version':version}, session='one')

    def test_binding_restores_safe_raw_fields_but_not_malformed_json(self):
        before = self.path.read_bytes(); form = self.binding()
        result = self.save(form)
        self.assertEqual(result['omitted_sections'], ['pricing'])
        restarted = Drafts(ConfigService(self.path, read_only=False))
        report = restarted.load({'draft_token':result['draft_token'], 'claim':True, 'expected_version':result['draft_version']}, session='new')
        self.assertEqual(report['form']['sort_order'], '-')
        self.assertEqual(report['form']['notes'], form['notes'])
        self.assertEqual(report['form']['sections'], {'listed_pricing':form['sections']['listed_pricing']})
        self.assertFalse(report['conflict']); self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(load_json(restarted.path(result['draft_token']))['form_version'], 2)

    def test_image_price_and_tier_draft_restore_without_dropping_rates_or_saving_config(self):
        form=self.binding();form['id']='image-primary'
        pricing={'currency':'USD','per_image':.04,'tiers':[
            {'when':{'operation':'text-to-image'},'per_image':.04},
            {'when':{'operation':'image-edit'},'per_request':.01,'per_image':.06}]}
        form['sections']={'pricing':json.dumps(pricing,indent=2)}
        before=self.path.read_bytes()
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key reads')):
            result=self.save(form)
            self.assertEqual(result['omitted_sections'],[])
            restarted=Drafts(ConfigService(self.path,read_only=False))
            restored=restarted.load({'draft_token':result['draft_token'],'claim':True,
                'expected_version':result['draft_version']},session='new')
        self.assertEqual(restored['form']['sections'],form['sections'])
        self.assertEqual(self.path.read_bytes(),before)

    def test_defaults_and_repair_source_rules_never_save_or_decrypt_config(self):
        with mock.patch('videocreate.config.storage.resolve_key', side_effect=AssertionError('No credential lookup')):
            result = self.save(self.defaults())
            self.assertEqual(self.drafts.load({'draft_token':result['draft_token']}, session='one')['form'], self.defaults())
            raw = b'{"schema_version":4,}'
            self.path.write_bytes(raw)
            form = {'kind':'repair','mode':'repair','backup_id':'a'*64}
            result = self.save(form, repair.sha(raw))
            self.assertFalse(self.drafts.load({'draft_token':result['draft_token']}, session='one')['conflict'])
            self.path.write_bytes(raw + b' ')
            self.assertTrue(self.drafts.load({'draft_token':result['draft_token']}, session='one')['conflict'])
            self.assertEqual(self.path.read_bytes(), raw + b' ')

    def test_advanced_json_omits_credentials_unknown_fields_and_sensitive_urls(self):
        for section, data in [('adapter_options', {'headers':{'Authorization':'NEVER-PERSIST'}}),
                              ('listed_pricing', {'unit':'image','source':{'kind':'documentation','auth':'NEVER-PERSIST'}}),
                              ('listed_pricing', {'unit':'image','source':{'kind':'documentation','url':'https://example.test?key=NEVER-PERSIST'}}),
                              ('listed_pricing', {'unit':'image','source':{'kind':'documentation','url':'  HTTPS://example.test?key=NEVER-PERSIST'}}),
                              ('listed_pricing', {'unit':'image','source':{'kind':'documentation','url':'file:///NEVER-PERSIST'}}),
                              ('declared_capabilities', {'references':{'images':{'api_key':'NEVER-PERSIST'}}})]:
            with self.subTest(section=section, data=data):
                form = self.binding(); form['sections'] = {section:json.dumps(data)}
                result = self.save(form)
                self.assertEqual(result['omitted_sections'], [section])
                self.assertNotIn('NEVER-PERSIST', self.drafts.path(result['draft_token']).read_text(encoding='utf-8'))
        form = self.binding(); form['sections'] = {'pricing':'{"currency":"USD","per_second":1e999}'}
        result = self.save(form)
        self.assertEqual(result['omitted_sections'], ['pricing'])

    def test_each_kind_rejects_credentials_paths_and_unknown_fields(self):
        for form in [self.binding(), self.defaults(), {'kind':'repair','mode':'restore','backup_id':'a'*64}]:
            for extra in [{'key':'NEVER-PERSIST'}, {'raw_config':{}}, {'auth':{}}, {'path':str(self.path)}]:
                with self.assertRaises(WebError): self.save({**form, **extra})
        for form in [{'kind':'repair','mode':'restore','backup_id':'../config.json'},
                     {**self.defaults(),'image':{'binding':'a','policy':'ask','key':'NEVER-PERSIST'}}]:
            with self.assertRaises(WebError): self.save(form)
        self.assertFalse(self.drafts.folder.exists())

    def test_owner_and_form_identity_cannot_be_repurposed(self):
        result = self.save(self.binding()); token = result['draft_token']
        original = self.drafts.path(token).read_bytes()
        for form in [self.defaults(), {**self.binding(),'id':'different-binding'}]:
            with self.assertRaises(WebError): self.save(form, token=token, version=result['draft_version'])
        self.assertEqual(self.drafts.path(token).read_bytes(), original)
        self.drafts.load({'draft_token':token,'claim':True, 'expected_version':result['draft_version']},session='two')
        with self.assertRaises(WebError): self.save(self.binding(), token=token)

    def test_legacy_v1_draft_survives_new_form_support(self):
        form = {'mode':'create','id':'','url':'https://old.example.test/v1','name':'旧草稿','notes':''}
        result = self.save(form); token = result['draft_token']
        row = load_json(self.drafts.path(token)); self.assertEqual(row['form_version'], 1)
        row.pop('omitted_sections'); atomic_json(self.drafts.path(token), row)
        self.assertEqual(self.drafts.load({'draft_token':token},session='one')['form'],form)
        row.update(form_version=99); atomic_json(self.drafts.path(token),row)
        with self.assertRaises(WebError): self.drafts.load({'draft_token':token},session='one')
        self.assertTrue(self.drafts.path(token).is_file())

    def test_changed_defaults_or_binding_and_restore_backup_have_source_conflicts(self):
        forms = [self.defaults(), self.binding(), {'kind':'repair','mode':'restore','backup_id':'a'*64}]
        tokens = [self.save(form)['draft_token'] for form in forms]
        changed = copy.deepcopy(self.value); changed['defaults']['resolution'] = '1080p'; atomic_json(self.path,changed)
        for token in tokens:
            current = self.drafts.load({'draft_token':token},session='new')
            report = self.drafts.load({'draft_token':token,'claim':True,'expected_version':current['draft_version']},session='new')
            self.assertTrue(report['conflict']); self.assertEqual(report['source_token'],self.source)
        self.assertEqual(load_json(self.path),changed)


if __name__ == '__main__': unittest.main()
