"""Actual policy transitions preserve tasks, approvals and versioned plan checks."""
import copy
import io
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'videocreate/src'), str(ROOT/'tests')]
from videocreate import production, production_policy as service, production_continue
from videocreate.config.storage import ConfigError, atomic_json, load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.profiles import create
from videocreate.planning.project import save_bundle, load_project
from videocreate.production_commands import production_command
from videocreate.runtime.state import read_state, save_state


class ProductionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'流程项目';save_bundle(self.root, smart_car())
        self.guard = patch('urllib.request.urlopen', side_effect=AssertionError('No real network'))
        self.guard.start();self.addCleanup(self.guard.stop)

    def options(self, root=None, required=None, mode='auto-within-authorization'):
        return {'mode': mode, 'required_stages': required or [], 'reason': 'Continue current plan, retaining specified checks',
            'source_token': service.describe(root or self.root)['source_token']}

    def save(self, root=None, **options):
        root = root or self.root
        value = options or self.options(root)
        preview = service.preview(root, **value)
        return service.save(root, **value, preview_token=preview['preview_token'])

    def test_offline_preview_explains_next_and_never_writes_or_approves(self):
        before = {p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with patch('videocreate.cli.read_config', side_effect=AssertionError('No provider config')):
            current = service.describe(self.root)
            preview = service.preview(self.root, **self.options(required=['script']))
        self.assertEqual(current['next']['id'], 'theme')
        self.assertEqual(preview['after']['next']['id'], 'script')
        theme = next(s for s in preview['after']['stages'] if s['id']=='theme')
        self.assertEqual(theme['status'], 'ready')
        self.assertEqual(theme['progression'], 'automatic-without-approval')
        self.assertFalse(theme['review_required'])
        self.assertEqual(preview['before']['review'], preview['after']['review'])
        self.assertFalse((self.root/'production').exists());self.assertFalse((self.root/'state.json').exists())
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.glob('*.json')})

    def test_required_checkpoints_advance_by_current_input_and_reopen_after_edit(self):
        self.save(**self.options(required=['script','theme']))
        self.assertEqual(production.status(self.root)['next']['id'], 'theme')
        for stage in ('theme', 'script'):
            current = service.describe(self.root)
            decision = service.inspect_stage(self.root, stage, source_token=current['source_token'])
            production.checkpoint(self.root, stage, reason='Inspected current plan fixture', expected_hash=decision['input_hash'])
        self.assertEqual(production.status(self.root)['next']['id'], 'generation')
        self.assertEqual(production_continue.describe(self.root)['action'], 'generation')
        director = load_project(self.root)['director'];director['shots'][0]['actions'][0]['description'] += ' A second gesture.'
        atomic_json(self.root/'director.json', director)
        current = production.status(self.root)
        self.assertEqual(current['next']['id'], 'script')
        self.assertEqual(next(s['status'] for s in current['stages'] if s['id']=='script'), 'stale')
        self.assertEqual(read_state(self.root)['jobs'], {})

    def test_source_changes_in_plan_tasks_or_policy_reject_old_preview_without_overwrite(self):
        for change in ('plan', 'state', 'policy'):
            with self.subTest(change=change):
                root = self.root.parent/change;save_bundle(root, smart_car())
                value = self.options(root);preview = service.preview(root, **value)
                if change == 'plan':
                    brief = load_project(root)['brief'];brief['audience']='Changed audience';atomic_json(root/'brief.json', brief)
                elif change == 'state':
                    save_state(root, {'schema_version':3, 'jobs':{'job-001':{'status':'submission_unknown'}}, 'ledger':[]})
                else:production.policy(root, 'auto-within-authorization', 'An intervening instruction')
                before = (root/'production/stages.json').read_bytes() if (root/'production/stages.json').exists() else None
                with self.assertRaisesRegex(ConfigError, 'source changed'):
                    service.save(root, **value, preview_token=preview['preview_token'])
                self.assertEqual(before, (root/'production/stages.json').read_bytes() if before else None)

    def test_preview_token_binds_reason_mode_and_exact_review_set(self):
        value = self.options(required=['theme']);preview = service.preview(self.root, **value)
        for key, item in [('reason','A different instruction'), ('mode','assisted'), ('required_stages',['script'])]:
            with self.subTest(key=key), self.assertRaisesRegex(ConfigError, 'preview changed'):
                service.save(self.root, **{**value,key:item}, preview_token=preview['preview_token'])
        self.assertFalse((self.root/'production/stages.json').exists())

    def test_invalid_options_and_media_stage_waivers_fail_before_writes(self):
        base = self.options()
        for change in ({'reason':''}, {'mode':'always-run'}, {'required_stages':['review']},
                {'required_stages':['theme','theme']}, {'required_stages':'theme'}, {'required_stages':[True]}, {'source_token':''}):
            with self.subTest(change=change), self.assertRaises(ConfigError):service.preview(self.root, **{**base,**change})
        with self.assertRaises(ConfigError):service.save(self.root, **base, preview_token='')
        self.assertFalse((self.root/'production/stages.json').exists())

    def test_legacy_record_migrates_without_dropping_checkpoints_history_or_custom_data(self):
        stage = production.status(self.root)['stages'][0]
        production.checkpoint(self.root, 'theme', reason='Prior inspection', expected_hash=stage['input_hash'])
        record = load_json(self.root/'production/stages.json');record['extension']={'owner':'fixture'}
        atomic_json(self.root/'production/stages.json', record)
        self.assertEqual(record['schema_version'], 1)
        self.save(**self.options(required=['script']))
        saved = load_json(self.root/'production/stages.json')
        self.assertEqual(saved['schema_version'], 2)
        self.assertEqual(saved['decisions'], record['decisions'])
        self.assertEqual(saved['history'][:-1], record['history'])
        self.assertEqual(saved['extension'], record['extension'])
        production.policy(self.root, 'assisted', 'Return to gradual checks')
        self.assertEqual(production.status(self.root)['required_authoring_stages'], ['script'])
        self.assertEqual(production.status(self.root)['next']['id'], 'outline')

    def test_noop_is_not_a_new_history_entry_or_an_implicit_checkpoint(self):
        self.save();path=self.root/'production/stages.json';before=path.read_bytes()
        result=self.save()
        self.assertFalse(result['changed']);self.assertEqual(path.read_bytes(), before)
        self.assertEqual(load_json(path)['decisions'], {})

    def test_all_media_branches_keep_required_checks_and_explicit_skip_reasons(self):
        for profile in ('scenic','mixed-video','edit-only','image-only','gif-only','gif-local'):
            with self.subTest(profile=profile):
                root=self.root.parent/profile;save_bundle(root,create(profile,topic='Fixture'))
                value=self.options(root,required=['theme','script','references'])
                self.save(root,**value);current=service.describe(root)
                self.assertEqual(current['required_authoring_stages'], ['theme','script','references'])
                for row in current['stages']:
                    if row['status']=='skipped':
                        self.assertEqual(row['progression'],'not-applicable');self.assertTrue(row.get('reason'))
                if profile in {'image-only','gif-only','scenic'}:self.assertEqual(current['next']['id'],'theme')
                elif profile=='gif-local':self.assertEqual(current['next']['id'],'import-gif-source')
                elif profile=='edit-only':self.assertEqual(current['next']['id'],'import-local-sources')
                else:self.assertEqual(current['next']['id'],'author-mixed-sources')

    def test_unknown_tasks_and_invalid_plans_take_precedence_over_policy_gates(self):
        for profile in ('scenic','image-only'):
            root=self.root.parent/profile;bundle=create(profile,topic='Fixture');save_bundle(root,bundle)
            jid=(bundle['generation-plan'].get('image_jobs') or bundle['generation-plan']['jobs'])[0]['id']
            before={'schema_version':3,'jobs':{jid:{'status':'submission_unknown'}},'ledger':[]}
            save_state(root,before)
            self.save(root,**self.options(root,required=['theme']))
            self.assertEqual(service.describe(root)['next']['id'],'reconcile')
            self.assertEqual(read_state(root),before)
        director=load_project(self.root)['director'];director['shots'][0]['scene_id']='missing-scene'
        atomic_json(self.root/'director.json',director)
        self.save(**self.options(required=['script']))
        self.assertEqual(production.status(self.root)['next']['id'],'repair-plan')

    def test_inspection_reads_actual_non_next_stage_and_rejects_unsupported_or_stale(self):
        current=service.describe(self.root)
        result=service.inspect_stage(self.root,'script',source_token=current['source_token'])
        self.assertEqual(result['value'],production.script_projection(load_project(self.root)))
        self.assertEqual(result['edit_layer'],'director');self.assertEqual(result['stage'],'script')
        for stage in ('review','generation','delivery'):
            with self.assertRaises(ConfigError):service.inspect_stage(self.root,stage,source_token=current['source_token'])
        self.save()
        with self.assertRaisesRegex(ConfigError,'source changed'):
            service.inspect_stage(self.root,'script',source_token=current['source_token'])

    def test_concurrent_saves_from_same_source_commit_once_and_keep_state(self):
        first=self.options(required=['theme']);second={**first,'required_stages':['script']}
        values=[(v,service.preview(self.root,**v)['preview_token']) for v in (first,second)]
        barrier=threading.Barrier(2)
        def apply(item):
            options,token=item;barrier.wait()
            try:service.save(self.root,**options,preview_token=token);return 'saved'
            except ConfigError:return 'stale'
        with ThreadPoolExecutor(max_workers=2) as executor:outcomes=list(executor.map(apply,values))
        self.assertCountEqual(outcomes,['saved','stale'])
        self.assertEqual(len(load_json(self.root/'production/stages.json')['history']),1)
        self.assertEqual(read_state(self.root)['jobs'],{})

    def test_cli_preview_save_share_service_and_reject_unused_policy_arguments(self):
        def cli(arguments):
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(production_command(arguments),0)
            return json.loads(output.getvalue())
        current=cli(['policy-show',str(self.root)])
        arguments=[str(self.root),'--mode','auto-within-authorization','--review-stage','script',
            '--reason','Continue fixture with script check','--source-token',current['source_token']]
        preview=cli(['policy-preview',*arguments]);self.assertFalse((self.root/'production').exists())
        saved=cli(['policy-save',*arguments,'--preview-token',preview['preview_token']])
        self.assertEqual(saved['next']['id'],'script')
        for arguments in (['policy-show',str(self.root),'--review-stage','theme'],
                ['status',str(self.root),'--review-stage','theme'],
                ['policy-preview',*arguments,'--preview-token','wrong']):
            with self.assertRaises(ConfigError):production_command(arguments)

    def test_policy_save_keeps_reviewed_image_evidence_and_final_video_pending(self):
        from PIL import Image
        from videocreate.local_sources import import_image
        from videocreate.review import receipts
        from videocreate.timeline.render import render
        root=self.root.parent/'local';save_bundle(root,create('edit-only'))
        source=self.root.parent/'still.png';Image.new('RGB',(128,72),(220,30,20)).save(source)
        import_image(root,source,source_id='still',seconds=.25)
        bundle=load_project(root);bundle['timeline'].update(width=128,height=72)
        atomic_json(root/'timeline.json',bundle['timeline']);render(root,bundle,read_state(root))
        packet=receipts.template(root,bundle);packet['reviewer_id']='synthetic-contract-fixture'
        packet['assets']={'still':packet['assets']['still']}
        for layer,row in packet['assets']['still']['layers'].items():
            if layer not in packet['assets']['still']['required_layers']:row['status']='not_applicable';continue
            row.update(status='pass',method='human-image',observations=['Synthetic receipt fixture, not actual human acceptance'],
                evidence=[{'path':packet['assets']['still']['path'],'sha256':packet['assets']['still']['sha256'],'kind':'image'}])
        receipts.apply(root,bundle,packet)
        before={str(p.relative_to(root)):p.read_bytes() for directory in ('reviews','deliverables')
            for p in (root/directory).rglob('*') if p.is_file()}
        state=read_state(root);self.save(root,**self.options(root))
        self.assertEqual(production.status(root)['next']['id'],'review')
        self.assertEqual(production.status(root)['review']['status'],'review_pending')
        self.assertEqual(production.status(root)['local_sources'][0]['content_status'],'reviewed')
        self.assertEqual(read_state(root),state)
        self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for directory in ('reviews','deliverables')
            for p in (root/directory).rglob('*') if p.is_file()})


if __name__=='__main__':unittest.main()
