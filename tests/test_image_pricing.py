"""Requested output counts, rather than provider defaults, determine image budgets."""
import base64
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_v3_config import config
from test_image_model_routing import PNG
from videocreate.config.management import migrate
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.runtime.budget import estimate_details


class ImagePricingTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.config=migrate(config(),ask=False)
        self.bid='image-primary'
        self.config['budget'].update(currency='USD',max_total=.05,unknown_price_policy='block')
        self.config['bindings'][self.bid]['pricing']={'currency':'USD','per_image':.04}

    def details(self,pricing,**parameters):
        binding=SimpleNamespace(options={'pricing':pricing})
        before=copy.deepcopy(pricing)
        result=estimate_details(binding,0,'USD',parameters=parameters)
        self.assertEqual(pricing,before)
        self.assertEqual(result['actual_payment'],'unknown')
        return result

    def test_schema_accepts_image_rates_and_tiers_but_rejects_video_and_duration_mixing(self):
        self.assertEqual(validate_config(self.config),[])
        item=self.config['bindings'][self.bid]
        item['pricing']={'currency':'USD','tiers':[{'when':{'operation':'text-to-image'},'per_image':.04}]}
        self.assertEqual(validate_config(self.config),[])
        for pricing in ({'currency':'USD','per_image':-.1},
                        {'currency':'USD','per_image':True},
                        {'currency':'USD','per_image':.04,'per_second':.1},
                        {'currency':'USD','per_image':.04,'minimum_seconds':1},
                        {'currency':'USD','per_image':.04,'round_seconds':1},
                        {'currency':'USD','tiers':[{'when':{'minimum_seconds':1},'per_image':.04}]},
                        {'currency':'USD','tiers':[{'when':{'operation':'text-to-video'},'per_image':.04}]},
                        {'currency':'USD','tiers':[{'when':{},'per_image':.04},
                            {'when':{},'per_second':.1}]}):
            with self.subTest(pricing=pricing):
                item['pricing']=pricing
                self.assertTrue(validate_config(self.config))
        item['pricing']={'currency':'USD','per_image':.04}
        self.config['bindings']['grok-on-sub2api']['pricing']=copy.deepcopy(item['pricing'])
        self.assertTrue(any('image' in e.lower() for e in validate_config(self.config)))

    def test_per_image_and_request_rates_add_for_explicit_positive_output_count(self):
        result=self.details({'currency':'USD','per_request':.01,'per_image':.04},
                            operation='text-to-image',image_count=3)
        self.assertEqual(result['amount'],.13)
        self.assertEqual(result['billed_images'],3)
        self.assertEqual(result['per_image'],.04)
        result=self.details({'currency':'USD','per_image':0},operation='image-edit',image_count=1)
        self.assertEqual(result['amount'],0)
        self.assertEqual(result['reason'],'estimated')

    def test_unknown_invalid_counts_and_video_context_never_prove_image_amount(self):
        pricing={'currency':'USD','per_image':.04}
        self.assertEqual(self.details(pricing,operation='text-to-image')['reason'],'image_count_unknown')
        for count in (0,-1,True,1.5,float('inf'),'1'):
            result=self.details(pricing,operation='text-to-image',image_count=count)
            self.assertIsNone(result['amount'])
            self.assertEqual(result['reason'],'image_count_invalid')
        self.assertEqual(self.details(pricing,operation='text-to-video',image_count=1)['reason'],
                         'image_operation_required')

    def test_image_tier_replaces_parent_rates_and_preserves_unknown_and_expiry_rules(self):
        pricing={'currency':'USD','per_image':999,'per_request':999,'tiers':[
            {'when':{'operation':'text-to-image'},'per_image':.04},
            {'when':{'operation':'image-edit'},'per_request':.08}]}
        self.assertEqual(self.details(pricing,operation='text-to-image',image_count=2)['amount'],.08)
        self.assertEqual(self.details(pricing,operation='image-edit')['amount'],.08)
        for extra,reason in [({'status':'unverified'},'price_unverified'),
                             ({'valid_until':'2000-01-01T00:00:00Z'},'price_expired'),
                             ({'currency':'CNY'},'currency_mismatch')]:
            self.assertEqual(self.details({'currency':'USD','per_image':.04,**extra},
                operation='text-to-image',image_count=1)['reason'],reason)

    def test_adapter_count_matches_transmitted_n_and_omitted_n_stays_unknown(self):
        from videocreate.adapters.image import BindingImageClient, requested_image_count
        from videocreate.catalog.bindings import configured_binding
        from videocreate.cli import legacy_engine
        legacy_engine()
        reference=self.root/'reference.png';reference.write_bytes(PNG)
        for fields,expected in [(['n'],1),([],None)]:
            self.config['bindings'][self.bid]['adapter_options']['image_request_fields']=fields
            binding=configured_binding(self.config,self.bid)
            with mock.patch('media_client.request_json',return_value={'data':[]}) as request:
                BindingImageClient(binding).create_payload('fixture',[],size='auto',quality='auto')
            sent=request.call_args.kwargs['value']
            self.assertEqual(requested_image_count(binding),expected)
            self.assertEqual(sent.get('n'),expected)
            with mock.patch('media_client.request_json',return_value={'data':[]}) as request:
                BindingImageClient(binding).create_payload('fixture',[reference],size='auto',quality='auto')
            body=request.call_args.kwargs['body']
            self.assertEqual(b'name="n"' in body,expected is not None)
            if expected is not None:self.assertIn(b'name="n"\r\n\r\n1\r\n',body)

    def test_cli_image_comparison_omits_video_defaults_and_rejects_explicit_video_flags(self):
        from videocreate.management_commands import providers_command
        path=self.root/'config.json';atomic_json(path,self.config);before=path.read_bytes()
        ids=[bid for bid,b in self.config['bindings'].items() if self.config['models'][b['model']]['kind']=='image'][:2]
        args=['compare','--config',str(path),'--operation','text-to-image']
        for bid in ids:args.extend(['--binding',bid])
        with mock.patch('videocreate.cli.print_result') as output:
            self.assertEqual(providers_command(args),0)
        result=output.call_args.args[0]
        self.assertEqual(result['scenario'],{'operation':'text-to-image'})
        self.assertEqual(result['cards'][0]['quote']['amount'],.04)
        for flag,value in [('--seconds','1'),('--resolution','720p'),('--aspect-ratio','16:9')]:
            with self.assertRaisesRegex(ConfigError,'do not apply to image'):
                providers_command([*args,flag,value])
        self.assertEqual(path.read_bytes(),before)

    def test_comparison_and_filter_use_one_requested_output_and_explain_provider_default(self):
        from videocreate.catalog.presentation import compare
        from videocreate.catalog.suitability import query
        ids=[bid for bid,b in self.config['bindings'].items() if self.config['models'][b['model']]['kind']=='image'][:2]
        self.assertIn(self.bid,ids)
        scenario={'operation':'text-to-image'}
        def quotes():
            card=next(c for c in compare(self.config,ids,scenario=scenario)['cards'] if c['id']==self.bid)
            fit=next(r['task_fit'] for r in query(self.config,scenario)['bindings'] if r['id']==self.bid)
            return card,fit
        card,fit=quotes()
        self.assertEqual(card['quote']['amount'],.04)
        self.assertIn('0.04/张 × 1',card['fields']['本次计费说明'])
        self.assertEqual(fit['quote']['calculation']['billed_images'],1)
        self.config['bindings'][self.bid]['adapter_options']['image_request_fields']=[]
        card,fit=quotes()
        self.assertIsNone(card['quote']['amount'])
        self.assertEqual(fit['quote']['calculation']['reason'],'image_count_unknown')

    def project(self):
        from videocreate.planning.profiles import create
        from videocreate.planning.project import save_bundle
        project=self.root/'project'
        bundle=create('image-only',title='Image price fixture',topic='Boat')
        save_bundle(project,bundle)
        return project,bundle

    def test_image_compile_action_preview_payload_and_reserved_estimate_agree(self):
        from videocreate import image_production, generation_actions
        from videocreate.runtime.state import read_state
        from videocreate.cli import legacy_engine
        legacy_engine()
        project,bundle=self.project();path=self.root/'config.json';atomic_json(path,self.config)
        compiled=image_production.compile_plan(project,bundle,self.config,self.root/'store')
        self.assertEqual(compiled['jobs'][0]['estimate'],.04)
        preview=generation_actions.preview(project,path,job_ids=['image-001'],bindings={'image-001':self.bid})
        self.assertEqual(preview['jobs'][0]['budget_estimate'],.04)
        self.assertEqual(preview['jobs'][0]['price']['estimate'],.04)
        with mock.patch('media_client.request_json',return_value={
                'data':[{'b64_json':base64.b64encode(PNG).decode()}]}) as request:
            result=image_production.run(project,bundle,self.config,self.root/'store')
        self.assertTrue(result['ok'])
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['value']['n'],1)
        ledger=read_state(project)['ledger']
        self.assertEqual(len(ledger),1)
        self.assertEqual(ledger[0]['estimated'],.04)
        self.assertIsNone(ledger[0]['actual'])

    def test_image_hard_budget_and_unknown_output_count_block_before_mock_wire_create(self):
        from videocreate import image_production
        from videocreate.runtime.state import read_state
        for unknown in (False,True):
            with self.subTest(unknown=unknown):
                self.root=self.root/str(unknown);self.root.mkdir()
                project,bundle=self.project()
                self.config['budget']['max_total']=.05 if unknown else .03
                if unknown:
                    self.config['bindings'][self.bid]['adapter_options']['image_request_fields']=[
                        'size','quality','response_format','output_format']
                with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send:
                    result=image_production.run(project,bundle,self.config,self.root/'store')
                self.assertFalse(result['ok']);send.assert_not_called()
                self.assertIn('Price is unknown' if unknown else 'Monetary budget',result['images'][0]['error'])
                self.assertEqual(read_state(project)['ledger'],[])
                self.assertEqual(read_state(project)['jobs'],{})


if __name__=='__main__':unittest.main()
