"""Edit-plan transactions, source/time mappings, real local rendering and GUI controls."""
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts'),str(ROOT/'tests')]
from videocreate import authoring, production
from videocreate.cli import main
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project, save_bundle
from videocreate.runtime.state import read_state, save_state
from videocreate.timeline_authoring import inspect
from videocreate.timeline.render import render
import test_screenplay_authoring as screenplay_tests
import test_mixed_video_production as mixed_tests


class TimelineAuthoringTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.parent=Path(temp.name);self.root=self.parent/'project';save_bundle(self.root,smart_car())

    def save(self,value):
        current=authoring.describe(self.root,'timeline')
        preview=authoring.preview(self.root,'timeline',value,source_token=current['source_token'])
        return authoring.save(self.root,'timeline',value,source_token=current['source_token'],preview_token=preview['preview_token'])

    def test_timeline_edits_preserve_active_tasks_candidates_ledger_and_generation_layers(self):
        state={'schema_version':3,'jobs':{'job-001':{'status':'submission_unknown','task_id':'original',
            'history':[{'attempt_id':'old'}],'binding_snapshot':{'binding_id':'original-binding'}}},'ledger':[{'event':'original'}]}
        save_state(self.root,state);before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        value=load_project(self.root)['timeline'];value['subtitles']=[{'text':'Observed caption','start':0,'end':1}]
        with mock.patch('videocreate.runtime.jobs.client') as client,mock.patch('urllib.request.urlopen') as network:
            result=self.save(value);client.assert_not_called();network.assert_not_called()
        for name,data in before.items():
            if name!='timeline.json':self.assertEqual((self.root/name).read_bytes(),data)
        self.assertEqual(load_json(Path(result['backup'])),smart_car()['timeline'])
        self.assertTrue(result['timeline_edit']['after']['ok']);self.assertEqual(result['paid_creates'],0)

    def test_source_captions_follow_reordered_retimed_segments_but_absolute_events_keep_time(self):
        value=smart_car()['timeline'];first,second=value['segments'][:2]
        value['subtitles']=[{'text':'Source anchored','segment_id':first['id'],'source_start':1,'source_end':2},
            {'text':'Absolute','start':.1,'end':.5}]
        value['audio_tracks']=[{'id':'voice','kind':'dialogue','clip_id':value['clips'][0]['id'],
            'source_in':1,'source_out':2,'timeline_start':.2}]
        value['segments'][0]['rate']=2;value['segments'][0]['source_audio']='mute'
        value['segments'][0],value['segments'][1]=second,first
        mapped=inspect(value);self.assertTrue(mapped['ok'])
        # First source window starts at .25: (1-.25)/2 + 2.5 seconds.
        self.assertEqual(mapped['subtitles'][0]['start'],2.875)
        self.assertEqual(mapped['subtitles'][0]['end'],3.375)
        self.assertEqual(mapped['subtitles'][1]['start'],.1);self.assertEqual(mapped['audio_tracks'][0]['timeline_start'],.2)

    def test_semantically_invalid_timeline_can_save_as_draft_with_mapping_errors(self):
        value=smart_car()['timeline'];value['segments'][0]['source_out']=100
        value['subtitles']=[{'text':'Cut caption','segment_id':value['segments'][1]['id'],'source_start':50,'source_end':60}]
        result=self.save(value);self.assertFalse(result['plan_validation']['ok'])
        self.assertFalse(result['timeline_edit']['after']['ok']);self.assertFalse((self.root/'state.json').exists())

    def test_custom_layer_path_and_noop_save_use_one_authoritative_file(self):
        value=smart_car()['timeline'];project=load_json(self.root/'project.json');project.setdefault('files',{})['timeline']='plans/edit.json'
        atomic_json(self.root/'plans/edit.json',value);atomic_json(self.root/'project.json',project)
        old=(self.root/'timeline.json').read_bytes();self.assertFalse(self.save(value)['changed'])
        value['segments'].reverse();self.save(value)
        self.assertEqual(load_json(self.root/'plans/edit.json'),value);self.assertEqual((self.root/'timeline.json').read_bytes(),old)

    def test_changed_task_state_invalidates_timeline_preview_without_writing_edit(self):
        current=authoring.describe(self.root,'timeline');value=current['value'];value['segments'].reverse()
        preview=authoring.preview(self.root,'timeline',value,source_token=current['source_token'])
        save_state(self.root,{'schema_version':3,'jobs':{'job-001':{'status':'queued'}},'ledger':[]})
        with self.assertRaisesRegex(ConfigError,'task state changed'):
            authoring.save(self.root,'timeline',value,source_token=current['source_token'],preview_token=preview['preview_token'])
        self.assertEqual(load_project(self.root)['timeline'],smart_car()['timeline'])

    def test_image_and_gif_collections_cannot_acquire_a_video_edit_source(self):
        for profile in ('image-only','gif-only','gif-local'):
            root=self.parent/profile;save_bundle(root,create(profile,title='Pure collection',topic='A boat'))
            with self.assertRaisesRegex(ConfigError,'no video timeline'):authoring.describe(root,'timeline')

    def test_canvas_bounds_are_shared_by_graph_preview_and_execution_validation(self):
        for width in (65,32,4098,True):
            value=smart_car()['timeline'];value['width']=width
            self.assertFalse(inspect(value)['ok'])
        value=smart_car()['timeline'];value['width']=66;self.assertTrue(inspect(value)['ok'])
        value=smart_car()['timeline'];value['width']=65;result=self.save(value)
        self.assertFalse(result['plan_validation']['ok']);self.assertFalse(result['timeline_edit']['after']['ok'])

    def test_animation_edit_keeps_its_sidecar_story_director_and_job_sources(self):
        from videocreate.animation import examples
        self.root=self.parent/'animation';examples.create(self.root)
        before={p:p.read_bytes() for p in self.root.glob('*.json')}
        value=authoring.describe(self.root,'timeline')['value'];value['subtitles']=[]
        self.save(value)
        for path,data in before.items():
            if path.name!='timeline.json':self.assertEqual(path.read_bytes(),data)

    def test_cli_uses_same_timeline_mapping_preview_and_save_without_provider_config(self):
        current=authoring.describe(self.root,'timeline');value=current['value'];value['segments'].reverse()
        file=self.parent/'edit.json';atomic_json(file,value)
        args=['authoring','preview',str(self.root),'--layer','timeline','--file',str(file),'--source-token',current['source_token']]
        with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config')):
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(args),0)
            preview=json.loads(output.getvalue());args[1]='save';args+=['--preview-token',preview['preview_token']]
            with redirect_stdout(io.StringIO()):self.assertEqual(main(args),0)
        self.assertEqual(load_project(self.root)['timeline'],value)


