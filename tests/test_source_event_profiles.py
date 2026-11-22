"""Source observations, required openings and edit mappings use the same event IDs."""
import copy
import io
import subprocess
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from videocreate import references
from videocreate.cli import main
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.media_references import digest
from videocreate.planning.profiles import create
from videocreate.planning.project import content_hash, load_project, save_bundle
from videocreate.reference_events import validate
from videocreate.timeline.events import event_map
from videocreate.review.comparison import event_history


class SourceEventProfileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.bundle = create('portrait')
        save_bundle(self.root, self.bundle)
        self.video = self.root/'source.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=32x32:r=24:d=2',
                        '-f','lavfi','-i','sine=duration=2','-c:v','libx264','-c:a','aac','-shortest',str(self.video)],
                       check=True,capture_output=True)
        result = references.analyze(self.video,self.root/'study',max_frames=4)
        self.report_path = Path(result['report'])
        self.report = load_json(self.report_path)
        self.document = {'reviewer_id':'', 'observations':[],
                         'participants':[{'id':'performer','description':'The source performer'}],
                         'events':[{'id':eid,'category':category,'start':start,'end':end,
                                    'notes':eid,'participants':['performer'],'status':'unverified',
                                    'must_preserve':True}
                                   for eid,category,start,end in [('opening','hook',0,1),('exit','action',1,2)]]}

    def profile(self):
        result = references.profile(self.report_path,self.document)
        path = Path(result['profile'])
        self.assertEqual(references.validate_profile(path),[])
        return path, load_json(path)

    def mapping_spec(self, profile_path):
        return {'schema_version':2,'source':{'path':self.video.name,'sha256':digest(self.video)},
                'source_profile':{'path':profile_path.relative_to(self.root).as_posix(),'sha256':digest(profile_path)},
                'target_job':self.bundle['generation-plan']['jobs'][0]['id'],'tolerance_seconds':1/24,
                'events':[{'id':eid,'source_event_id':eid,'target':[start,end],'reason':'Keep this source event'}
                          for eid,start,end in [('opening',0,1),('exit',1,2)]]}

    def test_cli_template_preserves_an_authored_file_and_profile_retains_unknown_coverage(self):
        path = self.root/'events.json'
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['reference','events',str(self.report_path),'--output',str(path)]),0)
        value = load_json(path)
        self.assertEqual(value['events'][0]['status'],'unverified')
        atomic_json(path,self.document)
        before = path.read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['reference','events',str(self.report_path),'--output',str(path)]),0)
        self.assertEqual(path.read_bytes(),before)
        _, profile = self.profile()
        self.assertEqual(profile['schema_version'],2)
        self.assertEqual(profile['semantic_status'],'unverified')
        self.assertEqual(profile['event_coverage']['temporal']['observed_event_seconds'],0)
        self.assertEqual(profile['event_coverage']['temporal']['unverified_intervals'],[[0,2]])

    def test_static_frames_and_transcription_cannot_certify_source_action_or_dialogue(self):
        event = self.document['events'][0]
        self.document['reviewer_id'] = 'fixture'
        event.update(status='observed',method='frames',frame_ids=[self.report['frames'][0]['id']])
        with self.assertRaisesRegex(ConfigError,'Static frames'):
            validate(self.report,self.document)
        event.update(category='dialogue',method='asr',transcript='Synthetic transcript')
        with self.assertRaisesRegex(ConfigError,'observation method'):
            validate(self.report,self.document)
        event['status'] = 'inferred'
        validate(self.report,self.document)
        _, profile = self.profile()
        self.assertEqual(profile['semantic_status'],'unverified')
        self.assertEqual(profile['event_coverage']['audio']['observed_event_seconds'],0)

    def test_event_profile_attaches_to_a_project_using_default_layer_paths(self):
        path, _ = self.profile()
        self.bundle['project'].pop('files', None)
        atomic_json(self.root/'project.json',self.bundle['project'])
        attached = references.attach(self.root,path)
        self.assertIn({key:attached[key] for key in ('path','sha256')},
                      load_project(self.root)['brief']['reference_profiles'])
        self.assertEqual(references.validate_profile(self.root/attached['path']),[])
        alias = path.with_name('renamed-events.json')
        alias.write_bytes(path.read_bytes())
        self.assertEqual(references.attach(self.root,alias),attached)

    def test_hash_bound_video_frame_evidence_survives_profile_attachment(self):
        frame = self.report['frames'][0]
        evidence_path = self.report_path.parent/'event-evidence'/(frame['id']+'.jpg')
        evidence_path.parent.mkdir()
        shutil.copyfile(self.report_path.parent/frame['path'],evidence_path)
        self.document['reviewer_id'] = 'fixture'
        self.document['evidence'] = [{'id':'motion-frame-001',
            'path':evidence_path.relative_to(self.report_path.parent).as_posix(),
            'sha256':digest(evidence_path),'source_sha256':self.report['source']['sha256'],
            'at_seconds':frame['at_seconds']}]
        event = self.document['events'][0]
        event.update(status='inferred',method='frames',evidence_ids=['motion-frame-001'])
        path, profile = self.profile()
        self.assertEqual(profile['events'][0]['evidence_ids'],['motion-frame-001'])
        attached = references.attach(self.root,path)
        copied = self.root/'assets/reference-studies'/profile['profile_hash'][:16]/evidence_path.relative_to(self.report_path.parent)
        self.assertEqual(digest(copied),digest(evidence_path))
        copied.write_bytes(b'changed')
        self.assertTrue(references.validate_profile(self.root/attached['path']))

    def test_external_still_observation_does_not_count_as_motion_review(self):
        frame = self.report['frames'][0]
        path = self.report_path.parent/'frame.jpg'
        shutil.copyfile(self.report_path.parent/frame['path'],path)
        self.document['reviewer_id']='still-review'
        self.document['evidence']=[{'id':'frame-visual','path':path.name,'sha256':digest(path),
            'source_sha256':self.report['source']['sha256'],'at_seconds':frame['at_seconds']}]
        event = self.document['events'][0]
        event.update(category='subject',status='observed',method='frames',evidence_ids=['frame-visual'],
                     start=0,end=2)
        _, profile = self.profile()
        self.assertEqual(profile['semantic_status'],'partial_observations')
        self.assertEqual(profile['event_coverage']['temporal']['observed_event_seconds'],0)
        event['category']='action'
        with self.assertRaisesRegex(ConfigError,'Static frames'):
            validate(self.report,self.document,evidence_root=self.report_path.parent)

    def test_event_revision_keeps_prior_profile_and_reuses_the_measured_analysis(self):
        first, before = self.profile()
        raw = first.read_bytes()
        measured = self.report_path.read_bytes()
        self.document['events'][0]['notes'] = 'Revised opening observation awaiting playback'
        second, after = self.profile()
        self.assertNotEqual(first,second)
        self.assertNotEqual(before['profile_hash'],after['profile_hash'])
        self.assertEqual(first.read_bytes(),raw)
        self.assertEqual(self.report_path.read_bytes(),measured)
        self.assertEqual(references.validate_profile(first),[])

    def test_saved_observations_keep_missing_source_events_in_delivery_history(self):
        path, _ = self.profile()
        spec = self.mapping_spec(path)
        self.bundle['timeline']['segments'][0]['source_in'] = .5
        timing = event_map(self.root,self.bundle,spec)
        saved = {'candidate':{'path':'output.mp4','sha256':'a'*64},
                 'events':[{'id':'start','source':[0,1],'candidate':[0,.5]}],'timing':timing}
        identity = content_hash(saved)
        receipt = {'comparison_hash':identity,'reviewer':'fixture',
                   'observations':{'start':{'status':'unverified','note':''}}}
        folder = self.root/'reviews/comparisons'/identity
        atomic_json(folder/'comparison.json',saved)
        atomic_json(folder/('observations-'+content_hash(receipt)+'.json'),receipt)
        history = event_history(self.root,{})
        self.assertIn('opening',history[0]['source_event_issues'][0])
        self.assertEqual(history[0]['source_profile']['events'][0]['id'],'opening')
        self.assertEqual(history[0]['events'][0]['status'],'unverified')

    def test_required_opening_is_rechecked_after_trimming_with_an_explicit_change_reason(self):
        path, _ = self.profile()
        spec = self.mapping_spec(path)
        result = event_map(self.root,self.bundle,spec)
        self.assertTrue(all(e['fully_retained'] for e in result['source_event_coverage']))
        self.assertEqual(result['events'][0]['source'],[0,1])
        self.bundle['timeline']['segments'][0]['source_in'] = .5
        incomplete = event_map(self.root,self.bundle,spec)
        self.assertIn('opening', incomplete['source_event_issues'][0])
        spec['source_event_changes'] = {'opening':'Remove the half-second preparation before the main gesture.'}
        result = event_map(self.root,self.bundle,spec)
        self.assertEqual(result['source_event_issues'], [])
        opening = result['source_event_coverage'][0]
        self.assertFalse(opening['fully_retained'])
        self.assertEqual(opening['retained_source_seconds'],.5)
        self.assertIn('change_reason',opening)
        self.assertEqual(result['source_profile']['events'][0]['status'],'unverified')

    def test_wrong_source_event_or_changed_profile_is_rejected(self):
        path, _ = self.profile()
        spec = self.mapping_spec(path)
        bad = copy.deepcopy(spec)
        bad['events'][0]['source_event_id'] = 'unknown'
        with self.assertRaisesRegex(ConfigError,'unknown source event'):
            event_map(self.root,self.bundle,bad)
        bad = copy.deepcopy(spec)
        bad['events'][0]['source'] = [.5,1.5]
        with self.assertRaisesRegex(ConfigError,'outside the original source event'):
            event_map(self.root,self.bundle,bad)
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ConfigError,'profile bytes changed'):
            event_map(self.root,self.bundle,spec)


if __name__ == '__main__':
    unittest.main()
