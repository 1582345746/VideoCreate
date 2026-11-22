"""Silent performance is independent of sound; legacy task identity stays stable."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'videocreate/src'))
from videocreate.planning.profiles import create
from videocreate.planning.project import compile_job,validate_plan
from videocreate.planning.performance import validation_errors
from videocreate.runtime.jobs import job_inputs


class MouthPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.b=create('portrait')
        self.shot=self.b['director']['shots'][0]
        self.job=self.b['generation-plan']['jobs'][0]

    def test_new_silent_project_allows_natural_expression(self):
        self.assertEqual(self.b['project']['prompt_semantics'],2)
        prompt=compile_job(self.b,self.job,max_bytes=10000)['prompt']
        self.assertNotIn('visible mouths stay closed',prompt)
        self.assertIn('Natural facial expression',prompt)
        self.assertTrue(validate_plan(self.b)['ok'])

    def test_silent_reference_mouth_gestures_do_not_need_fake_dialogue(self):
        self.shot['mouth_performance']={'mode':'silent-performance','direction':'Follow the visible reference mouth gestures.'}
        self.assertTrue(validate_plan(self.b)['ok'])
        prompt=compile_job(self.b,self.job,max_bytes=10000)['prompt']
        self.assertIn('speaking/singing mouth gestures silently',prompt)
        self.assertNotIn('mouths stay closed',prompt)

    def test_compact_multishot_shares_only_matching_sound_and_mouth_directions(self):
        from copy import deepcopy
        second = {**deepcopy(self.shot), 'id': 'second', 'mouth_performance': {'mode': 'closed'}}
        self.b['director']['shots'].append(second)
        self.job['shot_ids'].append(second['id'])
        previous = compile_job(self.b, self.job, max_bytes=20000)['prompt']
        self.assertEqual(previous.count('No background music.'), 2)
        self.b['project']['prompt_semantics'] = 3
        compact = compile_job(self.b, self.job, max_bytes=20000)['prompt']
        self.assertEqual(compact.count('No background music.'), 1)
        prefix, rest = compact.split('Current shot ', 1)
        self.assertIn('No background music.', prefix)
        first, second_text = rest.split('Current shot second')
        self.assertIn('Natural facial expression', first)
        self.assertNotIn('Keep visible mouths closed', first)
        self.assertIn('Keep visible mouths closed', second_text)

    def test_closed_and_speech_conflicts_are_explicit(self):
        self.shot['mouth_performance']={'mode':'closed'}
        self.shot['audio']={'mode':'native-dialogue','lines':[{'on_screen':True}]}
        self.assertTrue(any('closed mouth conflicts' in x for x in validation_errors(self.b)))
        self.shot['audio']={'mode':'offscreen','lines':[{'on_screen':False}]}
        self.assertEqual(validation_errors(self.b),[])
        self.shot['mouth_performance']={'mode':'speech'}
        self.assertTrue(any('requires timed on-screen lines' in x for x in validation_errors(self.b)))

    def test_explicit_closed_is_supported_without_audio(self):
        self.shot['mouth_performance']={'mode':'closed'}
        self.assertTrue(validate_plan(self.b)['ok'])
        self.assertIn('Keep visible mouths closed',compile_job(self.b,self.job,max_bytes=10000)['prompt'])

    def test_legacy_omission_and_explicit_v1_have_same_prompt_and_inputs(self):
        self.b['project'].pop('prompt_semantics')
        original=compile_job(self.b,self.job,max_bytes=10000)
        original_inputs=job_inputs(self.b,self.job,original)
        self.b['project']['prompt_semantics']=1
        current=compile_job(self.b,self.job,max_bytes=10000)
        self.assertEqual(original['prompt'],current['prompt'])
        self.assertEqual(original_inputs,job_inputs(self.b,self.job,current))
        self.assertIn('No speech; visible mouths stay closed.',current['prompt'])
        self.shot['mouth_performance']={'mode':'natural'}
        self.assertTrue(any('prompt_semantics=2' in x for x in validate_plan(self.b)['errors']))

    def test_upgrading_one_shot_control_changes_generation_input(self):
        before=job_inputs(self.b,self.job,compile_job(self.b,self.job,max_bytes=10000))
        self.shot['mouth_performance']={'mode':'silent-performance'}
        after=job_inputs(self.b,self.job,compile_job(self.b,self.job,max_bytes=10000))
        self.assertNotEqual(before,after)


if __name__=='__main__':unittest.main()
