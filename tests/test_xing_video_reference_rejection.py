import copy
import hashlib

from test_reference_fetch_rejection import ReferenceFetchRejectionTests
from videocreate.config.storage import ConfigError
from videocreate.runtime.failures import (XING_VIDEO_REFERENCE_CONTRACT,
    XING_REFERENCE_VIDEO_CONTRACT, xing_video_reference_rejection,
    xing_reference_video_rejection)
from videocreate.runtime.state import read_state
from vc_common import APIError


class XingVideoReferenceRejectionTests(ReferenceFetchRejectionTests):
    def setUp(self):
        super().setUp()
        self.snapshot.update(base_url='https://xingapi.top/v1', adapter='xingapi-video-v2',
                             remote_model='seedance2.5-T')
        self.error = APIError(400, 'this Miaowu video provider does not support reference videos', 'original-trace')
        self.state['jobs']['job']['error'] = str(self.error)
        self.state['jobs']['job']['submission_receipt']['media_references'] = [{'kind': 'video'}]
        self.receipt.update(contract_id=XING_VIDEO_REFERENCE_CONTRACT, method='explicit-create-validation-rejection')
        self.response = self.root / 'response.txt'
        self.response.write_text(str(self.error), encoding='utf-8')
        self.receipt['evidence'].append({'path': self.response.name, 'kind': 'create-response',
            'sha256': hashlib.sha256(self.response.read_bytes()).hexdigest()})

    def test_exact_provider_error_is_recognized_without_blanket_400_policy(self):
        self.assertTrue(xing_video_reference_rejection(400, str(self.error), self.snapshot))
        for status, message, changes in [
            (500, str(self.error), {}), (400, 'HTTP 400: Bad request', {}),
            (400, str(self.error) + ' moderation', {}),
            (400, str(self.error), {'base_url': 'https://xingapi.top.evil.test'}),
            (400, str(self.error), {'base_url': 'https://user:pass@xingapi.top'}),
            (400, str(self.error), {'base_url': 'https://xingapi.top:8443'}),
            (400, str(self.error), {'remote_model': 'seedance2.5-V'}),
            (400, str(self.error), {'adapter': 'newapi-json-v2'}),
        ]:
            with self.subTest(status=status, changes=changes):
                self.assertFalse(xing_video_reference_rejection(status, message, {**self.snapshot, **changes}))

    def test_broader_contract_is_limited_to_exact_t_and_v_models(self):
        for model in ['seedance2.5-T', 'seedance2.5-V']:
            self.assertTrue(xing_reference_video_rejection(400, str(self.error),
                                                            {**self.snapshot, 'remote_model': model}))
        self.assertFalse(xing_reference_video_rejection(400, str(self.error),
                                                        {**self.snapshot, 'remote_model': 'seedance2.5-S'}))
        self.assertFalse(xing_reference_video_rejection(400, 'HTTP 400: other', self.snapshot))

    def test_response_and_actual_video_input_are_required(self):
        for edit in ['absent-response', 'different-response', 'no-video', 'different-saved-trace']:
            with self.subTest(edit=edit):
                state, receipt = copy.deepcopy(self.state), copy.deepcopy(self.receipt)
                if edit == 'absent-response':
                    self.receipt['evidence'] = self.receipt['evidence'][:1]
                elif edit == 'different-response':
                    self.response.write_text('HTTP 400: unrelated', encoding='utf-8')
                    self.receipt['evidence'][-1]['sha256'] = hashlib.sha256(self.response.read_bytes()).hexdigest()
                elif edit == 'no-video':
                    self.state['jobs']['job']['submission_receipt']['media_references'] = [{'kind': 'image'}]
                else:
                    self.state['jobs']['job']['error'] = str(self.error).replace('original-trace', 'other-trace')
                with self.assertRaises(ConfigError):
                    self.resolve()
                self.state, self.receipt = state, receipt
                self.response.write_text(str(self.error), encoding='utf-8')

    def test_v_route_exact_rejection_reconciles_with_received_response(self):
        self.snapshot.update(remote_model='seedance2.5-V')
        self.error = APIError(400, 'this Miaowu video provider does not support reference videos', 'original-trace')
        self.state['jobs']['job'].update(error=str(self.error), binding_snapshot=self.snapshot,
            submission_receipt={'trace_ids': {'request_id': 'original-trace'},
                                'media_references': [{'kind': 'video'}]})
        self.response.write_text(str(self.error), encoding='utf-8')
        self.receipt.update(contract_id=XING_REFERENCE_VIDEO_CONTRACT,
                            method='explicit-create-validation-rejection')
        result = self.resolve()
        self.assertEqual(result['status'], 'rejected')
        saved = read_state(self.root)
        self.assertEqual(saved['ledger'][0]['status'], 'confirmed-pre-task-rejection')
        self.assertIsNone(saved['ledger'][0]['actual'])

        self.state['jobs']['job']['status'] = 'submission_unknown'
        self.snapshot['remote_model'] = 'seedance2.5-S'
        with self.assertRaises(ConfigError):
            self.resolve()
