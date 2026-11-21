"""Names locate exact identities; ambiguity never becomes a route or credential probe."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_v3_config import config
from videocreate.catalog.identity import identify
from videocreate.config import management as m
from videocreate.config.storage import ConfigError,atomic_json
from videocreate.management_commands import providers_command


class CatalogIdentityTests(unittest.TestCase):
    def setUp(self):
        self.value=m.migrate(config())
        self.uid='primary-sub2api';self.mid='grok-imagine-video-1.5';self.bid='grok-on-sub2api'
        self.value['upstreams'][self.uid]['display_name']='星光测试账户'
        self.value['bindings'][self.bid]['display_name']='我的视频接入'

    def test_four_name_input_combinations_narrow_only_supplied_terms_without_selecting(self):
        before=copy.deepcopy(self.value)
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('no credential lookup')), \
             mock.patch('socket.socket',side_effect=AssertionError('no network')):
            exact=identify(self.value,kind='video',model_name='我的视频接入',upstream_name='星光测试账户')
            self.assertEqual(exact['status'],'identified')
            self.assertEqual(exact['matches'][0]['binding_id'],self.bid)
            for values in ({'upstream_name':'星光测试账户'},{'model_name':self.mid},{}):
                result=identify(self.value,kind='video',**values)
                self.assertEqual(result['status'],'ambiguous')
                self.assertGreater(len(result['matches']),1)
                self.assertFalse(result['selection_changed']);self.assertFalse(result['credentials_checked'])
                self.assertEqual(result['readiness'],'not-checked')
        self.assertEqual(before,self.value)

    def test_duplicate_upstream_names_keep_archived_and_disabled_accounts_in_ambiguity(self):
        for uid in (self.uid,'backup-newapi'):self.value['upstreams'][uid]['display_name']='同名账户'
        self.value['upstreams']['backup-newapi']['archived']=True
        self.value['bindings']['grok-on-newapi']['enabled']=False
        result=identify(self.value,kind='video',model_name=self.mid,upstream_name='同名账户')
        self.assertEqual(result['status'],'ambiguous');self.assertEqual(result['needs_choice'],['upstream'])
        self.assertEqual({r['binding_id'] for r in result['matches']},{self.bid,'grok-on-newapi'})
        self.assertIn('archived',{r['state'] for r in result['matches']})
        pinned=identify(self.value,kind='video',model_name=self.mid,upstream_name='同名账户',upstream=self.uid)
        self.assertEqual(pinned['status'],'identified')

    def test_remote_id_case_and_media_kind_are_exact_without_substring_or_sentence_guessing(self):
        self.value['bindings'][self.bid]['remote_model']='Channel Exact V'
        self.value['bindings']['grok-on-newapi']['remote_model']='Channel exact v'
        for text,bid in (('Channel Exact V',self.bid),('Channel exact v','grok-on-newapi')):
            result=identify(self.value,kind='video',model_name=text)
            self.assertEqual(result['status'],'identified');self.assertEqual(result['matches'][0]['binding_id'],bid)
        for text in ('Channel','channel exact v','请用 Channel Exact V 生成','不存在'):
            self.assertEqual(identify(self.value,kind='video',model_name=text)['matches'],[])
        self.assertEqual(identify(self.value,kind='image',model_name='Channel Exact V')['matches'],[])

    def test_stable_ids_override_label_collisions_and_family_is_only_a_filter(self):
        self.value['upstreams']['backup-newapi']['display_name']=self.uid
        result=identify(self.value,kind='video',upstream_name=self.uid)
        self.assertEqual({r['upstream_id'] for r in result['matches']},{self.uid})
        self.value['bindings']['seedance-on-sub2api']['display_name']=self.mid
        result=identify(self.value,kind='video',model_name=self.mid)
        self.assertEqual({r['model_id'] for r in result['matches']},{self.mid})
        self.assertEqual(result['matches'][0]['matched_by']['model'],['model_id'])
        # A known image ID cannot be reinterpreted as a video label.
        image_id=next(mid for mid,row in self.value['models'].items() if row['kind']=='image')
        self.value['bindings'][self.bid]['display_name']=image_id
        self.assertEqual(identify(self.value,kind='video',model_name=image_id)['matches'],[])
        family=identify(self.value,kind='video',model_name='grok')
        self.assertGreater(len(family['matches']),1)
        self.assertTrue(all('family' in r['matched_by']['model'] for r in family['matches']))

    def test_known_upstream_without_bindings_is_reported_and_does_not_expand_to_other_accounts(self):
        self.value['upstreams']['fresh']=copy.deepcopy(self.value['upstreams'][self.uid])
        self.value['upstreams']['fresh']['display_name']='刚保存的上游'
        result=identify(self.value,kind='video',upstream_name='刚保存的上游')
        self.assertEqual(result['status'],'no_matches');self.assertEqual(result['matches'],[])
        self.assertEqual([r['id'] for r in result['upstream_matches']],['fresh'])

    def test_cli_is_read_only_and_rejects_execution_and_other_action_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'config.json';atomic_json(path,self.value);before=path.read_bytes()
            output=io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(providers_command(['identify','--config',str(path),'--kind','video',
                    '--upstream-name','星光测试账户','--model-name','我的视频接入']),0)
            self.assertEqual(json.loads(output.getvalue())['matches'][0]['binding_id'],self.bid)
            self.assertEqual(path.read_bytes(),before);self.assertEqual(list(root.iterdir()),[path])
            for args in (['identify','--kind','video','--apply'],['identify','--kind','video','--file','anything'],
                         ['identify'],['list','--model-name','我的视频接入']):
                with self.assertRaises((ConfigError,SystemExit)),redirect_stdout(io.StringIO()):
                    providers_command([*args,'--config',str(path)])

    def test_projection_redacts_known_auth_strings_and_omits_private_objects(self):
        for uid,field,text in ((self.uid,'api_key','inline-private-marker'),('backup-newapi','env','ENV_PRIVATE_MARKER'),
                               ('image-service','secret_ref','dpapi:private-marker')):
            self.value['upstreams'][uid]['auth']={'type':'bearer',field:text}
            self.value['upstreams'][uid]['display_name']='Saved '+text
        self.value['bindings'][self.bid]['display_name']='inline-private-marker ENV_PRIVATE_MARKER dpapi:private-marker'
        result=identify(self.value,kind='video',upstream=self.uid)
        encoded=json.dumps(result)
        for text in ('inline-private-marker','ENV_PRIVATE_MARKER','dpapi:private-marker','account_id','base_url','auth','notes'):
            self.assertNotIn(text,encoded)
        self.assertIn('[hidden]',encoded)
        self.assertFalse(result['credentials_checked'])

    def test_redacted_canonical_ids_require_review_and_no_binding_upstreams_remain_flagged(self):
        self.value['upstreams'][self.uid]['auth']={'type':'bearer','api_key':self.uid}
        unique=identify(self.value,kind='video',upstream=self.uid,model_name=self.mid)
        self.assertEqual(unique['status'],'review_required');self.assertTrue(unique['identifiers_redacted'])
        self.assertEqual(unique['matches'][0]['upstream_id'],'[hidden]')
        self.value['bindings']={bid:b for bid,b in self.value['bindings'].items() if b['upstream']!=self.uid}
        empty=identify(self.value,kind='video',upstream=self.uid)
        self.assertEqual(empty['status'],'no_matches');self.assertTrue(empty['identifiers_redacted'])
        self.assertEqual(empty['upstream_matches'][0]['id'],'[hidden]')

    def test_invalid_terms_and_missing_kind_fail_without_echoing_input(self):
        for kwargs in ({'kind':'audio'},{'kind':'video','model_name':''},{'kind':'video','upstream_name':42}):
            with self.assertRaises(ConfigError):identify(self.value,**kwargs)


if __name__=='__main__':unittest.main()
