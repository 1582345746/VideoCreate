"""Candidate builds must bind edited frontend/metadata to the shipped static bytes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from videocreate.config.schema import configuration_schema


SPEC=importlib.util.spec_from_file_location('web_candidate_build',Path(__file__).resolve().parents[1]/'tools/build_web_candidate.py')
build=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class CandidateBuildTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.output=self.root/'_local/attempt';self.output.mkdir(parents=True)
        for name in ('pyproject.toml','setup.py','MANIFEST.in','README.md',
                     'requirements/web.lock.txt','web/provider-config/package-lock.json',
                     'web/provider-config/src/App.vue','tools/build_web_candidate.py','tools/check_release.py'):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name,encoding='utf-8')
        self.static=self.root/'videocreate/src/videocreate/config_web/static'
        self.static.mkdir(parents=True);(self.static/'index.html').write_text('current page',encoding='utf-8')
        (self.static/'assets').mkdir();(self.static/'assets/app.js').write_text('current bundle',encoding='utf-8')

    def rebuild(self,command,**kwargs):
        dest=Path(command[command.index('--outDir')+1]);dest.mkdir()
        for p in self.static.rglob('*'):
            if p.is_file():
                q=dest/p.relative_to(self.static);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())

    def test_published_schema_gate_accepts_runtime_definition_without_rewriting_asset(self):
        schema=self.root/'videocreate/assets/schemas/videocreate.config.schema.json'
        schema.parent.mkdir(parents=True)
        # Whitespace is not semantic drift; validate without rewriting the asset.
        schema.write_text(json.dumps(configuration_schema(),indent=1)+'\n',encoding='utf-8')
        before=build.build_inputs(self.root)
        report=build.verify_published_schema(self.root,configuration_schema())
        self.assertTrue(report['matches_runtime'])
        self.assertEqual(report['sha256'],before[schema.relative_to(self.root).as_posix()])
        self.assertEqual(build.build_inputs(self.root),before)

    def test_missing_corrupt_and_stale_schema_stop_main_before_frontend_or_packaging(self):
        schema=self.root/'videocreate/assets/schemas/videocreate.config.schema.json'
        schema.parent.mkdir(parents=True)
        stale=configuration_schema()
        del stale['properties']['bindings']['additionalProperties']['properties']['pricing']['properties']['per_image']
        wrong_type=configuration_schema();wrong_type['properties']['revision']['minimum']=False
        for mode,raw in [('missing',None),('corrupt',b'{"broken":'),('non-UTF8',b'\xff'),
                         ('stale',json.dumps(stale).encode()),('nonobject',b'[]'),
                         ('boolean-for-number',json.dumps(wrong_type).encode())]:
            with self.subTest(mode=mode):
                if raw is None:
                    if schema.exists():schema.unlink()
                else:schema.write_bytes(raw)
                attempt=self.root/'_local'/mode
                before=build.build_inputs(self.root)
                with mock.patch.object(build,'ROOT',self.root), \
                     mock.patch.object(build.sys,'argv',['build_web_candidate.py','--output',str(attempt)]), \
                     mock.patch.object(build,'verify_frontend',side_effect=AssertionError('Frontend must not run')) as frontend, \
                     mock.patch.object(build.subprocess,'run',side_effect=AssertionError('Packaging must not run')) as run:
                    with self.assertRaisesRegex(RuntimeError,'Published configuration schema'):
                        build.main()
                frontend.assert_not_called();run.assert_not_called()
                self.assertEqual(build.build_inputs(self.root),before)
                self.assertFalse((attempt/'source').exists())
                self.assertFalse((attempt/'artifacts').exists())
                self.assertFalse((attempt/'candidate-build.json').exists())

    def test_matching_rebuild_keeps_workspace_static_bytes_and_uses_isolated_output(self):
        before=build.build_inputs(self.root)
        with mock.patch.object(build.shutil,'which',return_value='npm'),mock.patch.object(build.subprocess,'run',side_effect=self.rebuild) as run:
            report=build.verify_frontend(self.root,self.output)
        self.assertTrue(report['bundled_files_match'])
        self.assertFalse(report['workspace_static_modified'])
        self.assertEqual(build.build_inputs(self.root),before)
        self.assertEqual(Path(run.call_args.args[0][-2]).parent,self.output)
        self.assertEqual(run.call_args.kwargs['cwd'],self.root/'web/provider-config')

    def test_changed_or_extra_rebuilt_asset_rejects_candidate_without_overwriting_static(self):
        before=build.build_inputs(self.root)
        def changed(command,**kwargs):
            self.rebuild(command,**kwargs)
            output=Path(command[command.index('--outDir')+1]);(output/'assets/app.js').write_text('edited source bundle',encoding='utf-8')
        with mock.patch.object(build.shutil,'which',return_value='npm'),mock.patch.object(build.subprocess,'run',side_effect=changed):
            with self.assertRaisesRegex(RuntimeError,'stale or incomplete'):build.verify_frontend(self.root,self.output)
        self.assertEqual(build.build_inputs(self.root),before)

    def test_added_or_missing_rebuilt_asset_is_rejected_even_if_other_hashes_match(self):
        before=build.build_inputs(self.root)
        for mode in ('extra','missing'):
            output=self.output/mode;output.mkdir()
            def incomplete(command,**kwargs):
                self.rebuild(command,**kwargs)
                dest=Path(command[command.index('--outDir')+1])
                if mode=='extra':(dest/'unexpected.js').write_text('not in saved static')
                else:(dest/'index.html').unlink()
            with self.subTest(mode=mode),mock.patch.object(build.shutil,'which',return_value='npm'),mock.patch.object(build.subprocess,'run',side_effect=incomplete):
                with self.assertRaisesRegex(RuntimeError,'stale or incomplete'):build.verify_frontend(self.root,output)
        self.assertEqual(build.build_inputs(self.root),before)

    def test_build_input_manifest_covers_metadata_frontend_and_locks_excludes_node_cache(self):
        before=build.build_inputs(self.root)
        for name in ('README.md','pyproject.toml','requirements/web.lock.txt','web/provider-config/src/App.vue'):
            self.assertIn(name,before)
            p=self.root/name;prior=p.read_bytes();p.write_bytes(prior+b' changed')
            with self.assertRaisesRegex(RuntimeError,'Build inputs changed'):build.verify_inputs_unchanged(self.root,before)
            p.write_bytes(prior)
        cache=self.root/'web/provider-config/node_modules/cache.js';cache.parent.mkdir();cache.write_text('ignored')
        build.verify_inputs_unchanged(self.root,before)
        added=self.root/'web/provider-config/public/new.svg';added.parent.mkdir();added.write_text('<svg/>')
        with self.assertRaisesRegex(RuntimeError,'Build inputs changed'):build.verify_inputs_unchanged(self.root,before)

    def test_deleted_asset_or_input_and_failed_build_cannot_produce_success(self):
        before=build.build_inputs(self.root)
        (self.static/'assets/app.js').unlink()
        with self.assertRaisesRegex(RuntimeError,'Build inputs changed'):build.verify_inputs_unchanged(self.root,before)
        with mock.patch.object(build.shutil,'which',return_value='npm'),mock.patch.object(build.subprocess,'run',side_effect=RuntimeError('build failed')):
            with self.assertRaisesRegex(RuntimeError,'build failed'):build.verify_frontend(self.root,self.output)
        self.assertFalse((self.output/'candidate-build.json').exists())


if __name__=='__main__':unittest.main()
