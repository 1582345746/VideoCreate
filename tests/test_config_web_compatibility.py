"""Web edits and the original selection/task engine share one synthetic config."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_v3_config import config
from videocreate import selection
from videocreate.catalog.bindings import configured_binding
from videocreate.catalog.identity import identify
from videocreate.config import management as m
from videocreate.config.secrets import store_credential
from videocreate.config.storage import ConfigError, atomic_json, load_json, resolve_key
from videocreate.config_web.changes import Changes
from videocreate.config_web.service import ConfigService
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state


@unittest.skipUnless(os.name=='nt','Versioned synthetic credential integration needs Windows DPAPI')
class WebCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.path=self.root/'config.json';self.value=m.migrate(config())
        self.uid='primary-sub2api';self.bid='grok-on-sub2api'
        upstream=self.value['upstreams'][self.uid]
        upstream['account_id']=self.uid;upstream['credential_version']='fixture-v1'
        upstream['auth']=store_credential(self.root,self.uid,'original-test-key',version='fixture-v1')
        atomic_json(self.path,self.value)
        self.web=Changes(ConfigService(self.path,read_only=False))
        self.project=self.root/'project';save_bundle(self.project,smart_car())

    def change(self,operation,values,identity=None,key=None):
        p=self.web.preview({'operation':operation,'values':values,'id':identity,
            'expected_token':m.load(self.path)['token']},session='fixture')
        return self.web.commit({'preview_token':p['preview_token'],**({'credential':key} if key else {})},session='fixture')

    def edits(self):
        self.change('upstream.update',{'name':'same display name','notes':'metadata only'},self.uid)
        self.change('binding.update',{'display_name':'same display name','notes':'local quote',
            'listed_pricing':{'amount':9,'currency':'USD','unit':'request'}},self.bid)
        image=next(bid for bid,b in self.value['bindings'].items() if b['enabled'] and self.value['models'][b['model']]['kind']=='image')
        self.change('defaults.update',{'video':{'binding':'grok-on-newapi','policy':'use-default'},
            'image':{'binding':image,'policy':'ask'}})
        self.change('upstream.rotate',{'same_account':True},self.uid,key='rotated-test-key')
        self.change('upstream.archive',{},self.uid)

    def test_four_selection_inputs_and_old_number_scope_after_web_edit(self):
        value=m.load(self.path)['config']
        pair=selection.resolve(self.project,value,kind='video',store_root=self.root,
            model='grok-imagine-video-1.5',upstream=self.uid)
        self.assertEqual(pair,('grok-imagine-video-1.5',self.bid))
        menus=[]
        for filters in ({'upstream':self.uid},{'model':'grok-imagine-video-1.5'},{}):
            with self.assertRaises(selection.SelectionRequired) as error:
                selection.resolve(self.project,value,kind='video',store_root=self.root,**filters)
            packet=error.exception.payload;self.assertGreater(len(packet['choices']),1);menus.append(packet)
        second=self.root/'second';save_bundle(second,smart_car())
        foreign=menus[0]
        copied=second/'selections'/(foreign['selection_id']+'.json');atomic_json(copied,foreign)
        with self.assertRaises(ConfigError):
            selection.choose(second,value,selection_id=foreign['selection_id'],number=1,store_root=self.root)
        self.change('upstream.update',{'name':'same display name'},self.uid)
        updated=m.load(self.path)['config']
        for packet in menus:
            with self.assertRaisesRegex(ConfigError,'Configuration changed'):
                selection.choose(self.project,updated,selection_id=packet['selection_id'],number=1,store_root=self.root)
        self.assertIsNone(selection.project_choice(self.project,'image'))
        self.assertFalse((self.project/'state.json').exists())

    def test_known_task_keeps_original_snapshot_and_never_creates_again_after_all_web_edits(self):
        counts={'create':0,'poll':0,'download':0};seen=[];fail=[True]
        class Fake:
            last_submission={}
            def __init__(self,binding):seen.append(binding);self.binding=binding
            def prepare(self,*args,**kwargs):return {}
            def create(self,*args,**kwargs):counts['create']+=1;return 'original-task-id'
            def poll(self,task_id,**kwargs):
                counts['poll']+=1
                if fail[0]:raise TimeoutError('synthetic read interruption')
                assert task_id=='original-task-id'
                return {'status':'completed'}
            def download(self,task_id,payload,target):
                counts['download']+=1;assert task_id=='original-task-id';target.write_bytes(b'fixture clip')
        with mock.patch('videocreate.runtime.jobs.client',side_effect=Fake), \
                mock.patch('videocreate.timeline.render.probe',return_value={'duration':6,'fps':'24/1'}):
            with self.assertRaises(ConfigError):
                jobs.generate(self.project,self.value,store_root=self.root,job_ids=['job-001'],binding_override={'job-001':self.bid})
            original=copy.deepcopy(read_state(self.project)['jobs']['job-001'])
            self.edits();changed=m.load(self.path)['config'];fail[0]=False
            jobs.generate(self.project,changed,store_root=self.root,job_ids=['job-001'],retry='network',
                          reason='resume original synthetic task',allow_create=False)
        final=read_state(self.project)
        self.assertEqual(counts,{'create':1,'poll':2,'download':1})
        self.assertEqual(final['jobs']['job-001']['binding_snapshot'],original['binding_snapshot'])
        self.assertEqual(final['jobs']['job-001']['attempt_id'],original['attempt_id'])
        self.assertEqual(final['jobs']['job-001']['task_id'],'original-task-id')
        self.assertEqual(len(final['ledger']),1)
        self.assertEqual(seen[-1].remote_model,original['binding_snapshot']['remote_model'])
        self.assertEqual(seen[-1].base_url,original['binding_snapshot']['base_url'])
        self.assertEqual(seen[-1].adapter,original['binding_snapshot']['adapter'])
        self.assertEqual(seen[-1].key,'rotated-test-key')
        self.assertEqual(resolve_key(self.value['upstreams'][self.uid]['auth'],store_root=self.root),'original-test-key')

    def test_unknown_submission_is_held_after_web_default_rotation_and_archive(self):
        from videocreate.cli import legacy_engine
        legacy_engine()
        from provider_contracts import SubmissionUnknownError
        with mock.patch('videocreate.runtime.jobs.client') as factory:
            fake=factory.return_value;fake.last_submission={};fake.prepare.return_value={}
            fake.create.side_effect=SubmissionUnknownError('synthetic ambiguous result')
            with self.assertRaises(ConfigError):
                jobs.generate(self.project,self.value,store_root=self.root,job_ids=['job-001'],binding_override={'job-001':self.bid})
        before=read_state(self.project);self.assertEqual(before['jobs']['job-001']['status'],'submission_unknown')
        self.edits()
        with mock.patch('videocreate.runtime.jobs.client') as factory:
            with self.assertRaises(ConfigError):
                jobs.generate(self.project,m.load(self.path)['config'],store_root=self.root,job_ids=['job-001'])
            factory.assert_not_called()
        self.assertEqual(read_state(self.project),before)

    def test_duplicate_labels_do_not_merge_exact_remote_models_or_account_choices(self):
        for uid in (self.uid, 'backup-newapi'):
            self.change('upstream.update', {'name':'Duplicate upstream'}, uid)
        for bid, remote in ((self.bid,'Channel Model / Exact CASE'),
                            ('grok-on-newapi','Channel Model / exact case')):
            self.change('binding.update', {'display_name':'Duplicate model','remote_model':remote}, bid)
        value=m.load(self.path)['config'];before=self.path.read_bytes()
        packet=selection.menu(self.project,value,kind='video',store_root=self.root,
                              model='grok-imagine-video-1.5')
        self.assertEqual({r['id'] for r in packet['choices']},{self.bid,'grok-on-newapi'})
        for row in packet['choices']:
            selected=selection.choose(self.project,value,selection_id=packet['selection_id'],
                                      number=row['number'],scope='once',store_root=self.root)
            binding=configured_binding(value,selected['binding_id'])
            self.assertEqual(binding.remote_model,value['bindings'][row['id']]['remote_model'])
            self.assertEqual(binding.upstream_id,value['bindings'][row['id']]['upstream'])
        # Display labels are not stable aliases and cannot choose an account.
        with self.assertRaises(selection.SelectionRequired) as error:
            selection.resolve(self.project,value,kind='video',store_root=self.root,upstream='Duplicate upstream')
        self.assertEqual(error.exception.payload['choices'],[])
        self.assertEqual(self.path.read_bytes(),before)
        self.assertIsNone(selection.project_choice(self.project,'video'))
        self.assertFalse((self.project/'state.json').exists())

    def test_simultaneous_filtered_menus_and_projects_keep_each_number_and_media_scope(self):
        self.change('upstream.update', {'notes':'Web edit before concurrent menus'}, self.uid)
        value=m.load(self.path)['config'];before=self.path.read_bytes()
        other=self.root/'other-project';save_bundle(other,smart_car())
        packets=[selection.menu(self.project,value,kind='video',store_root=self.root,upstream=uid)
                 for uid in (self.uid,'backup-newapi')]
        image=selection.menu(self.project,value,kind='image',store_root=self.root)
        foreign=selection.menu(other,value,kind='video',store_root=self.root)
        self.assertEqual(len({p['selection_id'] for p in packets+[image,foreign]}),4)
        self.assertNotEqual(packets[0]['choices'][0]['id'],packets[1]['choices'][0]['id'])
        for packet in reversed(packets):
            result=selection.choose(self.project,value,selection_id=packet['selection_id'],number=1,
                                    scope='once',store_root=self.root)
            self.assertEqual(result['binding_id'],packet['choices'][0]['id'])
        video=selection.choose(self.project,value,selection_id=packets[1]['selection_id'],number=1,store_root=self.root)
        picture=selection.choose(self.project,value,selection_id=image['selection_id'],number=1,store_root=self.root)
        self.assertEqual(selection.project_choice(self.project,'video')['binding_id'],video['binding_id'])
        self.assertEqual(selection.project_choice(self.project,'image')['binding_id'],picture['binding_id'])
        self.assertIsNone(selection.project_choice(other,'video'))
        self.assertIsNone(selection.project_choice(other,'image'))
        self.assertEqual(self.path.read_bytes(),before)
        self.change('binding.update', {'notes':'Change after all menus'}, self.bid)
        changed=m.load(self.path)['config']
        for project,packet in [(self.project,p) for p in packets+[image]]+[(other,foreign)]:
            with self.assertRaisesRegex(ConfigError,'Configuration changed'):
                selection.choose(project,changed,selection_id=packet['selection_id'],number=1,store_root=self.root)
        self.assertFalse((self.project/'state.json').exists())
        self.assertFalse((other/'state.json').exists())

    def test_web_saved_names_resolve_offline_then_canonical_ids_enter_normal_selection(self):
        for uid in (self.uid,'backup-newapi'):
            self.change('upstream.update',{'name':'星光同名账户'},uid)
        for bid,remote in ((self.bid,'Channel Exact V'),('grok-on-newapi','Channel exact v')):
            self.change('binding.update',{'display_name':'我的视频接入','remote_model':remote},bid)
        value=m.load(self.path)['config'];before=self.path.read_bytes()
        project_before={p.relative_to(self.project):p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('identity is offline')), \
             mock.patch('socket.socket',side_effect=AssertionError('identity is offline')):
            ambiguous=identify(value,kind='video',upstream_name='星光同名账户',model_name='我的视频接入')
            self.assertEqual(ambiguous['status'],'ambiguous');self.assertEqual(ambiguous['needs_choice'],['upstream'])
            self.assertEqual({r['binding_id'] for r in ambiguous['matches']},{self.bid,'grok-on-newapi'})
            exact=identify(value,kind='video',upstream_name='星光同名账户',model_name='Channel Exact V')
            pinned=identify(value,kind='video',upstream=self.uid,model_name='我的视频接入')
            self.assertEqual(exact['status'],'identified');self.assertEqual(pinned['status'],'identified')
            self.assertEqual(exact['matches'][0]['binding_id'],pinned['matches'][0]['binding_id'])
        self.assertEqual(project_before,{p.relative_to(self.project):p.read_bytes() for p in self.project.rglob('*') if p.is_file()})
        row=exact['matches'][0]
        packet=selection.menu(self.project,value,kind='video',store_root=self.root,
                              model=row['model_id'],upstream=row['upstream_id'])
        choice=next(c for c in packet['choices'] if c['id']==row['binding_id'])
        selected=selection.choose(self.project,value,selection_id=packet['selection_id'],number=choice['number'],
                                  scope='once',store_root=self.root)
        self.assertEqual(selected['binding_id'],self.bid)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertIsNone(selection.project_choice(self.project,'video'))
        self.assertIsNone(selection.project_choice(self.project,'image'))
        self.assertFalse((self.project/'state.json').exists())

    def test_legacy_platform_alias_stays_model_scoped_and_ambiguity_blocks_resume(self):
        from videocreate.cli import legacy_engine
        engine=legacy_engine()
        from videocreate.config.bridge import engine_settings
        settings=engine_settings(m.load(self.path)['config'],store_root=self.root)
        # The broad example includes other disabled Grok accounts. An alias
        # must refuse these too: disabled does not prove remote task ownership.
        with self.assertRaisesRegex(engine.SkillError,'alias is ambiguous'):
            engine.resolved_video_upstream(settings,'sub2api','grok-imagine-video-1.5')
        fixture=m.load(self.path)['config']
        for uid,upstream in fixture['upstreams'].items():
            if uid != self.uid and upstream.get('platform') == 'sub2api':
                upstream['platform']='fixture-other-platform'
        m.save(self.path,fixture,expected_token=m.load(self.path)['token'],reason='synthetic unique legacy platform')
        settings=engine_settings(m.load(self.path)['config'],store_root=self.root)
        for model,bid in (('grok-imagine-video-1.5',self.bid),
                          ('seedance-2.0-mini-720p','seedance-on-sub2api')):
            row=engine.resolved_video_upstream(settings,'sub2api',model)
            self.assertEqual(row['id'],bid)
            self.assertEqual(set(row['model_map']),{model})
        self.edits()
        value=m.load(self.path)['config']
        settings=engine_settings(value,store_root=self.root)
        row=engine.resolved_video_upstream(settings,'sub2api','grok-imagine-video-1.5')
        self.assertEqual(row['id'],self.bid)
        self.assertEqual(row['key'],'rotated-test-key')
        self.assertEqual(engine.resolved_video_upstream(settings,'sub2api','Unknown Exact ID'),{})
        # Two accounts on one platform are legal; an old platform alias no
        # longer identifies which original account owns the remote task.
        value['upstreams']['backup-newapi']['platform']='sub2api'
        m.save(self.path,value,expected_token=m.load(self.path)['token'],reason='synthetic alias ambiguity')
        self.change('upstream.update', {'name':'Same platform, different account'}, 'backup-newapi')
        settings=engine_settings(m.load(self.path)['config'],store_root=self.root)
        with self.assertRaisesRegex(engine.SkillError,'alias is ambiguous'):
            engine.resolved_video_upstream(settings,'sub2api','grok-imagine-video-1.5')
        self.assertEqual(engine.resolved_video_upstream(settings,self.bid,'grok-imagine-video-1.5')['id'],self.bid)
        self.assertFalse((self.project/'state.json').exists())


if __name__=='__main__':unittest.main()
