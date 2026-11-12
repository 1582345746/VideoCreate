import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.catalog.presentation import compare, card, rows, pricing_text
from videocreate.catalog.bindings import configured_binding
from videocreate.catalog.evidence import record, status
from videocreate.config.management import migrate, add_binding
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.media_references import digest


class CatalogPresentationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.config=migrate(config())
        self.a='grok-on-sub2api';self.b='grok-on-newapi'
        self.config['bindings'][self.a]['pricing']={'currency':'USD','status':'confirmed',
            'tiers':[{'when':{'operation':'text-to-video','resolution':'720p'},'per_request':4.9}]}
        self.config['bindings'][self.b]['pricing']={'currency':'CNY','per_second':.2,'minimum_seconds':10,'round_seconds':5}
        self.scenario={'operation':'text-to-video','seconds':6,'resolution':'720p','aspect_ratio':'16:9'}

    def test_condition_tiers_are_visible_with_actual_rate_units_and_currency(self):
        price=pricing_text(self.config['bindings'][self.a]['pricing'])
        self.assertIn('USD 4.9/次',price)
        self.assertIn('文生视频 · 720p',price)
        self.assertNotEqual(price.strip(),'USD')
        self.assertIn('USD 0/次',pricing_text({'currency':'USD','per_request':0}))
        self.assertIn('单位未知',pricing_text(None,{'amount':1,'unit':'unknown'}))
        self.assertIn('币种未知',pricing_text(None,{'amount':4.9,'display_symbol':'$','unit':'request'}))

    def test_comparison_reuses_budget_rules_without_cross_currency_conversion_or_mutation(self):
        before=copy.deepcopy(self.config)
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('Do not read credentials')), \
             mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            result=compare(self.config,[self.a,self.b],store_root=self.root,scenario=self.scenario)
        self.assertEqual([(c['quote']['currency'],c['quote']['amount']) for c in result['cards']],[('USD',4.9),('CNY',2)])
        self.assertTrue(all(c['quote']['actual_payment']=='unknown' for c in result['cards']))
        self.assertEqual(result['paid_creates'],0)
        self.assertEqual(self.config,before)
        self.assertEqual(list(self.root.iterdir()),[])
        self.assertNotIn('test-only-value',json.dumps(result))

    def test_unknown_expired_overlapping_and_listed_prices_never_become_budget_quotes(self):
        item=self.config['bindings'][self.a]
        for price in [None,{'currency':'USD','per_request':1,'status':'unverified'},
                {'currency':'USD','per_request':1,'valid_until':'2000-01-01T00:00:00Z'},
                {'currency':'USD','tiers':[{'when':{},'per_request':1},{'when':{},'per_request':2}]}]:
            item['pricing']=price
            item['listed_pricing']={'amount':.1,'currency':'USD','unit':'request'}
            result=compare(self.config,[self.a,self.b],scenario=self.scenario)
            self.assertIsNone(result['cards'][0]['quote']['amount'])
            self.assertIn('未知',result['cards'][0]['fields']['本次估算（非实付）'])

    def test_parameter_preview_is_not_a_ready_check_and_reference_operation_needs_real_inputs(self):
        result=compare(self.config,[self.a,self.b],scenario=self.scenario)
        preview=result['cards'][0]['parameter_preview']
        self.assertEqual(preview['status'],'parameters-only')
        self.assertIn('no source hashes',preview['scope'])
        self.config['bindings'][self.a]['enabled']=False
        result=compare(self.config,[self.a,self.b],scenario={**self.scenario,'operation':'reference-to-video','seconds':31})
        self.assertEqual(result['cards'][0]['parameter_preview']['status'],'incompatible')
        self.assertTrue(any('disabled' in e for e in result['cards'][0]['parameter_preview']['errors']))

    def test_search_filters_and_sort_are_deterministic_without_rewriting_config(self):
        a=self.config['bindings'][self.a];a.update(notes='电影感\n夜景',tags=['保留原声'],favorite=True)
        before=copy.deepcopy(self.config)
        selected=rows(self.config,kind='video',family='grok',query='夜景 保留原声',favorites=True,order='name')
        self.assertEqual([r['id'] for r in selected],[self.a])
        self.assertEqual(rows(self.config,upstream='backup-newapi',query='夜景'),[])
        self.assertEqual(self.config,before)
        with self.assertRaises(ConfigError):rows(self.config,order='price')

    def test_draft_claims_notes_and_unknowns_remain_separate_from_executable_limits(self):
        self.config=add_binding(self.config,identity='wan-draft',upstream='primary-sub2api',
            model='wan-draft',remote_model='Wan-EXACT',family='wan')
        self.config['bindings']['wan-draft'].update(notes='30 图，10 视频',declared_capabilities={'references':{'images':30,'videos':10,'audios':None}})
        value=card(self.config,'wan-draft',store_root=self.root)
        self.assertEqual(value['fields']['参考执行约束'],'未配置')
        self.assertIn('音频 未知',value['fields']['供应商声明（非实测）'])
        self.assertEqual(value['fields']['接入状态'],'待接入')
        self.assertIn('未配置',value['fields']['逐操作实测'])

    def receipt(self,op,result):
        path=self.root/('evidence-'+op+'-'+result+'.txt');path.write_text('fixture output evidence',encoding='utf-8')
        binding=configured_binding(self.config,self.a)
        return record(self.root,binding,{'stage':'smoke','operation':op,'result':result,
            'binding_fingerprint':binding.snapshot()['fingerprint'],'reviewer_id':'test-fixture','method':'offline-fixture',
            'attempt_id':'fixture','task_id':'fixture','checks':{'downloaded':result=='pass'},
            'evidence':[{'path':str(path),'sha256':digest(path)}]})

    def test_evidence_is_operation_scoped_and_failures_are_not_hidden(self):
        self.receipt('text-to-video','pass')
        self.receipt('image-to-video','fail')
        binding=configured_binding(self.config,self.a)
        self.assertEqual(status(self.root,binding,operation='text-to-video')['stages']['smoke']['status'],'reported_pass')
        self.assertEqual(status(self.root,binding,operation='image-to-video')['stages']['smoke']['status'],'fail')
        self.assertEqual(status(self.root,binding,operation='reference-to-video')['stages']['smoke']['status'],'unverified')
        value=card(self.config,self.a,store_root=self.root)
        self.assertEqual(value['evidence']['text-to-video']['stages']['smoke']['status'],'reported_pass')
        self.assertEqual(value['evidence']['image-to-video']['stages']['smoke']['status'],'fail')

    def test_invalid_selection_or_scenario_fails_without_output(self):
        for ids in [[],[self.a],[self.a,self.a],[self.a,'missing']]:
            with self.assertRaises(ConfigError):compare(self.config,ids,scenario=self.scenario)
        for seconds in (True,0,-1,float('inf'),float('nan'),'five'):
            with self.assertRaises(ConfigError):compare(self.config,[self.a,self.b],scenario={**self.scenario,'seconds':seconds})

    def test_cli_uses_the_same_comparison_without_network_or_generation(self):
        from videocreate.management_commands import providers_command
        path=self.root/'config.json';atomic_json(path,self.config)
        output=io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(providers_command(['compare','--config',str(path),'--binding',self.a,'--binding',self.b,
                '--seconds','6','--resolution','720p','--aspect-ratio','16:9']),0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['cards'][0]['quote']['amount'],4.9)
        self.assertEqual(result['cards'][1]['quote']['amount'],2)
        self.assertEqual(result['paid_creates'],0)


if __name__=='__main__':unittest.main()
