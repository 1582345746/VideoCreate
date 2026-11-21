"""Project asset editing, local snapshots and per-source review dependencies."""
import base64
import copy
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts'),str(ROOT/'tests')]
from videocreate import authoring,asset_library,project_assets
from videocreate.cli import main
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import compile_job,load_project,save_bundle
from videocreate.review import receipts
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state,save_state
import test_screenplay_authoring as screenplay_tests

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS4cAAAAASUVORK5CYII=')


def voice(path):
    with wave.open(str(path),'wb') as out:
        out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(b'\0\0'*16000)


class ProjectAssetTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.parent=Path(temporary.name)
        self.root=self.parent/'项目';save_bundle(self.root,smart_car());self.image=self.parent/'原图.png';self.image.write_bytes(PNG)

    def save(self,director):
        current=authoring.describe(self.root,'director');report=authoring.preview(self.root,'director',director,source_token=current['source_token'])
        saved=authoring.save(self.root,'director',director,source_token=current['source_token'],preview_token=report['preview_token'])
        return saved

    def completed(self):
        bundle=load_project(self.root);records={}
        for index in (0,1):
            job=bundle['generation-plan']['jobs'][index];source=self.root/(job['id']+'.mp4');source.write_bytes(b'synthetic contract bytes only')
            compiled=compile_job(bundle,job,max_bytes=10000,root=self.root)
            records[job['id']]={'status':'completed','task_id':'original-'+job['id'],
                'input_hash':jobs.generation_inputs(self.root,bundle,job,compiled),
                'artifact':{'path':source.name,'sha256':project_assets.digest(source),'media':{'duration':5}}}
        save_state(self.root,{'schema_version':3,'jobs':records,'ledger':[]});return bundle

    def test_reference_staging_is_local_hash_bound_and_does_not_attach_or_mutate_plans(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            result=project_assets.stage_reference(self.root,self.image,kind='character')
        self.assertEqual((self.root/result['path']).read_bytes(),PNG);self.assertEqual(self.image.read_bytes(),PNG)
        self.assertEqual(Path(result['path']).stem,result['sha256']);self.assertEqual(result['content_status'],'unverified')
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        self.assertFalse((self.root/'state.json').exists())

    def test_concurrent_reference_staging_is_idempotent_and_never_overwrites_corrupted_snapshot(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _:project_assets.stage_reference(self.root,self.image,kind='prop'),range(3)))
        self.assertEqual(len({r['path'] for r in results}),1)
        target=self.root/results[0]['path'];target.write_bytes(b'preserve unexpected bytes')
        with self.assertRaisesRegex(ConfigError,'preserved'):project_assets.stage_reference(self.root,self.image,kind='prop')
        self.assertEqual(target.read_bytes(),b'preserve unexpected bytes')
        self.assertFalse(list(target.parent.glob('.staging-*')))

    def test_inspection_mutation_and_unsupported_reference_do_not_attach_or_leave_a_partial_snapshot(self):
        original=project_assets.inspect_reference
        def changed(path,kind):
            result=original(path,kind);path.write_bytes(b'changed during inspection');return result
        with mock.patch.object(project_assets,'inspect_reference',side_effect=changed):
            with self.assertRaisesRegex(ConfigError,'during inspection'):project_assets.stage_reference(self.root,self.image,kind='character')
        self.assertFalse(list((self.root/'assets/references/snapshots').glob('*')))
        with self.assertRaises(ConfigError):project_assets.stage_reference(self.root,self.image,kind='voice')
        self.assertEqual(load_project(self.root)['director'],smart_car()['director'])

    def test_audio_staging_requires_real_audio_and_preserves_the_original(self):
        source=self.parent/'声音.wav';voice(source);before=source.read_bytes()
        result=project_assets.stage_reference(self.root,source,kind='voice')
        self.assertEqual(result['inspection']['kind'],'audio');self.assertEqual(result['inspection']['duration'],1)
        self.assertEqual((self.root/result['path']).read_bytes(),before);self.assertEqual(source.read_bytes(),before)
        fake=self.parent/'fake.wav';fake.write_bytes(PNG)
        with self.assertRaises(ConfigError):project_assets.stage_reference(self.root,fake,kind='voice')

    def test_visual_and_physical_design_reuse_preserves_exact_immutable_library_versions(self):
        result=project_assets.stage_reference(self.root,self.image,kind='character');bundle=load_project(self.root)
        card=bundle['director']['assets'][0];card.update(references=[result['path']],
            visual_design={'identity':'圆脸人类书生','wardrobe':'青色长衫','expression_range':'克制的惊讶','visual_style':'写实'},
            physical_design={'scale':'成年人体型','placement':'桌旁可触到键盘','contact_constraints':'手掌支撑物件'})
        self.save(bundle['director']);store=self.parent/'library';revision=asset_library.publish(self.root,store,card['id'],'hero')
        target=self.parent/'next';save_bundle(target,smart_car());imported=asset_library.import_asset(target,store,'hero',revision['version'],'new-hero')
        self.assertEqual(imported['asset']['visual_design'],card['visual_design']);self.assertEqual(imported['asset']['physical_design'],card['physical_design'])
        self.assertEqual(imported['content_status'],'unverified')
        bundle['director']['assets'][0]['visual_design']['wardrobe']='白色长衫';self.save(bundle['director'])
        self.assertNotEqual(asset_library.publish(self.root,store,card['id'],'hero')['version'],revision['version'])
        self.assertEqual(load_project(target)['director']['assets'][-1]['visual_design']['wardrobe'],'青色长衫')

    def test_visible_asset_design_is_compiled_only_for_consuming_jobs(self):
        self.completed();bundle=load_project(self.root)
        bundle['director']['assets'][0]['visual_design']={'wardrobe':'青色长衫'}
        bundle['director']['assets'][0]['physical_design']={'contact_constraints':'双脚着地'}
        result=self.save(bundle['director'])
        self.assertEqual(result['impact']['changed_job_inputs'],['job-002'])
        first=compile_job(bundle,bundle['generation-plan']['jobs'][0],max_bytes=10000,root=self.root)
        second=compile_job(bundle,bundle['generation-plan']['jobs'][1],max_bytes=10000,root=self.root)
        self.assertNotIn('青色长衫',first['prompt']);self.assertIn('青色长衫',second['prompt'])
        self.assertIn('kongming.physical_design',second['retained'])
        self.assertEqual(read_state(self.root)['jobs']['job-002']['task_id'],'original-job-002')

    def test_card_reference_is_not_silently_sent_as_generation_reference(self):
        self.completed();bundle=load_project(self.root);snapshot=project_assets.stage_reference(self.root,self.image,kind='character')
        bundle['director']['assets'][0]['references']=[snapshot['path']]
        before=(self.root/'generation-plan.json').read_bytes();result=self.save(bundle['director'])
        self.assertEqual(result['impact']['changed_job_inputs'],[])
        self.assertEqual((self.root/'generation-plan.json').read_bytes(),before)

    def test_descriptor_and_reference_byte_changes_stale_only_sources_using_that_asset(self):
        bundle=self.completed();first=receipts.contracts(self.root,bundle,include_final=False)
        snapshot=project_assets.stage_reference(self.root,self.image,kind='character');bundle['director']['assets'][0]['references']=[snapshot['path']]
        second=receipts.contracts(self.root,bundle,include_final=False)
        self.assertEqual(first['job-001']['contract_hash'],second['job-001']['contract_hash'])
        self.assertNotEqual(first['job-002']['contract_hash'],second['job-002']['contract_hash'])
        (self.root/snapshot['path']).write_bytes(b'changed reference bytes')
        third=receipts.contracts(self.root,bundle,include_final=False)
        self.assertNotEqual(second['job-002']['contract_hash'],third['job-002']['contract_hash'])
        self.assertEqual(second['job-001']['contract_hash'],third['job-001']['contract_hash'])
        bundle['director']['assets'][0]['description']='Changed identity specification'
        self.assertNotEqual(third['job-002']['contract_hash'],receipts.contracts(self.root,bundle,include_final=False)['job-002']['contract_hash'])

    def test_old_source_passes_require_current_card_context_and_unrelated_source_passes_remain(self):
        bundle=self.completed();packet=receipts.template(self.root,bundle);packet['reviewer_id']='synthetic-contract-fixture'
        for asset in packet['assets'].values():
            for layer,item in asset['layers'].items():
                if layer not in asset['required_layers']:item['status']='not_applicable';continue
                item.update(status='pass',method='human-listening' if layer=='audio' else 'human-video',
                    observations=['Synthetic scope test; no actual human approval'],
                    evidence=[{'path':asset['path'],'sha256':asset['sha256'],'start':0,'end':asset['duration'],'kind':'video'}])
        receipts.apply(self.root,bundle,packet);before=(self.root/'state.json').read_bytes()
        bundle['director']['assets'][0]['visual_design']={'identity':'Changed identity'}
        result=receipts.summary(self.root,bundle)
        self.assertEqual(result['assets']['job-001']['performance_motion'],'pass')
        self.assertEqual(result['assets']['job-002']['identity'],'unverified')
        self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_board_shows_selected_candidate_and_opening_reference_but_never_approves_or_fetches(self):
        bundle=self.completed();snapshot=project_assets.stage_reference(self.root,self.image,kind='character')
        card=bundle['director']['assets'][0];card['references']=[snapshot['path']];card['description']='</pre><script>unexpected()</script>'
        bundle['generation-plan']['jobs'][1]['references']=[{'path':snapshot['path'],'sha256':snapshot['sha256'],'role':'opening-frame'}]
        atomic_json(self.root/'director.json',bundle['director']);atomic_json(self.root/'generation-plan.json',bundle['generation-plan'])
        state=read_state(self.root);chosen=copy.deepcopy(state['jobs']['job-002']);chosen['attempt_id']='chosen';chosen['artifact']['path']='chosen.mp4'
        (self.root/'chosen.mp4').write_bytes(b'synthetic contract bytes only')
        state['jobs']['job-002'].update(attempt_id='later',history=[chosen],selection={'attempt_id':'chosen','sha256':chosen['artifact']['sha256']})
        save_state(self.root,state);before=(self.root/'state.json').read_bytes()
        with mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            result=project_assets.board(self.root,'kongming')
        self.assertTrue(result['comparison_only']);self.assertEqual(result['content_status'],'unverified')
        self.assertTrue(any(m['path']=='chosen.mp4' for m in result['media']));self.assertTrue(any(m['role']=='任务首帧参考' for m in result['media']))
        text=Path(result['page']).read_text(encoding='utf-8');self.assertNotIn('<script>unexpected()',text);self.assertIn('&lt;script&gt;',text)
        self.assertIn('<video controls',text);self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_board_reports_tampered_snapshot_and_missing_sources_without_presenting_them_as_valid(self):
        self.completed();snapshot=project_assets.stage_reference(self.root,self.image,kind='character');bundle=load_project(self.root)
        bundle['director']['assets'][0]['references']=[snapshot['path']];self.save(bundle['director'])
        (self.root/snapshot['path']).write_bytes(b'tampered');(self.root/'job-002.mp4').unlink()
        result=project_assets.board(self.root,'kongming')
        self.assertEqual(result['media'],[]);self.assertIn(snapshot['path'],result['unavailable']);self.assertIn('job-002',result['unavailable'])

    def test_board_rejects_project_changes_during_export_instead_of_combining_two_versions(self):
        original=asset_library.impact
        def changed(*args):
            result=original(*args);bundle=load_project(self.root)
            bundle['director']['assets'][0]['description']='A newer asset revision';atomic_json(self.root/'director.json',bundle['director'])
            return result
        with mock.patch.object(asset_library,'impact',side_effect=changed):
            with self.assertRaisesRegex(ConfigError,'changed during'):project_assets.board(self.root,'kongming')
        self.assertFalse(list((self.root/'review/asset-boards').glob('*.html')))

    def test_board_rejects_tampered_imported_library_reference_without_replacing_bytes(self):
        staged=project_assets.stage_reference(self.root,self.image,kind='character');bundle=load_project(self.root)
        bundle['director']['assets'][0]['references']=[staged['path']];self.save(bundle['director'])
        store=self.parent/'library';revision=asset_library.publish(self.root,store,'kongming','hero')
        imported=asset_library.import_asset(self.root,store,'hero',revision['version'],'reused-hero')
        before=project_assets.board(self.root,'reused-hero');self.assertEqual(len(before['media']),1)
        path=imported['asset']['references'][0];(self.root/path).write_bytes(b'changed imported bytes')
        after=project_assets.board(self.root,'reused-hero')
        self.assertEqual(after['media'],[]);self.assertIn(path,after['unavailable'])
        self.assertEqual((self.root/path).read_bytes(),b'changed imported bytes')

    def test_cli_snapshot_and_board_do_not_read_provider_config(self):
        def call(args):
            with redirect_stdout(io.StringIO()) as output:code=main(['assets',*args])
            return code,json.loads(output.getvalue())
        with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config')):
            code,result=call(['stage-reference',str(self.root),'--source',str(self.image),'--asset-kind','prop'])
            self.assertEqual(code,0);self.assertEqual(result['paid_creates'],0)
            code,result=call(['board',str(self.root),'--asset-id','kongming']);self.assertEqual(code,0)
            self.assertTrue(Path(result['page']).is_file())


