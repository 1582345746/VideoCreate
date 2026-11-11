"""Motion budgets and local tempo edits preserve dialogue and existing generation."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'videocreate/src'))
from videocreate.animation import examples, previews
from videocreate.config.storage import ConfigError
from videocreate.planning.creative_audit import audit
from videocreate.planning.project import compile_job, content_hash, load_project, validate_plan
from videocreate.runtime.jobs import current_inputs
from videocreate.timeline.model import mapping


class AnimationRhythmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        examples.create(self.root / 'story')
        self.root /= 'story'
        self.bundle = load_project(self.root)

    def test_timing_reaches_compiler_and_only_invalidates_its_video_job(self):
        b = self.bundle
        first, other = b['generation-plan']['jobs'][:2]
        initial = current_inputs(self.root, b, first, {})
        unaffected = current_inputs(self.root, b, other, {})
        prompt = compile_job(b, first, max_bytes=4096)['prompt']
        self.assertIn('Action timing: brisk', prompt)
        b['director']['shots'][0]['timing']['action_start_by'] = .1
        self.assertNotEqual(current_inputs(self.root, b, first, {}), initial)
        self.assertEqual(current_inputs(self.root, b, other, {}), unaffected)
        b['timeline']['segments'][0]['rate'] = 1.5
        b['timeline']['segments'][0]['source_audio'] = 'retime'
        self.assertEqual(current_inputs(self.root, b, other, {}), unaffected)

    def test_invalid_deadlines_and_conflicting_long_holds_do_not_silently_pass(self):
        b = self.bundle
        timing = b['director']['shots'][0]['timing']
        timing['action_complete_by'] = 100
        self.assertFalse(validate_plan(b)['ok'])
        timing['action_complete_by'] = 2.3
        b['director']['shots'][0]['action_phases'] = [
            {'phase':'prepare','start':0,'end':1,'description':'Wait'},
            {'phase':'action','start':1,'end':1.5,'description':'Act'},
            {'phase':'settle','start':1.5,'end':3,'description':'Long hold'}]
        codes = {f['code'] for f in audit(b)['findings']}
        self.assertTrue({'timing-start-conflict','long-reaction-hold'} <= codes)

    def test_action_speed_edit_rebases_later_speech_without_accelerating_it(self):
        b = self.bundle
        first = b['timeline']['segments'][0]
        boundary = first['source_out'] - first['source_in']
        b['timeline']['audio_tracks'] = [{'id':'later','kind':'dialogue','path':'later.wav',
            'source_in':0,'source_out':.5,'timeline_start':boundary+.1}]
        before = content_hash(b)
        result = previews.prepare(b, {'reason':'Quicker nonverbal action',
            'segments':{first['id']:{'rate':1.5,'source_audio':'retime'}}})
        self.assertEqual(content_hash(b), before)
        self.assertAlmostEqual(result['audio_tracks'][0]['timeline_start'], boundary/1.5+.1)
        self.assertEqual(result['audio_tracks'][0]['source_out'], .5)
        self.assertAlmostEqual(mapping(result)['segments'][0]['duration'], boundary/1.5)

    def test_retime_rejects_dialogue_invalid_rate_and_overlapping_events(self):
        b = self.bundle
        seg = b['timeline']['segments'][0]
        edit = {'reason':'Tempo test','segments':{seg['id']:{'rate':1.5,'source_audio':'retime'}}}
        b['director']['shots'][0]['audio'] = {'mode':'native-dialogue','lines':[
            {'speaker':'lulu','text':'Test','on_screen':True,'start':.25,'end':1.5}]}
        with self.assertRaisesRegex(ConfigError,'dialogue shots'):
            previews.prepare(b,edit)
        b['director']['shots'][0]['audio'] = {'mode':'ambience'}
        for rate in (True,float('nan'),0):
            bad = copy.deepcopy(edit)
            bad['segments'][seg['id']]['rate'] = rate
            with self.assertRaises(ConfigError):
                previews.prepare(b,bad)
        b['timeline']['audio_tracks'] = [{'id':'music','kind':'music','path':'music.wav',
            'source_in':0,'source_out':1,'timeline_start':0}]
        with self.assertRaisesRegex(ConfigError,'independent audio'):
            previews.prepare(b,edit)
        b['timeline']['audio_tracks'] = []
        b['timeline']['subtitles'] = [{'text':'Cue','start':.2,'end':.7}]
        with self.assertRaisesRegex(ConfigError,'subtitle/overlay'):
            previews.prepare(b,edit)


if __name__ == '__main__':
    unittest.main()
