import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from videocreate.cli import main
from videocreate.config.storage import atomic_json
from videocreate.media_references import digest
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle
from videocreate.runtime.state import save_state


class TimelineEventMapTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.bundle = smart_car()
        self.clip = self.bundle['timeline']['clips'][0]
        self.job = self.clip['job_id']
        clip_id = self.clip['id']
        original = self.bundle['timeline']['segments'][0]
        self.bundle['timeline'].update(
            segments=[{**original, 'id': 'fast', 'source_in': 1, 'source_out': 3, 'rate': 2,
                       'source_audio': 'mute', 'clip_id': clip_id},
                      {**original, 'id': 'reuse', 'source_in': 0, 'source_out': 2, 'rate': 1,
                       'source_audio': 'mute', 'clip_id': clip_id}],
            audio_tracks=[], subtitles=[])
        save_bundle(self.root, self.bundle)
        source = self.root/'original.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=32x32:r=10:d=4',
                        '-f','lavfi','-i','sine=duration=3','-c:v','libx264','-c:a','aac',str(source)],
                       capture_output=True,check=True)
        self.media = {'path': source.name, 'sha256': digest(source)}
        self.spec = {'schema_version':1, 'source': self.media, 'audio': self.media, 'target_job': self.job,
                     'tolerance_seconds': 0.04, 'events': [
                         {'id':'press','reason':'Reprise','source':[2,4], 'audio':[0,2], 'target':[1,3]},
                         {'id':'exit','reason':'Cut away','source':[0,1], 'target':[3,4]}]}

    def invoke(self, expected=0):
        path = self.root/'events.json'
        atomic_json(path,self.spec)
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(['timeline','map',str(self.root),'--events',str(path)])
        self.assertEqual(result, expected, output.getvalue())
        return json.loads(output.getvalue())

    def test_retimed_and_repeated_clip_maps_each_retained_interval(self):
        result = self.invoke()
        first, second = result['events'][0]['occurrences']
        self.assertEqual((first['source'], first['audio'], first['target'], first['timeline']),
                         ([2,4],[0,2],[1,3],[0,1]))
        self.assertFalse(first['within_duration_tolerance'])
        self.assertEqual((second['source'],second['audio'],second['target'],second['timeline']),
                         ([2,3],[0,1],[1,2],[2,3]))
        self.assertTrue(second['within_duration_tolerance'])
        self.assertTrue(second['partially_retained'])
        self.assertEqual(result['events'][1]['edit_status'], 'omitted')
        self.assertEqual(result['target_clock']['basis'], 'planned-job')
        self.assertEqual(result['paid_creates'], 0)
        self.assertFalse((self.root/'state.json').exists())

    def test_audio_clock_uses_shorter_stream_and_rejects_changed_bytes(self):
        self.spec['events'][0]['audio'] = [2,3.5]
        self.assertIn('invalid audio interval', self.invoke(1)['error'])
        self.spec['audio'] = {**self.media, 'sha256':'0'*64}
        self.assertIn('bytes changed', self.invoke(1)['error'])

    def test_audio_alignment_rechecks_offsets_even_when_durations_match(self):
        self.bundle['timeline']['audio_tracks'] = [{
            'id':'beat', 'kind':'music', 'path':self.media['path'], 'source_in':0, 'source_out':2,
            'timeline_start':0.5}]
        atomic_json(self.root/'timeline.json', self.bundle['timeline'])
        self.spec['audio_track_id'] = 'beat'
        fast, repeated = self.invoke()['events'][0]['occurrences']
        self.assertEqual(fast['audio_alignment']['picture_minus_audio_seconds'], [-0.5,-1.5])
        self.assertTrue(repeated['within_duration_tolerance'])
        self.assertEqual(repeated['audio_alignment']['status'], 'outside-planned-tolerance')
        self.assertEqual(repeated['audio_alignment']['picture_minus_audio_seconds'], [1.5,1.5])

    def test_explicit_replacement_does_not_inherit_generated_timing(self):
        self.clip['path'] = self.media['path']
        atomic_json(self.root/'timeline.json', self.bundle['timeline'])
        result = self.invoke()
        self.assertEqual(result['unmatched_path_clips'],[self.clip['id']])
        self.assertEqual(result['events'][0]['occurrences'],[])
        save_state(self.root,{'schema_version':3,'ledger':[],'jobs':{
            self.job:{'status':'completed','artifact':self.media}}})
        result = self.invoke()
        self.assertEqual(result['target_clock']['sha256'],self.media['sha256'])
        self.assertEqual(len(result['events'][0]['occurrences']),2)
