import copy
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate import media_references as refs
from videocreate.adapters.xingapi_references import XingAPIReferenceVideoClient, LocalRequestError
from videocreate.catalog.bindings import configured_binding, validate_request
from videocreate.config.management import migrate
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import compile_job, save_bundle, validate_plan
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state
from videocreate.selection import candidates


def media_limits():
    limits = {'maximum_total_count': 50, 'maximum_total_bytes': 10000000,
        'minimum_url_validity_seconds': 60, 'audio_reference_with_generated_audio': False,
        'allowed_combinations': [['image'], ['video'], ['audio'], ['image', 'video'],
                                 ['image', 'audio'], ['video', 'audio'], ['image', 'video', 'audio']]}
    for kind, count, mime, roles in [('image',30,'image/png',['opening-frame','identity','prop','scene','style']),
            ('video',10,'video/mp4',['motion','scene','style']), ('audio',10,'audio/wav',['sound'])]:
        limits[kind] = {'maximum_count': count, 'maximum_bytes':1000000, 'maximum_total_bytes':10000000,
                        'mime_types':[mime], 'roles':roles}
        if kind != 'image':
            limits[kind].update(maximum_duration_seconds=30, maximum_total_duration_seconds=60)
    return limits


class TypedMediaGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.temp.name)
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=4:d=1',
            '-c:v','libx264','-pix_fmt','yuv420p',str(cls.fixture/'video.mp4')],check=True,capture_output=True)
        subprocess.run(['ffmpeg','-v','error','-i',str(cls.fixture/'video.mp4'),'-frames:v','1',
            str(cls.fixture/'image.png')],check=True,capture_output=True)
        with wave.open(str(cls.fixture/'audio.wav'),'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
            stream.writeframes(b'\x10\x20'*16000)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = smart_car()
        for shot in self.bundle['director']['shots']:
            shot['audio'] = {'mode':'mute'}
        save_bundle(self.root,self.bundle)
        self.config = migrate(config())
        self.bid = 'grok-on-sub2api'
        binding = self.config['bindings'][self.bid]
        binding.update(adapter='xingapi-video-v2',remote_model='seedance2.5-V',
            operations=['text-to-video','image-to-video','reference-to-video'],
            capability_overrides={'duration':{'minimum':1,'maximum':30,'step':1},
                'resolutions':['720p'], 'aspect_ratios':['16:9','9:16'],
                'audio_control':'model-default','max_prompt_bytes':15000,
                'media_reference_limits':media_limits()})
        self.config['budget']['max_video_requests'] = 30
        self.references = []
        for kind, suffix, role in [('image','png','identity'),('video','mp4','motion'),('audio','wav','sound')]:
            self.references.append(refs.register(self.root,self.fixture/(kind+'.'+suffix),kind=kind,role=role))
        self.job = self.bundle['generation-plan']['jobs'][0]
        self.job.update(operation='reference-to-video', references=copy.deepcopy(self.references),binding_id=self.bid)
        atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
        self.urls={}
        for index, reference in enumerate(self.references):
            media=refs.prepare_references(self.root,[reference])[0]
            url='https://media.example.test/m/'+str(index)*43+'/reference'+Path(reference['path']).suffix+'?signature=private-signature'
            variable='VC_TYPED_TEST_URL_'+str(index)
            patch=mock.patch.dict(os.environ,{variable:url})
            patch.start(); self.addCleanup(patch.stop)
            self.urls[reference['sha256']]=url
            with mock.patch.object(refs,'verify_url',return_value={'sha256':media['sha256'],'bytes':media['bytes'],'verified_at':time.time()}):
                refs.bind_url(self.root,reference,upstream_id=binding['upstream'],
                    account_id=self.config['upstreams'][binding['upstream']]['account_id'],
                    store_root=self.root,url_env=variable,expires_at=time.time()+10000)
        def verified(url, media, **kwargs):
            return {'sha256':media['sha256'],'bytes':media['bytes'],'verified_at':time.time()}
        self.verify=mock.patch.object(refs,'verify_url',side_effect=verified).start()
        self.addCleanup(mock.patch.stopall)

    def run_job(self, **kwargs):
        return jobs.generate(self.root,self.config,store_root=self.root,job_ids=['job-001'],poll_timeout=1,**kwargs)

    def transport_refs(self):
        b=self.config['bindings'][self.bid]
        return refs.resolve_transports(self.root,self.references,store_root=self.root,
            upstream_id=b['upstream'],account_id=self.config['upstreams'][b['upstream']]['account_id'],minimum_validity=60)

    def mock_generation(self, *, poll=None):
        import media_client
        send=mock.patch.object(media_client,'request_json',return_value={'id':'videoprep_fixture','status':'queued',
            'echo':{'images':list(self.urls.values())}}).start()
        mock.patch.object(XingAPIReferenceVideoClient,'poll',return_value=poll or {'status':'completed'}).start()
        mock.patch.object(XingAPIReferenceVideoClient,'download',
            side_effect=lambda task,payload,path:shutil.copyfile(self.fixture/'video.mp4',path)).start()
        return send

    def test_mixed_arrays_exact_model_order_and_redacted_persistence(self):
        send=self.mock_generation()
        self.assertTrue(self.run_job()['ok'])
        send.assert_called_once()
        body=send.call_args.kwargs['value']
        self.assertEqual(body['model'],'seedance2.5-V')
        for kind,field in [('image','images'),('video','videos'),('audio','audios')]:
            self.assertEqual(body[field],[self.urls[r['sha256']] for r in self.references if r['kind']==kind])
        self.assertNotIn('generate_audio',body)
        self.assertNotIn('seconds',body); self.assertNotIn('aspect_ratio',body)
        for path in [self.root/'state.json',*self.root.glob('jobs/*/*/request.json')]:
            text=path.read_text('utf-8')
            self.assertNotIn('private-signature',text)
            self.assertNotIn('https://media.example.test',text)
            self.assertNotIn('/m/'+('0'*43),text)
        state=read_state(self.root)
        self.assertEqual(state['jobs']['job-001']['binding_snapshot']['adapter_version'],2)
        self.assertEqual(len(state['ledger']),1)

    def test_input_order_and_roles_are_preserved_in_prompt_and_arrays(self):
        first={**self.references[0],'role':'style'}
        second={**self.references[0],'role':'identity'}
        self.job['references']=[self.references[1],first,self.references[2],second]
        atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
        compilation=compile_job(self.bundle,self.job,max_bytes=15000,root=self.root)
        self.assertEqual([(r['field'],r['index'],r['role']) for r in compilation['reference_map']],
            [('videos',1,'motion'),('images',1,'style'),('audios',1,'sound'),('images',2,'identity')])
        send=self.mock_generation()
        self.run_job()
        self.assertEqual(send.call_args.kwargs['value']['images'],[self.urls[first['sha256']]]*2)

    def test_invalid_later_job_blocks_entire_batch_without_reserving(self):
        later=self.bundle['generation-plan']['jobs'][1]
        later.update(operation='reference-to-video',binding_id=self.bid,references=self.references*11)
        atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
        send=self.mock_generation()
        for maximum in (1,3):
            self.config['execution']['max_concurrent_video_tasks']=maximum
            with self.assertRaises(ConfigError):
                jobs.generate(self.root,self.config,store_root=self.root,job_ids=['job-001',later['id']])
            self.assertFalse(read_state(self.root)['ledger'])
        send.assert_not_called()

    def test_expired_new_link_fails_before_create_and_budget(self):
        path=self.root/'references/transports.json'
        registry=load_json(path)
        for record in registry['links'].values(): record['expires_at']=time.time()-1
        atomic_json(path,registry)
        send=self.mock_generation()
        with self.assertRaisesRegex(ConfigError,'expires'):
            self.run_job()
        send.assert_not_called(); self.assertFalse(read_state(self.root)['ledger'])

    def test_read_recovery_needs_no_live_links_and_keeps_original_adapter(self):
        send=self.mock_generation()
        with mock.patch.object(XingAPIReferenceVideoClient,'poll',side_effect=TimeoutError('poll timeout')):
            with self.assertRaises(ConfigError): self.run_job()
        self.assertEqual(read_state(self.root)['jobs']['job-001']['task_id'],'videoprep_fixture')
        registry=load_json(self.root/'references/transports.json')
        for record in registry['links'].values(): record['expires_at']=time.time()-1
        atomic_json(self.root/'references/transports.json',registry)
        self.config['bindings'][self.bid].update(adapter='xingapi-video-v1',enabled=False)
        with mock.patch.object(refs,'resolve_transports',side_effect=AssertionError('Recovery fetched inputs')), \
                mock.patch.object(XingAPIReferenceVideoClient,'poll',return_value={'status':'completed'}) as poll:
            self.assertTrue(self.run_job(retry='network',reason='Resume original task')['ok'])
        poll.assert_called_once()
        send.assert_called_once()
        self.assertEqual(read_state(self.root)['jobs']['job-001']['binding_snapshot']['adapter'],'xingapi-video-v2')

    def test_unknown_submission_is_held_and_error_has_no_transport_url(self):
        send=self.mock_generation()
        send.side_effect=TimeoutError(next(iter(self.urls.values())))
        with self.assertRaises(ConfigError): self.run_job()
        with self.assertRaisesRegex(ConfigError,'submission unknown'):
            self.run_job(retry='network',reason='Read recovery')
        send.assert_called_once()
        self.assertNotIn('private-signature',(self.root/'state.json').read_text('utf-8'))
        self.assertEqual(read_state(self.root)['jobs']['job-001']['status'],'submission_unknown')

    def test_media_boundaries_combinations_and_audio_switch_have_zero_creates(self):
        from videocreate.catalog.bindings import validate_request
        b=configured_binding(self.config,self.bid)
        media=self.transport_refs()
        request={'operation':'reference-to-video','prompt':'Fixture','seconds':5,'resolution':'720p',
                 'aspect_ratio':'16:9','media_references':media,'generate_audio':False}
        self.assertTrue(validate_request(b,request)['ok'])
        for mutate in [lambda v:v.update(maximum_total_count=2), lambda v:v.update(maximum_total_bytes=1),
                lambda v:v['video'].update(maximum_duration_seconds=.1),
                lambda v:v['audio'].update(maximum_total_duration_seconds=.1),
                lambda v:v['image'].update(maximum_width=1),
                lambda v:v.update(allowed_combinations=[['image'],['audio'],['video']])]:
            bound=copy.deepcopy(b)
            mutate(bound.capabilities['media_reference_limits'])
            self.assertFalse(validate_request(bound,request)['ok'])
        self.assertFalse(validate_request(b,{**request,'generate_audio':True})['ok'])

    def test_unverified_url_is_rejected_locally_without_post(self):
        import media_client
        b=configured_binding(self.config,self.bid)
        media=self.transport_refs()
        media[0].pop('verification')
        with mock.patch.object(media_client,'request_json') as send:
            with self.assertRaises(LocalRequestError):
                jobs.client(b).create('Fixture',seconds=5,size='auto',resolution='720p',aspect_ratio='16:9',
                                     operation='reference-to-video',media_references=media)
            send.assert_not_called()

    def test_local_failure_after_reservation_is_proven_not_submitted(self):
        send=self.mock_generation()
        with mock.patch.object(XingAPIReferenceVideoClient,'create',side_effect=LocalRequestError('Expired before POST')):
            with self.assertRaises(ConfigError): self.run_job()
        send.assert_not_called()
        state=read_state(self.root)
        self.assertFalse(state['jobs']['job-001']['submission_sent'])
        self.assertEqual(state['ledger'][0]['status'],'not-submitted')
        self.assertEqual(state['ledger'][0]['actual'],0)
        from videocreate.runtime.budget import summary
        self.assertEqual(summary(state)['requests'],0)

    def test_selected_candidates_exclude_legacy_and_incompatible_media_contract(self):
        b=self.config['bindings'][self.bid]
        request=refs.selection_request(self.root,self.bundle,self.job)
        rows=candidates(self.config,kind='video',store_root=self.root,operation='reference-to-video',request=request)
        self.assertEqual([r['id'] for r in rows if r['eligible']],[self.bid])
        b['capability_overrides']['media_reference_limits']['allowed_combinations']=[['image']]
        rows=candidates(self.config,kind='video',store_root=self.root,operation='reference-to-video',request=request)
        self.assertFalse(any(r['eligible'] for r in rows))

    def test_unknown_kind_or_role_never_enters_legacy_image_fields(self):
        send=self.mock_generation()
        for change in [{'kind':'image','role':'sound'},{'kind':'video','role':'opening-frame'}]:
            self.job['references'][0].update(change)
            atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
            with self.assertRaises(ConfigError): self.run_job()
        send.assert_not_called()

    def test_attach_is_local_idempotent_and_preserves_plan_backup(self):
        from videocreate.media_reference_commands import command
        job=self.bundle['generation-plan']['jobs'][1]
        path=self.root/'registered.reference.json'
        atomic_json(path,self.references[1])
        with redirect_stdout(io.StringIO()):
            command(['attach',str(self.root),'--reference',str(path),'--job',job['id']])
            command(['attach',str(self.root),'--reference',str(path),'--job',job['id']])
        result=load_json(self.root/'generation-plan.json')['jobs'][1]
        self.assertEqual(result['operation'],'reference-to-video')
        self.assertEqual(result['references'],[self.references[1]])
        self.assertEqual(len(list((self.root/'references/plan-history').glob('*.json'))),1)
        self.assertFalse(read_state(self.root)['ledger'])

    def test_limits_are_explicit_and_cannot_be_enabled_on_legacy_adapter(self):
        self.assertEqual(validate_config(self.config),[])
        b=self.config['bindings'][self.bid]
        b['capability_overrides']['media_reference_limits']['video'].pop('maximum_duration_seconds')
        self.assertTrue(validate_config(self.config))
        b['capability_overrides']['media_reference_limits']=media_limits()
        b['adapter']='xingapi-video-v1'
        self.assertTrue(validate_config(self.config))


if __name__=='__main__':
    unittest.main()
