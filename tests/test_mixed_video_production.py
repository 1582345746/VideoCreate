"""Mixed plans exercise actual local rendering with fixture-only provider responses."""
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts'),str(ROOT/'tests')]
from videocreate import production
from videocreate.commands import plan_command, jobs_command
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.local_sources import import_clip,digest
from videocreate.planning.profiles import create
from videocreate.planning.project import compile_job,load_project,save_bundle,validate_plan
from videocreate.production_metrics import report
from videocreate.review import receipts
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state
from videocreate.timeline.render import render,probe
from test_v3_config import config


class MixedVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory();cls.source=Path(cls.fixture.name)/'source.mp4'
        subprocess.run([shutil.which('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i',
            'testsrc2=size=128x72:rate=24:duration=2','-f','lavfi','-i','sine=frequency=440:duration=2',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(cls.source)],capture_output=True,check=True)

    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'混合项目';self.store=self.root.parent/'config'
        save_bundle(self.root,create('mixed-video',title='Mixed production fixture'))
        self.config=config();self.config['execution']['max_concurrent_video_tasks']=1
        self.creates=[];self.guard=threading.Lock();outer=self
        class Client:
            def __init__(self,binding):self.binding=binding;self.last_submission={}
            def prepare(self,prompt,**kwargs):return {'prompt':prompt,'binding_snapshot':self.binding.snapshot()}
            def create(self,prompt,**kwargs):
                with outer.guard:
                    outer.creates.append({'prompt':prompt,'kwargs':kwargs})
                    return 'fixture-'+str(len(outer.creates))
            def poll(self,task_id,**kwargs):return {'status':'completed'}
            def query(self,task_id):return 'queued',{}
            def download(self,task_id,payload,destination):shutil.copyfile(outer.source,destination)
        patch=mock.patch('videocreate.runtime.jobs.client',side_effect=Client)
        self.client=patch.start();self.addCleanup(patch.stop)

    def bundle(self):return load_project(self.root)

    def local(self):return import_clip(self.root,self.source,source_id='archive',start=.25,end=1.25)

    def generated(self,count=1,local_dependency=True):
        bundle=self.bundle()
        if not any(s['id']=='generated-scene' for s in bundle['director']['scenes']):
            bundle['director']['scenes'].append({'id':'generated-scene','map':'One outdoor walkway','axis':'Camera stays south'})
        for index in range(count):
            sid,jid,cid='shot-gen-'+str(index),'gen-'+str(index),'clip-gen-'+str(index)
            bundle['director']['shots'].append({'id':sid,'scene_id':'generated-scene','framing':'Wide fixed camera',
                'information_goal':'A subject moves along the walkway '+str(index),'planned_seconds':2,
                'actions':[{'kind':'physical','description':'A subject takes one step'}],
                'cut_motivation':'Cut to show the result','audio':{'mode':'ambience'}})
            bundle['generation-plan']['jobs'].append({'id':jid,'shot_ids':[sid],'operation':'text-to-video','seconds':2,
                **({'depends_on':['archive']} if local_dependency else {})})
            bundle['timeline']['clips'].append({'id':cid,'job_id':jid})
            bundle['timeline']['segments'].append({'id':'seg-gen-'+str(index),'shot_id':sid,'clip_id':cid,
                'source_in':0,'source_out':1,'rate':1,'source_audio':'retime','cut_reason':'Show the next action'})
        for layer in ('director','generation-plan','timeline'):atomic_json(self.root/(layer+'.json'),bundle[layer])
        return bundle

    def run_jobs(self,**kwargs):return jobs.generate(self.root,self.config,store_root=self.store,**kwargs)

    def render(self):
        bundle=self.bundle();bundle['timeline'].update(width=128,height=72)
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        return render(self.root,bundle,read_state(self.root))

    def review_fixture(self):
        bundle=self.bundle();packet=receipts.template(self.root,bundle);packet['reviewer_id']='synthetic-contract-fixture'
        for asset in packet['assets'].values():
            for layer,observation in asset['layers'].items():
                if layer not in asset['required_layers']:observation['status']='not_applicable';continue
                observation.update(status='pass',method='human-listening' if layer=='audio' else 'human-video',
                    observations=['Synthetic verification; not actual human content approval'],
                    evidence=[{'path':asset['path'],'sha256':asset['sha256'],'start':0,'end':asset['duration'],'kind':'video'}])
        receipts.apply(self.root,bundle,packet)
        return packet

    def test_empty_mixed_profile_accepts_both_source_types_and_reports_authoring_next(self):
        current=production.status(self.root)
        self.assertEqual(current['next']['id'],'author-mixed-sources');self.assertFalse(current['ok'])
        self.assertEqual(current['jobs'],[]);self.assertEqual(current['budget']['requests'],0)
        self.assertEqual(create('mixed-video',seconds=30)['brief']['target_seconds'],30)
        for seconds in (0,float('inf'),True):
            with self.assertRaises(ConfigError):create('mixed-video',seconds=seconds)

    def test_local_only_phase_needs_no_config_and_no_model_jobs(self):
        before=digest(self.source);self.local()
        for command in ([plan_command,'compile'],[plan_command,'route'],[jobs_command,'run']):
            with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config needed')),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(command[0]([command[1],str(self.root)]),0)
            self.assertEqual(json.loads(output.getvalue())['jobs'],[])
        self.assertEqual(digest(self.source),before);self.assertEqual(read_state(self.root)['ledger'],[])
        self.assertEqual(read_state(self.root)['jobs'],{});self.client.assert_not_called()

    def test_import_after_authored_generated_job_preserves_its_prompt_and_task_definition(self):
        first=self.generated(local_dependency=False)
        compiled=compile_job(first,first['generation-plan']['jobs'][0],max_bytes=4096,root=self.root)
        self.local();after=self.bundle()
        self.assertEqual(first['generation-plan']['jobs'],after['generation-plan']['jobs'])
        self.assertEqual(compiled,compile_job(after,after['generation-plan']['jobs'][0],max_bytes=4096,root=self.root))
        self.assertTrue(validate_plan(after,self.root)['ok']);self.assertEqual(read_state(self.root)['ledger'],[])

    def test_serial_generation_render_delivery_and_metrics_keep_local_and_remote_separate(self):
        self.local();self.generated()
        with mock.patch('urllib.request.urlopen') as network:
            self.assertTrue(self.run_jobs()['ok']);result=self.render();package=production.delivery(self.root)
            network.assert_not_called()
        self.assertEqual(len(self.creates),1);self.assertEqual(set(read_state(self.root)['jobs']),{'gen-0'})
        self.assertEqual(len(read_state(self.root)['ledger']),1)
        self.assertAlmostEqual(probe(Path(result['path']))['duration'],2,delta=.08)
        self.assertTrue(probe(Path(result['path']))['has_audio'])
        self.assertEqual(package['status'],'review_pending');self.assertEqual(len(package['local_sources']),1)
        self.assertEqual(package['budget']['requests'],1)
        reading=Path(package['script']['reading_copy']).read_text(encoding='utf-8')
        self.assertIn('本地素材 archive',reading);self.assertIn('生成任务 gen-0',reading)
        measured=report(self.root)
        self.assertEqual(measured['seconds']['retained_available_playback'],2)
        self.assertEqual(measured['local_sources']['retained_available_playback'],1)
        self.assertEqual(measured['seconds']['generated_known'],2)
        self.assertEqual(measured['sample']['retained_jobs'],1)
        self.assertEqual(measured['sample']['create_attempts'],1)

    def test_parallel_dependency_waves_treat_local_sources_as_available_without_fake_jobs(self):
        self.local();self.generated(count=2);self.config['execution']['max_concurrent_video_tasks']=2
        self.assertTrue(self.run_jobs()['ok']);self.assertEqual(len(self.creates),2)
        self.assertEqual(set(read_state(self.root)['jobs']),{'gen-0','gen-1'})
        self.assertNotIn('archive',read_state(self.root)['jobs'])
        self.assertEqual(read_state(self.root)['ledger'][0]['kind'],'video')

    def test_remote_dependency_failure_blocks_successor_and_keeps_local_snapshot(self):
        imported=self.local();bundle=self.generated(count=2)
        bundle['generation-plan']['jobs'][1]['depends_on'].append('gen-0')
        atomic_json(self.root/'generation-plan.json',bundle['generation-plan'])
        self.config['execution']['max_concurrent_video_tasks']=2
        self.client.side_effect=None;client=self.client.return_value
        client.prepare.return_value={'prepared':True};client.create.side_effect=TimeoutError('Synthetic ambiguous create')
        current=self.run_jobs();self.assertFalse(current['ok']);client.create.assert_called_once()
        by_id={r['job_id']:r for r in current['jobs']};self.assertEqual(by_id['gen-1']['status'],'blocked')
        self.assertEqual(digest(self.root/imported['source']['path']),digest(self.source))

    def test_stale_local_snapshot_prevents_any_create_or_budget_in_serial_and_parallel(self):
        imported=self.local();self.generated(count=2)
        path=self.root/imported['source']['path'];path.write_bytes(path.read_bytes()+b'changed')
        for concurrency in (1,2):
            self.config['execution']['max_concurrent_video_tasks']=concurrency
            with self.assertRaises(ConfigError):self.run_jobs()
        self.assertEqual(self.creates,[]);self.assertEqual(read_state(self.root)['ledger'],[])
        impact=production.impact(self.root)
        self.assertEqual(impact['changed_local_sources'],['archive'])
        self.assertEqual(impact['dependent_jobs_to_check'],['gen-0','gen-1'])

    def test_local_dependency_is_revalidated_after_preflight_before_submission(self):
        imported=self.local();self.generated(count=2)
        original=jobs._prepare_job;calls=[]
        def change(*args,**kwargs):
            result=original(*args,**kwargs);calls.append(1)
            if len(calls)==2:
                path=self.root/imported['source']['path'];path.write_bytes(path.read_bytes()+b'changed')
            return result
        with mock.patch.object(jobs,'_prepare_job',side_effect=change):
            with self.assertRaises(ConfigError):self.run_jobs()
        self.assertEqual(self.creates,[]);self.assertEqual(read_state(self.root)['ledger'],[])

    def test_local_dependencies_order_work_and_do_not_implicitly_send_media(self):
        self.local();self.generated();self.run_jobs()
        self.assertNotIn('local-sources',self.creates[0]['prompt'])
        self.assertNotIn('Existing source framing',self.creates[0]['prompt'])
        self.assertFalse(self.creates[0]['kwargs'].get('references'))
        self.assertFalse(self.creates[0]['kwargs'].get('primary_reference'))

    def test_conflicting_ids_duplicate_local_coverage_and_unknown_dependencies_are_rejected(self):
        self.local();bundle=self.generated()
        for change in ('id','coverage','dependency'):
            bad=copy.deepcopy(bundle)
            if change=='id':bad['generation-plan']['local_sources'][0]['id']='gen-0'
            elif change=='coverage':bad['generation-plan']['local_sources'][0]['shot_ids'].append('shot-gen-0')
            else:bad['generation-plan']['jobs'][0]['depends_on'].append('missing')
            self.assertFalse(validate_plan(bad,self.root)['ok'])

    def test_resume_and_local_description_edit_reuse_completed_generated_candidate(self):
        self.local();self.generated();self.run_jobs();before=read_state(self.root)
        bundle=self.bundle();bundle['director']['shots'][0]['information_goal']='Different description of the same local footage'
        atomic_json(self.root/'director.json',bundle['director'])
        self.assertEqual(production.impact(self.root)['changed_job_inputs'],[])
        self.assertTrue(self.run_jobs()['ok']);self.assertEqual(len(self.creates),1)
        self.assertEqual(read_state(self.root)['ledger'],before['ledger'])

    def test_subtitle_edit_invalidates_final_while_both_source_reviews_remain_valid(self):
        self.local();self.generated();self.run_jobs();self.render();self.review_fixture()
        self.assertEqual(report(self.root)['seconds']['reviewed_usable_playback'],2)
        bundle=self.bundle();bundle['timeline']['subtitles']=[{'text':'Changed caption','start':0,'end':.5}]
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        stale=production.status(self.root)
        self.assertEqual(stale['local_sources'][0]['content_status'],'reviewed')
        self.assertEqual(stale['review']['assets']['gen-0']['performance_motion'],'pass')
        self.assertNotEqual(stale['review']['status'],'accepted_delivery')
        self.render()
        current=production.status(self.root)
        self.assertEqual(current['local_sources'][0]['content_status'],'reviewed')
        self.assertEqual(current['review']['assets']['gen-0']['performance_motion'],'pass')
        self.assertEqual(current['review']['assets']['final']['editorial'],'unverified')
        self.assertEqual(len(self.creates),1)

    def test_source_and_final_receipts_use_distinct_identity_and_motion_contracts(self):
        self.local();self.generated();self.run_jobs();self.render()
        actual=receipts.contracts(self.root,self.bundle());self.assertEqual(set(actual),{'archive','gen-0','final'})
        self.assertNotEqual(actual['archive']['contract_hash'],actual['gen-0']['contract_hash'])
        packet=self.review_fixture();wrong=copy.deepcopy(packet)
        wrong['assets']['archive']['layers']['performance_motion']['evidence'][0]['kind']='frames'
        self.assertTrue(receipts.validate_receipt(self.root,self.bundle(),wrong))

    def test_explicit_target_is_preserved_and_bad_import_keeps_existing_generation_plan(self):
        self.generated(local_dependency=False)
        bundle=self.bundle();bundle['brief']['target_seconds']=1
        atomic_json(self.root/'brief.json',bundle['brief'])
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with self.assertRaisesRegex(ConfigError,'retained duration'):self.local()
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        self.assertEqual(read_state(self.root)['jobs'],{})

    def test_one_changed_source_contract_does_not_erase_other_source_observations(self):
        self.local();self.generated();self.run_jobs();self.render();self.review_fixture()
        bundle=self.bundle();bundle['director']['shots'][0]['information_goal']='Updated local source interpretation'
        atomic_json(self.root/'director.json',bundle['director'])
        current=production.status(self.root)
        self.assertEqual(current['local_sources'][0]['content_status'],'unverified')
        self.assertEqual(current['review']['assets']['gen-0']['performance_motion'],'pass')
        self.assertNotEqual(current['review']['status'],'accepted_delivery')

    def test_manager_mixed_video_source_and_task_panel_has_import_control_without_network(self):
        import tkinter as tk
        from tkinter import ttk
        from videocreate.manager import Manager
        from videocreate.manager_projects import open_panel
        from videocreate.config.management import migrate
        self.local();self.generated()
        window=tk.Tk();window.withdraw();self.addCleanup(window.destroy)
        path=self.root.parent/'config.json';atomic_json(path,migrate(self.config));before=path.read_bytes()
        manager=Manager(window,path)
        def widgets(parent):
            for child in parent.winfo_children():yield child;yield from widgets(child)
        with mock.patch.object(manager,'error') as error,mock.patch('urllib.request.urlopen') as network:
            panel=open_panel(manager,self.root);panel.withdraw();window.update_idletasks()
            children=list(widgets(panel))
            self.assertTrue(any(isinstance(w,ttk.Button) and w.cget('text')=='导入本地视频' for w in children))
            values=[w.item(i,'values') for w in children if isinstance(w,ttk.Treeview) for i in w.get_children()]
            self.assertTrue(any(v[0]=='archive' and v[1]=='本地可用' for v in values))
            self.assertTrue(any(v[0]=='gen-0' and v[1]=='未提交' for v in values))
            panel.destroy();error.assert_not_called();network.assert_not_called()
        self.assertEqual(path.read_bytes(),before)

    def narrative(self):
        bundle=self.generated(count=2,local_dependency=False)
        bundle['brief']['intent']='narrative'
        bundle['story']={'logline':'One event visibly causes the next','goal':'Reach the far side',
            'obstacle':'A closed gate','choice':'Open the gate','consequence':'The path becomes available',
            'initial_state':{'gate':'closed','position':'near'},'beats':[
                {'id':'open','requires':{'gate':'closed'},'effects':{'gate':'open'},'causes':[],
                 'audience_learns':'The gate is now open','visible_evidence_needed':['gate-open']},
                {'id':'cross','requires':{'gate':'open'},'effects':{'position':'far'},'causes':['open'],
                 'audience_learns':'Opening the gate made crossing possible','visible_evidence_needed':['crossed']}]}
        bundle['director']['shots'][0].update(beat_id='open',visible_evidence=['gate-open'])
        bundle['director']['shots'][1].update(beat_id='cross',visible_evidence=['crossed'])
        bundle['generation-plan']['jobs']=bundle['generation-plan']['jobs'][1:]
        bundle['generation-plan']['jobs'][0]['depends_on']=['archive']
        bundle['timeline']['clips']=bundle['timeline']['clips'][1:]
        bundle['timeline']['segments']=bundle['timeline']['segments'][1:]
        for layer in ('brief','story','director','generation-plan','timeline'):atomic_json(self.root/(layer+'.json'),bundle[layer])
        return bundle

    def test_existing_shot_mapping_preserves_narrative_and_only_generates_the_other_shot(self):
        before=self.narrative();prompt=compile_job(before,before['generation-plan']['jobs'][0],max_bytes=4096,root=self.root)
        import_clip(self.root,self.source,source_id='archive',shot_id='shot-gen-0',start=.25,end=1.25)
        after=self.bundle()
        self.assertEqual(after['director'],before['director']);self.assertEqual(after['story'],before['story'])
        self.assertEqual(after['generation-plan']['jobs'],before['generation-plan']['jobs'])
        self.assertEqual(compile_job(after,after['generation-plan']['jobs'][0],max_bytes=4096,root=self.root),prompt)
        checked=validate_plan(after,self.root);self.assertTrue(checked['ok'],checked['errors'])
        after['timeline']['segments'].reverse();atomic_json(self.root/'timeline.json',after['timeline'])
        self.assertTrue(self.run_jobs()['ok']);self.render()
        self.assertEqual(len(self.creates),1);self.assertEqual(set(read_state(self.root)['jobs']),{'gen-1'})
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')

    def test_existing_shot_collision_rejects_without_replacing_jobs_sources_or_edit(self):
        self.local();self.generated(local_dependency=False)
        for shot_id in ('missing','shot-gen-0','shot-archive'):
            before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
            with self.assertRaises(ConfigError):import_clip(self.root,self.source,source_id='other',shot_id=shot_id)
            self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        self.assertEqual(self.creates,[]);self.assertEqual(read_state(self.root)['ledger'],[])

    def test_existing_shot_does_not_replace_preexisting_timeline_segment(self):
        bundle=self.narrative()
        bundle['timeline']['segments'].append({'id':'unfinished-edit','shot_id':'shot-gen-0','clip_id':'clip-gen-1',
            'source_in':0,'source_out':1,'rate':1,'source_audio':'mute','cut_reason':'An existing edit to preserve'})
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with self.assertRaisesRegex(ConfigError,'timeline segment'):
            import_clip(self.root,self.source,source_id='archive',shot_id='shot-gen-0')
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)

    def test_existing_shot_cli_maps_exact_id_and_rejects_unconsumed_options(self):
        from videocreate.production_commands import production_command
        self.narrative()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(production_command(['import-clip',str(self.root),'--source',str(self.source),
                '--source-id','archive','--shot-id','shot-gen-0','--start','.25','--end','1.25','--mute']),0)
        self.assertEqual(json.loads(output.getvalue())['source']['shot_ids'],['shot-gen-0'])
        self.assertEqual(self.bundle()['timeline']['segments'][-1]['source_audio'],'mute')
        with self.assertRaisesRegex(ConfigError,'only consumed'):
            production_command(['status',str(self.root),'--shot-id','shot-gen-0'])
        with self.assertRaisesRegex(ConfigError,'description applies'):
            import_clip(self.root,self.source,source_id='other',shot_id='shot-gen-0',description='Ignored text')
        local_root=self.root.parent/'edit';save_bundle(local_root,create('edit-only'))
        with self.assertRaisesRegex(ConfigError,'requires mixed-video'):
            import_clip(local_root,self.source,source_id='archive',shot_id='shot-gen-0')


if __name__=='__main__':unittest.main()
