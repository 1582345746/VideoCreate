"""Real picture/audio overlap, mappings, source-review boundaries and native forms."""
import copy
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'tests')]
from videocreate import authoring, production
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.local_sources import digest, import_clip, import_image
from videocreate.planning.project import load_project, save_bundle, validate_plan
from videocreate.planning.profiles import create
from videocreate.production_metrics import report
from videocreate.review import receipts
from videocreate.runtime.state import read_state
from videocreate.timeline.model import mapping, validate_timeline
from videocreate.timeline.render import render
from videocreate.timeline_authoring import inspect
import test_screenplay_authoring as forms


def transition(left='s1',right='s2',seconds=.5,kind='crossfade',audio='crossfade',identity='t1'):
    return {'id':identity,'left_segment_id':left,'right_segment_id':right,
            'kind':kind,'duration':seconds,'audio':audio}


def timeline(count=3):
    return {'format_version':2,'fps':'24/1','clips':[{'id':'c','job_id':'j'}],
        'segments':[{'id':'s'+str(i+1),'shot_id':'shot','clip_id':'c','source_in':0,
                     'source_out':1,'rate':1,'source_audio':'preserve','cut_reason':'A deliberate cut'} for i in range(count)],
        'transitions':[transition()], 'audio_tracks':[], 'subtitles':[]}


class TransitionMappingTests(unittest.TestCase):
    def test_animation_pilot_keeps_only_retained_boundaries_and_does_not_duplicate_overlap_events(self):
        from videocreate.animation.previews import prepare
        value=timeline();value['transitions'].append(transition('s2','s3',.25,identity='t2'))
        for i,segment in enumerate(value['segments']):segment['shot_id']='shot'+str(i+1)
        value['audio_tracks']=[{'id':'voice','kind':'dialogue','path':'voice.wav','source_in':0,'source_out':.2,'timeline_start':.6}]
        value['subtitles']=[{'text':'absolute','start':.6,'end':.8},
            {'text':'source','segment_id':'s2','source_start':.1,'source_end':.3}]
        bundle={'timeline':value,'animation':{'adaptation':{'pilot_shot_ids':['shot1','shot2']}},
                'director':{'shots':[{'id':'shot'+str(i+1)} for i in range(3)]}}
        before=copy.deepcopy(bundle);result=prepare(bundle)
        self.assertEqual(bundle,before);self.assertEqual(len(result['transitions']),1)
        self.assertEqual(len(result['audio_tracks']),1);self.assertEqual(len(result['subtitles']),2)
        self.assertEqual(result['audio_tracks'][0]['timeline_start'],.6)
        self.assertEqual(result['subtitles'][1]['segment_id'],'s2')
        self.assertEqual(mapping(result)['duration'],1.5)
        with self.assertRaisesRegex(ConfigError,'changed transition overlap'):
            prepare(bundle,{'reason':'Trim fixture','segments':{'s1':{'source_out':.75}}})

    def test_overlap_maps_source_captions_and_leaves_absolute_events_fixed(self):
        value=timeline();value['segments'][1].update(source_out=2,rate=2,source_audio='mute')
        value['subtitles']=[{'text':'Source','segment_id':'s2','source_start':.5,'source_end':1},
                            {'text':'Absolute','start':.1,'end':.3}]
        value['audio_tracks']=[{'id':'voice','kind':'dialogue','clip_id':'c','source_in':0,'source_out':.2,'timeline_start':1.1}]
        result=mapping(value)
        self.assertEqual(result['duration'],2.5)
        self.assertEqual([s['timeline_start'] for s in result['segments']],[0,.5,1.5])
        self.assertEqual(result['subtitles'][0]['start'],.75);self.assertEqual(result['subtitles'][0]['end'],1)
        self.assertEqual(result['subtitles'][1]['start'],.1);self.assertEqual(result['audio_tracks'][0]['timeline_start'],1.1)
        self.assertEqual(result['transitions'][0]['timeline_start'],.5)
        self.assertEqual(result['transition_overlap_seconds'],.5)

    def test_legacy_hard_cut_mapping_keeps_its_original_shape_and_duration(self):
        value=timeline();value.pop('format_version');value.pop('transitions')
        result=mapping(value);self.assertEqual(result['duration'],3)
        self.assertNotIn('transitions',result);self.assertNotIn('transition_overlap_seconds',result)

    def test_reorder_rename_duplicate_and_nonadjacent_boundaries_are_rejected(self):
        for mutation in ('reorder','rename','duplicate','nonadjacent'):
            value=timeline()
            if mutation=='reorder':value['segments'].reverse()
            elif mutation=='rename':value['segments'][1]['id']='renamed'
            elif mutation=='duplicate':value['transitions'].append(transition(identity='t2'))
            else:value['transitions'][0]['right_segment_id']='s3'
            with self.subTest(mutation=mutation):self.assertFalse(inspect(value)['ok'])

    def test_unknown_versions_fields_types_and_nonfinite_values_fail_validation(self):
        for key,item in [('duration',0),('duration',True),('duration',float('nan')),('duration',float('inf')),
                         ('kind','unsupported'),('kind',[]),('audio',{}),('extra','ignored')]:
            value=timeline();value['transitions'][0][key]=item
            with self.subTest(key=key,item=str(item)):self.assertTrue(validate_timeline(value))
        for version in (1,5,True,'2'):
            value=timeline();value['format_version']=version
            with self.subTest(version=version):self.assertTrue(validate_timeline(value))

    def test_subframe_overlap_short_segments_and_three_way_overlap_are_rejected(self):
        for duration in (.01,.51,1,2):
            value=timeline();value['transitions'][0]['duration']=duration
            with self.subTest(duration=duration):self.assertTrue(validate_timeline(value))
        value=timeline();value['segments'][2]['source_out']=.99
        self.assertTrue(validate_timeline(value))
        value=timeline();value['transitions']=[transition(seconds=.75),transition('s2','s3',.75,identity='t2')]
        self.assertTrue(any('three-way' in e for e in validate_timeline(value)))
        value['transitions'][0]['duration']=.5;value['transitions'][1]['duration']=.5
        self.assertFalse(validate_timeline(value))

    def test_audio_absolute_subtitles_and_overlays_are_checked_against_shortened_picture(self):
        for group,record in [('audio_tracks',{'id':'a','kind':'dialogue','clip_id':'c','source_in':0,'source_out':1,'timeline_start':1.75}),
                             ('subtitles',{'text':'past end','start':2.4,'end':2.75}),
                             ('overlays',{'id':'o','text':'past end','start':2.4,'end':2.75})]:
            value=timeline();value[group]=[record]
            with self.subTest(group=group):self.assertTrue(validate_timeline(value))

    def test_rational_fps_uses_exact_output_frame_intervals(self):
        value=timeline();value['fps']='24000/1001'
        for segment in value['segments']:segment['source_out']=1.001
        value['transitions'][0]['duration']=.5005
        self.assertFalse(validate_timeline(value));self.assertAlmostEqual(mapping(value)['duration'],2.5025)


class TransitionRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory();folder=Path(cls.shared.name)
        cls.sources=[]
        for color,frequency in [('red',440),('blue',880),('green',1320)]:
            path=folder/(color+'.mp4')
            subprocess.run([shutil.which('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i',
                'color=c='+color+':s=128x72:r=24:d=2','-f','lavfi','-i','sine=frequency='+str(frequency)+':duration=2',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)],capture_output=True,check=True)
            cls.sources.append(path)

    @classmethod
    def tearDownClass(cls):cls.shared.cleanup()

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'转场项目';save_bundle(self.root,create('edit-only'))
        guard=patch('urllib.request.urlopen',side_effect=AssertionError('No network'));guard.start();self.addCleanup(guard.stop)

    def prepare(self,count=2,audio='crossfade',kind='crossfade'):
        for index in range(count):import_clip(self.root,self.sources[index%3],source_id='local'+str(index),start=0,end=1)
        bundle=load_project(self.root);value=bundle['timeline'];value.update(width=128,height=72,format_version=2)
        for segment in value['segments']:segment['source_audio']='preserve'
        ids=[s['id'] for s in value['segments']]
        value['transitions']=[transition(ids[0],ids[1],audio=audio,kind=kind)]
        atomic_json(self.root/'timeline.json',value)
        return bundle

    def pixel(self,path,seconds):
        data=subprocess.run([shutil.which('ffmpeg'),'-v','error','-ss',str(seconds),'-i',str(path),
            '-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
        return tuple(data[:3])

    def amplitude(self,path,start,frequency):
        data=subprocess.run([shutil.which('ffmpeg'),'-v','error','-ss',str(start),'-i',str(path),
            '-t','0.04','-vn','-f','s16le','-ac','1','-ar','48000','-'],capture_output=True,check=True).stdout
        samples=struct.unpack('<'+'h'*(len(data)//2),data)
        real=sum(v*math.cos(2*math.pi*frequency*i/48000) for i,v in enumerate(samples))
        imaginary=sum(v*math.sin(2*math.pi*frequency*i/48000) for i,v in enumerate(samples))
        return math.hypot(real,imaginary)/len(samples)

    def test_audio_deliveries_from_same_edit_have_only_selected_frequencies(self):
        bundle = self.prepare()
        value = bundle['timeline']
        value['audio_tracks'] = [
            {'id':role, 'kind':role, 'clip_id':clip['id'], 'source_in':0, 'source_out':1, 'timeline_start':0}
            for role, clip in zip(('dialogue', 'music'), value['clips'])]
        atomic_json(self.root/'timeline.json', value)
        bundle['brief']['audio_policy'] = 'silent'
        original_state = read_state(self.root)
        silent = render(self.root, bundle, original_state, output_name='silent.mp4')
        self.assertFalse(silent['media']['has_audio'])
        self.assertEqual(silent['audio_delivery']['mode'], 'silent')
        for mode, audible in [('dialogue',(True,False)), ('music',(False,True)), ('dialogue-music',(True,True))]:
            result = render(self.root, bundle, original_state, output_name=mode+'.mp4', audio_output=mode)
            self.assertEqual(result['media']['frame_count'], silent['media']['frame_count'])
            self.assertEqual(receipts.contracts(self.root,bundle,output_name=mode+'.mp4')['final']['audio_delivery'],
                             result['audio_delivery'])
            path = Path(result['path'])
            self.assertEqual(tuple(self.amplitude(path,.25,hz)>250 for hz in (440,880)), audible)
        bundle['brief']['audio_policy'] = 'ambience'
        with self.assertRaisesRegex(ConfigError, 'audio delivery changed'):
            receipts.contracts(self.root,bundle,output_name='silent.mp4')
        self.assertEqual(read_state(self.root), original_state)

    def test_mapped_review_uses_final_bytes_and_rechecks_event_evidence_on_import(self):
        from videocreate.review.comparison import export_comparison, record_observations
        bundle = self.prepare()
        local = bundle['generation-plan']['local_sources'][0]
        card_path = self.root/'character.png'
        subprocess.run(['ffmpeg','-v','error','-i',str(self.sources[0]),'-frames:v','1',str(card_path)],
                       check=True,capture_output=True)
        bundle['director']['assets'].append({'id':'character','kind':'character','description':'Selected character',
                                             'references':[card_path.name]})
        shot = next(s for s in bundle['director']['shots'] if s['id'] in local['shot_ids'])
        shot['asset_ids'] = ['character']
        atomic_json(self.root/'director.json',bundle['director'])
        source = {k:local[k] for k in ('path','sha256')}
        spec = {'schema_version':1,'source':source,'audio':source,'target_job':local['id'],
                'tolerance_seconds':1/24,'events':[
                    {'id':'opening','source':[0,.5],'audio':[0,.5],'target':[0,.5],'reason':'Opening half second'}]}
        output = 'silent.mp4'
        render(self.root,bundle,read_state(self.root),output_name=output,audio_output='silent')
        page = export_comparison(self.root,bundle,spec,mapped=True,output_name=output)
        self.assertFalse(page['candidate_has_audio_stream'])
        compared = json.loads((Path(page['page']).parent/'comparison.json').read_text(encoding='utf-8'))
        self.assertEqual(compared['visual_references'][0]['sha256'],digest(card_path))
        receipt = {'schema_version':1,'comparison_hash':page['comparison_hash'],'reviewer':'fixture',
                   'observations':{'event-1-use-1':{'status':'unverified','note':''}}}
        saved = record_observations(self.root,bundle,spec,receipt,mapped=True,output_name=output)
        self.assertTrue(Path(saved['observations']).is_file())
        spec['events'][0]['target'] = [.25,.75]
        with self.assertRaisesRegex(ConfigError,'current comparison'):
            record_observations(self.root,bundle,spec,receipt,mapped=True,output_name=output)
        bundle['timeline']['segments'][0]['cut_reason'] += ' changed'
        with self.assertRaisesRegex(ConfigError,'manifest is stale'):
            export_comparison(self.root,bundle,spec,mapped=True,output_name=output)

    def test_real_crossfade_blends_picture_and_source_audio_with_shortened_duration(self):
        bundle=self.prepare();before=[digest(p) for p in self.sources]
        result=render(self.root,bundle,read_state(self.root));path=Path(result['path'])
        self.assertAlmostEqual(result['media']['duration'],1.5,delta=.045)
        self.assertEqual(int(result['media']['frame_count']),36)
        red=self.pixel(path,.25);middle=self.pixel(path,.75);blue=self.pixel(path,1.25)
        self.assertGreater(red[0],200);self.assertLess(red[2],40)
        self.assertGreater(middle[0],60);self.assertGreater(middle[2],60)
        self.assertLess(abs(middle[0]-middle[2]),50)
        self.assertGreater(blue[2],200);self.assertLess(blue[0],40)
        self.assertGreater(self.amplitude(path,.55,440),self.amplitude(path,.55,880)*2)
        self.assertGreater(self.amplitude(path,.9,880),self.amplitude(path,.9,440)*2)
        self.assertEqual(before,[digest(p) for p in self.sources]);self.assertEqual(read_state(self.root)['jobs'],{})
        metrics=report(self.root);self.assertEqual(metrics['seconds']['retained_available_playback'],2)
        self.assertEqual(metrics['seconds']['output_timeline_duration'],1.5);self.assertEqual(metrics['seconds']['transition_overlap'],.5)
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')

    def test_source_audio_cut_uses_overlap_midpoint_without_stretch_or_double_dialogue(self):
        bundle=self.prepare(audio='cut');result=render(self.root,bundle,read_state(self.root));path=Path(result['path'])
        self.assertGreater(self.amplitude(path,.63,440),self.amplitude(path,.63,880)*10)
        self.assertGreater(self.amplitude(path,.84,880),self.amplitude(path,.84,440)*10)
        self.assertAlmostEqual(result['media']['duration'],1.5,delta=.045)

    def test_mixed_hard_cuts_and_multiple_transition_kinds_decode_with_expected_frame_count(self):
        bundle=self.prepare(count=4,kind='fade-black');ids=[s['id'] for s in bundle['timeline']['segments']]
        bundle['timeline']['transitions'][0]['duration']=.25
        bundle['timeline']['transitions'].append(transition(ids[1],ids[2],.25,kind='wipe-left',identity='t2'))
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        result=render(self.root,bundle,read_state(self.root))
        self.assertEqual(int(result['media']['frame_count']),84);self.assertAlmostEqual(result['media']['duration'],3.5,delta=.045)
        self.assertEqual(result['technical_decode'],'pass')

    def test_mapped_source_review_rejects_transition_overlap_but_retains_unmodified_intervals(self):
        bundle=self.prepare();result=render(self.root,bundle,read_state(self.root))
        expected=receipts.contracts(self.root,bundle)['local0']
        def item(start,end):
            return {'path':'deliverables/preview.mp4','sha256':result['sha256'],'kind':'video','start':start,'end':end,
                'mapped_view':{'manifest':'deliverables/preview.manifest.json','timeline':'timeline.json','start':start,'end':end}}
        for layer in ('performance_motion','audio'):
            self.assertTrue(receipts._mapped_view(self.root,expected,item(.1,.3),layer))
            self.assertFalse(receipts._mapped_view(self.root,expected,item(.6,.8),layer))

    def test_invalid_transition_fails_before_tools_and_preserves_previous_output(self):
        bundle=self.prepare();render(self.root,bundle,read_state(self.root))
        before={p.name:p.read_bytes() for p in (self.root/'deliverables').glob('*') if p.is_file()}
        bundle['timeline']['transitions'][0]['duration']=2
        with patch('subprocess.run',side_effect=AssertionError('No tool for invalid edit')):
            with self.assertRaises((ConfigError,ValueError)):render(self.root,bundle,read_state(self.root))
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'deliverables').glob('*') if p.is_file()})

    def test_transition_assembly_failure_preserves_prior_video_manifest_and_sources(self):
        bundle=self.prepare();render(self.root,bundle,read_state(self.root))
        before={p.name:p.read_bytes() for p in (self.root/'deliverables').glob('*') if p.is_file()}
        with patch('videocreate.timeline.transitions.assemble',side_effect=ConfigError('Synthetic local failure')):
            with self.assertRaises(ConfigError):render(self.root,bundle,read_state(self.root))
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'deliverables').glob('*') if p.is_file()})

    def test_static_hold_and_retimed_video_transition_has_exact_frames_without_invented_source_seconds(self):
        from PIL import Image
        image=self.root/'red.png';Image.new('RGB',(128,72),'red').save(image)
        import_image(self.root,image,source_id='still',seconds=1)
        import_clip(self.root,self.sources[1],source_id='take',start=0,end=2)
        bundle=load_project(self.root);value=bundle['timeline'];value.update(width=128,height=72,format_version=2)
        value['segments'][1].update(rate=2,source_audio='retime')
        value['transitions']=[transition('seg-still','seg-take',.25)]
        atomic_json(self.root/'timeline.json',value)
        result=render(self.root,bundle,read_state(self.root))
        self.assertEqual(int(result['media']['frame_count']),42);self.assertAlmostEqual(result['media']['duration'],1.75,delta=.045)
        self.assertEqual(result['fps_report'][0]['source_frame_samples_per_timeline_second'],None)
        self.assertEqual(report(self.root)['seconds']['retained_unique_source'],2)

    def test_rational_frame_rate_and_a_hard_cut_before_transition_render_exact_total_frames(self):
        bundle=self.prepare(count=3);value=bundle['timeline'];value['fps']='24000/1001'
        for segment in value['segments']:segment['source_out']=1.001
        ids=[s['id'] for s in value['segments']]
        value['transitions']=[transition(ids[1],ids[2],.5005)]
        atomic_json(self.root/'timeline.json',value)
        result=render(self.root,bundle,read_state(self.root))
        self.assertEqual(int(result['media']['frame_count']),60)
        self.assertAlmostEqual(result['media']['duration'],2.5025,delta=.045)

    def test_rendered_source_subtitles_follow_overlap_and_independent_audio_keeps_absolute_time(self):
        bundle=self.prepare();value=bundle['timeline']
        value['subtitles']=[{'text':'Source mapped','segment_id':value['segments'][1]['id'],'source_start':.25,'source_end':.5},
                            {'text':'Absolute','start':.1,'end':.2}]
        import shutil
        shutil.copyfile(self.sources[2],self.root/'independent.mp4')
        value['audio_tracks']=[{'id':'voice','kind':'dialogue','path':'independent.mp4','source_in':0,'source_out':.2,'timeline_start':1.1}]
        atomic_json(self.root/'timeline.json',value);result=render(self.root,bundle,read_state(self.root))
        text=(self.root/'deliverables/preview.srt').read_text(encoding='utf-8')
        self.assertIn('00:00:00,750 --> 00:00:01,000',text);self.assertIn('00:00:00,100 --> 00:00:00,200',text)
        path=Path(result['path'])
        self.assertGreater(self.amplitude(path,1.15,1320),self.amplitude(path,.65,1320)*10)

    def test_transition_edit_preserves_generated_task_and_source_approval_but_invalidates_final(self):
        import test_mixed_video_production as mixed
        fixture=mixed.MixedVideoTests();fixture.source=self.sources[0];fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.local();fixture.generated();fixture.run_jobs();fixture.render();fixture.review_fixture()
        current=authoring.describe(fixture.root,'timeline');value=current['value']
        ids=[s['id'] for s in value['segments']];value.update(format_version=2,transitions=[transition(ids[0],ids[1],.25)])
        before=(fixture.root/'state.json').read_bytes();preview=authoring.preview(fixture.root,'timeline',value,source_token=current['source_token'])
        authoring.save(fixture.root,'timeline',value,source_token=current['source_token'],preview_token=preview['preview_token'])
        fixture.render();status=production.status(fixture.root)
        self.assertEqual(status['local_sources'][0]['content_status'],'reviewed')
        self.assertEqual(status['review']['assets']['gen-0']['performance_motion'],'pass')
        self.assertEqual(status['review']['assets']['final']['editorial'],'unverified')
        self.assertEqual((fixture.root/'state.json').read_bytes(),before);self.assertEqual(len(fixture.creates),1)

    def test_text_card_animatic_shares_overlap_duration_and_stays_unverified(self):
        from videocreate.planning.preview import preview
        bundle=self.prepare()
        result=preview(self.root,bundle,video=True)
        from videocreate.timeline.render import probe
        self.assertAlmostEqual(probe(Path(result['video']))['duration'],1.5,delta=.045)
        self.assertEqual(result['duration'],1.5);self.assertFalse(result['content_verified'])
        self.assertEqual(result['status'],'draft_preview')
        html=Path(result['html']).read_text(encoding='utf-8')
        self.assertIn('转场规划',html);self.assertIn('incoming_transition',html)

    def test_cli_mapping_and_render_use_new_format_without_provider_configuration(self):
        import io,json
        from contextlib import redirect_stdout
        from videocreate.commands import timeline_command
        bundle=self.prepare()
        with patch('videocreate.cli.read_config',side_effect=AssertionError('No provider configuration')):
            with redirect_stdout(io.StringIO()) as capture:
                self.assertEqual(timeline_command(['map',str(self.root)]),0)
            self.assertEqual(json.loads(capture.getvalue())['duration'],1.5)
            with redirect_stdout(io.StringIO()) as capture:
                self.assertEqual(timeline_command(['render',str(self.root)]),0)
            self.assertEqual(json.loads(capture.getvalue())['mapping']['duration'],1.5)


