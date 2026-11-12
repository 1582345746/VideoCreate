import copy
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.config.management import migrate
from videocreate.config.schema import validate_config
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.runtime import jobs, quotas
from videocreate.runtime.state import read_state, save_state, state_lock
import vc_common


class QuotaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = migrate(config())
        self.uid = 'primary-sub2api'
        self.other = 'backup-newapi'
        self.config['upstreams'][self.uid]['quotas'] = {
            'max_remote_inflight': 1, 'create_rpm': 2, 'poll_rpm': 1, 'download_rpm': 1}
        self.project = self.root / 'project'
        self.project.mkdir()
        save_state(self.project, {'schema_version': 3, 'jobs': {}, 'ledger': []})
        quotas.watch(self.root, self.project)

    def record(self, status='queued', **extra):
        record = {'attempt_id': 'attempt-original', 'status': status, 'task_id': 'videoprep_original',
                  'binding_snapshot': {'upstream_id': self.uid, 'identity': {'account_id': self.uid}}, **extra}
        state = read_state(self.project); state['jobs']['first'] = record
        save_state(self.project, state)
        return record

    def test_schema_limits_are_optional_positive_integers(self):
        self.assertEqual(validate_config(self.config), [])
        for value in (0, -1, 1.5, True, None):
            changed = copy.deepcopy(self.config)
            changed['upstreams'][self.uid]['quotas']['create_rpm'] = value
            self.assertTrue(validate_config(changed))
        self.config['upstreams'][self.uid]['quotas'] = {}
        self.assertEqual(validate_config(self.config), [])

    def test_account_and_group_aliases_are_transitive_and_strictest(self):
        third = 'image-service'
        self.config['upstreams'][self.other]['account_id'] = self.uid
        self.config['upstreams'][self.other]['capacity_group'] = 'shared-capacity'
        self.config['upstreams'][third]['capacity_group'] = 'shared-capacity'
        self.config['upstreams'][third]['quotas'] = {'create_rpm': 1, 'poll_rpm': 9}
        self.config['upstreams'][third]['archived'] = True
        ids, limits = quotas.policy(self.config, third)
        self.assertEqual(set(ids), {self.uid, self.other, third})
        self.assertEqual(limits['poll_rpm'], 1)
        self.assertEqual(limits['create_rpm'], 1)
        self.record()
        with self.assertRaisesRegex(quotas.QuotaExceeded, 'max_remote_inflight'):
            with quotas.admission(self.root, self.config, third): self.fail('alias bypass')

    def test_blank_account_identity_does_not_merge_unrelated_upstreams(self):
        for item in self.config['upstreams'].values(): item['account_id']=''
        self.assertEqual(quotas.members(self.config,self.uid),[self.uid])
        self.assertEqual(quotas.members(self.config,self.other),[self.other])

    def test_unknown_and_locally_stopped_tasks_never_expire_but_remote_completion_releases(self):
        for status in ('queued', 'running', 'submitting', 'submission_unknown', 'read_pending', 'unknown'):
            self.record(status)
            with mock.patch('videocreate.runtime.quotas.time.time', return_value=10**11):
                self.assertEqual(quotas.status(self.root, self.config, self.uid)['remote_inflight'], 1)
        for status in ('completed', 'failed', 'rejected', 'cancelled', 'expired', 'output_invalid'):
            self.record(status)
            self.assertEqual(quotas.status(self.root, self.config, self.uid)['remote_inflight'], 0)
        self.record('read_pending', provider_completed_at=1)
        self.assertEqual(quotas.status(self.root, self.config, self.uid)['remote_inflight'], 0)
        self.record('submission_unknown', submission_sent=False)
        self.assertEqual(quotas.status(self.root, self.config, self.uid)['remote_inflight'], 0)

    def test_missing_or_corrupt_project_keeps_observed_hold(self):
        self.record(); quotas.status(self.root, self.config, self.uid)
        for data in ('{broken', None):
            path = self.project / 'state.json'
            if data is None: path.unlink()
            else: path.write_text(data, encoding='utf-8')
            result = quotas.status(self.root, self.config, self.uid)
            self.assertEqual(result['remote_inflight'], 1)
            self.assertFalse(result['active'][0]['source_available'])
            self.assertEqual(result['unavailable_projects'], [str(self.project)])
        self.record('failed')
        self.assertEqual(quotas.status(self.root, self.config, self.uid)['remote_inflight'], 0)

    def test_prior_indexed_projects_count_without_running_them_again(self):
        old = self.root / 'old'; old.mkdir()
        save_state(old, {'schema_version':3, 'jobs':{'old':self.record()}, 'ledger':[]})
        self.record('completed')
        atomic_json(self.root / 'runtime/projects.json', {'schema_version':1, 'paths':[str(old)]})
        result = quotas.status(self.root, self.config, self.uid)
        self.assertEqual(result['remote_inflight'], 1)
        self.assertEqual(result['active'][0]['project'], str(old))

    def test_windows_are_shared_persistent_and_separate_and_clock_rollback_is_conservative(self):
        with mock.patch('videocreate.runtime.quotas.time.time', return_value=100):
            quotas.request(self.root, self.config, self.uid, 'poll')
            quotas.request(self.root, self.config, self.uid, 'download')
            with quotas.admission(self.root, self.config, self.uid): pass
            with quotas.admission(self.root, self.config, self.uid): pass
        with mock.patch('videocreate.runtime.quotas.time.time', return_value=99):
            with self.assertRaises(quotas.QuotaExceeded) as caught:
                quotas.request(self.root, self.config, self.uid, 'poll')
            self.assertEqual(caught.exception.retry_after_seconds, 61)
            with self.assertRaises(quotas.QuotaExceeded):
                with quotas.admission(self.root, self.config, self.uid): self.fail('RPM bypass')
        with mock.patch('videocreate.runtime.quotas.time.time', return_value=160):
            quotas.request(self.root, self.config, self.uid, 'poll')
        self.assertEqual(quotas.status(self.root, self.config, self.other)['remote_inflight'], 0)

    def test_second_process_cannot_reset_persisted_window(self):
        quotas.request(self.root, self.config, self.uid, 'poll')
        conf = self.root / 'config.json'; atomic_json(conf, self.config)
        repo = Path(__file__).resolve().parents[1]
        code = ('import sys; from pathlib import Path; '
                'sys.path.insert(0,sys.argv[1]); from videocreate.runtime import quotas; '
                'from videocreate.config.storage import load_json; '
                'quotas.request(Path(sys.argv[2]),load_json(Path(sys.argv[3])),sys.argv[4],"poll")')
        result = subprocess.run([sys.executable,'-I','-c',code,str(repo/'videocreate/src'),str(self.root),str(conf),self.uid],
                                capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('poll_rpm', result.stderr)

    def test_concurrent_projects_admit_one_durable_intent(self):
        self.config['upstreams'][self.uid]['quotas']['create_rpm'] = 100
        other = self.root / 'other'; other.mkdir(); save_state(other, {'schema_version':3,'jobs':{},'ledger':[]})
        quotas.watch(self.root, other)
        barrier = threading.Barrier(2)
        def run(project):
            barrier.wait()
            try:
                with state_lock(project), quotas.admission(self.root, self.config, self.uid):
                    save_state(project, {'schema_version':3,'jobs':{'one':{
                        'attempt_id':project.name,'status':'submitting','binding_snapshot':{'upstream_id':self.uid}}},'ledger':[]})
                return True
            except quotas.QuotaExceeded: return False
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(run, [self.project, other]))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(quotas.status(self.root, self.config, self.uid)['remote_inflight'], 1)

    def test_read_guards_stop_before_network_and_restore_after_exception(self):
        body = io.BytesIO(b'{}'); body.headers = {}
        with mock.patch('urllib.request.urlopen', return_value=body) as network:
            with quotas.network_scope(self.root, self.config, self.uid, 'poll'):
                self.assertEqual(vc_common.request_json('GET','https://provider.test/task',key='test'), {})
                with self.assertRaises(quotas.QuotaExceeded):
                    vc_common.request_json('GET','https://provider.test/task',key='test')
            self.assertEqual(network.call_count, 1)
            body = io.BytesIO(b'{}'); body.headers = {}; network.return_value = body
            self.assertEqual(vc_common.request_json('GET','https://provider.test/task',key='test'), {})
        with quotas.network_scope(self.root, self.config, self.uid, 'download'):
            quotas.request(self.root, self.config, self.uid, 'download')
            with mock.patch('urllib.request.urlopen') as network:
                with self.assertRaises(quotas.QuotaExceeded):
                    vc_common.download_file('https://provider.test/output', self.root/'never.mp4')
                network.assert_not_called()


class QuotaRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.store = self.root / 'store'
        self.project = self.root / 'video'; save_bundle(self.project, smart_car())
        self.config = migrate(config(), ask=False); self.uid = 'primary-sub2api'
        self.config['upstreams'][self.uid]['quotas'] = {'max_remote_inflight':1, 'create_rpm':1}
        self.calls = 0; self.mode = 'timeout'
        outer = self
        class Client:
            def __init__(self,binding): self.binding=binding; self.last_submission={}
            def prepare(self,prompt,**kwargs): return {'prompt':prompt}
            def create(self,prompt,**kwargs):
                outer.calls+=1
                if outer.mode=='unknown':
                    from provider_contracts import SubmissionUnknownError
                    raise SubmissionUnknownError('Connection ended without task ID')
                return 'videoprep_original'
            def poll(self,tid,**kwargs):
                assert tid=='videoprep_original'
                if outer.mode=='timeout': raise TimeoutError('Local wait stopped')
                if outer.mode=='query-quota':
                    vc_common.request_json('GET','https://provider.test/task',key='test')
                return {'status':'completed'}
            def download(self,tid,payload,destination):
                if outer.mode=='download-failure': raise OSError('Temporary download failure')
                destination.write_bytes(b'source')
        patch = mock.patch('videocreate.runtime.jobs.client',side_effect=Client);patch.start();self.addCleanup(patch.stop)
        probe = mock.patch('videocreate.timeline.render.probe',return_value={'duration':6});probe.start();self.addCleanup(probe.stop)

    def run_job(self, jid='job-001', **kwargs):
        return jobs.generate(self.project,self.config,store_root=self.store,job_ids=[jid],
                             binding_override={jid:'grok-on-sub2api'},**kwargs)

    def test_inflight_rejects_new_job_before_ledger_and_resume_bypasses_create_caps(self):
        with self.assertRaises(ConfigError): self.run_job()
        before = (self.project/'state.json').read_bytes()
        with self.assertRaisesRegex(quotas.QuotaExceeded,'max_remote_inflight'): self.run_job('job-002')
        self.assertEqual((self.project/'state.json').read_bytes(),before)
        self.assertEqual(self.calls,1)
        self.mode='complete'
        self.assertTrue(self.run_job(retry='network',reason='Resume known task')['ok'])
        self.assertEqual(self.calls,1)
        self.assertEqual(quotas.status(self.store,self.config,self.uid)['remote_inflight'],0)
        with self.assertRaisesRegex(quotas.QuotaExceeded,'create_rpm'): self.run_job('job-002')
        self.assertEqual(len(read_state(self.project)['ledger']),1)

    def test_download_failure_releases_remote_capacity_without_recreating(self):
        self.mode='download-failure'
        with self.assertRaises(ConfigError): self.run_job()
        record=read_state(self.project)['jobs']['job-001']
        self.assertEqual(record['status'],'read_pending')
        self.assertTrue(record['provider_completed_at'])
        self.assertEqual(quotas.status(self.store,self.config,self.uid)['remote_inflight'],0)
        self.mode='complete';self.run_job(retry='network',reason='Resume download')
        self.assertEqual(self.calls,1)

    def test_ambiguous_create_keeps_remote_hold_and_original_ledger(self):
        self.mode='unknown'
        with self.assertRaises(ConfigError): self.run_job()
        before=(self.project/'state.json').read_bytes()
        with self.assertRaisesRegex(quotas.QuotaExceeded,'max_remote_inflight'): self.run_job('job-002')
        self.assertEqual((self.project/'state.json').read_bytes(),before)
        self.assertEqual(self.calls,1)
        self.assertEqual(read_state(self.project)['jobs']['job-001']['status'],'submission_unknown')

    def test_poll_quota_keeps_same_task_and_sends_no_new_request(self):
        self.config['upstreams'][self.uid]['quotas']['poll_rpm']=1
        quotas.request(self.store,self.config,self.uid,'poll');self.mode='query-quota'
        with mock.patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ConfigError,'poll_rpm'): self.run_job()
            network.assert_not_called()
        record=read_state(self.project)['jobs']['job-001']
        self.assertEqual((record['status'],record['task_id']),('read_pending','videoprep_original'))
        self.assertEqual(self.calls,1)

    def test_images_and_video_share_capacity_when_account_matches(self):
        from videocreate.assets import generate_image
        self.config['upstreams']['image-service']['account_id']=self.uid
        with self.assertRaises(ConfigError): self.run_job()
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as create:
            with self.assertRaisesRegex(quotas.QuotaExceeded,'max_remote_inflight'):
                generate_image(self.project,self.config,store_root=self.store,job_id='portrait',
                               prompt='A historical portrait',references=[],size='1024x1024',quality='auto')
            create.assert_not_called()
        self.assertEqual(len(read_state(self.project)['ledger']),1)


if __name__ == '__main__': unittest.main()
