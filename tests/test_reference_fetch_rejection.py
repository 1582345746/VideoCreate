import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_v3_config import config  # establishes source imports
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.runtime.failures import (
    REFERENCE_FETCH_CONTRACT, confirmed_rejection, reference_fetch_rejection)
from videocreate.runtime.reconcile import reconcile
from videocreate.runtime.state import read_state
from vc_common import APIError


MESSAGE = ('参考素材 images[3] 下载失败或超时（media.example.test），无法读取该链接。'
           '请换成稳定的公网链接（图床、对象存储），或直接传 base64（data:<类型>;base64,<内容>）')


class ReferenceFetchRejectionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.snapshot = {'base_url': 'https://suanliai.top/v1', 'adapter': 'newapi-json-v2',
            'remote_model': '官渠sd2.5-flash(20参任选/10-5-5/5-30秒/720P)', 'fingerprint': 'original-binding'}
        self.binding = SimpleNamespace(options={}, snapshot=lambda: copy.deepcopy(self.snapshot))
        self.error = APIError(400, MESSAGE, 'original-trace')
        self.state = {'schema_version': 3, 'jobs': {'job': {
            'status': 'submission_unknown', 'attempt_id': 'original-attempt', 'task_id': '',
            'binding_snapshot': self.snapshot, 'error': str(self.error),
            'submission_receipt': {'trace_ids': {'request_id': 'original-trace'}}}},
            'ledger': [{'attempt_id': 'original-attempt', 'status': 'submission_unknown',
                        'estimated': 4.85, 'actual': None}]}
        self.evidence = self.root / 'contract.txt'
        self.evidence.write_text('Provider documentation: image download failure rejects before task creation.', encoding='utf-8')
        self.receipt = {'job_id': 'job', 'attempt_id': 'original-attempt',
            'binding_fingerprint': 'original-binding', 'reviewer_id': 'test-operator',
            'outcome': 'rejected-before-task', 'method': 'documented-create-response',
            'contract_id': REFERENCE_FETCH_CONTRACT, 'request_id': 'original-trace',
            'evidence': [{'path': 'contract.txt', 'sha256': hashlib.sha256(self.evidence.read_bytes()).hexdigest(),
                          'kind': 'provider-contract'}]}

    def resolve(self, receipt=None):
        atomic_json(self.root / 'state.json', self.state)
        return reconcile(self.root, {}, receipt or self.receipt, store_root=self.root)

    def test_exact_provider_error_is_recognized_without_blanket_400_policy(self):
        self.assertTrue(confirmed_rejection(self.error, self.binding))
        for error in [APIError(500, MESSAGE), APIError(400, 'Bad request'),
                      APIError(400, MESSAGE.replace('images[3]', 'videos[0]')),
                      APIError(400, MESSAGE + ' content policy'), TimeoutError(MESSAGE)]:
            with self.subTest(error=type(error).__name__, text=str(error)[:50]):
                self.assertFalse(confirmed_rejection(error, self.binding))
        for update in [{'base_url': 'https://other.example/v1'}, {'base_url': 'https://suanliai.top.evil.test'},
                       {'base_url': 'https://suanliai.top:8443'}, {'adapter': 'newapi-json-v1'},
                       {'remote_model': 'unverified-model'}]:
            self.assertFalse(reference_fetch_rejection(400, str(self.error), {**self.snapshot, **update}))

    def test_resolution_preserves_received_response_and_cost_uncertainty(self):
        result = self.resolve()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['paid_creates'], 0)
        saved = read_state(self.root)
        self.assertEqual(saved['jobs']['job']['error'], str(self.error))
        self.assertEqual(saved['ledger'][0]['status'], 'confirmed-pre-task-rejection')
        self.assertEqual(saved['ledger'][0]['estimated'], 4.85)
        self.assertIsNone(saved['ledger'][0]['actual'])
        self.assertEqual(saved['jobs']['job']['attempt_id'], 'original-attempt')

    def test_wrong_trace_contract_task_or_absent_evidence_cannot_unlock(self):
        for update in [{'request_id': 'other-request'}, {'contract_id': 'invented'},
                       {'task_id': 'task-already-created'}, {'evidence': []},
                       {'method': 'log-not-found'}, {'binding_fingerprint': 'changed'}]:
            with self.subTest(update=update):
                with self.assertRaises(ConfigError):
                    self.resolve({**self.receipt, **update})
                self.assertEqual(read_state(self.root)['jobs']['job']['status'], 'submission_unknown')

    def test_timeout_or_existing_task_remains_unknown(self):
        for update in [{'error': 'Timeout'}, {'task_id': 'existing-task'},
                       {'submission_receipt': {}}, {'error': str(APIError(400, '查不到记录'))}]:
            original = copy.deepcopy(self.state['jobs']['job'])
            self.state['jobs']['job'].update(update)
            with self.assertRaises(ConfigError):
                self.resolve()
            self.state['jobs']['job'] = original

    def test_changed_contract_evidence_is_rejected(self):
        self.evidence.write_text('Changed evidence', encoding='utf-8')
        with self.assertRaisesRegex(ConfigError, 'stale'):
            self.resolve()


if __name__ == '__main__':
    unittest.main()
