"""Observable local finishing, bounded authoring and unchanged generation state."""
import copy
import io
import json
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'tests')]
from videocreate import authoring, production
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.planning.project import load_project, validate_plan
from videocreate.runtime.state import read_state
from videocreate.timeline import finishing
from videocreate.timeline.model import mapping, validate_timeline
from videocreate.timeline.render import render
from videocreate.timeline_authoring import inspect
import test_timeline_transitions as transitions
import test_screenplay_authoring as forms


class FinishingValidationTests(unittest.TestCase):
    def value(self):
        value=transitions.timeline();value['format_version']=3
        return value

    def test_versioned_contract_keeps_old_timelines_and_rejects_unversioned_controls(self):
        self.assertFalse(validate_timeline(transitions.timeline()))
        for version in (None,1,2):
            value=self.value();value['filters']=[]
            if version is None:value.pop('format_version')
            else:value['format_version']=version
            with self.subTest(version=version):self.assertTrue(validate_timeline(value))
        for key,value in [('filters',[]),('loudness',{'target_lufs':-16}),
                           ('subtitle_render',{'burn':False,'style':'clean'})]:
            timeline=self.value();timeline[key]=value
            self.assertFalse(validate_timeline(timeline))

    def test_unknown_filters_free_form_code_duplicates_and_bad_types_fail_before_rendering(self):
        for value in ('warm',{},None,[{}],['none'],['movie=secret.mp4'],['warm','warm']):
            for scope in ('global','segment'):
                timeline=self.value();target=timeline if scope=='global' else timeline['segments'][0]
                target['filters']=value
                with self.subTest(value=value,scope=scope):self.assertFalse(inspect(timeline)['ok'])

    def test_loudness_and_caption_fields_are_strict_and_finite(self):
        for value in (None,{},True,{'target_lufs':True},{'target_lufs':float('nan')},
                      {'target_lufs':-25},{'target_lufs':-9},{'target_lufs':-16,'af':'volume=10'}):
            timeline=self.value();timeline['loudness']=value
            with self.subTest(value=value):self.assertTrue(validate_timeline(timeline))
        for value in (None,{},True,{'burn':1,'style':'clean'}, {'burn':True,'style':[]},
                      {'burn':True,'style':'file.ass'},{'burn':True,'style':'clean','font':'secret.ttf'}):
            timeline=self.value();timeline['subtitle_render']=value
            with self.subTest(value=value):self.assertTrue(validate_timeline(timeline))

    def test_overlap_is_detected_after_source_mapping_and_unburned_overlaps_remain_authorable(self):
        value=self.value();value['subtitle_render']={'burn':True,'style':'clean'}
        value['subtitles']=[{'text':'one','segment_id':'s1','source_start':.5,'source_end':.9},
                           {'text':'two','segment_id':'s2','source_start':0,'source_end':.3}]
        self.assertTrue(any('overlap' in e for e in validate_timeline(value)))
        value['subtitle_render']['burn']=False
        self.assertFalse(validate_timeline(value));self.assertEqual(mapping(value)['subtitles'][1]['start'],.5)

    def test_burned_blank_or_nul_cues_fail_without_turning_literal_text_into_code(self):
        for text in ('  ','\x00'):
            value=self.value();value['subtitle_render']={'burn':True,'style':'clean'}
            value['subtitles']=[{'text':text,'start':0,'end':.5}]
            self.assertFalse(inspect(value)['ok'])
        value['subtitles'][0]['text']='中文 [标签] C:\\foo $(echo no); <b>literal</b>'
        self.assertTrue(inspect(value)['ok'])

    def test_animation_pilot_preserves_controls_and_selected_segment_filters(self):
        from videocreate.animation.previews import prepare
        value=self.value();value.update(filters=['cool'],loudness={'target_lufs':-18},
                                         subtitle_render={'burn':True,'style':'news'})
        for i,segment in enumerate(value['segments']):segment['shot_id']='shot'+str(i+1)
        value['segments'][1]['filters']=['sharpen']
        value['subtitles']=[{'text':'source','segment_id':'s2','source_start':.25,'source_end':.5}]
        bundle={'timeline':value,'animation':{'adaptation':{'pilot_shot_ids':['shot1','shot2']}},
                'director':{'shots':[{'id':'shot'+str(i+1)} for i in range(3)]}}
        before=copy.deepcopy(bundle);result=prepare(bundle)
        self.assertEqual(bundle,before);self.assertEqual(result['filters'],['cool'])
        self.assertEqual(result['segments'][1]['filters'],['sharpen'])
        self.assertEqual(result['loudness'],{'target_lufs':-18})
        self.assertEqual(mapping(result)['subtitles'][0]['start'],.75)


