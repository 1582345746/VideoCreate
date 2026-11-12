"""Generation plans remain editable without losing original tasks or local media."""
import base64
import copy
import io
import json
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts'),str(ROOT/'tests')]
from videocreate import authoring,generation_authoring
from videocreate.cli import main
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project,save_bundle,compile_job
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state,save_state
import test_screenplay_authoring as screenplay_tests
import test_project_asset_authoring as asset_tests
import test_gif_media as gif_tests

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS4cAAAAASUVORK5CYII=')


class GenerationAuthoringTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.parent=Path(temporary.name);self.root=self.parent/'project';save_bundle(self.root,smart_car())

    def snapshot(self):return authoring.describe(self.root,'generation-plan')

    def preview(self,value,current=None):
        current=current or self.snapshot()
        return authoring.preview(self.root,'generation-plan',value,source_token=current['source_token'])

    def save(self,value,current=None):
        current=current or self.snapshot();report=self.preview(value,current)
        return authoring.save(self.root,'generation-plan',value,source_token=current['source_token'],preview_token=report['preview_token'])

    def tasks(self,status='completed'):
        bundle=load_project(self.root);records={}
        for job in bundle['generation-plan']['jobs']:
            compiled=compile_job(bundle,job,max_bytes=10000,root=self.root)
            records[job['id']]={'status':status,'task_id':'original-'+job['id'],
                'input_hash':jobs.generation_inputs(self.root,bundle,job,compiled),
                'binding_snapshot':{'binding_id':'original-binding','capabilities':{'max_prompt_bytes':10000}},
                'history':[{'attempt_id':'old-attempt'}]}
        save_state(self.root,{'schema_version':3,'jobs':records,'ledger':[{'event':'original-ledger'}]})

    def test_completed_job_edit_stales_only_consuming_input_and_saves_one_layer(self):
        self.tasks();before={p.name:p.read_bytes() for p in self.root.glob('*.json')};value=self.snapshot()['value']
        value['jobs'][1]['seconds']=7
        with mock.patch('videocreate.runtime.jobs.client') as client,mock.patch('urllib.request.urlopen') as network:
            result=self.save(value);client.assert_not_called();network.assert_not_called()
        self.assertEqual(result['impact']['changed_job_inputs'],['job-002'])
        self.assertEqual(load_json(Path(result['backup'])),smart_car()['generation-plan'])
        for name,data in before.items():
            if name!='generation-plan.json':self.assertEqual((self.root/name).read_bytes(),data)

    def test_active_unknown_and_read_pending_jobs_reject_changes_without_writes(self):
        for status in ('submitting','submission_unknown','queued','in_progress','read_pending','unknown'):
            self.tasks(status);value=self.snapshot()['value'];value['jobs'][0]['seconds']=7
            before=(self.root/'generation-plan.json').read_bytes()
            with self.assertRaisesRegex(ConfigError,'active or unresolved'):self.save(value)
            self.assertEqual((self.root/'generation-plan.json').read_bytes(),before)
        self.assertFalse((self.root/'production/backups').exists())

    def test_noop_active_plan_can_be_read_previewed_and_saved_without_task_changes(self):
        self.tasks('submission_unknown');before=(self.root/'state.json').read_bytes()
        result=self.save(self.snapshot()['value']);self.assertFalse(result['changed'])
        self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_saved_task_ids_cannot_be_removed_renamed_or_moved_between_kinds(self):
        self.tasks()
        for action in ('remove','rename','move'):
            value=self.snapshot()['value']
            if action=='rename':value['jobs'][0]['id']='new-name'
            else:
                job=value['jobs'].pop(0)
                if action=='move':value['image_jobs']=[{'id':job['id'],'operation':'text-to-image','prompt':'A boat','size':'1024x1024','quality':'auto','output_format':'png'}]
            with self.assertRaisesRegex(ConfigError,'cannot be deleted'):self.preview(value)

    def test_orphaned_task_history_cannot_be_claimed_by_a_new_job(self):
        self.tasks();state=read_state(self.root);state['jobs']['orphan']=copy.deepcopy(state['jobs']['job-001']);save_state(self.root,state)
        value=self.snapshot()['value'];value['jobs'].append({**value['jobs'][0],'id':'orphan'})
        with self.assertRaisesRegex(ConfigError,'already belongs'):self.preview(value)

    def test_route_edits_describe_future_scope_and_preserve_original_binding_and_candidates(self):
        self.tasks();before=(self.root/'state.json').read_bytes();value=self.snapshot()['value']
        value['jobs'][0].update(model='future-model',binding_id='future-binding')
        result=self.save(value);row=result['generation_changes']['jobs'][0]
        self.assertEqual(row['route_change']['original_binding'],'original-binding')
        self.assertIn('future explicit attempt',row['route_change']['scope'])
        self.assertEqual(result['impact']['changed_job_inputs'],[])
        self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_new_unsubmitted_jobs_can_be_added_removed_and_reordered_without_timeline_rewrites(self):
        before=(self.root/'timeline.json').read_bytes();value=self.snapshot()['value']
        value['jobs'].append({**copy.deepcopy(value['jobs'][0]),'id':'new-job'});value['jobs'].reverse();result=self.save(value)
        self.assertIn('new-job',result['impact']['not_submitted']);self.assertFalse((self.root/'state.json').exists())
        value=self.snapshot()['value'];value['jobs']=[job for job in value['jobs'] if job['id']!='new-job'];self.save(value)
        self.assertEqual((self.root/'timeline.json').read_bytes(),before)

    def test_incomplete_mapping_and_cyclic_dependencies_save_as_blocked_drafts(self):
        value=self.snapshot()['value'];value['jobs'][0]['shot_ids']=['missing-shot']
        value['jobs'][0]['depends_on']=['job-002'];value['jobs'][1]['depends_on']=['job-001']
        result=self.save(value);self.assertFalse(result['plan_validation']['ok'])
        self.assertTrue(any('cyclic' in e for e in result['plan_validation']['errors']))
        with mock.patch('videocreate.runtime.jobs.client') as client:
            with self.assertRaises(ConfigError):jobs.generate(self.root,{},store_root=self.parent)
            client.assert_not_called()

    def test_local_source_and_local_gif_records_are_owned_by_their_existing_services(self):
        value=self.snapshot()['value']
        source={'id':'local','kind':'video','path':'source.mp4','sha256':'a'*64,'shot_ids':['shot-001'],
            'media':{'duration':1,'width':16,'height':16,'has_audio':False,'fps':'24/1'}}
        value['local_sources']=[source]
        with self.assertRaisesRegex(ConfigError,'local import/GIF'):self.preview(value)
        self.root=self.parent/'local-gif';save_bundle(self.root,create('gif-local',title='Local GIF'))
        frame=self.parent/'frame.png';frame.write_bytes(PNG)
        from videocreate.local_gifs import build
        built=build(self.root,gif_id='loop',frames=[frame,frame],fps=10,width=96)
        before=(self.root/'generation-plan.json').read_bytes();value=self.snapshot()['value']
        value['local_gifs'][0]['recipe']['width']=128
        with self.assertRaisesRegex(ConfigError,'local import/GIF'):self.preview(value)
        self.assertEqual((self.root/'generation-plan.json').read_bytes(),before)

    def test_stale_preview_after_task_transition_preserves_plan(self):
        self.tasks('failed');current=self.snapshot();value=copy.deepcopy(current['value']);value['jobs'][0]['seconds']=7
        report=self.preview(value,current);state=read_state(self.root);state['jobs']['job-001']['status']='queued';save_state(self.root,state)
        with self.assertRaisesRegex(ConfigError,'active or unresolved'):
            authoring.save(self.root,'generation-plan',value,source_token=current['source_token'],preview_token=report['preview_token'])
        self.assertEqual(load_project(self.root)['generation-plan'],current['value'])

    def test_custom_layer_path_and_noop_save_preserve_authoritative_files(self):
        project=load_json(self.root/'project.json');project.setdefault('files',{})['generation-plan']='plans/generation.json'
        atomic_json(self.root/'plans/generation.json',self.snapshot()['value']);atomic_json(self.root/'project.json',project)
        legacy=(self.root/'generation-plan.json').read_bytes();value=self.snapshot()['value'];value['jobs'][0]['seconds']=7
        self.save(value);self.assertEqual(load_json(self.root/'plans/generation.json'),value)
        self.assertEqual((self.root/'generation-plan.json').read_bytes(),legacy)
        self.assertFalse(self.save(value)['changed'])

    def test_animation_projection_cannot_gain_a_competing_generation_source(self):
        atomic_json(self.root/'animation.json',{})
        project=load_json(self.root/'project.json');project.setdefault('files',{})['animation']='animation.json';atomic_json(self.root/'project.json',project)
        with self.assertRaisesRegex(ConfigError,'sidecar'):self.snapshot()

    def test_image_attempts_keep_same_active_guard_and_preserve_terminal_history(self):
        self.root=self.parent/'images';save_bundle(self.root,create('image-only',title='Images',topic='A boat'))
        value=self.snapshot()['value'];job=value['image_jobs'][0]
        record={'status':'submission_unknown','kind':'image','task_id':'original-image','history':[{'attempt_id':'older'}]}
        save_state(self.root,{'schema_version':3,'jobs':{job['id']:record},'ledger':[]})
        job['prompt']='A revised image'
        with self.assertRaisesRegex(ConfigError,'active or unresolved'):self.preview(value)
        state=read_state(self.root);state['jobs'][job['id']]['status']='failed';save_state(self.root,state);before=(self.root/'state.json').read_bytes()
        self.assertTrue(self.save(value)['changed']);self.assertEqual((self.root/'state.json').read_bytes(),before)
        value['image_jobs']=[]
        with self.assertRaisesRegex(ConfigError,'cannot be deleted'):self.preview(value)

    def test_registered_reference_json_checks_real_bytes_strips_transport_and_preserves_kind_order(self):
        source=self.root/'ref.png';source.write_bytes(PNG)
        from videocreate.media_references import register
        ref=register(self.root,source,kind='image',role='identity')
        imported=generation_authoring.reference_from_json(self.root,{**ref,'url':'https://private.example.test/token'})
        self.assertEqual(imported,ref);self.assertNotIn('url',imported)
        self.assertEqual(generation_authoring.reference_from_json(self.root,ref,image=True),{'path':ref['path'],'sha256':ref['sha256']})
        (self.root/ref['path']).write_bytes(b'changed')
        with self.assertRaises(ConfigError):generation_authoring.reference_from_json(self.root,ref)

    def test_wrong_reference_kind_is_rejected_for_image_tasks(self):
        with self.assertRaisesRegex(ConfigError,'image references only'):
            generation_authoring.reference_from_json(self.root,{'kind':'audio'},image=True)

    def test_image_reference_json_retains_animated_gif_bytes_and_checks_hash(self):
        source=self.root/'animation.gif';source.write_bytes(gif_tests.gif_fixture((5,10)))
        from videocreate.media.gif import probe_image
        metadata=probe_image(source);ref={'path':'animation.gif','sha256':metadata['sha256'],'kind':'image','role':'identity'}
        result=generation_authoring.reference_from_json(self.root,ref,image=True)
        self.assertEqual(result['sha256'],metadata['sha256']);self.assertEqual(probe_image(source)['frame_count'],2)
        with self.assertRaisesRegex(ConfigError,'bytes changed'):
            generation_authoring.reference_from_json(self.root,{**ref,'sha256':'0'*64},image=True)

    def test_cli_generation_layer_uses_same_offline_preview_and_save(self):
        current=self.snapshot();value=current['value'];value['jobs'][0]['seconds']=7
        edit=self.parent/'edit.json';atomic_json(edit,value)
        args=['authoring','preview',str(self.root),'--layer','generation-plan','--file',str(edit),'--source-token',current['source_token']]
        with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config')):
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(args),0)
            preview=json.loads(output.getvalue());args[1]='save';args+=['--preview-token',preview['preview_token']]
            with redirect_stdout(io.StringIO()):self.assertEqual(main(args),0)
        self.assertEqual(load_project(self.root)['generation-plan'],value)


