"""Real legacy producer, immutable source project and independent local v3 output."""
import copy
import io
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts'),str(ROOT/'tests')]
from videocreate import legacy_edit_import as migrate, production
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.planning.project import load_project,validate_plan
from videocreate.runtime.state import read_state
from videocreate.timeline.model import mapping,validate_timeline
from videocreate.timeline.render import render
from editing_workflow import create_edit_plan
import test_screenplay_authoring as forms


class LegacyImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory();cls.assets=Path(cls.shared.name)
        for color,freq in [('red',440),('blue',880)]:
            subprocess.run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c='+color+':s=320x180:r=30:d=2',
                '-f','lavfi','-i','sine=frequency='+str(freq)+':duration=2',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(cls.assets/(color+'.mp4'))],capture_output=True,check=True)
        for name,freq,duration in [('music',1320,.5),('voice',1760,1)]:
            subprocess.run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i',
                f'sine=frequency={freq}:duration={duration}','-c:a','pcm_s16le',str(cls.assets/(name+'.wav'))],capture_output=True,check=True)

    @classmethod
    def tearDownClass(cls):cls.shared.cleanup()

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name);self.source=self.base/'旧剪辑';self.source.mkdir();self.destination=self.base/'新v3'
        for path in self.assets.iterdir():shutil.copyfile(path,self.source/path.name)
        atomic_json(self.source/'state.json',{'shots':{'legacy':{'task_id':'do-not-resubmit'}},'budget':{'requests':7}})
        atomic_json(self.source/'project.json',{'version':1,'private_history':'must remain'})
        self.plan=create_edit_plan(self.source,{'shots':[{'id':'皇帝','seconds':2},{'id':'大臣','seconds':2}],
            'defaults':{'video_size':'320x180'},'audio':{'mode':'silent'}},
            {'shots':{'皇帝':{'video':{'status':'completed','path':'red.mp4'}},
                      '大臣':{'video':{'status':'completed','path':'blue.mp4'}}}},normalize_lufs=None)
        guard=patch('urllib.request.urlopen',side_effect=AssertionError('No network'));guard.start();self.addCleanup(guard.stop)

    def save(self):atomic_json(self.source/'edit-plan.json',self.plan)
    def snapshot(self):return {p.relative_to(self.source).as_posix():migrate.digest(p) for p in self.source.rglob('*') if p.is_file()}
    def preview(self):self.save();return migrate.preview(self.source,self.destination)
    def execute(self):
        report=self.preview();return migrate.execute(self.source,self.destination,expected_token=report['preview_token'])

    def test_actual_legacy_plan_previews_read_only_and_copies_unreviewed_independent_project(self):
        before=self.snapshot();report=migrate.preview(self.source,self.destination)
        self.assertEqual(before,self.snapshot());self.assertFalse(self.destination.exists())
        self.assertEqual([r['legacy_input_id'] for r in report['input_mapping']],['皇帝','大臣'])
        self.assertEqual(report['duration'],4);result=migrate.execute(self.source,self.destination,expected_token=report['preview_token'])
        bundle=load_project(self.destination);self.assertTrue(validate_plan(bundle,self.destination)['ok'])
        self.assertEqual(before,self.snapshot());self.assertEqual(read_state(self.destination)['jobs'],{})
        self.assertEqual(read_state(self.destination)['ledger'],[]);self.assertFalse((self.destination/'state.json').exists())
        for source in bundle['generation-plan']['local_sources']:
            self.assertEqual(migrate.digest(self.destination/source['path']),source['sha256'])
        manifest=load_json(Path(result['manifest']));self.assertEqual(manifest['review_approvals_imported'],0)
        self.assertEqual(manifest['status'],'imported_unreviewed');self.assertEqual(result['paid_creates'],0)
        self.assertEqual(result['status'],'review_pending')

    def test_v1_defaults_keep_cuts_no_filters_and_natural_source_speed(self):
        self.plan['version']=1
        for item in self.plan['timeline']['inputs']:item.pop('speed');item.pop('filters')
        self.execute();timeline=load_project(self.destination)['timeline']
        self.assertEqual([s['rate'] for s in timeline['segments']],[1,1]);self.assertEqual(timeline['filters'],[])
        self.assertNotIn('transitions',timeline);self.assertNotIn('loudness',timeline)

    def test_trim_speed_global_segment_filters_and_each_transition_are_preserved(self):
        self.plan['timeline']['inputs'][0].update(edit_in=.2,edit_out=1.8,speed=2,filters=['sharpen'])
        self.plan['filters']=[{'preset':'warm','scope':'all'}]
        for kind,expected in [('cut',None),('dissolve','crossfade'),('fade-black','fade-black'),('wipe-left','wipe-left'),('slide-left','slide-left')]:
            self.plan['timeline']['transitions']=[{'after':'皇帝','type':kind,'duration':0 if kind=='cut' else .2}]
            report=self.preview();timeline=report['bundle']['timeline'];segment=timeline['segments'][0]
            with self.subTest(kind=kind):
                self.assertEqual((segment['source_in'],segment['source_out'],segment['rate']),(.2,1.8,2))
                self.assertEqual(segment['filters'],['sharpen']);self.assertEqual(timeline['filters'],['warm'])
                self.assertAlmostEqual(report['duration'],2.8 if kind=='cut' else 2.6)
                if expected:self.assertEqual(timeline['transitions'][0]['kind'],expected)
                else:self.assertNotIn('transitions',timeline)

    def test_audio_contract_preserves_legacy_source_gains_music_loop_voice_and_lufs(self):
        for music,voice,gain in [('', '',0),('music.wav','',20*math.log10(.75)),('', 'voice.wav',20*math.log10(.35)),('music.wav','voice.wav',20*math.log10(.35))]:
            self.plan['audio_mix'].update(music=music,voice=voice,normalize_lufs=-18)
            report=self.preview();value=report['bundle']['timeline']
            self.assertFalse(value['mix_limiter']);self.assertEqual(value['loudness'],{'target_lufs':-18})
            self.assertTrue(all(abs(s['source_gain_db']-gain)<1e-9 for s in value['segments']))
            for track in value['audio_tracks']:
                self.assertEqual(track['loop'],track['kind']=='music')
                self.assertEqual(track['source_out'],4 if track['kind']=='music' else 1)

    def test_utf8_source_captions_keep_absolute_time_text_and_explicit_burn(self):
        (self.source/'台词.srt').write_text('\ufeff1\n00:00:01,000 --> 00:00:01,500\n圣旨：[重启]\n第二行\n',encoding='utf-8')
        self.plan['subtitles']={'path':'台词.srt','style':'news','burn':True}
        report=self.preview();value=report['bundle']['timeline']
        self.assertEqual(value['subtitles'],[{'start':1,'end':1.5,'text':'圣旨：[重启]\n第二行'}])
        self.assertEqual(value['subtitle_render'],{'style':'news','burn':True})
        self.plan['subtitles']['burn']=False;value=self.preview()['bundle']['timeline']
        self.assertFalse(value['subtitle_render']['burn']);self.assertEqual(value['subtitles'][0]['start'],1)

    def test_stale_plan_media_caption_or_destination_token_cannot_create_project(self):
        for change in ('plan','media','caption','destination'):
            (self.source/'caption.srt').write_text('1\n00:00:00,000 --> 00:00:00,500\nCaption\n',encoding='utf-8')
            self.plan['subtitles']={'path':'caption.srt','style':'clean','burn':True};report=self.preview()
            if change=='plan':self.plan['finishing']['fade_seconds']=.2;self.save()
            if change=='media':
                with (self.source/'red.mp4').open('ab') as stream:stream.write(b'changed')
            if change=='caption':(self.source/'caption.srt').write_text('1\n00:00:00,000 --> 00:00:00,500\nChanged\n',encoding='utf-8')
            target=self.destination if change!='destination' else self.base/'another'
            with self.subTest(change=change):
                with self.assertRaisesRegex(ConfigError,'changed'):migrate.execute(self.source,target,expected_token=report['preview_token'])
                self.assertFalse(target.exists())

    def test_existing_nested_parent_or_same_destination_rejected_without_mutation(self):
        before=self.snapshot()
        for target in (self.source,self.source/'nested',self.source.parent):
            with self.subTest(target=target):
                with self.assertRaises(ConfigError):migrate.preview(self.source,target)
        self.assertEqual(before,self.snapshot())

    def test_missing_outside_or_changed_file_paths_never_escape_project(self):
        for path in ('missing.mp4','../outside.mp4',str(self.assets/'red.mp4')):
            self.plan['timeline']['inputs'][0]['path']=path;self.save()
            with self.subTest(path=path):
                with self.assertRaises(ConfigError):migrate.preview(self.source,self.destination)
            self.assertFalse(self.destination.exists())

    def test_unknown_settings_and_unsupported_backends_are_explicit_errors(self):
        original=copy.deepcopy(self.plan)
        for section,key,value in [(None,'unknown','ignore?'),('timeline','custom_filter','movie=x'),
                                  ('finishing','crop','unknown'),('audio_mix','preserve_source',False),
                                  ('backend','selected','chatcut'),('timeline','fps',24),('subtitles','style',[])]:
            self.plan=copy.deepcopy(original);target=self.plan if section is None else self.plan[section];target[key]=value;self.save()
            with self.subTest(section=section,key=key):
                with self.assertRaises(ConfigError):migrate.preview(self.source,self.destination)
            self.assertFalse(self.destination.exists())

    def test_bad_filters_overlay_nonfinite_windows_and_frame_grid_rejected(self):
        original=copy.deepcopy(self.plan)
        for mode in ('filters','overlay','nan','frame-grid','fade'):
            self.plan=copy.deepcopy(original)
            if mode=='filters':self.plan['timeline']['inputs'][0]['filters']=['cool','cool']
            if mode=='overlay':self.plan['overlays']=[{'text':'ignored before'}]
            if mode=='nan':self.plan['timeline']['inputs'][0]['speed']='NaN'
            if mode=='frame-grid':self.plan['timeline']['transitions'][0].update(type='dissolve',duration=.51)
            if mode=='fade':self.plan['finishing']['fade_seconds']=3
            self.save()
            with self.subTest(mode=mode):
                with self.assertRaises((ConfigError,ValueError)):migrate.preview(self.source,self.destination)

    def test_styled_malformed_or_overlapping_burned_srt_rejected(self):
        for text in ('garbage','1\n00:99:00,000 --> 00:00:01,000\nx',
            '1\n00:00:00,000 --> 00:00:00,500\n<b>Styled</b>',
            '1\n00:00:00,000 --> 00:00:01,000\nx\n\n2\n00:00:00,500 --> 00:00:01,500\ny'):
            (self.source/'bad.srt').write_text(text,encoding='utf-8');self.plan['subtitles']={'path':'bad.srt','burn':True,'style':'clean'};self.save()
            with self.subTest(text=text):
                with self.assertRaises((ConfigError,ValueError)):migrate.preview(self.source,self.destination)

    def test_failed_decode_or_source_change_during_copy_never_publishes_destination(self):
        report=self.preview();before=self.snapshot()
        original=subprocess.run
        def fail_decode(args,**kwargs):
            if '-xerror' in args:return subprocess.CompletedProcess(args,1,stderr=b'bad frame')
            return original(args,**kwargs)
        with patch.object(subprocess,'run',side_effect=fail_decode):
            with self.assertRaisesRegex(ConfigError,'decode'):migrate.execute(self.source,self.destination,expected_token=report['preview_token'])
        self.assertEqual(before,self.snapshot());self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.base.glob('.videocreate-migration-*')),[])

    def frame(self,path,t):
        return subprocess.run([shutil.which('ffmpeg'),'-v','error','-ss',str(t),'-i',str(path),'-frames:v','1',
            '-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout

    def amplitude(self,path,start,freq):
        data=subprocess.run([shutil.which('ffmpeg'),'-v','error','-ss',str(start),'-i',str(path),'-t','0.08',
            '-vn','-f','s16le','-ac','1','-ar','48000','-'],capture_output=True,check=True).stdout
        values=struct.unpack('<'+'h'*(len(data)//2),data)
        return abs(sum(v*complex(math.cos(2*math.pi*freq*i/48000),math.sin(2*math.pi*freq*i/48000)) for i,v in enumerate(values)))/len(values)

    def test_real_migrated_video_has_slide_fade_literal_captions_and_looped_audio(self):
        self.plan['timeline']['transitions'][0].update(type='slide-left',duration=.4)
        self.plan['filters']=[{'preset':'warm','scope':'all'}]
        self.plan['timeline']['inputs'][1]['filters']=['monochrome']
        self.plan['audio_mix'].update(music='music.wav',voice='voice.wav')
        self.plan['finishing']['fade_seconds']=.2
        (self.source/'caption.srt').write_text('1\n00:00:02,000 --> 00:00:02,500\n圣旨：[重启]\n',encoding='utf-8')
        self.plan['subtitles']={'path':'caption.srt','style':'clean','burn':True}
        self.execute();before=self.snapshot();bundle=load_project(self.destination)
        result=render(self.destination,bundle,read_state(self.destination));path=Path(result['path'])
        self.assertAlmostEqual(result['media']['duration'],3.6,delta=.035);self.assertEqual(int(result['media']['frame_count']),108)
        self.assertLess(max(self.frame(path,0)[:3]),5)
        self.assertLess(max(self.frame(path,3.55)[:3]),35)
        late=self.frame(path,3)[:3];self.assertLess(max(late)-min(late),6)
        def whites(b):return sum(min(b[i:i+3])>190 for i in range(0,len(b),3))
        self.assertGreater(whites(self.frame(path,2.25)),80);self.assertLess(whites(self.frame(path,2.75)),20)
        self.assertGreater(self.amplitude(path,3,1320),40)  # .5-second music really continues beyond its first loop.
        self.assertGreater(self.amplitude(path,.4,1760),self.amplitude(path,3,1760)*5)
        self.assertEqual(self.snapshot(),before);self.assertEqual(production.delivery(self.destination)['status'],'review_pending')
        self.assertEqual(result['finishing']['looped_audio'],['legacy-music'])

    def test_changed_during_decode_is_rechecked_before_new_project_is_published(self):
        report=self.preview();original=subprocess.run;changed=[]
        def mutate(args,**kwargs):
            result=original(args,**kwargs)
            if '-xerror' in args and not changed:
                changed.append(True)
                with (self.source/'red.mp4').open('ab') as stream:stream.write(b'changed-after-copy')
            return result
        with patch.object(subprocess,'run',side_effect=mutate):
            with self.assertRaisesRegex(ConfigError,'changed'):migrate.execute(self.source,self.destination,expected_token=report['preview_token'])
        self.assertFalse(self.destination.exists());self.assertTrue(changed)

    def test_two_imports_to_same_destination_do_not_merge_or_inherit_previous_state(self):
        self.execute();before={p.relative_to(self.destination).as_posix():migrate.digest(p) for p in self.destination.rglob('*') if p.is_file()}
        with self.assertRaises(ConfigError):migrate.preview(self.source,self.destination)
        self.assertEqual(before,{p.relative_to(self.destination).as_posix():migrate.digest(p) for p in self.destination.rglob('*') if p.is_file()})

    def test_format_four_controls_reject_lower_versions_invalid_fades_loops_and_gains(self):
        value=self.preview()['bundle']['timeline']
        for key,item in [('fade_seconds',float('inf')),('fade_seconds',-1),('mix_limiter',1)]:
            candidate=copy.deepcopy(value);candidate[key]=item
            with self.subTest(key=key,item=item):self.assertTrue(validate_timeline(candidate))
        for gain in (True,'-10',float('nan'),61):
            candidate=copy.deepcopy(value);candidate['segments'][0]['source_gain_db']=gain
            self.assertTrue(validate_timeline(candidate))
        candidate=copy.deepcopy(value);candidate['audio_tracks']=[{'id':'music','kind':'music','path':'music.wav',
            'source_in':0,'source_out':1,'timeline_start':0,'loop':'true'}]
        self.assertTrue(validate_timeline(candidate))
        for version in (1,2,3):
            candidate=copy.deepcopy(value);candidate['format_version']=version
            self.assertTrue(validate_timeline(candidate))

    def test_real_source_gain_is_applied_without_changing_source_audio_bytes(self):
        self.execute();bundle=load_project(self.destination);before=self.snapshot()
        baseline=render(self.destination,bundle,read_state(self.destination),output_name='base.mp4')
        for segment in bundle['timeline']['segments']:segment['source_gain_db']=-12
        atomic_json(self.destination/'timeline.json',bundle['timeline'])
        quiet=render(self.destination,bundle,read_state(self.destination),output_name='quiet.mp4')
        ratio=self.amplitude(Path(quiet['path']),.5,440)/self.amplitude(Path(baseline['path']),.5,440)
        self.assertAlmostEqual(ratio,10**(-12/20),delta=.015);self.assertEqual(self.snapshot(),before)

    def test_cli_preview_import_and_local_render_need_no_provider_configuration(self):
        from videocreate.production_commands import production_command
        with patch('videocreate.cli.read_config',side_effect=AssertionError('No config')):
            args=['--source',str(self.source),'--destination',str(self.destination)]
            with redirect_stdout(io.StringIO()) as stream:self.assertEqual(production_command(['legacy-edit-preview',*args]),0)
            token=json.loads(stream.getvalue())['preview_token']
            with redirect_stdout(io.StringIO()):self.assertEqual(production_command(['legacy-edit-import',*args,'--preview-token',token]),0)
        self.assertTrue(validate_plan(load_project(self.destination),self.destination)['ok'])


class LegacyImportFormTests(unittest.TestCase):
    setUp=forms.ScreenplayFormsTests.setUp
    field=forms.ScreenplayFormsTests.field
    button=forms.ScreenplayFormsTests.button
    widgets=forms.ScreenplayFormsTests.widgets
    pump=forms.ScreenplayFormsTests.pump

    def test_manager_uses_shared_preview_and_refuses_changed_form_before_import(self):
        from videocreate.manager_legacy_edit import open_form
        with patch('videocreate.legacy_edit_import.preview',return_value={'ok':True,'source':str(self.root),
                'destination':str(self.root.with_name(self.root.name+'-v3')),'preview_token':'bound'}) as described:
            win=open_form(self.manager,source=self.root);win.withdraw()
            self.button(win,'预览迁移').invoke()
            import time
            deadline=time.monotonic()+10
            while win.migration_call.busy and time.monotonic()<deadline:win.update();time.sleep(.01)
            self.assertEqual(win.migration_state['report']['preview_token'],'bound');described.assert_called_once()
            self.field(win.migration_form,'destination',str(self.root.with_name('changed')))
            with patch.object(self.manager,'error') as error,patch('videocreate.legacy_edit_import.execute') as imported:
                self.button(win,'按此预览创建 v3 项目').invoke();imported.assert_not_called();error.assert_called_once()
            self.assertEqual(self.path.read_bytes(),self.before);win.destroy()

    def test_native_format_four_controls_preview_and_roundtrip_without_task_changes(self):
        from videocreate.manager_authoring import open_editor
        from videocreate.planning.project import load_project
        win=open_editor(self.manager,self.root,'timeline');win.withdraw();form=win.authoring_timeline
        self.field(form.finishing,'fade_seconds','.2');self.field(form.finishing,'mix_limiter','否')
        self.field(form.segments.editor,'source_gain_db','-8');form.audio.add()
        self.field(form.audio.editor,'clip_id',form.clips.items[0]['id'])
        self.field(form.audio.editor,'loop','是');form.draw()
        value=win.authoring_read();self.assertEqual(value['format_version'],4);self.assertTrue(form.graph_data['ok'])
        self.button(win,'预览修改影响').invoke();self.pump(win)
        self.button(win,'保存当前创作层').invoke();self.pump(win);win.destroy()
        self.assertEqual(load_project(self.root)['timeline'],value);self.assertEqual(self.path.read_bytes(),self.before)
        win=open_editor(self.manager,self.root,'timeline');win.withdraw()
        self.assertEqual(win.authoring_read(),value);win.destroy()


if __name__=='__main__':unittest.main()
