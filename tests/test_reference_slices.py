import copy
import io
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from test_typed_media_generation import media_limits
from videocreate import media_references as refs
from videocreate.config.management import migrate
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.media_reference_commands import command
from videocreate.planning.examples import smart_car
from videocreate.planning.project import load_project, save_bundle, validate_plan
from videocreate.reference_slices import slice_reference
from videocreate.routing import recommend
from videocreate.runtime.state import read_state


class ReferenceSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.temp.name)
        cls.samples = b''.join(struct.pack('<h', (i % 1000) - 500) for i in range(48000))
        with wave.open(str(cls.fixture / 'source.wav'), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(cls.samples)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=64x64:r=12:d=3',
            '-i', str(cls.fixture/'source.wav'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', str(cls.fixture/'source.mp4')], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = smart_car()
        for shot in self.bundle['director']['shots']:
            shot['audio'] = {'mode': 'mute'}
        save_bundle(self.root, self.bundle)

    def source(self, kind='audio'):
        return refs.register(self.root, self.fixture/('source.mp4' if kind == 'video' else 'source.wav'),
                             kind=kind, role='motion' if kind == 'video' else 'sound')

    def test_pcm_slice_has_exact_requested_samples_and_preserves_source(self):
        source = self.source()
        result = slice_reference(self.root, source, start=.25, end=1.5)
        with wave.open(str(self.root/result['reference']['path']), 'rb') as output:
            self.assertEqual(output.getframerate(), 16000)
            self.assertEqual(output.getnchannels(), 1)
            self.assertEqual(output.readframes(output.getnframes()), self.samples[4000*2:24000*2])
        self.assertEqual(result['actual_duration_seconds'], 1.25)
        self.assertEqual(refs.digest(self.root/source['path']), source['sha256'])
        self.assertEqual(result['paid_creates'], 0)
        self.assertFalse(result['plan_modified'])

    def test_extract_dialogue_pins_speaker_video_interval_and_original_mix(self):
        source = self.source('video')
        result = slice_reference(self.root, source, start=.25, end=1.5, extract_speaker='speaker-a')
        self.assertEqual(result['audio_source'], 'original-mix')
        ref = result['reference']
        manifest = load_json(self.root / ref['derivation']['path'])
        self.assertEqual(manifest['speaker'], 'speaker-a')
        self.assertEqual(manifest['source'], source)
        self.assertEqual(manifest['interval'], {'start_seconds': .25, 'end_seconds': 1.5})
        prepared = refs.prepare_references(self.root, [ref])[0]
        self.assertEqual((prepared['kind'], prepared['role'], prepared['mime_type']), ('audio', 'sound', 'audio/wav'))
        with wave.open(str(self.root / ref['path']), 'rb') as audio:
            self.assertEqual(audio.getnframes(), int(audio.getframerate() * 1.25))
        silent = self.root / 'silent.mp4'
        subprocess.run(['ffmpeg','-v','error','-i',str(self.fixture/'source.mp4'),'-an','-c:v','copy',str(silent)],check=True)
        no_audio = refs.register(self.root, silent, kind='video', role='motion')
        with self.assertRaisesRegex(ConfigError, 'No decodable audio'):
            slice_reference(self.root, no_audio, start=0, end=1, extract_speaker='speaker-a')

    def test_decoded_video_slice_is_playable_and_preserves_audio(self):
        source = self.source('video')
        result = slice_reference(self.root, source, start=.5, end=1.5)
        output = self.root/result['reference']['path']
        probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(output)]))
        self.assertEqual({s['codec_type'] for s in probe['streams']}, {'video','audio'})
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'],check=True,capture_output=True)
        self.assertAlmostEqual(result['actual_duration_seconds'], 1, delta=.1)
        self.assertEqual(refs.digest(self.root/source['path']), source['sha256'])
        record=load_json(self.root/result['reference']['derivation']['path'])
        self.assertEqual(record['interval'], {'start_seconds':.5,'end_seconds':1.5})
        self.assertEqual(record['output']['duration_seconds'], result['actual_duration_seconds'])

    def test_invalid_intervals_fail_before_ffmpeg_or_output_creation(self):
        source = self.source()
        run_process=subprocess.run
        for start,end in [(-1,1),(0,0),(2,1),(0,3.01),(True,1),(0,False),('0',1),
                          (float('nan'),1),(0,float('inf'))]:
            with self.subTest(start=start,end=end), mock.patch('videocreate.reference_slices.subprocess.run',wraps=run_process) as run:
                with self.assertRaises(ConfigError):
                    slice_reference(self.root,source,start=start,end=end)
                self.assertTrue(all(Path(call.args[0][0]).stem.lower()=='ffprobe' for call in run.call_args_list))
                self.assertFalse(list((self.root/'assets/media-references').glob('*.derivation.json')))

    def test_legacy_or_image_reference_is_not_a_temporal_slice(self):
        source=self.source()
        for value in [{k:v for k,v in source.items() if k!='kind'}, {**source,'kind':'image'}]:
            with self.assertRaises(ConfigError): slice_reference(self.root,value,start=0,end=1)

    def test_deterministic_slice_does_not_overwrite_distinct_provenance(self):
        source=self.source()
        first=slice_reference(self.root,source,start=.5,end=1.5)
        again=slice_reference(self.root,source,start=.5,end=1.5)
        self.assertEqual(first,again)
        # This periodic PCM source has the same bytes at a different interval.
        second=slice_reference(self.root,source,start=1.5,end=2.5)
        self.assertEqual(first['reference']['sha256'],second['reference']['sha256'])
        self.assertNotEqual(first['reference_file'],second['reference_file'])
        self.assertNotEqual(first['reference']['derivation'],second['reference']['derivation'])

    def test_manifest_tampering_and_missing_source_are_rejected(self):
        source=self.source()
        derived=slice_reference(self.root,source,start=0,end=1)['reference']
        manifest=self.root/derived['derivation']['path']
        original=manifest.read_bytes()
        manifest.write_bytes(original+b' ')
        with self.assertRaisesRegex(ConfigError,'manifest hash'):
            refs.prepare_references(self.root,[derived])
        manifest.write_bytes(original)
        (self.root/source['path']).write_bytes(b'changed')
        with self.assertRaises(ConfigError): refs.prepare_references(self.root,[derived])

    def test_rehashed_forged_output_metadata_or_outside_path_is_rejected(self):
        source=self.source()
        derived=slice_reference(self.root,source,start=0,end=1)['reference']
        path=self.root/derived['derivation']['path']
        original=load_json(path)
        for change in ('output','source','interval'):
            value=copy.deepcopy(original)
            if change=='output': value['output']['bytes']+=1
            elif change=='source': value['source']['path']='../outside.wav'
            else: value['interval']['end_seconds']=4
            atomic_json(path,value)
            derived['derivation']['sha256']=refs.digest(path)
            with self.assertRaises(ConfigError): refs.prepare_references(self.root,[derived])

    def test_nested_slices_preserve_original_chain(self):
        source=self.source()
        first=slice_reference(self.root,source,start=.5,end=2.5)['reference']
        second=slice_reference(self.root,first,start=.25,end=1.25)['reference']
        self.assertEqual(refs.prepare_references(self.root,[second])[0]['duration_seconds'],1)
        record=load_json(self.root/second['derivation']['path'])
        self.assertEqual(record['source'],first)
        (self.root/first['derivation']['path']).write_bytes(b'{}')
        with self.assertRaises(ConfigError): refs.prepare_references(self.root,[second])

    def test_cli_slice_attach_preserves_derivation_and_validates_plan(self):
        source=self.source()
        path=self.root/'source.reference.json'
        atomic_json(path,source)
        before=(self.root/'generation-plan.json').read_bytes()
        capture=io.StringIO()
        with redirect_stdout(capture):
            self.assertEqual(command(['slice',str(self.root),'--reference',str(path),'--start','.25','--end','1.25']),0)
        result=json.loads(capture.getvalue())
        self.assertEqual(before,(self.root/'generation-plan.json').read_bytes())
        with redirect_stdout(io.StringIO()):
            command(['attach',str(self.root),'--reference',result['reference_file'],'--job','job-001'])
        bundle=load_project(self.root)
        self.assertEqual(bundle['generation-plan']['jobs'][0]['references'],[result['reference']])
        self.assertTrue(validate_plan(bundle,self.root)['ok'])
        self.assertFalse(read_state(self.root)['ledger'])
        (self.root/result['reference']['derivation']['path']).write_bytes(b'{}')
        self.assertFalse(validate_plan(bundle,self.root)['ok'])

    def test_recommendation_uses_actual_typed_video_and_audio_limits(self):
        value=migrate(config())
        bid='grok-on-sub2api'
        binding=value['bindings'][bid]
        binding.update(adapter='xingapi-video-v2',operations=['reference-to-video'],
            capability_overrides={'duration':{'minimum':1,'maximum':30,'step':1},
                'resolutions':['720p'],'aspect_ratios':['16:9','9:16'],'audio_control':'model-default',
                'media_reference_limits':media_limits()})
        job=self.bundle['generation-plan']['jobs'][0]
        job.update(binding_id=bid,operation='reference-to-video',references=[self.source('video'),self.source()])
        result=recommend(self.bundle,value,store_root=self.root,root=self.root)
        self.assertEqual(result['jobs'][0]['recommended'],bid)
        binding['capability_overrides']['media_reference_limits']['video']['maximum_duration_seconds']=1
        result=recommend(self.bundle,value,store_root=self.root,root=self.root)
        self.assertIsNone(result['jobs'][0]['recommended'])
        self.assertTrue(result['jobs'][0]['candidates'][0]['request_errors'])
        with self.assertRaisesRegex(ConfigError,'project root'):
            recommend(self.bundle,value,store_root=self.root)

    def test_existing_derived_reference_can_be_hosted_without_losing_provenance(self):
        derived=slice_reference(self.root,self.source(),start=0,end=1)
        value=migrate(config())
        path=self.root/'config.json'
        atomic_json(path,value)
        from videocreate import media_server
        with mock.patch.object(media_server,'status',return_value={'running':True}), \
             mock.patch.object(media_server,'settings',return_value={'public_base_url':'https://example.test','max_link_seconds':20000}), \
             mock.patch.object(media_server,'publish',return_value={'url':'https://example.test/x','expires_at':20000,'publication_id':'fixture'}), \
             mock.patch('videocreate.media_reference_commands.bind_url',return_value={}) as bind, redirect_stdout(io.StringIO()):
            command(['host',str(self.root),'--reference',derived['reference_file'],'--upstream','primary-sub2api','--config',str(path)])
        self.assertEqual(bind.call_args.args[1],derived['reference'])


if __name__=='__main__':
    unittest.main()
