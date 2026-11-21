"""Anonymous diagnostics and nonsecret source-bound Web drafts."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config import management as m
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.config_web.drafts import Drafts
from videocreate.config_web.inspections import Inspections
from videocreate.config_web.service import ConfigService
from videocreate.config_web.errors import WebError


class WebInspectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'config.json'; self.value = m.migrate(config())
        self.secret = 'isolated-legacy-key-sentinel'
        for u in self.value['upstreams'].values(): u['auth']={'type':'bearer','api_key':self.secret}
        atomic_json(self.path,self.value)
        self.service=ConfigService(self.path,read_only=False)
        self.inspections=Inspections(self.service);self.drafts=Drafts(self.service)

    def form(self):
        return {'mode':'create','id':'','url':'https://draft.example.test/v1','name':'未提交上游','notes':'仅备注'}

    def draft(self):
        return self.drafts.save({'source_token':m.fingerprint(self.value),'form':self.form()},session='one')['draft_token']

    def test_draft_recovers_after_server_restart_without_key_or_auto_commit(self):
        original=self.path.read_bytes();token=self.draft()
        restarted=Drafts(self.service)
        version=restarted.load({'draft_token':token},session='after-restart')['draft_version']
        d=restarted.load({'draft_token':token,'claim':True,'expected_version':version},session='after-restart')
        self.assertEqual(d['form'],self.form());self.assertFalse(d['credential_saved'])
        self.assertFalse(d['conflict']);self.assertEqual(self.path.read_bytes(),original)
        self.assertNotIn(self.secret,restarted.path(token).read_text(encoding='utf-8'))
        with self.assertRaises(WebError):
            self.drafts.save({'draft_token':token,'source_token':d['source_token'],'form':self.form()},session='one')

    def test_draft_rejects_key_raw_config_sensitive_url_and_foreign_path(self):
        for extra in ({'key':'unsubmitted-private-key'},{'auth':{}},{'raw_config':{}}):
            with self.assertRaises(WebError):
                self.drafts.save({'source_token':m.fingerprint(self.value),'form':{**self.form(),**extra}},session='one')
        with self.assertRaises(WebError):
            self.drafts.save({'source_token':m.fingerprint(self.value),'form':{**self.form(),'url':'https://draft.example?key=unsubmitted-private-key'}},session='one')
        for token in ('../../config.json',str(self.path),'x'*48):
            with self.assertRaises(WebError):self.drafts.load({'draft_token':token},session='one')
        self.assertFalse(self.drafts.folder.exists())

    def test_draft_source_conflict_expiry_version_and_discard_rules(self):
        token=self.draft();self.value['defaults']['resolution']='1080p';atomic_json(self.path,self.value)
        self.assertTrue(self.drafts.load({'draft_token':token},session='one')['conflict'])
        target=self.drafts.path(token);row=load_json(target);row['expires_at']=time.time()-1;atomic_json(target,row)
        with self.assertRaises(WebError):self.drafts.load({'draft_token':token},session='one')
        row.update(expires_at=time.time()+100,schema_version=99);atomic_json(target,row)
        with self.assertRaises(WebError):self.drafts.load({'draft_token':token},session='one')
        self.assertTrue(target.exists());self.drafts.discard({'draft_token':token,'expected_version':self.drafts.raw(token)[1]},session='one');self.assertFalse(target.exists())

    def test_read_only_cannot_save_claim_or_discard_drafts(self):
        token=self.draft();readonly=Drafts(ConfigService(self.path))
        for call in (lambda:readonly.save({'source_token':m.fingerprint(self.value),'form':self.form()},session='one'),
                     lambda:readonly.load({'draft_token':token,'claim':True},session='one'),
                     lambda:readonly.discard({'draft_token':token},session='one')):
            with self.assertRaises(WebError) as e:call()
            self.assertEqual(e.exception.status,403)

    def test_anonymous_preview_export_is_exact_and_never_reads_external_credentials(self):
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key reads')), \
             mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')):
            p=self.inspections.diagnostic_preview({},session='one')
            result=self.inspections.diagnostic_export({'preview_token':p['preview_token']},session='one')
        target=self.inspections.exported(result['id']);report=load_json(target)
        self.assertEqual(report,p['report'])
        for value in (self.secret,str(self.path),'provider_accounts.'):
            self.assertNotIn(value,target.read_text(encoding='utf-8'))
        with self.assertRaises(WebError):self.inspections.diagnostic_export({'preview_token':p['preview_token']},session='one')
        for bad in ('../config',str(self.path),'x'*48):
            with self.assertRaises(WebError):self.inspections.exported(bad)

    def test_changed_source_expired_or_foreign_diagnostic_preview_cannot_export(self):
        p=self.inspections.diagnostic_preview({},session='one');token=p['preview_token']
        with self.assertRaises(WebError):self.inspections.diagnostic_export({'preview_token':token},session='other')
        self.value['defaults']['resolution']='1080p';atomic_json(self.path,self.value)
        with self.assertRaises(WebError):self.inspections.diagnostic_export({'preview_token':token},session='one')
        self.inspections.previews[token]['expires']=0
        with self.assertRaises(WebError):self.inspections.diagnostic_export({'preview_token':token},session='one')
        self.assertEqual(list(self.inspections.folder.glob('*.json')),[])

    def test_comparison_filter_and_evidence_are_offline_and_allowlisted(self):
        original=self.path.read_bytes();ids=list(self.value['bindings'])[:2]
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key reads')), \
             mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')):
            comparison=self.inspections.compare({'bindings':ids,'scenario':{'operation':'text-to-video','seconds':5}})
            filtered=self.inspections.filter({'scenario':{'operation':'text-to-video','seconds':5}})
            evidence=self.inspections.evidence({'binding':ids[0]})
        for packet in (comparison,filtered,evidence):
            encoded=json.dumps(packet)
            for forbidden in (self.secret,'account_id','secret_ref','"auth"',str(self.path)):
                self.assertNotIn(forbidden,encoded)
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(len(comparison['cards']),2)
        self.assertTrue(filtered['rows'])
        for stages in evidence['operations'].values():
            self.assertEqual({r['status'] for r in stages.values()},{'unverified'})

    def test_evidence_fingerprint_identifies_loaded_config_even_if_file_changes_during_read(self):
        from videocreate.catalog import evidence
        bid = next(iter(self.value['bindings']))
        token = m.fingerprint(self.value); status = evidence.status
        def change_during_read(*args, **kwargs):
            self.value['bindings'][bid]['notes'] = 'Changed without incrementing revision'
            atomic_json(self.path, self.value)
            return status(*args, **kwargs)
        with mock.patch('videocreate.config.storage.resolve_key', side_effect=AssertionError('No key reads')), \
             mock.patch('urllib.request.build_opener', side_effect=AssertionError('No network')):
            with mock.patch.object(evidence, 'status', side_effect=change_during_read):
                old = self.inspections.evidence({'binding': bid})
            current_bytes = self.path.read_bytes()
            current = self.inspections.evidence({'binding': bid})
        self.assertEqual(old['config_token'], token)
        self.assertNotEqual(current['config_token'], token)
        self.assertEqual(current['config_token'], m.fingerprint(self.value))
        self.assertEqual(current['binding'], bid)
        self.assertEqual((current['network_requests'], current['paid_creates']), (0, 0))
        self.assertNotIn(self.secret, json.dumps(current))
        self.assertEqual(self.path.read_bytes(), current_bytes)

    def test_billing_explanation_and_image_comparison_remain_safe_and_read_only(self):
        ids=['grok-on-sub2api','grok-on-newapi']
        self.value['bindings'][ids[0]]['pricing']={'currency':'USD','tiers':[
            {'when':{'resolution':'720p'},'per_request':2}]}
        self.value['bindings'][ids[1]]['pricing']={'currency':'USD','per_second':.22,'per_request':1,
                                                'minimum_seconds':7,'round_seconds':5}
        images=[bid for bid,b in self.value['bindings'].items() if self.value['models'][b['model']]['kind']=='image'][:2]
        self.value['bindings'][images[0]]['pricing']={'currency':'USD','per_request':.04}
        atomic_json(self.path,self.value);before=self.path.read_bytes()
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key reads')), \
             mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')):
            comparison=self.inspections.compare({'bindings':ids,'scenario':{'operation':'text-to-video','seconds':6}})
            image=self.inspections.compare({'bindings':images,'scenario':{'operation':'text-to-image'}})
            filtered=self.inspections.filter({'scenario':{'operation':'text-to-video','seconds':6}})
        self.assertIn('分辨率',comparison['cards'][0]['fields']['本次计费说明'])
        self.assertIn('0.22/秒 × 10 计费秒',comparison['cards'][1]['fields']['本次计费说明'])
        self.assertEqual(image['cards'][0]['fields']['本次估算（非实付）'],'USD 0.04')
        quote=next(r['fit']['quote'] for r in filtered['rows'] if r['id']==ids[0])
        self.assertEqual(quote['calculation']['reason'],'tier_parameters_missing')
        for result in (comparison,image,filtered):
            for forbidden in (self.secret,'account_id','secret_ref',str(self.path),'source_url'):
                self.assertNotIn(forbidden,json.dumps(result))
        self.assertEqual(self.path.read_bytes(),before)

    def test_saved_image_price_uses_transmitted_count_and_cannot_be_spoofed_by_scenario(self):
        from videocreate.config_web.changes import Changes
        changes=Changes(self.service)
        bid='image-primary'
        images=[k for k,b in self.value['bindings'].items() if self.value['models'][b['model']]['kind']=='image'][:2]
        def save(values):
            preview=changes.preview({'operation':'binding.update','id':bid,'values':values,
                'expected_token':m.load(self.path)['token']},session='one')
            return changes.commit({'preview_token':preview['preview_token']},session='one')
        save({'pricing':{'currency':'USD','per_request':.01,'per_image':.04}})
        for omitted in (False,True):
            if omitted:
                options=m.load(self.path)['config']['bindings'][bid]['adapter_options']
                save({'adapter_options':{**options,'image_request_fields':[]}})
            before=self.path.read_bytes()
            with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key reads')), \
                 mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')):
                comparison=self.inspections.compare({'bindings':images,'scenario':{'operation':'text-to-image'}})
                filtered=self.inspections.filter({'scenario':{'operation':'text-to-image'}})
                quote=next(row['fit']['quote'] for row in filtered['rows'] if row['id']==bid)
                self.assertEqual(quote['amount'],None if omitted else .05)
                self.assertEqual(quote['calculation']['billed_images'],None if omitted else 1)
                self.assertEqual(quote['calculation']['reason'],'image_count_unknown' if omitted else 'estimated')
                self.assertIn('供应商默认值' if omitted else '0.04/张 × 1',comparison['cards'][0]['fields']['本次计费说明'])
                for action in (lambda:self.inspections.filter({'scenario':{'operation':'text-to-image','image_count':99}}),
                               lambda:self.inspections.compare({'bindings':images,'scenario':{'operation':'text-to-image','image_count':99}})):
                    with self.assertRaises(ConfigError):action()
            self.assertEqual(self.path.read_bytes(),before)

    def test_saved_general_price_does_not_hide_an_unresolved_conditional_tier(self):
        from videocreate.config_web.changes import Changes
        ids=['grok-on-sub2api','grok-on-newapi']
        changes=Changes(self.service)
        preview=changes.preview({'operation':'binding.update','id':ids[0],
            'values':{'pricing':{'currency':'USD','tiers':[
                {'when':{},'per_request':2},{'when':{'resolution':'720p'},'per_request':3}]}},
            'expected_token':m.load(self.path)['token']},session='one')
        self.assertTrue(changes.commit({'preview_token':preview['preview_token']},session='one')['ok'])
        before=self.path.read_bytes()
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key reads')), \
             mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')):
            for resolution,reason,amount in [(None,'tier_parameters_missing',None),('1080p','estimated',2),('720p','tier_ambiguous',None)]:
                scenario={'operation':'text-to-video','seconds':6}
                if resolution:scenario['resolution']=resolution
                comparison=self.inspections.compare({'bindings':ids,'scenario':scenario})
                filtered=self.inspections.filter({'scenario':scenario})
                quote=next(row['fit']['quote'] for row in filtered['rows'] if row['id']==ids[0])
                self.assertEqual(quote['amount'],amount)
                self.assertEqual(quote['calculation']['reason'],reason)
                field=comparison['cards'][0]['fields']['本次估算（非实付）']
                self.assertEqual(field,'USD 2' if amount is not None else '未知，不能用于硬预算')
                for packet in (comparison,filtered):
                    for forbidden in (self.secret,'account_id','secret_ref',str(self.path)):
                        self.assertNotIn(forbidden,json.dumps(packet))
        self.assertEqual(self.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
