import copy
import io
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts')]
from videocreate import local_gifs, production
from videocreate.commands import plan_command, review_command
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.local_sources import digest
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project, save_bundle, validate_plan
from videocreate.production_commands import production_command
from videocreate.production_metrics import report
from videocreate.runtime.state import read_state


def png(width, height, color):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))
        +chunk(b'IDAT',zlib.compress((b'\0'+bytes(color)*width)*height))+chunk(b'IEND',b''))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg/FFprobe required')
class LocalGifProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory();folder=Path(cls.fixture.name)
        cls.source=folder/'source.mp4'
        subprocess.run([shutil.which('ffmpeg'),'-nostdin','-v','error','-f','lavfi','-i',
            'testsrc2=size=128x72:rate=10','-t','1','-pix_fmt','yuv420p','-y',str(cls.source)],
            capture_output=True,timeout=30,check=True)
        cls.frames=[]
        for i,color in enumerate(((255,0,0),(0,255,0),(0,0,255))):
            path=folder/(str(i)+'.png');path.write_bytes(png(96,64,color));cls.frames.append(path)

    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)/'中文项目'
        save_bundle(self.root,create('gif-local',title='Local GIF fixture'))

    def bundle(self):return load_project(self.root)

    def build(self,**kwargs):
        return local_gifs.build(self.root,gif_id='gif-001',source=self.source,duration=.6,fps=10,width=96,**kwargs)

    def review(self,status='pass',temporal=True):
        return local_gifs.review(self.root,gif_id='gif-001',status=status,reviewer_id='synthetic-test',
            observation='Synthetic pipeline test; not human visual acceptance',temporal_observation=temporal)

    def test_empty_local_profile_requests_sources_without_provider_requirements(self):
        current=production.status(self.root)
        self.assertFalse(current['ok']);self.assertEqual(current['next']['id'],'import-gif-source')
        self.assertEqual(current['jobs'],[]);self.assertEqual(current['budget']['requests'],0)
        self.assertEqual(self.bundle()['generation-plan']['image_jobs'],[])

    def test_video_conversion_copies_source_and_creates_no_remote_task_budget_or_network(self):
        before=digest(self.source)
        with mock.patch('urllib.request.urlopen') as network, mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as image:
            value=self.build();current=production.status(self.root);package=production.delivery(self.root)
            network.assert_not_called();image.assert_not_called()
        self.assertEqual(digest(self.source),before)
        self.assertTrue(value['full_decode_verified']);self.assertEqual(current['jobs'],[])
        self.assertEqual(read_state(self.root),{'schema_version':3,'jobs':{},'ledger':[]})
        self.assertEqual(package['status'],'review_pending');self.assertIn('gif_id',package['artifacts'][0])
        self.assertTrue(package['artifacts'][0]['media']['animated'])
        self.assertEqual(package['local_gifs'][0]['status'],'completed')
        states={s['id']:s['status'] for s in current['stages']}
        self.assertEqual(states['generation'],'skipped');self.assertEqual(states['editing'],'complete')
        measured=report(self.root);self.assertEqual(measured['local_gifs']['completed_current'],1)
        self.assertEqual(measured['images']['planned'],0);self.assertEqual(measured['sample']['create_attempts'],0)
        self.assertEqual(measured['seconds']['generated_known'],0)

    def test_source_is_project_owned_and_relocation_keeps_derivation_valid(self):
        self.build()
        new_root=self.root.parent/'relocated';shutil.copytree(self.root,new_root)
        with mock.patch.object(local_gifs,'digest',wraps=local_gifs.digest):
            self.assertTrue(validate_plan(load_project(new_root),new_root)['ok'])
        self.assertEqual(production.status(new_root)['local_gifs'][0]['status'],'completed')
        self.assertNotEqual(self.bundle()['generation-plan']['local_gifs'][0]['recipe']['sources'][0]['path'],str(self.source))

    def test_temporal_review_and_same_byte_defect_dominance(self):
        self.build()
        with self.assertRaises(ConfigError):self.review(temporal=False)
        receipt=self.review();self.assertEqual(production.delivery(self.root)['status'],'accepted_delivery')
        (self.root/receipt['receipt']).unlink()
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')
        self.review(status='fail');self.review()
        self.assertEqual(production.delivery(self.root)['status'],'rejected')
        self.assertEqual(read_state(self.root)['jobs'],{})

    def test_parameter_edit_stales_output_explicit_rebuild_preserves_prior_and_requires_new_review(self):
        first=self.build();self.review()
        bundle=self.bundle();item=bundle['generation-plan']['local_gifs'][0];item['recipe']['width']=128
        atomic_json(self.root/'generation-plan.json',bundle['generation-plan'])
        self.assertEqual(production.impact(self.root)['changed_local_gifs'],['gif-001'])
        with self.assertRaises(ConfigError):production.delivery(self.root)
        with self.assertRaises(ConfigError):self.review()
        rebuilt=local_gifs.build(self.root,gif_id='gif-001',rebuild=True)
        self.assertNotEqual(first['gif']['derivation'],rebuilt['gif']['derivation'])
        self.assertTrue((self.root/first['gif']['derivation']['path']).is_file())
        current=load_json(self.root/rebuilt['gif']['derivation']['path'])
        self.assertEqual(current['previous_derivation'],first['gif']['derivation'])
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')
        self.review();self.assertEqual(production.delivery(self.root)['status'],'accepted_delivery')

    def test_changed_snapshot_manifest_or_output_cannot_deliver_or_review(self):
        for target in ('source','manifest','output'):
            with self.subTest(target=target):
                value=self.build() if not self.bundle()['generation-plan']['local_gifs'] else local_gifs.build(self.root,gif_id='gif-001',rebuild=True)
                item=value['gif'];manifest=self.root/item['derivation']['path'];record=load_json(manifest)
                path={'source':self.root/item['recipe']['sources'][0]['path'],
                    'manifest':manifest,'output':self.root/record['artifact']['path']}[target]
                raw=path.read_bytes();path.write_bytes(raw+b'changed')
                self.assertEqual(production.status(self.root)['local_gifs'][0]['status'],'stale')
                with self.assertRaises(ConfigError):production.delivery(self.root)
                with self.assertRaises(ConfigError):self.review()
                path.write_bytes(raw)

    def test_frames_keep_order_and_duplicate_frames_and_convert_without_provider_config(self):
        order=[self.frames[2],self.frames[0],self.frames[2]]
        value=local_gifs.build(self.root,gif_id='gif-001',frames=order,fps=10,width=96)
        refs=value['gif']['recipe']['sources']
        self.assertEqual([r['sha256'] for r in refs],[digest(p) for p in order])
        self.assertEqual(refs[0]['path'],refs[2]['path'])
        row=production.status(self.root)['local_gifs'][0]
        self.assertEqual(row['media']['frame_count'],3)
        self.assertEqual(row['media']['duration_ms'],300)
        self.assertEqual(row['media']['loop'],0)
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_invalid_interval_and_mismatched_frames_leave_plan_bytes_unchanged(self):
        target=self.root/'generation-plan.json';before=target.read_bytes()
        for changes in ({'start':.8,'duration':.6},{'start':float('nan')},{'fps':True},{'width':1}):
            values={'gif_id':'gif-001','source':self.source,'duration':.6,'fps':10,'width':96,**changes}
            with self.assertRaises(ConfigError):local_gifs.build(self.root,**values)
            self.assertEqual(target.read_bytes(),before)
        other=self.root.parent/'other.png';other.write_bytes(png(80,64,(255,0,0)))
        with self.assertRaises(ConfigError):local_gifs.build(self.root,gif_id='gif-001',frames=[*self.frames,other])
        self.assertEqual(target.read_bytes(),before)

    def test_collision_and_non_gif_profile_rejected_without_tasks(self):
        self.build();before=(self.root/'generation-plan.json').read_bytes()
        with self.assertRaises(ConfigError):self.build()
        self.assertEqual((self.root/'generation-plan.json').read_bytes(),before)
        other=self.root.parent/'images';save_bundle(other,create('image-only',topic='A boat'))
        with self.assertRaises(ConfigError):local_gifs.build(other,gif_id='gif-001',source=self.source)
        bundle=self.bundle();bundle['generation-plan']['local_gifs'].append(copy.deepcopy(bundle['generation-plan']['local_gifs'][0]))
        self.assertFalse(validate_plan(bundle,self.root)['ok'])

    def test_optimistic_save_conflict_preserves_concurrent_edit_and_original(self):
        convert=local_gifs._convert;changed=[]
        def concurrent(*args,**kwargs):
            result=convert(*args,**kwargs)
            bundle=self.bundle();bundle['generation-plan']['local_gifs']=[]
            # Simulate a legitimate same-layer change while conversion ran outside the lock.
            atomic_json(self.root/'generation-plan.json',bundle['generation-plan'])
            with (self.root/'generation-plan.json').open('ab') as handle:handle.write(b'\n')
            changed.append((self.root/'generation-plan.json').read_bytes())
            return result
        with mock.patch.object(local_gifs,'_convert',side_effect=concurrent):
            with self.assertRaisesRegex(ConfigError,'Project changed'):self.build()
        self.assertEqual((self.root/'generation-plan.json').read_bytes(),changed[0])
        self.assertEqual(read_state(self.root)['jobs'],{})

    def test_atomic_save_failure_preserves_plan_and_completed_derivation_for_recovery(self):
        original=local_gifs.atomic_json;target=self.root/'generation-plan.json';before=target.read_bytes()
        def fail(path,value):
            if path==target:raise OSError('Synthetic write failure')
            return original(path,value)
        with mock.patch.object(local_gifs,'atomic_json',side_effect=fail):
            with self.assertRaises(OSError):self.build()
        self.assertEqual(target.read_bytes(),before)
        self.assertTrue(list((self.root/'assets/generated').glob('*/final.gif.json')))

    def test_cli_local_compile_route_status_page_inbox_brief_and_review_require_no_config(self):
        with redirect_stdout(io.StringIO()) as output:
            code=production_command(['gif-video',str(self.root),'--source',str(self.source),'--gif','gif-001',
                '--duration','.6','--fps','10','--width','96'])
        self.assertEqual(code,0)
        for action in ('compile','route','preview'):
            with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('Must not load provider config')),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(plan_command([action,str(self.root)]),0)
            self.assertEqual(json.loads(output.getvalue())['paid_creates'],0)
        for action in ('page','inbox','status'):
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(review_command([action,str(self.root)]),0)
            self.assertTrue(json.loads(output.getvalue())['ok'])
        brief=production.script_export(self.root)
        self.assertIn('本地 GIF 配方',Path(brief['reading_copy']).read_text(encoding='utf-8'))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(review_command(['gif',str(self.root),'--gif','gif-001','--status','pass','--reviewer','fixture',
                '--observation','Synthetic full playback receipt','--temporal-observation']),0)
        self.assertEqual(report(self.root)['delivery_status'],'accepted_delivery')

    def test_title_change_keeps_output_and_review_current(self):
        self.build();self.review()
        project=load_json(self.root/'project.json');project['title']='Changed title';atomic_json(self.root/'project.json',project)
        self.assertEqual(production.impact(self.root)['changed_local_gifs'],[])
        self.assertEqual(production.delivery(self.root)['status'],'accepted_delivery')

    def test_identical_rebuild_keeps_prior_pass_outside_current_derivation(self):
        self.build();self.review()
        local_gifs.build(self.root,gif_id='gif-001',rebuild=True)
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')
        self.review(status='fail')
        local_gifs.build(self.root,gif_id='gif-001',rebuild=True)
        self.assertEqual(production.delivery(self.root)['status'],'rejected')

    def test_malformed_receipt_does_not_approve_or_crash_status(self):
        self.build();output=self.review();target=self.root/output['receipt'];value=load_json(target)
        for changes in ({'recipe_hash':'0'*64},{'derivation':{}},{'reviewer_id':None},{'observation':42}):
            atomic_json(target,{**value,**changes})
            self.assertEqual(production.delivery(self.root)['status'],'review_pending')

    def test_frame_duration_must_follow_count_and_fps_and_unsupported_local_mixing_is_rejected(self):
        local_gifs.build(self.root,gif_id='gif-001',frames=self.frames,fps=10,width=96)
        bundle=self.bundle();bundle['generation-plan']['local_gifs'][0]['recipe']['duration']=1
        self.assertFalse(validate_plan(bundle,self.root)['ok'])
        other=create('scenic',seconds=10);other['generation-plan']['local_gifs']=self.bundle()['generation-plan']['local_gifs']
        self.assertFalse(validate_plan(other)['ok'])

    def test_manager_local_gif_panel_and_conversion_forms_offscreen_without_network(self):
        import tkinter as tk
        from videocreate.manager import Manager
        from videocreate.manager_gifs import open_form
        from videocreate.manager_projects import open_panel
        from videocreate.config.management import migrate
        from test_v3_config import config
        self.build()
        window=tk.Tk();window.withdraw();self.addCleanup(window.destroy)
        settings=self.root.parent/'config.json';atomic_json(settings,migrate(config()));before=settings.read_bytes()
        manager=Manager(window,settings)
        with mock.patch.object(manager,'error') as error,mock.patch('urllib.request.urlopen') as network:
            panel=open_panel(manager,self.root);panel.withdraw()
            for frames,paths in ((False,[self.source]),(True,self.frames)):
                form=open_form(manager,self.root,frames=frames,paths=paths);form.withdraw();window.update_idletasks();form.destroy()
            window.update_idletasks();panel.destroy();error.assert_not_called();network.assert_not_called()
        self.assertEqual(settings.read_bytes(),before)

    def test_rebuild_and_frame_cli_reject_ignored_parameters_before_any_conversion(self):
        cases=[['gif-rebuild','--gif','gif-001','--fps','20'],
            ['gif-frames','--gif','gif-001','--frame',str(self.frames[0]),'--duration','1'],
            ['gif-video','--gif','gif-001','--source',str(self.source),'--end','1']]
        with mock.patch.object(local_gifs,'build') as build:
            for action,*args in cases:
                with self.assertRaises(ConfigError):production_command([action,str(self.root),*args])
            build.assert_not_called()


if __name__=='__main__':unittest.main()