class FinishingRenderTests(unittest.TestCase):
    setUpClass=classmethod(transitions.TransitionRenderTests.setUpClass.__func__)
    tearDownClass=classmethod(transitions.TransitionRenderTests.tearDownClass.__func__)
    setUp=transitions.TransitionRenderTests.setUp
    prepare=transitions.TransitionRenderTests.prepare
    pixel=transitions.TransitionRenderTests.pixel

    def save(self,bundle):
        bundle['timeline']['format_version']=3
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        self.assertTrue(validate_plan(bundle,self.root)['ok'])

    def test_global_and_segment_filters_change_real_picture_and_keep_transitions_and_sources(self):
        bundle=self.prepare();value=bundle['timeline'];value['filters']=['warm']
        value['segments'][1]['filters']=['monochrome'];self.save(bundle)
        before={p:p.read_bytes() for p in self.sources}
        result=render(self.root,bundle,read_state(self.root));path=Path(result['path'])
        pixel=self.pixel(path,1.25);self.assertLess(max(pixel)-min(pixel),5)
        first=self.pixel(path,.25);self.assertGreater(first[0],first[2]+150)
        self.assertEqual(int(result['media']['frame_count']),36)
        self.assertEqual(result['finishing']['global_filters'],['warm'])
        self.assertEqual(result['finishing']['segment_filters'],{value['segments'][1]['id']:['monochrome']})
        self.assertEqual(before,{p:p.read_bytes() for p in self.sources})
        self.assertEqual(read_state(self.root)['jobs'],{});self.assertEqual(read_state(self.root)['ledger'],[])
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')

    def test_all_supported_presets_are_consumed_by_the_real_renderer(self):
        bundle=self.prepare();value=bundle['timeline'];value.pop('transitions')
        for preset in finishing.FILTERS:
            value['filters']=[preset];self.save(bundle)
            with self.subTest(preset=preset):
                result=render(self.root,bundle,read_state(self.root))
                self.assertEqual(result['technical_decode'],'pass')
                self.assertEqual(int(result['media']['frame_count']),48)

    def frame(self,path,seconds):
        return subprocess.run([shutil.which('ffmpeg'),'-v','error','-ss',str(seconds),'-i',str(path),
            '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout

    def test_caption_pixels_use_mapped_source_times_and_literal_unicode_text_while_retaining_srt(self):
        bundle=self.prepare();value=bundle['timeline'];value['width']=320;value['height']=180
        value['subtitles']=[{'text':'圣旨：重启！[literal] $(no)','segment_id':value['segments'][1]['id'],
                             'source_start':.25,'source_end':.5}]
        value['subtitle_render']={'burn':False,'style':'clean'};self.save(bundle)
        baseline=render(self.root,bundle,read_state(self.root),output_name='plain.mp4')
        value['subtitle_render']['burn']=True;self.save(bundle)
        result=render(self.root,bundle,read_state(self.root));path=Path(result['path'])
        raw=self.frame(Path(baseline['path']),.875);burned=self.frame(path,.875)
        # A large bright text mask only exists during the mapped .75--1 second cue.
        def whites(data):return sum(min(data[i:i+3])>190 for i in range(0,len(data),3))
        self.assertGreater(whites(burned),whites(raw)+80)
        self.assertLess(whites(self.frame(path,.5)),50);self.assertLess(whites(self.frame(path,1.25)),50)
        text=path.with_suffix('.srt').read_text(encoding='utf-8')
        self.assertIn('00:00:00,750 --> 00:00:01,000',text);self.assertIn('圣旨：重启！[literal] $(no)',text)
        self.assertEqual(result['finishing']['subtitle_render']['burned_cues'],1)
        self.assertEqual(result['content'],'unverified')

    def test_all_caption_styles_render_and_boundary_end_is_exclusive(self):
        bundle=self.prepare();value=bundle['timeline'];value.update(width=256,height=144)
        value['subtitles']=[{'text':'中文\nCaption','start':.25,'end':.5}]
        for style in finishing.STYLES:
            value['subtitle_render']={'burn':True,'style':style};self.save(bundle)
            result=render(self.root,bundle,read_state(self.root));path=Path(result['path'])
            frame=self.frame(path,.375);after=self.frame(path,.5)
            count=lambda b:sum(b[i]>150 and b[i+1]>150 for i in range(0,len(b),3))
            with self.subTest(style=style):self.assertGreater(count(frame),count(after)+60)

    def test_complete_mix_is_normalized_with_actual_encoded_measurements(self):
        bundle=self.prepare();value=bundle['timeline'];value.pop('transitions')
        shutil.copyfile(self.sources[2],self.root/'voice.mp4')
        value['audio_tracks']=[{'id':'voice','kind':'dialogue','path':'voice.mp4','source_in':0,
            'source_out':2,'timeline_start':0,'gain_db':-12}]
        for segment in value['segments']:segment['source_audio']='mute'
        value['loudness']={'target_lufs':-16};self.save(bundle)
        result=render(self.root,bundle,read_state(self.root));info=result['finishing']['loudness']
        self.assertEqual(info['status'],'processed');self.assertTrue(info['within_1_lu'])
        self.assertGreater(info['after']['integrated_lufs']-info['before']['integrated_lufs'],10)
        self.assertEqual(info['after'],finishing.measure(shutil.which('ffmpeg'),Path(result['path']),-16))
        self.assertLessEqual(info['after']['true_peak_dbtp'],0)
        self.assertEqual(result['audio_content'],'unverified');self.assertEqual(result['auxiliary_hashes'].keys(),{'voice.mp4'})

    def test_silent_audio_is_not_fabricated_and_reports_null_measurements(self):
        bundle=self.prepare();value=bundle['timeline']
        for segment in value['segments']:segment['source_audio']='mute'
        value['loudness']={'target_lufs':-18};self.save(bundle)
        result=render(self.root,bundle,read_state(self.root));info=result['finishing']['loudness']
        self.assertEqual(info['status'],'skipped_silence');self.assertTrue(info['after']['silent'])
        self.assertIsNone(info['after']['integrated_lufs']);json.dumps(result,allow_nan=False)

    def test_combined_transitions_burn_and_loudness_trim_encoder_tail_to_picture_duration(self):
        bundle=self.prepare();value=bundle['timeline'];value.update(width=320,height=180,
            filters=['warm'],loudness={'target_lufs':-16},subtitle_render={'burn':True,'style':'clean'})
        for segment in value['segments']:segment['source_out']=2
        value['segments'][1]['filters']=['monochrome']
        value['subtitles']=[{'text':'组合字幕','segment_id':value['segments'][1]['id'],
                             'source_start':.5,'source_end':1}]
        self.save(bundle);result=render(self.root,bundle,read_state(self.root))
        self.assertEqual(int(result['media']['frame_count']),84)
        self.assertAlmostEqual(result['media']['duration'],3.5,delta=.002)
        self.assertEqual(result['finishing']['loudness']['status'],'processed')
        self.assertTrue(result['finishing']['loudness']['within_1_lu'])

    def test_normalization_failure_keeps_previous_deliverable_and_manifest(self):
        bundle=self.prepare();old=render(self.root,bundle,read_state(self.root));path=Path(old['path'])
        before={p:p.read_bytes() for p in (path,path.with_suffix('.manifest.json'),path.with_suffix('.srt'))}
        bundle['timeline']['loudness']={'target_lufs':-16};self.save(bundle)
        with patch('videocreate.timeline.finishing.measure',side_effect=ConfigError('Measurement unavailable')):
            with self.assertRaisesRegex(ConfigError,'Measurement unavailable'):render(self.root,bundle,read_state(self.root))
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_mapped_final_evidence_cannot_approve_filtered_picture_or_normalized_source_audio(self):
        from videocreate.review import receipts
        for mode in ('global','segment','caption','loudness','none'):
            bundle=self.prepare();value=bundle['timeline'];value.pop('transitions')
            if mode=='global':value['filters']=['cool']
            if mode=='segment':value['segments'][0]['filters']=['cool']
            if mode=='caption':value.update(subtitle_render={'burn':True,'style':'clean'},subtitles=[{'text':'caption','start':.1,'end':.3}])
            if mode=='loudness':value['loudness']={'target_lufs':-16}
            self.save(bundle);result=render(self.root,bundle,read_state(self.root))
            expected=receipts.contracts(self.root,bundle)['local0']
            evidence={'path':'deliverables/preview.mp4','sha256':result['sha256'],'kind':'video','start':.1,'end':.3,
                'mapped_view':{'manifest':'deliverables/preview.manifest.json','timeline':'timeline.json','start':.1,'end':.3}}
            with self.subTest(mode=mode):
                self.assertEqual(receipts._mapped_view(self.root,expected,evidence,'performance_motion'),mode in {'none','loudness'})
                self.assertEqual(receipts._mapped_view(self.root,expected,evidence,'audio'),mode!='loudness')
            # Each subcase uses a new project so imports do not accumulate duplicate IDs.
            shutil.rmtree(self.root)
            from videocreate.planning.project import save_bundle
            from videocreate.planning.profiles import create
            save_bundle(self.root,create('edit-only'))

    def test_cli_render_requires_no_provider_configuration(self):
        from videocreate.commands import timeline_command
        bundle=self.prepare();bundle['timeline']['filters']=['monochrome'];self.save(bundle)
        with patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config')):
            with redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(timeline_command(['render',str(self.root)]),0)
        self.assertEqual(json.loads(stream.getvalue())['finishing']['global_filters'],['monochrome'])

    def test_finishing_edit_preserves_original_source_reviews_and_tasks_and_invalidates_final(self):
        import test_mixed_video_production as mixed
        fixture=mixed.MixedVideoTests();fixture.source=self.sources[0];fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.local();fixture.generated();fixture.run_jobs();fixture.render();fixture.review_fixture()
        before=(fixture.root/'state.json').read_bytes()
        current=authoring.describe(fixture.root,'timeline');value=current['value']
        value.update(format_version=3,filters=['warm'],loudness={'target_lufs':-18},
                     subtitle_render={'burn':True,'style':'clean'},subtitles=[{'text':'Observed caption','start':.25,'end':.75}])
        preview=authoring.preview(fixture.root,'timeline',value,source_token=current['source_token'])
        authoring.save(fixture.root,'timeline',value,source_token=current['source_token'],preview_token=preview['preview_token'])
        fixture.render();status=production.status(fixture.root)
        self.assertEqual(status['local_sources'][0]['content_status'],'reviewed')
        self.assertEqual(status['review']['assets']['gen-0']['performance_motion'],'pass')
        self.assertEqual(status['review']['assets']['final']['editorial'],'unverified')
        self.assertEqual((fixture.root/'state.json').read_bytes(),before);self.assertEqual(len(fixture.creates),1)

    def test_text_preview_reports_planned_effects_without_claiming_material_finishing(self):
        from videocreate.planning.preview import preview
        bundle=self.prepare();bundle['timeline']['filters']=['monochrome'];self.save(bundle)
        result=preview(self.root,bundle)
        self.assertEqual(result['finishing_plan'],{'filters':['monochrome']})
        self.assertFalse(result['finishing_effects_rendered']);self.assertFalse(result['content_verified'])
        reading=production.script_export(self.root)
        self.assertIn('monochrome',Path(reading['reading_copy']).read_text(encoding='utf-8'))


class FinishingFormTests(unittest.TestCase):
    setUp=forms.ScreenplayFormsTests.setUp
    field=forms.ScreenplayFormsTests.field
    button=forms.ScreenplayFormsTests.button
    widgets=forms.ScreenplayFormsTests.widgets
    pump=forms.ScreenplayFormsTests.pump

    def open(self):
        from videocreate.manager_authoring import open_editor
        win=open_editor(self.manager,self.root,'timeline');win.withdraw()
        return win,win.authoring_timeline

    def test_actual_controls_save_and_reopen_without_changing_generation_or_config(self):
        before=load_project(self.root);win,form=self.open()
        self.assertEqual(win.authoring_read(),before['timeline'])
        self.field(form.finishing,'filters','warm,sharpen')
        self.field(form.finishing,'loudness.target_lufs','-18')
        self.field(form.finishing,'subtitle_render.burn','是');self.field(form.finishing,'subtitle_render.style','news')
        self.field(form.segments.editor,'filters','monochrome');form.draw()
        self.assertTrue(form.graph_data['ok']);self.assertEqual(win.authoring_read()['format_version'],3)
        self.button(win,'预览修改影响').invoke();self.pump(win)
        self.button(win,'保存当前创作层').invoke();self.pump(win)
        after=load_project(self.root);win.destroy()
        self.assertEqual(after['generation-plan'],before['generation-plan'])
        self.assertEqual(after['director'],before['director']);self.assertEqual(self.path.read_bytes(),self.before)
        win,form=self.open();self.assertEqual(win.authoring_read(),after['timeline'])
        self.assertEqual(after['timeline']['loudness'],{'target_lufs':-18})
        self.assertEqual(after['timeline']['segments'][0]['filters'],['monochrome']);win.destroy()

    def test_deleting_controls_disables_processing_and_preserves_explicit_empty_lists(self):
        value=load_project(self.root)['timeline'];value.update(format_version=3,filters=[],
            loudness={'target_lufs':-16},subtitle_render={'burn':False,'style':'clean'})
        value['segments'][0]['filters']=[];atomic_json(self.root/'timeline.json',value)
        win,form=self.open();self.assertEqual(win.authoring_read(),value)
        for key in ('loudness.target_lufs','subtitle_render.burn','subtitle_render.style'):self.field(form.finishing,key,'')
        result=win.authoring_read();self.assertNotIn('loudness',result);self.assertNotIn('subtitle_render',result)
        self.assertEqual(result['filters'],[]);self.assertEqual(result['segments'][0]['filters'],[]);win.destroy()


if __name__=='__main__':unittest.main()
