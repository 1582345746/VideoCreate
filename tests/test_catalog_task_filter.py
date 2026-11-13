"""Task search must match executable bounds and never masquerade as readiness."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from test_typed_media_generation import media_limits
from videocreate.catalog import suitability
from videocreate.catalog.bindings import configured_binding,validate_request
from videocreate.config.management import migrate,add_binding
from videocreate.config.storage import ConfigError,atomic_json
from videocreate.management_commands import providers_command


class CatalogTaskFilterTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.value=migrate(config());self.bid='grok-on-sub2api'
        self.task={'operation':'text-to-video','seconds':5,'resolution':'720p','aspect_ratio':'16:9'}

    def fit(self,value=None,bid=None):
        result=suitability.query(self.value,value or self.task)
        return next(row['task_fit'] for row in result['bindings'] if row['id']==(bid or self.bid))

    def typed(self):
        item=self.value['bindings'][self.bid]
        item.update(adapter='xingapi-video-v2',operations=['text-to-video','image-to-video','reference-to-video'])
        item['capability_overrides']={'media_reference_limits':media_limits()}
        return item['capability_overrides']['media_reference_limits']

    def test_matching_scalar_search_is_read_only_without_resolving_keys_or_network(self):
        before=copy.deepcopy(self.value)
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No credential reads')),\
                mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            report=suitability.query(self.value,self.task)
        fit=next(r['task_fit'] for r in report['bindings'] if r['id']==self.bid)
        self.assertTrue(fit['matches']);self.assertFalse(fit['ready_to_create'])
        self.assertEqual(self.value,before);self.assertFalse(list(self.root.iterdir()))
        self.assertFalse(report['selection_changed']);self.assertEqual(report['paid_creates'],0)
        self.assertNotIn('test-only-value',json.dumps(report));self.assertIn('complete request and budget',report['unchecked'])

    def test_each_scalar_exclusion_and_resolution_condition_is_explained(self):
        self.value['bindings'][self.bid]['capability_overrides']['conditions']=[{'when':{'resolution':'1080p'},'max_seconds':6}]
        for changes,word in [({'seconds':31},'Duration'),({'resolution':'8k'},'resolution'),
                ({'aspect_ratio':'99:1'},'aspect_ratio'),({'seconds':7,'resolution':'1080p'},'condition')]:
            with self.subTest(changes=changes):
                fit=self.fit({**self.task,**changes});self.assertFalse(fit['matches'])
                self.assertTrue(any(word in reason for reason in fit['reasons']))

    def test_invalid_shapes_nan_and_boolean_numbers_are_rejected_before_catalog_evaluation(self):
        for value in [None,[],{}, {'operation':'unsupported'},{'operation':[]}, {**self.task,'seconds':True},
                {**self.task,'seconds':float('nan')},{**self.task,'seconds':float('inf')},
                {**self.task,'seconds':0},{**self.task,'resolution':[]},{**self.task,'aspect_ratio':''},
                {**self.task,'generate_audio':1},{**self.task,'reference_counts':[]},
                {**self.task,'reference_counts':{'image':True}},{**self.task,'reference_counts':{'video':-1}},
                {**self.task,'reference_counts':{'audios':1}},{**self.task,'prompt':'Do not accept arbitrary request fields'}]:
            with self.subTest(value=value),self.assertRaises(ConfigError):suitability.query(self.value,value)

    def test_full_request_rejects_nonfinite_or_wrong_duration_without_throwing_arithmetic_error(self):
        binding=configured_binding(self.value,self.bid)
        for seconds in [float('nan'),float('inf'),'bad',True]:
            with self.subTest(seconds=seconds):self.assertFalse(validate_request(binding,{**self.task,'seconds':seconds})['ok'])

    def test_draft_vendor_claims_never_enable_matching(self):
        self.value=add_binding(self.value,identity='draft-wan',upstream='primary-sub2api',model='draft-wan',
            remote_model='Wan-EXACT',family='wan')
        self.value['bindings']['draft-wan'].update(declared_capabilities={'duration':{'maximum':999}},notes='100 images')
        fit=self.fit(bid='draft-wan');self.assertEqual(fit['status'],'excluded')
        self.assertIn('Protocol is not configured',fit['unknowns']);self.assertFalse(fit['matches'])

    def test_disabled_archived_and_unregistered_routes_are_excluded(self):
        for group,key,field in [('bindings',self.bid,'enabled'),('upstreams','primary-sub2api','archived'),
                ('models','grok-imagine-video-1.5','archived')]:
            value=copy.deepcopy(self.value);self.value[group][key][field]=False if field=='enabled' else True
            self.assertFalse(self.fit()['matches']);self.value=value
        self.value['routes']['grok-imagine-video-1.5']['candidates'].remove(self.bid)
        self.assertIn('Binding is not registered in the model route',self.fit()['reasons'])

    def test_legacy_primary_plus_additional_image_counts_obey_separate_limits(self):
        self.value['bindings'][self.bid]['capability_overrides'].update(max_reference_images=4,max_additional_reference_images=2)
        request={**self.task,'operation':'image-to-video','reference_counts':{'image':3}}
        self.assertTrue(self.fit(request)['matches'])
        request['reference_counts']['image']=4
        self.assertIn('Too many additional reference images for this binding',self.fit(request)['reasons'])
        request['reference_counts']['image']=0
        self.assertIn('This operation needs at least one reference image',self.fit(request)['reasons'])

    def test_text_only_rejects_reference_counts_but_unspecified_counts_do_not_invent_zero(self):
        self.assertTrue(self.fit()['matches'])
        self.assertFalse(self.fit({**self.task,'reference_counts':{'image':1}})['matches'])
        self.assertTrue(self.fit({**self.task,'reference_counts':{}})['matches'])

    def test_typed_combined_and_per_type_counts_come_from_executable_contract(self):
        limits=self.typed();limits['maximum_total_count']=3
        request={**self.task,'operation':'reference-to-video','reference_counts':{'image':1,'video':1,'audio':1}}
        self.assertTrue(self.fit(request)['matches'])
        request['reference_counts']['image']=2
        self.assertIn('Too many combined media references',self.fit(request)['reasons'])
        limits['image']['maximum_count']=1
        self.assertIn('image: reference count exceeds binding limit',self.fit(request)['reasons'])

    def test_unknown_typed_limits_and_unspecified_reference_types_remain_unverified(self):
        self.typed();self.value['bindings'][self.bid]['capability_overrides'].pop('media_reference_limits')
        request={**self.task,'operation':'reference-to-video','reference_counts':{'video':1}}
        fit=self.fit(request);self.assertEqual(fit['status'],'unverified');self.assertFalse(fit['matches'])
        self.typed();request.pop('reference_counts')
        self.assertEqual(self.fit(request)['status'],'unverified')

    def test_mixed_reference_combination_audio_switch_and_opening_role_are_checked(self):
        limits=self.typed();limits['allowed_combinations']=[['image'],['audio']]
        request={**self.task,'operation':'reference-to-video','reference_counts':{'image':1,'audio':1}}
        self.assertIn('This media reference combination is not enabled on the binding',self.fit(request)['reasons'])
        limits['audio_reference_with_generated_audio']=False;request['reference_counts']={'audio':1};request['generate_audio']=True
        self.assertIn('Audio reference with generated audio is not enabled for this binding',self.fit(request)['reasons'])
        limits['image']['roles']=['identity'];request.update(operation='image-to-video',reference_counts={'image':1},generate_audio=False)
        self.assertIn('Opening-frame image role is not enabled',self.fit(request)['reasons'])

    def test_count_match_never_approves_actual_missing_media_properties(self):
        self.typed();request={**self.task,'operation':'reference-to-video','reference_counts':{'video':1}}
        self.assertTrue(self.fit(request)['matches'])
        actual={k:v for k,v in request.items() if k!='reference_counts'}
        actual['media_references']=[{'kind':'video'}]
        report=validate_request(configured_binding(self.value,self.bid),actual)
        self.assertFalse(report['ok']);self.assertTrue(any('bytes' in error for error in report['errors']))

    def test_legacy_adapter_does_not_gain_typed_reference_support(self):
        request={**self.task,'operation':'reference-to-video','reference_counts':{'video':1}}
        self.value['bindings'][self.bid]['operations'].append('reference-to-video')
        self.assertIn('This adapter does not transmit typed image/video/audio references',self.fit(request)['reasons'])

    def test_audio_unknown_is_unverified_and_model_default_does_not_claim_switch_transmission(self):
        caps=self.value['bindings'][self.bid]['capability_overrides'];caps['audio_control']='unknown'
        self.assertEqual(self.fit({**self.task,'generate_audio':True})['status'],'unverified')
        caps['audio_control']='unsupported';self.assertFalse(self.fit({**self.task,'generate_audio':True})['matches'])
        caps['audio_control']='model-default';fit=self.fit({**self.task,'generate_audio':False})
        self.assertTrue(fit['matches']);self.assertTrue(any('not transmitted' in text for text in fit['warnings']))

    def test_price_quotes_use_existing_currency_tiers_and_never_rank(self):
        item=self.value['bindings'][self.bid]
        item['pricing']={'currency':'USD','tiers':[{'when':{'operation':'text-to-video','resolution':'720p'},'per_request':4.9}]}
        self.assertEqual(self.fit()['quote']['amount'],4.9)
        self.assertIsNone(self.fit({'operation':'text-to-video'})['quote']['amount'])
        item['pricing']['status']='unverified';self.assertIsNone(self.fit()['quote']['amount'])
        self.assertEqual(self.fit()['quote']['actual_payment'],'unknown')

    def test_image_tasks_and_edit_counts_are_separate_from_video_parameters(self):
        image=next(bid for bid,b in self.value['bindings'].items() if b['adapter']=='openai-images-v1' and b['enabled'])
        task={'operation':'image-edit','reference_counts':{'image':1}}
        self.assertTrue(self.fit(task,bid=image)['matches'])
        task['reference_counts']['image']=2;self.assertFalse(self.fit(task,bid=image)['matches'])
        for extra in [{'seconds':5},{'resolution':'720p'},{'generate_audio':False},{'reference_counts':{'audio':1}}]:
            with self.subTest(extra=extra),self.assertRaises(ConfigError):suitability.query(self.value,{'operation':'text-to-image',**extra})

    def test_filter_composes_with_upstream_family_search_and_favorites(self):
        self.value['bindings'][self.bid].update(favorite=True,notes='夜景')
        report=suitability.query(self.value,self.task,upstream='primary-sub2api',family='grok',query='夜景',favorites=True,order='name')
        self.assertEqual([row['id'] for row in report['bindings']],[self.bid])
        self.assertEqual(report['counts']['parameters-match'],1)

    def test_cli_same_results_with_optional_exclusion_reasons_and_no_files_changed(self):
        path=self.root/'config.json';atomic_json(path,self.value);draft=self.root/'task.json';atomic_json(draft,self.task)
        before=path.read_bytes()
        for extra in [[],['--include-excluded']]:
            output=io.StringIO()
            with redirect_stdout(output):code=providers_command(['filter','--config',str(path),'--scenario-file',str(draft),*extra])
            self.assertEqual(code,0);report=json.loads(output.getvalue());self.assertNotIn('test-only-value',output.getvalue())
            self.assertEqual(len(report['bindings']),sum(report['counts'].values()) if extra else report['counts']['parameters-match'])
        self.assertEqual(path.read_bytes(),before);self.assertEqual(len(list(self.root.iterdir())),2)
        with self.assertRaises(ConfigError):providers_command(['filter','--config',str(path)])
        with self.assertRaises(ConfigError):providers_command(['list','--config',str(path),'--scenario-file',str(draft)])


if __name__=='__main__':unittest.main()
