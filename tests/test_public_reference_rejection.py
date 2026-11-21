import copy
import hashlib
import unittest

from test_reference_fetch_rejection import ReferenceFetchRejectionTests
from videocreate.runtime.failures import PUBLIC_REFERENCE_CONTRACT, public_reference_rejection
from videocreate.config.storage import ConfigError
from vc_common import APIError

MESSAGE = ('生成失败：Jianwei references must use public HTTP(S) URLs '
           'without embedded login credentials～（本次不扣费）')


class PublicReferenceRejectionTests(ReferenceFetchRejectionTests):
    def setUp(self):
        super().setUp()
        self.snapshot.update(remote_model='稳定高速sd2.5(30参任选/4-30秒/720P)',
                             adapter_options={'reference_transport': 'data-uri'})
        self.error = APIError(400, MESSAGE, 'original-trace')
        self.state['jobs']['job']['error'] = str(self.error)
        self.receipt.update(contract_id=PUBLIC_REFERENCE_CONTRACT,
                            method='explicit-create-validation-rejection')
        response = self.root / 'response.txt'
        response.write_text(str(self.error), encoding='utf-8')
        self.receipt['evidence'].append({'path': response.name, 'kind': 'create-response',
                                       'sha256': hashlib.sha256(response.read_bytes()).hexdigest()})

    def test_exact_provider_error_is_recognized_without_blanket_400_policy(self):
        self.assertTrue(public_reference_rejection(400, str(self.error), self.snapshot))
        for status, message, changes in [
            (500, str(self.error), {}), (400, 'HTTP 400: 生成失败', {}),
            (400, str(self.error).replace('～（本次不扣费）', ''), {}),
            (400, str(self.error) + ' moderation', {}),
            (400, str(self.error), {'base_url': 'https://suanliai.top.evil.test'}),
            (400, str(self.error), {'base_url': 'https://user:pass@suanliai.top'}),
            (400, str(self.error), {'adapter_options': {'reference_transport': 'https'}}),
            (400, str(self.error), {'remote_model': 'other'}),
            (400, str(self.error), {'adapter': 'newapi-json-v1'}),
        ]:
            with self.subTest(status=status, changes=changes):
                self.assertFalse(public_reference_rejection(status, message, {**self.snapshot, **changes}))

    def test_missing_actual_response_stays_unknown(self):
        receipt = copy.deepcopy(self.receipt)
        receipt['evidence'] = receipt['evidence'][:1]
        with self.assertRaises(ConfigError):
            self.resolve(receipt)


if __name__ == '__main__':
    unittest.main()
