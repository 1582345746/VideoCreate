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
    adapter = "xingapi-video-v2"
    legacy_adapter = "xingapi-video-v1"
    client_class = XingAPIReferenceVideoClient
    remote_model = "seedance2.5-V"
    duration_field = "duration"
    ratio_field = "ratio"
    create_endpoint = "/v1/videos/generations"

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
        binding.update(adapter=self.adapter,remote_model=self.remote_model,
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

    def attach_event_map(self):
        spec = {'schema_version':1, 'target_job':self.job['id'], 'tolerance_seconds':1/24,
                'source':{k:self.references[1][k] for k in ('path','sha256')},
                'events':[{'id':'start','source':[0,1],'target':[0,1],'reason':'Opening source action'}]}
        path = self.root/'events.json'
        atomic_json(path,spec)
        self.job['event_map'] = {'path':path.name,'sha256':refs.digest(path)}
        atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
        return path

    def test_event_map_preview_and_original_request_survive_later_local_map_edits(self):
        from videocreate.commands import plan_command
        original = jobs.current_inputs(self.root,self.bundle,self.job,{})
        path = self.attach_event_map()
        self.assertEqual(jobs.current_inputs(self.root,self.bundle,self.job,{}), original)
        cfg = self.root/'test-config.json'
        atomic_json(cfg,self.config)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plan_command(['compile',str(self.root),'--config',str(cfg),'--job',self.job['id']]),0)
        preview = load_json(self.root/'jobs/job-001/compiled.preview.json')['request_preview']
        self.assertEqual(preview['local_event_timing']['events'][0]['occurrences'][0]['timeline'],[0,0.75])
        send = self.mock_generation()
        with mock.patch.object(self.client_class,'poll',side_effect=TimeoutError('poll timeout')):
            with self.assertRaises(ConfigError):
                self.run_job()
        saved = read_state(self.root)['jobs'][self.job['id']]['compilation']['reference_inputs']['local_event_timing']
        path.write_bytes(b'local edit awaiting validation')
        self.assertFalse(validate_plan(self.bundle,self.root)['ok'])
        self.assertTrue(self.run_job(retry='network',reason='Resume original accepted task')['ok'])
        send.assert_called_once()
        current = read_state(self.root)['jobs'][self.job['id']]
        self.assertEqual(current['compilation']['reference_inputs']['local_event_timing'],saved)

    def test_invalid_event_map_stops_new_create_before_budget_reservation(self):
        path = self.attach_event_map()
        spec = load_json(path)
        spec['target_job'] = 'another-job'
        atomic_json(path,spec)
        self.job['event_map']['sha256'] = refs.digest(path)
        atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
        send = self.mock_generation()
        with self.assertRaisesRegex(ConfigError,'event map must target'):
            self.run_job()
        send.assert_not_called()
        self.assertFalse(read_state(self.root)['ledger'])

    def test_required_source_opening_cannot_be_silently_trimmed_from_a_new_request(self):
        from videocreate import references as source_references
        video = self.references[1]
        study = source_references.analyze(self.root/video['path'],self.root/'source-study',max_frames=3)
        observations = {'reviewer_id':'','observations':[],'participants':[],
                        'events':[{'id':'opening','category':'hook','start':0,'end':1,'notes':'First source beat',
                                   'participants':[],'status':'unverified','must_preserve':True}]}
        profile = Path(source_references.profile(Path(study['report']),observations)['profile'])
        spec = {'schema_version':2, 'target_job':self.job['id'],'tolerance_seconds':1/24,
                'source':{k:video[k] for k in ('path','sha256')},
                'source_profile':{'path':profile.relative_to(self.root).as_posix(),'sha256':refs.digest(profile)},
                'events':[{'id':'start','source_event_id':'opening','target':[0,1],'reason':'Keep the opening beat'}]}
        path = self.root/'events.json'
        atomic_json(path,spec)
        self.job['event_map'] = {'path':path.name,'sha256':refs.digest(path)}
        atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
        send = self.mock_generation()
        with self.assertRaisesRegex(ConfigError,'Required source events.*opening'):
            self.run_job()
        send.assert_not_called()
        self.assertFalse(read_state(self.root)['ledger'])
        spec['source_event_changes'] = {'opening':'Omit the first quarter-second preparation as planned in the edit.'}
        atomic_json(path,spec)
        self.job['event_map']['sha256'] = refs.digest(path)
        atomic_json(self.root/'generation-plan.json',self.bundle['generation-plan'])
        self.assertTrue(self.run_job()['ok'])
        send.assert_called_once()

    def test_offline_compile_with_imported_card_and_mixed_references(self):
        from videocreate import asset_library
        from videocreate.commands import plan_command
        from videocreate.media_reference_commands import command as media_command
        from videocreate.planning.project import load_project
        source = self.bundle['director']['assets'][0]
        source['references'] = [self.references[0]['path']]
        atomic_json(self.root / 'director.json', self.bundle['director'])
        version = asset_library.publish(self.root, self.root / 'store', source['id'], 'hero')['version']
        asset_library.import_asset(self.root, self.root / 'store', 'hero', version, 'costume')
        bundle = load_project(self.root)
        shot = next(s for s in bundle['director']['shots'] if s['id'] in self.job['shot_ids'])
        shot['asset_ids'].append('costume')
        atomic_json(self.root / 'director.json', bundle['director'])
        self.job['references'] = self.references[1:]
        atomic_json(self.root / 'generation-plan.json', self.bundle['generation-plan'])
        cfg = self.root / 'test-config.json'
        atomic_json(cfg, self.config)
        with redirect_stdout(io.StringIO()), mock.patch.object(refs, 'resolve_transports', side_effect=AssertionError):
            attach = ['attach', str(self.root), '--asset-id', 'costume', '--role', 'identity', '--job', self.job['id']]
            self.assertEqual(media_command(attach), 0)
            self.assertEqual(media_command(attach), 0)
            self.assertEqual(plan_command(['compile', str(self.root), '--config', str(cfg), '--job', self.job['id']]), 0)
        preview = load_json(self.root / 'jobs' / self.job['id'] / 'compiled.preview.json')['request_preview']
        self.assertEqual(preview['reference_counts'], {'image': 1, 'video': 1, 'audio': 1})
        self.assertEqual([item['kind'] for item in preview['references']], ['video', 'audio', 'image'])
        image = preview['references'][-1]
        self.assertEqual(image['library_revision'], {'library_id': 'hero', 'version': version})
        self.assertIn({'shot_id': shot['id'], 'asset_id': 'costume'}, image['shot_assets'])
        self.assertEqual(image['sha256'], self.references[0]['sha256'])
        self.assertFalse((self.root / 'state.json').exists())

    def test_cast_sheet_cli_preserves_order_and_individual_source_evidence(self):
        from PIL import Image
        from videocreate.asset_library import import_asset, publish
        from videocreate.media_reference_commands import command
        from videocreate.planning.request_preview import describe_inputs
        from videocreate.planning.project import load_project
        card = self.bundle['director']['assets'][0]
        sources = []
        for name, shade in [('red', 'red'), ('blue', 'blue')]:
            path = self.root / (name + '.png')
            Image.new('RGB', (8, 12), shade).save(path)
            card['references'] = [path.name]
            atomic_json(self.root / 'director.json', self.bundle['director'])
            version = publish(self.root, self.root/'store', card['id'], name)['version']
            result = import_asset(self.root, self.root/'store', name, version, name)
            self.bundle = load_project(self.root)
            card = self.bundle['director']['assets'][0]
            sources.append(self.root / result['asset']['references'][0])
        spec = self.root / 'layout.json'
        atomic_json(spec, {'columns': 2, 'cells': [{'asset_id':'red'}, {'asset_id':'blue','crop_xywh':[0,2,8,8]}]})
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(command(['cast-sheet', str(self.root), '--spec', str(spec)]), 0)
        sheet = json.loads(buffer.getvalue())['reference']
        ref = refs.prepare_references(self.root, [sheet])[0]
        with Image.open(self.root / sheet['path']) as image:
            self.assertEqual(image.getpixel((192,320)), (255,0,0))
            self.assertEqual(image.getpixel((576,320)), (0,0,255))
        job = self.bundle['generation-plan']['jobs'][0]
        job['references'] = [sheet]
        shot = next(s for s in self.bundle['director']['shots'] if s['id'] in job['shot_ids'])
        shot['actors'] = ['blue', 'red']
        self.bundle['project']['prompt_semantics'] = 3
        compiled = compile_job(self.bundle, job, max_bytes=15000, root=self.root)
        self.assertIn('Cast (image.row.column): 1.1.2 1.1.1', compiled['prompt'])
        preview = describe_inputs(self.root, self.bundle, job, {'media_references':[ref], 'generate_audio':False})
        cells = preview['references'][0]['cast_cells']
        self.assertEqual([(c['column'],c['library_revision']['library_id'],c['shot_ids'])
                          for c in cells], [(1,'red',[shot['id']]),(2,'blue',[shot['id']])])
        self.assertFalse((self.root/'state.json').exists())
        with self.assertRaisesRegex(ConfigError, 'crop must fit'):
            atomic_json(spec, {'columns':1,'cells':[{'asset_id':'blue','crop_xywh':[0,0,9,12]}]})
            command(['cast-sheet', str(self.root), '--spec', str(spec)])
        sources[1].write_bytes(b'changed')
        with self.assertRaisesRegex(ConfigError, 'source changed'):
            refs.prepare_references(self.root, [sheet])

    def test_png_conversion_keeps_webp_source_bound_for_runtime_preflight(self):
        from PIL import Image
        from videocreate import asset_library
        from videocreate.media_reference_commands import command
        from videocreate.planning.project import load_project
        from videocreate.planning.request_preview import describe_inputs
        webp = self.root / 'cast.webp'
        Image.new('RGBA', (31, 13), (9, 20, 213, 130)).save(webp, lossless=True)
        source = self.bundle['director']['assets'][0]
        source['references'] = ['cast.webp']
        atomic_json(self.root / 'director.json', self.bundle['director'])
        version = asset_library.publish(self.root, self.root / 'store', source['id'], 'cast')['version']
        imported = asset_library.import_asset(self.root, self.root / 'store', 'cast', version, 'look')
        with redirect_stdout(io.StringIO()):
            command(['attach', str(self.root), '--job', self.job['id'], '--asset-id', 'look', '--role', 'identity', '--as-png'])
        bundle = load_project(self.root)
        job = bundle['generation-plan']['jobs'][0]
        inputs = refs.selection_request(self.root, bundle, job)
        self.assertEqual(inputs['media_references'][-1]['mime_type'], 'image/png')
        item = describe_inputs(self.root, bundle, job, inputs)['references'][-1]
        self.assertEqual(item['source_sha256'], refs.digest(webp))
        self.assertEqual(item['library_revision']['version'], version)
        self.assertNotEqual(item['sha256'], item['source_sha256'])
        (self.root / imported['asset']['references'][0]).write_bytes(b'changed')
        with self.assertRaisesRegex(ConfigError, 'Original image changed'):
            refs.selection_request(self.root, bundle, job)

    def transport_refs(self):
        b=self.config['bindings'][self.bid]
        return refs.resolve_transports(self.root,self.references,store_root=self.root,
            upstream_id=b['upstream'],account_id=self.config['upstreams'][b['upstream']]['account_id'],minimum_validity=60)

    def mock_generation(self, *, poll=None):
        import media_client
        send=mock.patch.object(media_client,'request_json',return_value={'id':'videoprep_fixture','status':'queued',
            'echo':{'images':list(self.urls.values())}}).start()
        mock.patch.object(self.client_class,'poll',return_value=poll or {'status':'completed'}).start()
        mock.patch.object(self.client_class,'download',
            side_effect=lambda task,payload,path:shutil.copyfile(self.fixture/'video.mp4',path)).start()
        return send

    def test_mixed_arrays_exact_model_order_and_redacted_persistence(self):
        send=self.mock_generation()
        self.assertTrue(self.run_job()['ok'])
        send.assert_called_once()
        body=send.call_args.kwargs['value']
        self.assertEqual(body['model'],self.remote_model)
        self.assertTrue(send.call_args.args[1].endswith(self.create_endpoint))
        for kind,field in [('image','images'),('video','videos'),('audio','audios')]:
            self.assertEqual(body[field],[self.urls[r['sha256']] for r in self.references if r['kind']==kind])
        self.assertNotIn('generate_audio',body)
        self.assertEqual(body[self.duration_field],self.job['seconds'])
        self.assertEqual(body[self.ratio_field],self.bundle['brief']['aspect_ratio'])
        self.assertNotIn('seconds' if self.duration_field == 'duration' else 'duration',body)
        self.assertNotIn('aspect_ratio' if self.ratio_field == 'ratio' else 'ratio',body)
        for path in [self.root/'state.json',*self.root.glob('jobs/*/*/request.json')]:
            text=path.read_text('utf-8')
            self.assertNotIn('private-signature',text)
            self.assertNotIn('https://media.example.test',text)
            self.assertNotIn('/m/'+('0'*43),text)
        state=read_state(self.root)
        self.assertEqual(state['jobs']['job-001']['binding_snapshot']['adapter_version'],2)
        self.assertEqual(len(state['ledger']),1)
        persisted = state['jobs']['job-001']['compilation']['reference_inputs']
        self.assertEqual([r['sha256'] for r in persisted['references']], [r['sha256'] for r in self.references])
        self.assertEqual(persisted['verification'], 'planned-inputs-only')

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
        with mock.patch.object(self.client_class,'poll',side_effect=TimeoutError('poll timeout')):
            with self.assertRaises(ConfigError): self.run_job()
        self.assertEqual(read_state(self.root)['jobs']['job-001']['task_id'],'videoprep_fixture')
        registry=load_json(self.root/'references/transports.json')
        for record in registry['links'].values(): record['expires_at']=time.time()-1
        atomic_json(self.root/'references/transports.json',registry)
        self.config['bindings'][self.bid].update(adapter=self.legacy_adapter,enabled=False)
        with mock.patch.object(refs,'resolve_transports',side_effect=AssertionError('Recovery fetched inputs')), \
                mock.patch.object(self.client_class,'poll',return_value={'status':'completed'}) as poll:
            self.assertTrue(self.run_job(retry='network',reason='Resume original task')['ok'])
        poll.assert_called_once()
        send.assert_called_once()
        self.assertEqual(read_state(self.root)['jobs']['job-001']['binding_snapshot']['adapter'],self.adapter)

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
        with mock.patch.object(self.client_class,'create',side_effect=LocalRequestError('Expired before POST')):
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
        b['adapter']=self.legacy_adapter
        self.assertTrue(validate_config(self.config))


if __name__=='__main__':
    unittest.main()