class TransitionFormTests(unittest.TestCase):
    setUp=forms.ScreenplayFormsTests.setUp
    field=forms.ScreenplayFormsTests.field
    button=forms.ScreenplayFormsTests.button
    widgets=forms.ScreenplayFormsTests.widgets
    pump=forms.ScreenplayFormsTests.pump

    def open(self):
        from videocreate.manager_authoring import open_editor
        window=open_editor(self.manager,self.root,'timeline');window.withdraw()
        return window,window.authoring_timeline

    def test_actual_form_adds_stable_boundary_previews_and_saves_only_edit_layer(self):
        before=load_project(self.root);window,form=self.open()
        self.assertEqual(window.authoring_read(),before['timeline'])
        form.transitions.add();form.draw();self.assertTrue(form.graph_data['ok'])
        self.assertEqual(window.authoring_read()['format_version'],2)
        self.assertAlmostEqual(form.graph_data['duration'],mapping(before['timeline'])['duration']-.5)
        self.button(window,'预览修改影响').invoke();self.pump(window)
        self.button(window,'保存当前创作层').invoke();self.pump(window)
        after=load_project(self.root)
        self.assertEqual(after['generation-plan'],before['generation-plan']);self.assertEqual(after['director'],before['director'])
        self.assertEqual(len(after['timeline']['transitions']),1);self.assertEqual(self.path.read_bytes(),self.before)

    def test_reorder_rejects_stale_boundary_and_graph_selects_original_transition_id(self):
        window,form=self.open();form.transitions.add();form.draw()
        identity=form.transitions.items[0]['id'];form.select_transition(identity)
        self.assertEqual(form.transitions.editor.read()['id'],identity)
        form.segments.refresh(0);form.segments.move(1);form.draw();self.assertFalse(form.graph_data['ok'])
        self.assertEqual(form.transitions.read()[0]['id'],identity);window.destroy()

    def test_noop_reopening_preserves_transition_settings_and_removal_restores_hard_cut(self):
        window,form=self.open();form.transitions.add();value=window.authoring_read();window.destroy()
        atomic_json(self.root/'timeline.json',value);window,form=self.open()
        self.assertEqual(window.authoring_read(),value)
        form.transitions.delete();form.draw();self.assertTrue(form.graph_data['ok'])
        self.assertNotIn('transitions',form.graph_data)
        self.assertEqual(window.authoring_read()['transitions'],[]);window.destroy()


if __name__=='__main__':unittest.main()