class ProjectAssetFormTests(unittest.TestCase):
    setUp=screenplay_tests.ScreenplayFormsTests.setUp
    widgets=screenplay_tests.ScreenplayFormsTests.widgets
    button=screenplay_tests.ScreenplayFormsTests.button
    field=screenplay_tests.ScreenplayFormsTests.field
    pump=screenplay_tests.ScreenplayFormsTests.pump

    def wait_progress(self,progress):
        progress.withdraw();deadline=time.monotonic()+5
        def check():
            if not progress.winfo_exists() or time.monotonic()>=deadline:self.window.quit()
            else:self.window.after(10,check)
        self.window.after(0,check);self.window.mainloop();self.assertFalse(progress.winfo_exists())

    def open(self):
        from videocreate.manager_authoring import open_editor
        win=open_editor(self.manager,self.root,'director',assets_only=True);win.withdraw();return win

    def test_all_card_types_roundtrip_and_design_edits_save_without_changing_scenes_shots_or_config(self):
        bundle=load_project(self.root);bundle['director']['assets'].append({'id':'voice','kind':'voice','description':'voice card','references':[]})
        bundle['director']['assets'][0]['visual_design']={};atomic_json(self.root/'director.json',bundle['director'])
        win=self.open();editor=win.authoring_director.assets.items
        for index in range(len(editor.items)):
            editor.commit();editor.refresh(index);self.assertEqual(win.authoring_read(),bundle['director'])
        editor.commit();editor.refresh(0);editor.editor.visual.enabled.set(True)
        self.field(editor.editor.visual.form,'wardrobe','青色长衫');editor.editor.physical.enabled.set(True)
        self.field(editor.editor.physical.form,'scale','成年人体型')
        with mock.patch.object(self.manager,'error') as error:
            self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win);error.assert_not_called()
        after=load_project(self.root);self.assertEqual(after['director']['scenes'],bundle['director']['scenes'])
        self.assertEqual(after['director']['shots'],bundle['director']['shots']);self.assertEqual(after['director']['assets'][0]['visual_design']['wardrobe'],'青色长衫')
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_import_button_runs_off_main_thread_and_save_attaches_snapshot_without_network(self):
        image=self.parent/'local.png';image.write_bytes(PNG);win=self.open();refs=win.authoring_director.assets.items.editor.references
        threads=[];original=project_assets.stage_reference
        def staged(*args,**kwargs):threads.append(threading.get_ident());return original(*args,**kwargs)
        with mock.patch.object(project_assets,'stage_reference',side_effect=staged),mock.patch('urllib.request.urlopen') as network,mock.patch.object(self.manager,'error') as error:
            progress=refs.import_file(image);self.wait_progress(progress)
            self.assertEqual(load_project(self.root)['director']['assets'][0].get('references',[]),[])
            path=refs.paths[0];self.assertEqual((self.root/path).read_bytes(),PNG)
            self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
            error.assert_not_called();network.assert_not_called()
        self.assertNotIn(threading.get_ident(),threads);self.assertEqual(load_project(self.root)['director']['assets'][0]['references'],[path])
        self.assertFalse((self.root/'state.json').exists())

    def test_removing_unsaved_reference_keeps_snapshot_and_cancelled_form_keeps_plan(self):
        image=self.parent/'local.png';image.write_bytes(PNG);before=(self.root/'director.json').read_bytes();win=self.open()
        refs=win.authoring_director.assets.items.editor.references;self.wait_progress(refs.import_file(image));path=self.root/refs.paths[0]
        refs.tree.selection_set(0);refs.remove();self.assertEqual(refs.paths,[]);self.assertTrue(path.is_file())
        win.destroy();self.assertEqual((self.root/'director.json').read_bytes(),before)

    def test_new_voice_card_and_reference_import_need_no_model_selection(self):
        source=self.parent/'voice.wav';voice(source);win=self.open();cards=win.authoring_director.assets.items;cards.add()
        editor=cards.editor;self.field(editor.form,'kind','voice');self.field(editor.form,'description','声音样本')
        self.wait_progress(editor.references.import_file(source));path=editor.references.paths[0]
        self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
        new=load_project(self.root)['director']['assets'][-1];self.assertEqual(new['kind'],'voice');self.assertEqual(new['references'],[path])
        self.assertFalse((self.root/'state.json').exists())

    def test_saved_board_opens_local_page_without_creating_an_approval(self):
        win=self.open();refs=win.authoring_director.assets.items.editor.references
        with mock.patch('videocreate.manager_assets.webbrowser.open') as browser,mock.patch.object(self.manager,'error') as error:
            self.wait_progress(refs.board());browser.assert_called_once();error.assert_not_called()
        self.assertTrue(browser.call_args.args[0].startswith('file:'));self.assertFalse((self.root/'state.json').exists());win.destroy()

    def test_destroyed_import_form_cancels_poll_and_worker_retains_only_unattached_snapshot(self):
        image=self.parent/'local.png';image.write_bytes(PNG);before=(self.root/'director.json').read_bytes()
        win=self.open();refs=win.authoring_director.assets.items.editor.references;started=threading.Event();release=threading.Event();finished=threading.Event()
        original=project_assets.stage_reference
        def delayed(*args,**kwargs):
            started.set();release.wait(2)
            try:return original(*args,**kwargs)
            finally:finished.set()
        with mock.patch.object(project_assets,'stage_reference',side_effect=delayed):
            existing=set(self.window.tk.call('after','info'))
            progress=refs.import_file(image);progress.withdraw();self.assertTrue(started.wait(1))
            timers=set(self.window.tk.call('after','info'))-existing;self.assertTrue(timers)
            win.destroy();self.assertFalse(timers & set(self.window.tk.call('after','info')))
            self.assertIn(self.manager.recovery.timer,self.window.tk.call('after','info'))
            release.set();deadline=time.monotonic()+4
            def check():
                if finished.is_set() or time.monotonic()>=deadline:self.window.quit()
                else:self.window.after(10,check)
            self.window.after(0,check);self.window.mainloop();self.assertTrue(finished.is_set())
        self.assertEqual((self.root/'director.json').read_bytes(),before)
        self.assertTrue(list((self.root/'assets/references/snapshots').glob('*.png')))


if __name__=='__main__':unittest.main()
