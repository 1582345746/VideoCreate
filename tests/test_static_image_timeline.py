"""Real still/video edits; no provider requests or real content approvals."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'videocreate/src'), str(ROOT/'videocreate/scripts'), str(ROOT/'tests')]
from PIL import Image
from videocreate import authoring, production, still_images
from videocreate.commands import plan_command
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.local_sources import digest, import_clip, import_image, verify_source
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project, save_bundle, validate_plan
from videocreate.production_commands import production_command
from videocreate.production_metrics import report
from videocreate.review import page, receipts
from videocreate.runtime.state import read_state
from videocreate.timeline.render import render, probe


class StaticImageTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory();folder = Path(cls.shared.name)
        cls.red, cls.blue = folder/'red.png', folder/'blue.webp'
        Image.new('RGB', (128,72), (240,20,20)).save(cls.red)
        Image.new('RGB', (128,72), (20,20,240)).save(cls.blue, lossless=True)
        cls.video = folder/'source.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-v','error','-y','-f','lavfi','-i',
            'testsrc2=size=128x72:rate=24:duration=1','-f','lavfi','-i',
            'sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p',
            '-c:a','aac','-shortest',str(cls.video)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'图片剪辑'
        save_bundle(self.root, create('edit-only',title='Static edit fixture'))
        guard = mock.patch('urllib.request.urlopen', side_effect=AssertionError('No real network'))
        guard.start();self.addCleanup(guard.stop)

    def add(self, identity='still', seconds=.5, source=None):
        return import_image(self.root, source or self.red, source_id=identity, seconds=seconds)

    def render(self):
        bundle = load_project(self.root);bundle['timeline'].update(width=128,height=72)
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        return render(self.root,bundle,read_state(self.root))

    def image_receipt(self):
        bundle = load_project(self.root)
        packet = receipts.template(self.root,bundle)
        packet['reviewer_id'] = 'synthetic-contract-fixture'
        packet['assets'] = {k:v for k,v in packet['assets'].items() if v.get('media_kind')=='image'}
        for asset in packet['assets'].values():
            for layer, observation in asset['layers'].items():
                if layer not in asset['required_layers']:
                    observation['status']='not_applicable';continue
                observation.update(status='pass',method='human-image',
                    observations=['Synthetic receipt validator fixture, not actual content approval'],
                    evidence=[{'path':asset['path'],'sha256':asset['sha256'],'kind':'image'}])
        return packet

    def test_import_preserves_exact_source_and_static_metadata_without_tasks(self):
        before = digest(self.red);result = self.add()
        self.assertEqual(result['source']['kind'],'image')
        self.assertNotIn('duration',result['source']['media']);self.assertNotIn('fps',result['source']['media'])
        self.assertEqual(digest(verify_source(self.root,result['source'])),before)
        self.assertEqual(digest(self.red),before)
        self.assertTrue(result['full_decode_verified']);self.assertTrue(validate_plan(load_project(self.root),self.root)['ok'])
        self.assertEqual(read_state(self.root)['jobs'],{});self.assertEqual(read_state(self.root)['ledger'],[])
        current = production.status(self.root)
        self.assertEqual(current['local_sources'][0]['kind'],'imported-image')
        self.assertEqual(current['local_sources'][0]['content_status'],'unverified')

    def test_corrupt_animated_wrong_profile_and_bad_hold_preserve_plan(self):
        corrupt = self.root/'corrupt.png';corrupt.write_bytes(b'not-image')
        animation = self.root/'animation.webp'
        with Image.open(self.red) as first, Image.open(self.blue) as second:
            first.save(animation,save_all=True,append_images=[second],duration=100,loop=0)
        before = {p.name:p.read_bytes() for p in self.root.glob('*.json')}
        for source, seconds in ((corrupt,1),(animation,1),(self.red,0),(self.red,True),(self.red,float('inf'))):
            with self.subTest(source=source,seconds=seconds), self.assertRaises(ConfigError):
                self.add(source=source,seconds=seconds)
        with self.assertRaises(ConfigError): self.add(identity='final')
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.glob('*.json')})
        other = self.root.parent/'images';save_bundle(other,create('image-only',topic='One static fixture'))
        with self.assertRaises(ConfigError):import_image(other,self.red,source_id='wrong-workflow')

    def test_holds_extend_without_fictitious_source_duration_and_reject_video_options(self):
        self.add();bundle=load_project(self.root)
        bundle['timeline']['segments'][0]['source_out']=7
        self.assertTrue(validate_plan(bundle,self.root)['ok'])
        for key,value in (('source_in',.1),('rate',2),('source_audio','preserve')):
            bad=copy.deepcopy(bundle);bad['timeline']['segments'][0][key]=value
            self.assertFalse(validate_plan(bad,self.root)['ok'])
        bad=copy.deepcopy(bundle)
        bad['timeline']['audio_tracks']=[{'id':'invalid-audio','kind':'music','clip_id':'clip-still',
            'source_in':0,'source_out':1,'timeline_start':0}]
        self.assertFalse(validate_plan(bad,self.root)['ok'])
        bad=copy.deepcopy(bundle);bad['generation-plan']['local_sources'][0]['media']['duration']=7
        self.assertFalse(validate_plan(bad,self.root)['ok'])

    def test_actual_mixed_edit_has_requested_stills_audio_captions_and_correct_metrics(self):
        self.add('red',.5);import_clip(self.root,self.video,source_id='take',end=.5)
        self.add('blue',.5,self.blue)
        bundle=load_project(self.root)
        bundle['timeline']['audio_tracks']=[{'id':'voice','kind':'dialogue','clip_id':'clip-take',
            'source_in':0,'source_out':.25,'timeline_start':.1,'gain_db':-6}]
        bundle['timeline']['subtitles']=[{'text':'Observed fixture label','segment_id':'seg-red',
            'source_start':0,'source_end':.4}]
        atomic_json(self.root/'timeline.json',bundle['timeline'])
        result=self.render();self.assertAlmostEqual(probe(Path(result['path']))['duration'],1.5,delta=.08)
        for at,dominant in ((.2,0),(1.2,2)):
            raw=subprocess.check_output([shutil.which('ffmpeg'),'-v','error','-ss',str(at),'-i',result['path'],
                '-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'])
            self.assertGreater(raw[dominant],150)
        self.assertEqual(result['source_kinds'],{'clip-red':'image','clip-take':'video','clip-blue':'image'})
        self.assertIsNone(result['fps_report'][0]['source_frame_samples_per_timeline_second'])
        measured=report(self.root)
        self.assertEqual(measured['seconds']['generated_known'],0)
        self.assertEqual(measured['seconds']['retained_available_playback'],1.5)
        self.assertEqual(measured['seconds']['retained_unique_source'],.5)
        self.assertEqual(measured['local_sources']['static_retained_playback'],1)
        self.assertIn('Observed fixture label',Path(result['path']).with_suffix('.srt').read_text(encoding='utf-8'))
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')

    def test_source_review_uses_exact_image_and_never_approves_final_motion(self):
        self.add();self.render();bundle=load_project(self.root)
        packet=self.image_receipt();asset=packet['assets']['still']
        self.assertIsNone(asset['duration']);self.assertEqual(asset['windows'],[])
        self.assertEqual(asset['required_layers'],['clean_frame'])
        self.assertEqual(receipts.validate_receipt(self.root,bundle,packet),[])
        receipts.apply(self.root,bundle,packet)
        current=production.status(self.root)
        self.assertEqual(current['local_sources'][0]['content_status'],'reviewed')
        self.assertEqual(current['review']['status'],'review_pending')
        final=receipts.contracts(self.root,bundle)['final']
        self.assertIn('performance_motion',final['required_layers']);self.assertIn('editorial',final['required_layers'])
        self.assertEqual(report(self.root)['local_sources']['static_reviewed_playback'],.5)
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_static_receipts_reject_temporal_claims_wrong_bytes_and_fake_timestamps(self):
        self.add();packet=self.image_receipt();bundle=load_project(self.root)
        for change in ('motion','kind','time','path','method'):
            bad=copy.deepcopy(packet);asset=bad['assets']['still'];observation=asset['layers']['clean_frame']
            if change=='motion':asset['layers']['performance_motion']=copy.deepcopy(observation)
            elif change=='kind':observation['evidence'][0]['kind']='video'
            elif change=='time':observation['evidence'][0].update(start=0,end=1)
            elif change=='path':
                target=self.root/'other.png';shutil.copyfile(self.blue,target)
                observation['evidence'][0].update(path='other.png',sha256=digest(target))
            else:observation['method']='human-video'
            with self.subTest(change=change):self.assertTrue(receipts.validate_receipt(self.root,bundle,bad))

    def test_timeline_edits_preserve_image_review_and_invalidate_only_final_edit(self):
        self.add();self.render();bundle=load_project(self.root)
        receipts.apply(self.root,bundle,self.image_receipt())
        initial=receipts.contracts(self.root,bundle)['still'];before=read_state(self.root)
        snapshot=authoring.describe(self.root,'timeline');timeline=copy.deepcopy(snapshot['value'])
        timeline['segments'][0]['source_out']=1
        timeline['subtitles']=[{'text':'New still caption','start':0,'end':.5}]
        preview=authoring.preview(self.root,'timeline',timeline,source_token=snapshot['source_token'])
        authoring.save(self.root,'timeline',timeline,source_token=snapshot['source_token'],preview_token=preview['preview_token'])
        self.assertEqual(production.impact(self.root)['changed_job_inputs'],[])
        self.assertEqual(receipts.contracts(self.root,load_project(self.root),include_final=False)['still'],initial)
        self.assertIn('stale',production.status(self.root)['review']['final_error'])
        self.render();self.assertEqual(production.status(self.root)['local_sources'][0]['content_status'],'reviewed')
        self.assertEqual(read_state(self.root),before)

    def test_changed_image_or_metadata_blocks_validation_render_review_and_metrics(self):
        result=self.add();source=result['source'];bundle=load_project(self.root)
        path=verify_source(self.root,source);path.write_bytes(self.blue.read_bytes())
        self.assertFalse(validate_plan(bundle,self.root)['ok'])
        for call in (lambda:render(self.root,bundle,read_state(self.root)),lambda:receipts.contracts(self.root,bundle)):
            with self.assertRaises(ConfigError):call()
        self.assertEqual(report(self.root)['local_sources']['static_retained_playback'],0)
        path.write_bytes(self.red.read_bytes());bundle['generation-plan']['local_sources'][0]['media']['width']=999
        self.assertFalse(validate_plan(bundle,self.root)['ok'])

    def test_cli_import_and_route_are_offline_and_report_static_reading_and_page(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(production_command(['import-image',str(self.root),'--source',str(self.red),
                '--source-id','cli-still','--duration','.5']),0)
        self.assertEqual(json.loads(output.getvalue())['source']['kind'],'image')
        for action in ('compile','route'):
            with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config')), redirect_stdout(io.StringIO()):
                self.assertEqual(plan_command([action,str(self.root)]),0)
        reading=production.script_export(self.root)
        self.assertIn('静态图片停留',Path(reading['reading_copy']).read_text(encoding='utf-8'))
        result=page.export(self.root);html=Path(result['page']).read_text(encoding='utf-8')
        packet=json.loads(html.split('<script id="data" type="application/json">',1)[1].split('</script>',1)[0])
        self.assertEqual(packet['receipt']['assets']['cli-still']['media_kind'],'image')
        self.assertIn('still-player',html);self.assertIn('human-image',html)
        with self.assertRaises(ConfigError):
            production_command(['import-image',str(self.root),'--source',str(self.red),'--source-id','bad','--start','1'])

    def test_exif_orientation_and_transparency_normalize_for_render_without_rewriting_original(self):
        image=self.root/'oriented.jpg';normalized=self.root/'normalized.png'
        original=Image.new('RGB',(40,20),(200,40,30));exif=Image.Exif();exif[274]=6
        original.save(image,exif=exif);sha=digest(image)
        result=still_images.inspect(image,normalized=normalized)
        self.assertEqual((result['width'],result['height']),(20,40));self.assertEqual(digest(image),sha)
        with Image.open(normalized) as actual:self.assertEqual(actual.size,(20,40))
        transparent=self.root/'alpha.png';Image.new('RGBA',(8,8),(240,20,20,0)).save(transparent)
        still_images.inspect(transparent,normalized=normalized)
        with Image.open(normalized) as actual:self.assertEqual(actual.getpixel((0,0)),(0,0,0))

    def test_relocation_and_interrupted_import_preserve_exact_original_layers(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')};real=atomic_json
        def fail(target,value):
            if target==self.root/'timeline.json':raise OSError('Synthetic write failure')
            return real(target,value)
        with mock.patch('videocreate.local_sources.atomic_json',side_effect=fail):
            with self.assertRaises(OSError):self.add()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.glob('*.json')})
        self.add();self.render();relocated=self.root.parent/'relocated';shutil.copytree(self.root,relocated)
        self.assertTrue(validate_plan(load_project(relocated),relocated)['ok'])
        self.assertEqual(production.delivery(relocated)['status'],'review_pending')

    def test_mixed_generated_dependency_uses_static_source_without_implicit_reference(self):
        from videocreate.runtime import jobs
        from test_v3_config import config
        self.root=self.root.parent/'mixed';save_bundle(self.root,create('mixed-video'))
        self.add();bundle=load_project(self.root)
        bundle['director']['shots'].append({'id':'generated','scene_id':'local-edit','framing':'Fixed wide',
            'information_goal':'One step','actions':[{'kind':'physical','description':'Take one step'}],
            'planned_seconds':2,'cut_motivation':'Show next action','audio':{'mode':'ambience'}})
        bundle['generation-plan']['jobs']=[{'id':'gen','shot_ids':['generated'],'operation':'text-to-video',
            'seconds':2,'depends_on':['still'],'binding_id':'grok-on-sub2api'}]
        bundle['timeline']['clips'].append({'id':'clip-gen','job_id':'gen'})
        bundle['timeline']['segments'].append({'id':'seg-gen','clip_id':'clip-gen','shot_id':'generated',
            'source_in':0,'source_out':.5,'rate':1,'source_audio':'retime','cut_reason':'Fixture action'})
        for layer in ('director','generation-plan','timeline'):atomic_json(self.root/(layer+'.json'),bundle[layer])
        calls=[];video=self.video
        class Client:
            def __init__(self,binding):self.last_submission={}
            def prepare(self,prompt,**kwargs):return {'prompt':prompt}
            def create(self,prompt,**kwargs):calls.append(kwargs);return 'fixture-generated-task'
            def poll(self,*args,**kwargs):return {'status':'completed'}
            def download(self,task_id,payload,destination):shutil.copyfile(video,destination)
        with mock.patch('videocreate.runtime.jobs.client',side_effect=Client):
            self.assertTrue(jobs.generate(self.root,config(),store_root=self.root.parent/'config')['ok'])
        self.assertEqual(len(calls),1);self.assertFalse(calls[0].get('references'))
        self.render();before=read_state(self.root)
        self.assertEqual(set(receipts.contracts(self.root,load_project(self.root))),{'still','gen','final'})
        self.assertEqual(report(self.root)['seconds']['generated_known'],1)
        self.assertEqual(len(before['ledger']),1)
        timeline=load_project(self.root)['timeline'];timeline['segments'][0]['source_out']=1
        atomic_json(self.root/'timeline.json',timeline)
        self.assertEqual(production.impact(self.root)['changed_job_inputs'],[])
        self.render();self.assertEqual(read_state(self.root),before)

    def test_existing_mixed_shot_mapping_preserves_director_and_cannot_replace_coverage(self):
        self.root=self.root.parent/'mapped';bundle=create('mixed-video')
        bundle['director']['scenes']=[{'id':'scene','map':'A still illustration','axis':'Authored viewpoint'}]
        shot={'id':'authored','scene_id':'scene','information_goal':'Show an authored illustration','framing':'Full image',
            'actions':[{'kind':'hold','description':'Hold existing image'}],'planned_seconds':2,
            'audio':{'mode':'mute'},'cut_motivation':'Cut to next illustration'}
        bundle['director']['shots']=[shot];save_bundle(self.root,bundle)
        result=import_image(self.root,self.red,source_id='mapped',seconds=.5,shot_id='authored')
        self.assertEqual(load_project(self.root)['director'],bundle['director'])
        self.assertEqual(result['source']['shot_ids'],['authored'])
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with self.assertRaises(ConfigError):
            import_image(self.root,self.blue,source_id='replacement',seconds=.5,shot_id='authored')
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.glob('*.json')})


if __name__=='__main__':unittest.main()