class TimelineFormTests(unittest.TestCase):
    setUp=screenplay_tests.ScreenplayFormsTests.setUp
    widgets=screenplay_tests.ScreenplayFormsTests.widgets
    button=screenplay_tests.ScreenplayFormsTests.button
    field=screenplay_tests.ScreenplayFormsTests.field
    pump=screenplay_tests.ScreenplayFormsTests.pump

    def open(self):
        from videocreate.manager_authoring import open_editor
        win=open_editor(self.manager,self.root,'timeline');win.withdraw();return win

    def test_noop_all_form_rows_preserve_optional_fields_and_original_whitespace(self):
        bundle=load_project(self.root);timeline=bundle['timeline']
        timeline['segments'][0]['cut_reason']='  Original spacing\n';timeline['segments'][0].pop('rate',None)
        timeline['subtitles']=[{'text':'  Text\n','segment_id':timeline['segments'][0]['id'],
            'source_start':1,'source_end':2,'start':50,'end':51}]
        timeline['audio_tracks']=[];timeline['overlays']=[];atomic_json(self.root/'timeline.json',timeline)
        win=self.open();form=win.authoring_timeline
        self.assertEqual(win.authoring_read(),timeline)
        for editor in (form.clips,form.segments,form.audio,form.subtitles,form.overlays):
            for index in range(len(editor.items)):
                editor.commit();editor.refresh(index);self.assertEqual(win.authoring_read(),timeline)
        self.button(win,'预览修改影响').invoke();self.pump(win)
        self.button(win,'保存当前创作层').invoke();self.pump(win)
        self.assertFalse((self.root/'production/backups').exists())

    def test_real_controls_reorder_trim_mute_and_save_only_timeline(self):
        original=load_project(self.root);saved=[]
        win=self.open();form=win.authoring_timeline;first=form.segments.items[0]['id']
        self.field(form.segments.editor,'source_in','0.2');self.field(form.segments.editor,'source_audio','mute')
        form.segments.move(1);form.draw();self.assertEqual(form.graph_data['segments'][1]['id'],first)
        with mock.patch.object(self.manager,'error') as error,mock.patch('urllib.request.urlopen') as network:
            self.button(win,'预览修改影响').invoke();self.pump(win)
            self.button(win,'保存当前创作层').invoke();self.pump(win);error.assert_not_called();network.assert_not_called()
        after=load_project(self.root);self.assertEqual(after['timeline']['segments'][1]['source_in'],.2)
        self.assertEqual(after['generation-plan'],original['generation-plan']);self.assertEqual(after['director'],original['director'])
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_graph_click_selects_the_same_stable_segment_without_changing_plan(self):
        win=self.open();form=win.authoring_timeline;form.select_segment(2)
        self.assertEqual(form.segments.current,2);self.assertEqual(form.segments.editor.read()['id'],smart_car()['timeline']['segments'][2]['id'])
        self.assertEqual(win.authoring_read(),smart_car()['timeline']);win.destroy()

    def test_absolute_and_source_subtitles_switch_explicitly_without_shadow_coordinates(self):
        win=self.open();editor=win.authoring_timeline.subtitles;editor.add();cue=editor.editor
        self.field(cue.form,'text','A verified line');cue.mode.set('源片区间')
        self.field(cue.form,'segment_id',win.authoring_timeline.segments.items[0]['id']);self.field(cue.form,'source_start','0.3');self.field(cue.form,'source_end','0.7')
        value=cue.read();self.assertNotIn('start',value);self.assertEqual(value['source_start'],.3)
        editor.commit();editor.refresh(editor.current);cue=editor.editor;cue.mode.set('成片时间')
        self.field(cue.form,'start','0.2');self.field(cue.form,'end','0.8')
        value=cue.read();self.assertNotIn('segment_id',value);self.assertNotIn('source_start',value);self.assertEqual(value['end'],.8)
        win.destroy()

    def test_unused_legacy_caption_coordinates_survive_noop_and_cannot_choose_mode(self):
        timeline=load_project(self.root)['timeline']
        timeline['subtitles']=[{'text':'Absolute cue','start':.3,'end':.7,'source_start':10,'source_end':11}]
        atomic_json(self.root/'timeline.json',timeline);win=self.open();cue=win.authoring_timeline.subtitles.editor
        self.assertEqual(win.authoring_read(),timeline)
        self.field(cue.form,'segment_id',timeline['segments'][0]['id']);self.field(cue.form,'source_start','12')
        self.assertEqual(win.authoring_read(),timeline);win.destroy()

    def test_cleared_source_anchor_cannot_fall_back_to_legacy_absolute_coordinates(self):
        timeline=load_project(self.root)['timeline']
        timeline['subtitles']=[{'text':'Source cue','segment_id':timeline['segments'][0]['id'],
            'source_start':.3,'source_end':.7,'start':.3,'end':.7}]
        atomic_json(self.root/'timeline.json',timeline);win=self.open();form=win.authoring_timeline
        self.field(form.subtitles.editor.form,'segment_id','');form.draw()
        self.assertFalse(form.graph_data['ok']);self.assertEqual(win.authoring_read()['subtitles'][0]['segment_id'],'')
        win.destroy()

    def test_audio_and_overlay_events_save_order_and_cue_times_without_generation(self):
        win=self.open();form=win.authoring_timeline;form.audio.add();audio=form.audio.editor
        self.field(audio,'clip_id','clip-001');self.field(audio,'gain_db','-3');self.field(audio,'timeline_start','1.5')
        form.overlays.add();self.field(form.overlays.editor,'text','A visible label')
        self.field(form.overlays.editor,'position','top');self.field(form.overlays.editor,'end','2')
        self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
        timeline=load_project(self.root)['timeline'];self.assertEqual(timeline['audio_tracks'][0]['gain_db'],-3)
        self.assertEqual(timeline['audio_tracks'][0]['timeline_start'],1.5);self.assertEqual(timeline['overlays'][0]['position'],'top')
        self.assertFalse((self.root/'state.json').exists())

    def test_project_local_picker_rejects_external_files_and_never_copies(self):
        win=self.open();form=win.authoring_timeline;form.audio.add()
        local=self.root/'voice.wav';local.write_bytes(b'not-yet-probed');outside=self.parent/'outside.wav';outside.write_bytes(b'outside')
        form.audio.editor.choose(local);self.assertEqual(form.audio.editor.read()['path'],'voice.wav')
        with mock.patch.object(self.manager,'error') as error:form.audio.editor.choose(outside);error.assert_called_once()
        self.assertEqual(form.audio.editor.read()['path'],'voice.wav');self.assertEqual(outside.read_bytes(),b'outside');win.destroy()

    def test_new_clip_and_segment_can_be_removed_without_deleting_source_or_tasks(self):
        win=self.open();form=win.authoring_timeline;original=win.authoring_read()
        form.clips.add();self.field(form.clips.editor.form,'job_id','job-001');form.clips.editor.match()
        form.segments.add();self.field(form.segments.editor,'clip_id',form.clips.read()[-1]['id'])
        self.field(form.segments.editor,'shot_id','shot-001');self.field(form.segments.editor,'cut_reason','New insert')
        form.draw();self.assertTrue(form.graph_data['ok'])
        form.segments.delete();form.clips.delete();self.assertEqual(win.authoring_read(),original);win.destroy()

    def test_refresh_link_choices_includes_unsaved_ids_and_keeps_current_fields(self):
        win=self.open();form=win.authoring_timeline;form.clips.add()
        self.field(form.clips.editor.form,'job_id','job-001');self.field(form.clips.editor.form,'id','new-clip')
        form.segments.add();self.field(form.segments.editor,'id','new-segment');self.field(form.segments.editor,'cut_reason','Retain this reason')
        form.refresh_links()
        self.assertEqual(form.segments.editor.read()['cut_reason'],'Retain this reason')
        choices=next(kind for path,var,kind in form.segments.editor.fields if path=='clip_id')
        self.assertIn('new-clip',choices)
        form.subtitles.add();choices=next(kind for path,var,kind in form.subtitles.editor.form.fields if path=='segment_id')
        self.assertIn('new-segment',choices);win.destroy()

    def test_invalid_retained_interval_shows_error_in_graph_and_preview_and_saves_draft(self):
        win=self.open();form=win.authoring_timeline;self.field(form.segments.editor,'source_out','0')
        form.draw();self.assertFalse(form.graph_data['ok'])
        self.button(win,'预览修改影响').invoke();self.pump(win);self.button(win,'保存当前创作层').invoke();self.pump(win)
        self.assertEqual(load_project(self.root)['timeline']['segments'][0]['source_out'],0)

    def test_project_panel_exposes_timeline_only_for_video_profiles(self):
        from videocreate.manager_projects import open_panel
        for profile in ('mixed-video','edit-only','image-only','gif-only','gif-local'):
            root=self.parent/profile;save_bundle(root,create(profile,title='Panel',topic='A boat'))
            panel=open_panel(self.manager,root);panel.withdraw()
            buttons=[w.cget('text') for w in self.widgets(panel) if w.winfo_class()=='TButton']
            self.assertEqual('剪辑时间线与声音' in buttons,profile in {'mixed-video','edit-only'});panel.destroy()


class TimelineRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.source=Path(cls.temp.name)/'source.mp4'
        subprocess.run([shutil.which('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i',
            'testsrc2=size=128x72:rate=24:duration=2','-f','lavfi','-i','sine=frequency=440:duration=2',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(cls.source)],capture_output=True,check=True)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_saved_caption_audio_edit_rerenders_without_recreate_and_invalidates_only_final_review(self):
        fixture=mixed_tests.MixedVideoTests();fixture.source=self.source;fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.local();fixture.generated();fixture.run_jobs();fixture.render();fixture.review_fixture()
        original=(fixture.root/'state.json').read_bytes();current=authoring.describe(fixture.root,'timeline');value=current['value']
        value['subtitles']=[{'text':'Observed fixture caption','segment_id':value['segments'][0]['id'],
            'source_start':.3,'source_end':.7}]
        value['audio_tracks']=[{'id':'voice','kind':'dialogue','clip_id':value['clips'][0]['id'],
            'source_in':.2,'source_out':.5,'timeline_start':1.2,'gain_db':-9}]
        report=authoring.preview(fixture.root,'timeline',value,source_token=current['source_token'])
        with mock.patch('urllib.request.urlopen',side_effect=AssertionError('No live requests')):
            authoring.save(fixture.root,'timeline',value,source_token=current['source_token'],preview_token=report['preview_token'])
            self.assertEqual((fixture.root/'state.json').read_bytes(),original)
            stale=production.status(fixture.root);self.assertNotEqual(stale['review']['status'],'accepted_delivery')
            fixture.render();current_status=production.status(fixture.root)
            self.assertEqual(current_status['local_sources'][0]['content_status'],'reviewed')
            self.assertEqual(current_status['review']['assets']['gen-0']['performance_motion'],'pass')
            self.assertEqual(current_status['review']['assets']['final']['editorial'],'unverified')
            self.assertTrue(fixture.run_jobs()['ok'])
        self.assertEqual(len(fixture.creates),1)
        self.assertIn('Observed fixture caption',(fixture.root/'deliverables/preview.srt').read_text(encoding='utf-8'))
        self.assertEqual((fixture.root/'state.json').read_bytes(),original)


if __name__=='__main__':unittest.main()