class GenerationFormTests(unittest.TestCase):
    setUp=screenplay_tests.ScreenplayFormsTests.setUp
    widgets=screenplay_tests.ScreenplayFormsTests.widgets
    button=screenplay_tests.ScreenplayFormsTests.button
    field=screenplay_tests.ScreenplayFormsTests.field
    pump=screenplay_tests.ScreenplayFormsTests.pump
    wait_progress=asset_tests.ProjectAssetFormTests.wait_progress

    def open(self):
        from videocreate.manager_authoring import open_editor
        win=open_editor(self.manager,self.root,'generation-plan');win.withdraw();return win

    def test_video_jobs_roundtrip_and_seconds_edit_save_without_config_or_timeline_change(self):
        original=load_project(self.root);value=original['generation-plan'];value['jobs'][0].update(references=[],depends_on=[],model='')
        atomic_json(self.root/'generation-plan.json',value);win=self.open();form=win.authoring_generation
        self.assertEqual(win.authoring_read(),value)
        for index in range(len(form.jobs.items)):
            form.jobs.commit();form.jobs.refresh(index);self.assertEqual(win.authoring_read(),value)
        self.field(form.jobs.editor.form,'seconds','7')
        with mock.patch.object(self.manager,'error') as error:
            self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win);error.assert_not_called()
        after=load_project(self.root);self.assertEqual(after['timeline'],original['timeline']);self.assertEqual(self.path.read_bytes(),self.before)
        self.assertEqual(after['generation-plan']['jobs'][-1]['seconds'],7)

    def test_binding_choice_can_explicitly_fill_exact_internal_model_without_changing_config(self):
        win=self.open();route=win.authoring_generation.jobs.editor.route
        binding=next(key for key,b in self.manager.value['bindings'].items() if self.manager.value['models'][b['model']]['kind']=='video')
        self.field(route.form,'binding_id',binding);route.match();value=route.read()
        self.assertEqual(value['model'],self.manager.value['bindings'][binding]['model'])
        self.assertEqual(self.path.read_bytes(),self.before);self.assertFalse((self.root/'state.json').exists());win.destroy()

    def test_job_order_and_new_incomplete_job_do_not_rewrite_source_or_playback(self):
        before=(self.root/'timeline.json').read_bytes();win=self.open();form=win.authoring_generation.jobs
        form.move(1);form.add();self.field(form.editor.form,'shot_ids','missing-shot')
        self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
        self.assertEqual((self.root/'timeline.json').read_bytes(),before)
        self.assertEqual(load_project(self.root)['generation-plan']['jobs'][-1]['shot_ids'],['missing-shot'])

    def test_image_and_native_gif_job_forms_select_correct_branch_and_keep_other_layers(self):
        for profile in ('image-only','gif-only','gif-local'):
            self.root=self.parent/profile;save_bundle(self.root,create(profile,title='Pure test',topic='A boat'))
            original=load_project(self.root);win=self.open();form=win.authoring_generation
            self.assertIsNone(form.jobs);self.assertEqual(win.authoring_read(),original['generation-plan'])
            if not form.images.items:form.images.add()
            self.field(form.images.editor.form,'prompt','A synthetic boat moving slowly')
            self.assertEqual(form.images.editor.read()['output_format'],'png' if profile=='image-only' else 'gif')
            self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
            self.assertEqual(load_project(self.root)['timeline'],original['timeline']);self.assertFalse((self.root/'state.json').exists())

    def test_local_reference_picker_hashes_bytes_off_thread_and_save_attaches_only_to_job(self):
        source=self.root/'local.png';source.write_bytes(PNG);win=self.open();editor=win.authoring_generation.jobs.editor
        self.field(editor.form,'operation','image-to-video');refs=editor.references.items;refs.add()
        self.field(refs.editor.form,'role','opening-frame')
        with mock.patch('urllib.request.urlopen') as network,mock.patch.object(self.manager,'error') as error:
            self.wait_progress(refs.editor.choose(source))
            self.assertEqual(load_project(self.root)['generation-plan']['jobs'][0].get('references',[]),[])
            self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
            network.assert_not_called();error.assert_not_called()
        reference=load_project(self.root)['generation-plan']['jobs'][0]['references'][0]
        self.assertEqual(reference['path'],'local.png');self.assertEqual(reference['role'],'opening-frame');self.assertEqual(source.read_bytes(),PNG)

    def test_registered_audio_json_import_preserves_type_and_role_without_publishing(self):
        source=self.root/'voice.wav'
        with wave.open(str(source),'wb') as out:out.setparams((1,2,16000,0,'NONE','not compressed'));out.writeframes(b'\0\0'*16000)
        from videocreate.media_references import register
        ref=register(self.root,source,kind='audio',role='sound');file=self.root/'voice-reference.json';atomic_json(file,ref)
        win=self.open();editor=win.authoring_generation.jobs.editor;self.field(editor.form,'operation','reference-to-video')
        with mock.patch.object(self.manager,'error') as error,mock.patch('urllib.request.urlopen') as network:
            self.wait_progress(editor.references.import_json(file));error.assert_not_called();network.assert_not_called()
        value=win.authoring_read();self.assertEqual(value['jobs'][0]['references'],[ref])
        win.destroy();self.assertEqual(load_project(self.root)['generation-plan'],smart_car()['generation-plan'])

    def test_outside_file_selection_is_rejected_without_copy_or_plan_change(self):
        source=self.parent/'outside.png';source.write_bytes(PNG);win=self.open();refs=win.authoring_generation.jobs.editor.references.items;refs.add()
        before=(self.root/'generation-plan.json').read_bytes()
        with mock.patch.object(self.manager,'error') as error:
            self.assertIsNone(refs.editor.choose(source));error.assert_called_once()
        self.assertEqual((self.root/'generation-plan.json').read_bytes(),before);win.destroy()

    def test_pure_image_reference_picker_preserves_gif_animation_without_frame_extraction(self):
        self.root=self.parent/'gif-input';save_bundle(self.root,create('gif-only',title='GIF input',topic='A boat'))
        source=self.root/'animated.gif';original=gif_tests.gif_fixture((5,10));source.write_bytes(original)
        win=self.open();editor=win.authoring_generation.images.editor;self.field(editor.form,'operation','image-edit')
        refs=editor.references.items;refs.add()
        with mock.patch.object(self.manager,'error') as error:
            self.wait_progress(refs.editor.choose(source));error.assert_not_called()
        reference=win.authoring_read()['image_jobs'][0]['references'][0]
        self.assertEqual(reference['path'],'animated.gif');self.assertEqual(source.read_bytes(),original)
        self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
        self.assertEqual(load_project(self.root)['generation-plan']['image_jobs'][0]['references'],[reference])

    def test_project_panel_exposes_generation_editor_for_video_and_image_but_not_edit_only(self):
        from videocreate.manager_projects import open_panel
        for profile in ('mixed-video','image-only','gif-local','edit-only'):
            root=self.parent/('panel-'+profile);save_bundle(root,create(profile,title='Panel',topic='A boat'))
            panel=open_panel(self.manager,root);panel.withdraw()
            buttons=[widget.cget('text') for widget in self.widgets(panel) if widget.winfo_class()=='TButton']
            self.assertEqual('生成任务与参考' in buttons,profile!='edit-only');panel.destroy()


if __name__=='__main__':unittest.main()
