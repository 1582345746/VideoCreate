import concurrent.futures
import tempfile
import unittest
import wave
from pathlib import Path

from videocreate import asset_library as library
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import load_project, save_bundle


class AssetLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.target, self.store = (self.root / n for n in ('source', 'target', 'store'))
        bundle = smart_car()
        asset = bundle['director']['assets'][0]
        self.aid = asset['id']
        asset['references'] = ['reference.png']
        save_bundle(self.source, bundle)
        # Minimal format fixture; this library never claims visual approval or full image decode.
        (self.source / 'reference.png').write_bytes(b'\x89PNG\r\n\x1a\noriginal fixture')
        save_bundle(self.target, smart_car())

    def publish(self):
        return library.publish(self.source, self.store, self.aid, 'hero', title='主角', tags=['喜剧'])

    def test_reuse_copies_immutable_versions_and_does_not_inherit_approval(self):
        first = self.publish()
        imported = library.import_asset(self.target, self.store, 'hero', first['version'], 'new-hero')
        copied = self.target / imported['asset']['references'][0]
        before = copied.read_bytes()
        (self.source / 'reference.png').write_bytes(b'\x89PNG\r\n\x1a\nnew fixture')
        second = self.publish()
        self.assertNotEqual(first['version'], second['version'])
        self.assertEqual(copied.read_bytes(), before)
        self.assertEqual(len(library.catalog(self.store)['items']), 2)
        self.assertEqual(imported['content_status'], 'unverified')
        self.assertTrue(library.import_asset(self.target, self.store, 'hero', first['version'], 'new-hero')['reused'])
        with self.assertRaisesRegex(ConfigError, 'already exists'):
            library.import_asset(self.target, self.store, 'hero', second['version'], 'new-hero')

    def test_changed_library_bytes_fail_before_project_mutation(self):
        item = self.publish()
        manifest = Path(item['manifest'])
        media = manifest.parent / load_json(manifest)['payload']['media'][0]['file']
        media.write_bytes(b'tampered')
        before = (self.target / 'director.json').read_bytes()
        with self.assertRaisesRegex(ConfigError, 'media changed'):
            library.import_asset(self.target, self.store, 'hero', item['version'], 'new-hero')
        self.assertEqual((self.target / 'director.json').read_bytes(), before)

    def test_changed_project_snapshot_is_not_silently_repaired(self):
        item = self.publish()
        result = library.import_asset(self.target, self.store, 'hero', item['version'], 'new-hero')
        (self.target / result['asset']['references'][0]).write_bytes(b'edited locally')
        with self.assertRaisesRegex(ConfigError, 'snapshot bytes changed'):
            library.import_asset(self.target, self.store, 'hero', item['version'], 'new-hero')

    def test_version_conflict_and_unsafe_paths(self):
        item = self.publish()
        manifest = load_json(Path(item['manifest']))
        manifest['payload']['descriptor']['description'] = 'changed'
        atomic_json(Path(item['manifest']), manifest)
        self.assertFalse(library.catalog(self.store)['ok'])
        for name in ('../outside', 'CON', 'con', 'Hero', 'lpt1'):
            with self.assertRaises(ConfigError):
                library.publish(self.source, self.store, self.aid, name)
        with self.assertRaises(ConfigError):
            library.describe(self.store, 'hero', '../outside')

    def test_concurrent_add_and_import_are_idempotent(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            revisions = list(executor.map(lambda _: self.publish()['version'], range(3)))
        self.assertEqual(len(set(revisions)), 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: library.import_asset(
                self.target, self.store, 'hero', revisions[0], 'new-hero'), range(3)))
        self.assertEqual(sum(not r['reused'] for r in results), 1)
        self.assertEqual(sum(a['id'] == 'new-hero' for a in load_project(self.target)['director']['assets']), 1)

    def test_voice_references_copy_audio_and_remain_unverified(self):
        bundle = load_project(self.source)
        bundle['director']['assets'].append({'id': 'voice-a', 'kind': 'voice', 'description': '声音样本', 'references': ['voice.wav']})
        atomic_json(self.source / 'director.json', bundle['director'])
        with wave.open(str(self.source / 'voice.wav'), 'wb') as out:
            out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            out.writeframes(b'\0\0' * 16000)
        result = library.publish(self.source, self.store, 'voice-a', 'voice')
        imported = library.import_asset(self.target, self.store, 'voice', result['version'], 'voice-b')
        self.assertEqual((self.target / imported['asset']['references'][0]).read_bytes(), (self.source / 'voice.wav').read_bytes())
        self.assertEqual(imported['content_status'], 'unverified')

    def test_impact_lists_actual_direct_and_transitive_jobs_without_editing(self):
        result = library.impact(self.source, self.aid)
        self.assertTrue(result['shots'])
        self.assertTrue(result['jobs'])
        self.assertFalse((self.source / 'state.json').exists())
