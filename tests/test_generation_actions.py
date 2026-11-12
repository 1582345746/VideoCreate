"""Generation panel service uses real state/media with fixture-only upstreams."""
import base64
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
sys.path[:0] = [str(ROOT/'videocreate/src'), str(ROOT/'tests'), str(ROOT/'videocreate/scripts')]
from videocreate import generation_actions as actions, selection
from videocreate.config.management import migrate
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project, save_bundle
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state, save_state
from test_v3_config import config
from test_image_model_routing import PNG


class GenerationActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.TemporaryDirectory();cls.source = Path(cls.media.name)/'source.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-nostdin', '-v','error','-y','-f','lavfi','-i',
            'testsrc2=size=128x72:rate=24:duration=1', '-c:v','libx264','-pix_fmt','yuv420p',str(cls.source)],
            check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):cls.media.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name);self.root = self.parent/'project';self.path = self.parent/'config/config.json'
        self.config = migrate(config());atomic_json(self.path, self.config)
        save_bundle(self.root, create('scenic', seconds=10, title='Fixture generation'))
        self.calls, self.reads, self.downloads = [], [], []
        outer = self
        class Client:
            def __init__(self, binding):self.binding = binding;self.last_submission = {}
            def prepare(self, prompt, **kwargs):return {'remote_model':self.binding.remote_model,'prompt':prompt}
            def create(self, prompt, **kwargs):
                outer.calls.append((self.binding.id,prompt));return 'videoprep_fixture_'+str(len(outer.calls))
            def poll(self, task_id, **kwargs):
                outer.reads.append(task_id);return {'status':'completed','model':self.binding.remote_model}
            def download(self, task_id, payload, destination):
                outer.downloads.append(task_id);shutil.copyfile(outer.source,destination)
        self.patch = mock.patch('videocreate.runtime.jobs.client',side_effect=Client)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.network = mock.patch('urllib.request.urlopen',side_effect=AssertionError('No real network'))
        self.network.start();self.addCleanup(self.network.stop)
        self.arguments = {'job_ids':['job-001'], 'bindings':{'job-001':'grok-on-sub2api'}}

    def run_preview(self, **kwargs):
        arguments = {**self.arguments, **kwargs}
        preview = actions.preview(self.root, self.path, **arguments)
        return actions.execute(self.root, self.path, expected_token=preview['token'], **arguments)

    def test_preview_is_zero_create_and_does_not_reserve_or_edit_configuration(self):
        before = self.path.read_bytes()
        report = actions.preview(self.root,self.path,**self.arguments)
        self.assertEqual(report['new_requests'],1)
        self.assertEqual(report['jobs'][0]['remote_model'],self.config['bindings']['grok-on-sub2api']['remote_model'])
        self.assertNotIn('test-only-value',json.dumps(report))
        self.assertEqual(self.calls,[]);self.assertFalse((self.root/'state.json').exists())
        self.assertEqual(before,self.path.read_bytes())

    def test_create_once_then_recovery_keeps_saved_route_with_no_new_reservation(self):
        result = self.run_preview();self.assertTrue(result['ok']);self.assertEqual(result['new_recorded_attempts'],1)
        before = read_state(self.root);original = before['jobs']['job-001']['binding_snapshot']
        self.config['bindings']['grok-on-sub2api']['enabled']=False
        self.config['defaults']['video_model']='seedance-2.0-mini-720p';atomic_json(self.path,self.config)
        result=self.run_preview(mode='resume',bindings={},max_new_requests=0)
        self.assertTrue(result['ok']);self.assertEqual(len(self.calls),1)
        self.assertEqual(read_state(self.root)['ledger'],before['ledger'])
        self.assertEqual(read_state(self.root)['jobs']['job-001']['binding_snapshot'],original)

    def test_numbered_choice_returns_original_job_context_and_creates_nothing(self):
        with self.assertRaises(selection.SelectionRequired) as raised:
            actions.preview(self.root,self.path,job_ids=['job-001'])
        packet = raised.exception.payload
        self.assertEqual(packet['job_id'],'job-001');self.assertTrue(packet['choices'])
        choice=selection.choose(self.root,self.config,selection_id=packet['selection_id'],number=1,scope='once',store_root=self.path.parent)
        preview=actions.preview(self.root,self.path,job_ids=['job-001'],bindings={'job-001':choice['binding_id']})
        self.assertEqual(preview['jobs'][0]['binding'],packet['choices'][0]['id'])
        self.assertEqual(self.calls,[]);self.assertEqual(read_state(self.root)['ledger'],[])
        self.assertIsNone(selection.project_choice(self.root,'video'))

    def batch(self):
        self.root=self.parent/'batch'
        bundle=create('scenic',seconds=20,title='Dependency batch')
        bundle['generation-plan']['jobs'][1]['depends_on']=['job-001']
        for job in bundle['generation-plan']['jobs']:job['binding_id']='grok-on-sub2api'
        save_bundle(self.root,bundle)

    def test_dependencies_are_in_preview_limit_and_one_execution(self):
        self.batch()
        with self.assertRaisesRegex(ConfigError,'need 2 new requests'):
            actions.preview(self.root,self.path,job_ids=['job-002'])
        arguments={'job_ids':['job-002'],'max_new_requests':2}
        preview=actions.preview(self.root,self.path,**arguments)
        self.assertEqual(preview['ordered_jobs'],['job-001','job-002'])
        self.assertFalse(preview['jobs'][0]['explicit'])
        result=actions.execute(self.root,self.path,expected_token=preview['token'],**arguments)
        self.assertTrue(result['ok']);self.assertEqual(len(self.calls),2)
        self.assertEqual(len(read_state(self.root)['ledger']),2)

    def test_bad_later_job_and_budget_stop_before_any_create(self):
        self.batch()
        director=load_project(self.root)['director'];director['shots'][1]['actions'][0]['description']='x'*20000
        atomic_json(self.root/'director.json',director)
        with self.assertRaises(ConfigError):
            actions.preview(self.root,self.path,job_ids=['job-002'],max_new_requests=2)
        self.assertEqual(self.calls,[]);self.assertEqual(read_state(self.root)['ledger'],[])
        self.root=self.parent/'budget'
        save_bundle(self.root,create('scenic',seconds=10))
        self.config['budget']['max_video_requests']=1;atomic_json(self.path,self.config)
        save_state(self.root,{'schema_version':3,'jobs':{},'ledger':[{'attempt_id':'existing','kind':'video',
            'job_id':'older','estimated':0,'actual':0,'currency':'CNY','status':'completed'}]})
        with self.assertRaisesRegex(ConfigError,'budget is exhausted'):
            actions.preview(self.root,self.path,**self.arguments)
        self.assertEqual(self.calls,[])

    def test_saved_config_plan_and_task_changes_invalidate_preview(self):
        for target in ('configuration','plan','state'):
            with self.subTest(target=target):
                initial_config=self.path.read_bytes();initial_brief=(self.root/'brief.json').read_bytes()
                preview=actions.preview(self.root,self.path,**self.arguments)
                if target=='configuration':
                    value=copy.deepcopy(self.config);value['bindings']['grok-on-sub2api']['notes']='changed';atomic_json(self.path,value)
                elif target=='plan':
                    value=load_json(self.root/'brief.json');value['audience']='changed audience';atomic_json(self.root/'brief.json',value)
                else:
                    save_state(self.root,{'schema_version':3,'jobs':{},'ledger':[],'new_observation':'changed'})
                with self.assertRaisesRegex(ConfigError,'preview changed'):
                    actions.execute(self.root,self.path,expected_token=preview['token'],**self.arguments)
                self.path.write_bytes(initial_config);(self.root/'brief.json').write_bytes(initial_brief)
                if (self.root/'state.json').exists():(self.root/'state.json').unlink()
        self.assertEqual(self.calls,[])

    def test_unknown_and_new_tasks_cannot_use_recovery_only_execution(self):
        for record in ({},{'status':'submission_unknown','task_id':'maybe-original'}):
            save_state(self.root,{'schema_version':3,'jobs':{'job-001':record} if record else {},'ledger':[]})
            with self.assertRaises(ConfigError):
                actions.preview(self.root,self.path,job_ids=['job-001'],mode='resume',max_new_requests=0)
            with self.assertRaises(ConfigError):
                jobs.generate(self.root,self.config,store_root=self.path.parent,job_ids=['job-001'],allow_create=False)
        self.assertEqual(self.calls,[]);self.assertEqual(read_state(self.root)['ledger'],[])

    def test_recovery_rechecks_no_create_under_runtime_lock(self):
        self.run_preview()
        state=read_state(self.root);state['jobs']['job-001'].update(status='read_pending',artifact={});save_state(self.root,state)
        original_prepare=jobs._prepare_job
        def change_after_prepare(*args,**kwargs):
            result=original_prepare(*args,**kwargs)
            changed=read_state(self.root);changed['jobs']['job-001'].update(task_id='',status='failed');save_state(self.root,changed)
            return result
        with mock.patch.object(jobs,'_prepare_job',side_effect=change_after_prepare):
            with self.assertRaisesRegex(ConfigError,'recovery only permits'):
                jobs.generate(self.root,self.config,store_root=self.path.parent,job_ids=['job-001'],allow_create=False)
        self.assertEqual(len(self.calls),1);self.assertEqual(len(read_state(self.root)['ledger']),1)

    def test_content_retry_preserves_original_and_requires_selected_reason(self):
        self.run_preview();before=read_state(self.root)['jobs']['job-001']
        with self.assertRaises(ConfigError):self.run_preview(mode='content')
        result=self.run_preview(mode='content',reason='Observed fixture defect')
        self.assertTrue(result['ok']);self.assertEqual(len(self.calls),2)
        current=read_state(self.root)['jobs']['job-001']
        self.assertEqual(current['history'][0]['task_id'],before['task_id'])
        self.assertTrue((self.root/before['artifact']['path']).is_file())

    def test_replan_does_not_permit_changed_dependency_inputs(self):
        self.batch();self.run_preview(job_ids=['job-002'],bindings={},max_new_requests=2)
        value=load_project(self.root)['director'];value['shots'][0]['actions'][0]['description']+=' A changed action.'
        atomic_json(self.root/'director.json',value)
        with self.assertRaisesRegex(ConfigError,'job-001: inputs changed'):
            self.run_preview(job_ids=['job-002'],bindings={},mode='replan',reason='Only replace the selected insert')
        with self.assertRaisesRegex(ConfigError,'generation inputs changed'):
            jobs.generate(self.root,self.config,store_root=self.path.parent,job_ids=['job-002'],retry='replan',reason='Only selected insert')
        self.assertEqual(len(self.calls),2)

    def image_project(self):
        self.root=self.parent/'images'
        save_bundle(self.root,create('image-only',title='Fixture image',topic='A synthetic boat'))
        return {'job_ids':['image-001'],'bindings':{'image-001':'image-primary'}}

    def test_image_create_skip_and_reprocess_use_original_attempt(self):
        arguments=self.image_project()
        payload={'data':[{'b64_json':base64.b64encode(PNG).decode()}]}
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload',return_value=payload) as create_call:
            preview=actions.preview(self.root,self.path,**arguments)
            actions.execute(self.root,self.path,expected_token=preview['token'],**arguments)
            state=read_state(self.root);original=copy.deepcopy(state)
            preview=actions.preview(self.root,self.path,job_ids=['image-001'],mode='resume')
            self.assertEqual(preview['jobs'][0]['action'],'skip')
            actions.execute(self.root,self.path,expected_token=preview['token'],job_ids=['image-001'],mode='resume')
            current=state['jobs']['image-001'];current['status']='output_invalid'
            response=self.root/'jobs/image-001/saved-response.json';atomic_json(response,payload)
            current['provider_response']=response.relative_to(self.root).as_posix();save_state(self.root,state)
            preview=actions.preview(self.root,self.path,job_ids=['image-001'],mode='resume')
            self.assertEqual(preview['jobs'][0]['action'],'reprocess')
            actions.execute(self.root,self.path,expected_token=preview['token'],job_ids=['image-001'],mode='resume')
            self.assertEqual(create_call.call_count,1)
            self.assertEqual(read_state(self.root)['jobs']['image-001']['attempt_id'],original['jobs']['image-001']['attempt_id'])
            self.assertEqual(len(read_state(self.root)['ledger']),1)

    def test_image_bad_later_request_is_blocked_before_batch_dispatch(self):
        arguments=self.image_project();generation=load_project(self.root)['generation-plan']
        second=copy.deepcopy(generation['image_jobs'][0]);second.update(id='image-002',size='999x999')
        generation['image_jobs'].append(second);atomic_json(self.root/'generation-plan.json',generation)
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send:
            with self.assertRaises(ConfigError):
                actions.preview(self.root,self.path,job_ids=['image-001','image-002'],max_new_requests=2,
                    bindings={jid:'image-primary' for jid in ('image-001','image-002')})
            send.assert_not_called()
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_cli_prepare_and_execute_share_service_and_resume_never_creates(self):
        from videocreate.commands import jobs_command
        arguments=['--job','job-001','--config',str(self.path),'--binding','grok-on-sub2api']
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(jobs_command(['prepare',str(self.root),*arguments]),0)
        preview=json.loads(output.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(jobs_command(['execute',str(self.root),*arguments,'--token',preview['token']]),0)
            self.assertEqual(jobs_command(['resume',str(self.root),'--job','job-001','--config',str(self.path)]),0)
        self.assertEqual(len(self.calls),1)


if __name__ == '__main__':unittest.main()
