import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts')]
from videocreate import production
from videocreate.commands import plan_command
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.local_sources import import_clip,verify_source,digest
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project,save_bundle,validate_plan
from videocreate.production_commands import production_command
from videocreate.production_metrics import report
from videocreate.review import receipts
from videocreate.runtime.state import read_state
from videocreate.timeline.render import render,probe


class EditOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory()
        cls.source=Path(cls.shared.name)/'source.mp4'
        subprocess.run([shutil.which('ffmpeg'),'-nostdin','-v','error','-y',
            '-f','lavfi','-i','testsrc2=size=128x72:rate=24:duration=2',
            '-f','lavfi','-i','sine=frequency=440:duration=2',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(cls.source)],
            check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):cls.shared.cleanup()

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'剪辑项目'
        save_bundle(self.root,create('edit-only',title='Local editing fixture'))

    def add(self,identity='take-001',**kwargs):
        return import_clip(self.root,self.source,source_id=identity,**kwargs)

    def test_profile_is_explicit_draft_and_cannot_contain_generation_jobs(self):
        self.assertFalse(validate_plan(load_project(self.root),self.root)['ok'])
        self.assertEqual(production.status(self.root)['next']['id'],'import-local-sources')
        with self.assertRaisesRegex(ConfigError,'omit --seconds'):create('edit-only',seconds=5)
        self.add()
        bundle=load_project(self.root)
        bundle['generation-plan']['jobs']=[{'id':'job-x','shot_ids':['shot-take-001'],
            'operation':'text-to-video','seconds':2}]
        self.assertIn('Edit-only plans must not contain generation jobs',validate_plan(bundle,self.root)['errors'])

    def test_import_preserves_source_and_no_task_or_budget_is_created(self):
        before=digest(self.source)
        with mock.patch('urllib.request.urlopen') as network, mock.patch('videocreate.runtime.jobs.client') as client:
            result=self.add(start=.25,end=1.25,description='Synthetic source interval for testing')
            network.assert_not_called();client.assert_not_called()
        self.assertTrue(result['full_decode_verified'])
        self.assertEqual(result['retained_seconds'],1)
        self.assertEqual(digest(self.source),before)
        self.assertTrue(Path(result['backup']).is_file())
        bundle=load_project(self.root)
        self.assertTrue(validate_plan(bundle,self.root)['ok'])
        self.assertEqual(bundle['generation-plan']['jobs'],[])
        self.assertEqual(read_state(self.root)['ledger'],[])
        self.assertFalse((self.root/'state.json').exists())
        self.assertEqual(digest(verify_source(self.root,result['source'])),before)

    def test_invalid_interval_duplicate_or_wrong_workflow_preserves_plan(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        for start,end in ((-1,1),(1,1),(0,99),(float('nan'),1),(True,1)):
            with self.assertRaises(ConfigError):self.add(start=start,end=end)
            self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        self.add()
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with self.assertRaisesRegex(ConfigError,'already exists'):self.add()
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        other=self.root/'generated';save_bundle(other,create('scenic',seconds=10))
        with self.assertRaisesRegex(ConfigError,'edit-only'):import_clip(other,self.source,source_id='local')

    def test_mutated_source_or_metadata_blocks_validation_render_and_review(self):
        result=self.add();bundle=load_project(self.root)
        altered=copy.deepcopy(bundle);altered['generation-plan']['local_sources'][0]['media']['duration']=30
        self.assertFalse(validate_plan(altered,self.root)['ok'])
        with self.assertRaisesRegex(ConfigError,'duration'):receipts.contracts(self.root,altered)
        source_path=self.root/result['source']['path']
        source_path.write_bytes(source_path.read_bytes()+b'changed')
        self.assertFalse(validate_plan(bundle,self.root)['ok'])
        with self.assertRaisesRegex(ConfigError,'bytes changed'):render(self.root,bundle,read_state(self.root))
        state=production.status(self.root)
        self.assertEqual(state['local_sources'][0]['status'],'stale')
        self.assertEqual(state['next']['id'],'repair-plan')

    def test_clip_override_or_out_of_bounds_window_cannot_bypass_registration(self):
        self.add();bundle=load_project(self.root)
        for field,value in (('path','different.mp4'),('job_id','unknown-source')):
            bad=copy.deepcopy(bundle);bad['timeline']['clips'][0][field]=value
            self.assertFalse(validate_plan(bad,self.root)['ok'])
        bad=copy.deepcopy(bundle);bad['timeline']['segments'][0]['source_out']=10
        self.assertFalse(validate_plan(bad,self.root)['ok'])

    def test_stage_policy_skips_generation_and_reports_local_sources_separately(self):
        self.add()
        production.policy(self.root,'auto-within-authorization','User requested local editing')
        status=production.status(self.root)
        stages={s['id']:s for s in status['stages']}
        self.assertEqual(stages['generation']['status'],'skipped')
        self.assertEqual(stages['script']['status'],'skipped')
        self.assertEqual(stages['outline']['status'],'skipped')
        self.assertEqual(status['next']['id'],'editing')
        self.assertEqual(status['jobs'],[])
        self.assertEqual(status['local_sources'][0]['status'],'available')
        self.assertEqual(status['budget']['requests'],0)

    def test_actual_render_preserves_audio_and_delivers_unreviewed_without_creates(self):
        self.add(start=.25,end=1.25)
        bundle=load_project(self.root)
        bundle['timeline'].update(width=128,height=72)
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        with mock.patch('urllib.request.urlopen') as network:
            result=render(self.root,bundle,read_state(self.root))
            network.assert_not_called()
        actual=probe(Path(result['path']))
        self.assertAlmostEqual(actual['duration'],1,delta=.08)
        self.assertTrue(actual['has_audio'])
        metrics=report(self.root)
        self.assertEqual(metrics['seconds']['generated_known'],0)
        self.assertEqual(metrics['seconds']['retained_available_playback'],1)
        self.assertEqual(metrics['local_sources']['available_retained_sources'],1)
        self.assertIsNone(metrics['rates']['reviewed_source_jobs_over_available_selected_jobs'])
        package=production.delivery(self.root)
        self.assertEqual(package['status'],'review_pending')
        self.assertEqual(package['jobs'],[])
        self.assertEqual(len(package['local_sources']),1)
        self.assertEqual(package['budget']['requests'],0)
        self.assertIn('剪辑清单',Path(package['script']['reading_copy']).read_text(encoding='utf-8'))

    def test_source_and_final_review_need_actual_temporal_evidence_and_subtitles_stale_final_only(self):
        self.add(start=0,end=1)
        bundle=load_project(self.root);bundle['timeline'].update(width=128,height=72)
        atomic_json(self.root/'timeline.json',bundle['timeline']);render(self.root,bundle,read_state(self.root))
        packet=receipts.template(self.root,bundle)
        self.assertEqual(set(packet['assets']),{'take-001','final'})
        packet['reviewer_id']='synthetic-contract-fixture'
        for asset in packet['assets'].values():
            for layer,observation in asset['layers'].items():
                if layer not in asset['required_layers']:
                    observation['status']='not_applicable';continue
                observation.update(status='pass',method='human-listening' if layer=='audio' else 'human-video',
                    observations=['Synthetic contract fixture; not an actual human approval'],
                    evidence=[{'path':asset['path'],'sha256':asset['sha256'],
                        'start':0,'end':asset['duration'],'kind':'video'}])
        self.assertEqual(receipts.validate_receipt(self.root,bundle,packet),[])
        static=copy.deepcopy(packet)
        static['assets']['take-001']['layers']['performance_motion']['evidence'][0]['kind']='frames'
        self.assertTrue(receipts.validate_receipt(self.root,bundle,static))
        receipts.apply(self.root,bundle,packet)
        self.assertEqual(production.status(self.root)['local_sources'][0]['content_status'],'reviewed')
        before_source=receipts.contracts(self.root,bundle)['take-001']
        bundle['timeline']['subtitles']=[{'text':'Changed subtitle','start':0,'end':.5}]
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        self.assertEqual(production.impact(self.root)['changed_job_inputs'],[])
        with self.assertRaisesRegex(ConfigError,'stale'):receipts.contracts(self.root,bundle)
        render(self.root,bundle,read_state(self.root))
        self.assertEqual(receipts.contracts(self.root,bundle)['take-001']['contract_hash'],before_source['contract_hash'])
        self.assertEqual(read_state(self.root)['jobs'],{})
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_offline_cli_import_compile_route_needs_no_provider_config(self):
        with redirect_stdout(io.StringIO()) as captured:
            production_command(['import-clip',str(self.root),'--source',str(self.source),
                '--source-id','cli-source','--start','.5','--end','1','--mute'])
        self.assertEqual(json.loads(captured.getvalue())['paid_creates'],0)
        for action in ('compile','route'):
            with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config needed')), \
                    redirect_stdout(io.StringIO()) as captured:
                self.assertEqual(plan_command([action,str(self.root)]),0)
            self.assertEqual(json.loads(captured.getvalue())['jobs'],[])

    def test_invalid_media_and_reserved_review_id_are_actionable_and_preserve_plan(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        bad=self.root/'not-video.mp4';bad.write_text('not video')
        for source,identity in ((bad,'bad'),(self.source,'final')):
            with self.assertRaises(ConfigError):import_clip(self.root,source,source_id=identity)
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)

    def test_interrupted_save_restores_exact_original_layer_bytes(self):
        path=self.root/'director.json'
        path.write_text(json.dumps(load_json(path),ensure_ascii=True,indent=4)+'\n\n',encoding='utf-8')
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        real=atomic_json
        def write(target,value):
            if target==self.root/'generation-plan.json':raise OSError('Synthetic disk failure')
            return real(target,value)
        with mock.patch('videocreate.local_sources.atomic_json',side_effect=write):
            with self.assertRaisesRegex(OSError,'Synthetic'):self.add()
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        self.assertEqual(read_state(self.root)['jobs'],{})

    def test_two_imports_of_same_bytes_share_storage_but_keep_independent_windows(self):
        first=self.add(start=0,end=1)
        second=self.add('take-002',start=.5,end=1.5,preserve_audio=False)
        self.assertEqual(first['source']['path'],second['source']['path'])
        bundle=load_project(self.root)
        self.assertTrue(validate_plan(bundle,self.root)['ok'])
        self.assertEqual(bundle['timeline']['segments'][1]['source_audio'],'mute')
        metrics=report(self.root)
        self.assertEqual(metrics['local_sources']['available_retained_sources'],2)
        self.assertEqual(metrics['seconds']['retained_available_playback'],2)
        self.assertEqual(metrics['seconds']['retained_unique_source'],1.5)
        self.assertEqual(metrics['sample']['retained_jobs'],0)

    def test_manager_import_runs_off_thread_and_updates_source_panel_offscreen(self):
        import tkinter as tk
        from tkinter import ttk
        from videocreate.manager import Manager
        from videocreate.manager_projects import open_panel
        from test_v3_config import config
        from videocreate.config.management import migrate
        window=tk.Tk();window.withdraw()
        self.addCleanup(window.destroy)
        config_path=self.root/'test-config.json';atomic_json(config_path,migrate(config()))
        before=config_path.read_bytes()
        manager=Manager(window,config_path)
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        with mock.patch('urllib.request.urlopen') as network, mock.patch.object(manager,'error') as error:
            panel=open_panel(manager,self.root);panel.withdraw()
            button=next(w for w in widgets(panel) if isinstance(w,ttk.Button) and w.cget('text')=='导入本地视频')
            with mock.patch('tkinter.filedialog.askopenfilename',return_value=str(self.source)):
                button.invoke()
            dialog=next(w for w in widgets(window) if isinstance(w,tk.Toplevel) and '导入本地视频' in w.title())
            dialog.withdraw()
            submit=next(w for w in widgets(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='导入并加入时间线')
            threads=[];real=import_clip
            def observed(*args,**kwargs):
                threads.append(threading.get_ident())
                return real(*args,**kwargs)
            with mock.patch('videocreate.local_sources.import_clip',side_effect=observed):
                submit.invoke()
                self.assertEqual(str(submit.cget('state')),'disabled')
                deadline=time.monotonic()+15
                while dialog.winfo_exists() and time.monotonic()<deadline:
                    window.update();time.sleep(.01)
                self.assertFalse(dialog.winfo_exists(),'Background import did not complete')
            self.assertNotEqual(threads[0],threading.get_ident())
            trees=[w for w in widgets(panel) if isinstance(w,ttk.Treeview)]
            rows=[tree.item(item,'values') for tree in trees for item in tree.get_children()]
            self.assertTrue(any(row[0]=='source-001' and row[1]=='本地可用' for row in rows))
            error.assert_not_called();network.assert_not_called()
        self.assertEqual(config_path.read_bytes(),before)
        self.assertEqual(read_state(self.root)['ledger'],[])


if __name__=='__main__':unittest.main()
