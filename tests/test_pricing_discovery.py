import copy
import unittest

from videocreate.catalog.pricing import normalize
from videocreate.config.storage import ConfigError


class PricingDiscoveryTests(unittest.TestCase):
    def fixture(self, unit='second'):
        return {'currency': 'USD', 'data': [{'id': 'seedance2.5-V', 'description': 'provider claim',
            'billing_mode': 'video', 'video_billing_unit': unit, 'pricing_configured': True,
            'pricing': {'unit': 'usd_per_second' if unit == 'second' else 'usd_per_video',
                'tiers': [{'tier_label': '720P', 'min_tokens': 0, 'max_tokens': None, 'per_request_price': .299}]}}]}

    def test_reused_per_request_field_obeys_explicit_billing_unit(self):
        body = self.fixture()
        before = copy.deepcopy(body)
        row = normalize(body)[0]
        self.assertEqual(row['quote'], {'currency': 'USD', 'unit': 'second', 'amount': .299, 'resolution': '720p', 'actual_payment': 'unknown'})
        self.assertEqual(row['remote_model'], 'seedance2.5-V')
        self.assertEqual(body, before)
        self.assertEqual(normalize(self.fixture('request'))[0]['quote']['unit'], 'request')

    def test_ambiguous_tiers_currency_or_units_never_choose_arbitrary_price(self):
        for change in ('tiers', 'currency', 'units', 'nan', 'tier'):
            body = self.fixture()
            p = body['data'][0]['pricing']
            if change == 'tiers': p['tiers'].append(copy.deepcopy(p['tiers'][0]))
            elif change == 'currency': body['currency'] = 'CNY'
            elif change == 'units': p['unit'] = 'usd_per_video'
            elif change == 'nan': p['tiers'][0]['per_request_price'] = float('nan')
            else: p['tiers'][0]['tier_label'] = 'special'
            self.assertIsNone(normalize(body)[0]['quote'])

    def test_duplicate_ids_rejected(self):
        body = self.fixture()
        body['data'].append(copy.deepcopy(body['data'][0]))
        with self.assertRaises(ConfigError):
            normalize(body)

    def test_malformed_pricing_is_actionable(self):
        body = self.fixture()
        body['data'][0]['pricing'] = []
        with self.assertRaises(ConfigError):
            normalize(body)
