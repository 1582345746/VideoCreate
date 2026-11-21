"""Budget explanations are the calculation, rather than a second guessed price."""
import copy
import unittest
from types import SimpleNamespace

from videocreate.runtime.budget import estimate, estimate_details, reserve
from videocreate.config.storage import ConfigError


class BudgetExplanationTests(unittest.TestCase):
    def details(self, price, seconds=6, currency='USD', parameters=None):
        binding=SimpleNamespace(options={'pricing':price})
        before=copy.deepcopy(binding.options)
        result=estimate_details(binding,seconds,currency,parameters=parameters)
        self.assertEqual(estimate(binding,seconds,currency,parameters=parameters),result['amount'])
        self.assertEqual(binding.options,before)
        self.assertEqual(result['actual_payment'],'unknown')
        return result

    def test_unknown_prices_have_distinct_reasons_without_exposing_sources(self):
        cases=[(None,'price_missing'),({'currency':'CNY','per_request':1},'currency_mismatch'),
               ({'currency':'USD','per_request':1,'status':'unverified'},'price_unverified'),
               ({'currency':'USD'},'rate_missing')]
        for price,reason in cases:
            with self.subTest(reason=reason):
                if price:price['source']={'url':'https://sensitive.example.test/private'}
                result=self.details(price)
                self.assertEqual(result['reason'],reason)
                self.assertIsNone(result['amount'])
                self.assertNotIn('sensitive',str(result))

    def test_effective_expired_and_invalid_time_are_separate_unknowns(self):
        for field,value,reason in [('effective_at','2999-01-01T00:00:00Z','price_not_effective'),
                ('valid_until','2000-01-01T00:00:00Z','price_expired'),
                ('valid_until','2999-01-01T00:00:00','price_time_invalid'),
                ('effective_at','invalid-private-sentinel','price_time_invalid')]:
            with self.subTest(reason=reason):
                result=self.details({'currency':'USD','per_request':1,field:value})
                self.assertEqual(result['reason'],reason)
                self.assertIsNone(result['amount'])
                self.assertNotIn('private-sentinel',str(result))

    def test_tier_missing_parameter_no_match_overlap_and_inclusive_boundaries(self):
        price={'currency':'USD','per_request':999,'tiers':[
            {'when':{'resolution':'720p','minimum_seconds':5,'maximum_seconds':10},'per_request':2},
            {'when':{'resolution':'1080p'},'per_second':.5}]}
        self.assertEqual(self.details(price)['reason'],'tier_parameters_missing')
        self.assertEqual(self.details(price)['missing_parameters'],['resolution'])
        self.assertEqual(self.details(price,parameters={'resolution':'480p'})['reason'],'tier_no_match')
        for seconds in (5,10):
            result=self.details(price,seconds,parameters={'resolution':'720p'})
            self.assertEqual(result['amount'],2)
            self.assertEqual(result['matched_tiers'],[1])
        self.assertEqual(self.details(price,11,parameters={'resolution':'720p'})['reason'],'tier_no_match')
        price['tiers'].append(copy.deepcopy(price['tiers'][0]))
        result=self.details(price,parameters={'resolution':'720p'})
        self.assertEqual(result['reason'],'tier_ambiguous')
        self.assertEqual(result['matched_tiers'],[1,3])
        self.assertIsNone(result['amount'])

    def test_minimum_then_ceiling_additive_rates_and_explicit_zero(self):
        result=self.details({'currency':'USD','per_request':1,'per_second':.22,
                             'minimum_seconds':7,'round_seconds':5})
        self.assertEqual(result['billed_seconds'],10)
        self.assertEqual(result['amount'],3.2)
        self.assertEqual((result['per_request'],result['per_second']),(1,.22))
        result=self.details({'currency':'USD','per_request':0},seconds=0)
        self.assertEqual(result['amount'],0)
        self.assertEqual(result['reason'],'estimated')

    def test_unresolved_tier_can_overlap_a_known_match_and_blocks_hard_budget(self):
        price={'currency':'USD','tiers':[{'when':{},'per_request':2},
               {'when':{'aspect_ratio':'9:16'},'per_request':3}]}
        result=self.details(price)
        self.assertIsNone(result['amount'])
        self.assertEqual(result['reason'],'tier_parameters_missing')
        self.assertEqual(result['missing_parameters'],['aspect_ratio'])
        self.assertEqual(result['matched_tiers'],[1])
        state={'ledger':[]}
        with self.assertRaisesRegex(ConfigError,'Price is unknown'):
            reserve(state,{'currency':'USD','max_total':2},attempt_id='a',job_id='j',kind='video',estimated=result['amount'])
        self.assertEqual(state,{'ledger':[]})
        self.assertEqual(self.details(price,parameters={'aspect_ratio':'16:9'})['amount'],2)
        self.assertEqual(self.details(price,parameters={'aspect_ratio':'9:16'})['reason'],'tier_ambiguous')

    def test_only_still_possible_tiers_contribute_missing_context(self):
        price={'currency':'USD','tiers':[{'when':{},'per_request':2},
            {'when':{'operation':'image-edit','resolution':'private-value'},'per_request':9},
            {'when':{'minimum_seconds':7,'aspect_ratio':'9:16'},'per_request':8},
            {'when':{'resolution':'720p','aspect_ratio':'9:16'},'per_request':3}]}
        result=self.details(price,parameters={'operation':'text-to-video'})
        self.assertEqual(result['reason'],'tier_parameters_missing')
        self.assertEqual(result['missing_parameters'],['aspect_ratio','resolution'])
        self.assertNotIn('private-value',str(result))
        result=self.details(price,parameters={'operation':'text-to-video','resolution':'1080p'})
        self.assertEqual(result['amount'],2)
        self.assertEqual(result['missing_parameters'],[])

    def test_definite_overlap_remains_ambiguous_even_with_other_unknown_tiers(self):
        price={'currency':'USD','tiers':[{'when':{},'per_request':0},
            {'when':{},'per_request':2},{'when':{'resolution':'720p'},'per_request':3}]}
        result=self.details(price)
        self.assertIsNone(result['amount'])
        self.assertEqual(result['reason'],'tier_ambiguous')
        self.assertEqual(result['matched_tiers'],[1,2])

    def test_invalid_duration_or_overflow_cannot_supply_hard_budget_amount(self):
        for seconds in (-1,float('nan'),float('inf'),True):
            result=self.details({'currency':'USD','per_second':1},seconds)
            self.assertEqual(result['reason'],'duration_invalid')
        price={'currency':'USD','per_second':1e308}
        result=self.details(price,1e308)
        self.assertEqual(result['reason'],'estimate_not_finite')
        with self.assertRaisesRegex(ConfigError,'Price is unknown'):
            reserve({'ledger':[]},{'currency':'USD','max_total':100},attempt_id='a',job_id='j',kind='video',estimated=result['amount'])


if __name__=='__main__':unittest.main()
