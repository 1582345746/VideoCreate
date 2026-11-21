import base64
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts'),str(ROOT/'tests')]
from videocreate import image_production as images,production
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.planning.project import load_project,save_bundle,validate_plan
from videocreate.planning.profiles import create
from videocreate.runtime.state import read_state,save_state
from videocreate.review.receipts import review_image
from videocreate.production_metrics import report
from videocreate.commands import plan_command,review_command
from test_v3_config import config
from test_image_model_routing import PNG
from test_gif_media import gif_fixture


class ImageProductionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'images'
        self.config=config();self.store=Path(temporary.name)/'config'
        save_bundle(self.root,create('image-only',title='Image plan',topic='A boat at sunset'))

    def bundle(self):return load_project(self.root)

    def run_images(self,payload=PNG,**kwargs):
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload',return_value={
                'data':[{'b64_json':base64.b64encode(payload).decode()}]}) as create_call:
            result=images.run(self.root,self.bundle(),self.config,self.store,**kwargs)
        return result,create_call

    def review(self,identity='image-001',status='pass',temporal=False):
        return review_image(self.root,job_id=identity,status=status,reviewer_id='synthetic-fixture',
            observation='Synthetic receipt fixture; not actual content acceptance',temporal_observation=temporal)

    def test_explicit_profiles_have_no_video_jobs_and_reject_video_content_or_wrong_format(self):
        for profile in ('image-only','gif-only'):
            bundle=create(profile,topic='A moving boat')
            self.assertTrue(validate_plan(bundle)['ok'])
            self.assertEqual(bundle['generation-plan']['jobs'],[])
            self.assertEqual(bundle['timeline']['segments'],[])
            with self.assertRaises(ConfigError):create(profile,seconds=5)
        bundle=self.bundle();bundle['generation-plan']['image_jobs'][0]['output_format']='gif'
        self.assertFalse(validate_plan(bundle)['ok'])
        bundle=self.bundle();bundle['generation-plan']['image_jobs'][0]['prompt']=' '
        self.assertFalse(validate_plan(bundle)['ok'])
        other=create('scenic',seconds=10);other['generation-plan']['image_jobs']=self.bundle()['generation-plan']['image_jobs']
        self.assertFalse(validate_plan(other)['ok'])

    def test_new_image_plan_status_skips_unused_stages_and_has_zero_video_requirements(self):
        production.policy(self.root,'auto-within-authorization','User requested image workflow')
        current=production.status(self.root)
        self.assertTrue(current['ok'])
        self.assertEqual(current['next']['id'],'generation')
        stages={s['id']:s['status'] for s in current['stages']}
        for identity in ('outline','script','editing'):self.assertEqual(stages[identity],'skipped')
        self.assertEqual(current['jobs'][0]['kind'],'image')
        self.assertEqual(current['budget']['requests'],0)

    def test_whole_batch_preflight_rejects_bad_later_image_before_any_create(self):
        bundle=self.bundle();second=copy.deepcopy(bundle['generation-plan']['image_jobs'][0])
        second.update(id='image-002',size='999x999');bundle['generation-plan']['image_jobs'].append(second)
        atomic_json(self.root/'generation-plan.json',bundle['generation-plan'])
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send:
            with self.assertRaises(ConfigError):images.run(self.root,bundle,self.config,self.store)
            send.assert_not_called()
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_unresolved_price_tier_blocks_image_create_without_budget_or_attempt(self):
        from videocreate.config.management import migrate
        self.config=migrate(self.config,ask=False)
        self.config['budget'].update(currency='USD',max_total=2,unknown_price_policy='block')
        self.config['bindings']['image-primary']['pricing']={'currency':'USD','tiers':[
            {'when':{},'per_request':2},{'when':{'resolution':'720p'},'per_request':3}]}
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send:
            preview=images.compile_plan(self.root,self.bundle(),self.config,self.store)
            self.assertIsNone(preview['jobs'][0]['estimate'])
            result=images.run(self.root,self.bundle(),self.config,self.store)
            self.assertFalse(result['ok'])
            self.assertIn('Price is unknown',result['images'][0]['error'])
            send.assert_not_called()
        state=read_state(self.root)
        self.assertEqual(state['ledger'],[])
        self.assertEqual(state['jobs'],{})

    def test_create_once_resume_pins_original_image_and_delivery_requires_review(self):
        result,created=self.run_images();self.assertTrue(result['ok']);created.assert_called_once()
        self.config['defaults']['image_model']='nonexistent-new-default'
        repeated,created=self.run_images();self.assertTrue(repeated['ok']);created.assert_not_called()
        current=production.status(self.root)
        self.assertEqual(current['next']['id'],'theme')
        package=production.delivery(self.root)
        self.assertEqual(package['status'],'review_pending')
        self.assertEqual(package['budget']['requests'],1)
        self.assertNotIn('video',package)
        self.review()
        self.assertEqual(production.delivery(self.root)['status'],'accepted_delivery')

    def test_image_prompt_change_blocks_old_review_until_explicit_replan(self):
        self.run_images();self.review()
        bundle=self.bundle();bundle['generation-plan']['image_jobs'][0]['prompt']='A different boat'
        atomic_json(self.root/'generation-plan.json',bundle['generation-plan'])
        self.assertEqual(production.impact(self.root)['changed_job_inputs'],['image-001'])
        self.assertEqual(production.status(self.root)['jobs'][0]['status'],'stale')
        with self.assertRaises(ConfigError):self.review()
        with self.assertRaises(ConfigError):self.run_images()
        with self.assertRaises(ConfigError):self.run_images(retry='replan',reason='change without selected ID')
        result,created=self.run_images(job_ids=['image-001'],retry='replan',reason='User changed subject')
        self.assertTrue(result['ok']);created.assert_called_once()
        self.assertEqual(read_state(self.root)['jobs']['image-001']['content_status'],'unverified')
        self.assertEqual(len(read_state(self.root)['ledger']),2)

    def test_title_change_preserves_source_review_but_changed_result_bytes_blocks_delivery(self):
        self.run_images();self.review()
        project=load_json(self.root/'project.json');project['title']='New title';atomic_json(self.root/'project.json',project)
        self.assertEqual(production.impact(self.root)['changed_job_inputs'],[])
        self.assertEqual(production.delivery(self.root)['status'],'accepted_delivery')
        artifact=read_state(self.root)['jobs']['image-001']['artifact']
        (self.root/artifact['path']).write_bytes(PNG+b'changed')
        with self.assertRaises(ConfigError):production.delivery(self.root)

    def test_unknown_image_submission_preserves_attempt_and_never_recreates(self):
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload',side_effect=TimeoutError('Unknown create')) as send:
            result=images.run(self.root,self.bundle(),self.config,self.store)
            self.assertFalse(result['ok']);send.assert_called_once()
        before=read_state(self.root)
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send:
            with self.assertRaises(ConfigError):images.run(self.root,self.bundle(),self.config,self.store)
            held=images.compile_plan(self.root,self.bundle(),self.config,self.store)
            send.assert_not_called()
        self.assertEqual(held['jobs'][0]['status'],'held')
        self.assertEqual(read_state(self.root),before)
        self.assertEqual(production.status(self.root)['next']['id'],'reconcile')

    def test_animated_gif_needs_multiple_frames_and_temporal_receipt(self):
        self.root=self.root.parent/'gifs'
        save_bundle(self.root,create('gif-only',topic='A moving boat'))
        self.config['bindings']['image-primary'].setdefault('capability_overrides',{}).update(output_formats=['png','gif'],animated_output='supported')
        result,_=self.run_images(payload=gif_fixture((5,12)))
        self.assertTrue(result['ok'])
        with self.assertRaises(ConfigError):self.review()
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')
        self.review(temporal=True)
        package=production.delivery(self.root)
        self.assertEqual(package['status'],'accepted_delivery')
        self.assertTrue(package['artifacts'][0]['media']['animated'])
        metrics=report(self.root)
        self.assertEqual(metrics['images']['animated_current'],1)
        self.assertEqual(metrics['seconds']['generated_known'],0)

    def test_one_frame_gif_is_not_deliverable_animation(self):
        self.root=self.root.parent/'gifs'
        save_bundle(self.root,create('gif-only',topic='A moving boat'))
        self.config['bindings']['image-primary'].setdefault('capability_overrides',{}).update(output_formats=['png','gif'],animated_output='supported')
        result,_=self.run_images(payload=gif_fixture((5,)))
        self.assertFalse(result['ok'])
        self.assertEqual(read_state(self.root)['jobs']['image-001']['status'],'output_invalid')
        with self.assertRaises(ConfigError):production.delivery(self.root)

    def test_missing_or_tampered_receipt_never_approves_delivery(self):
        self.run_images();receipt=self.review()
        path=self.root/receipt['receipt'];value=load_json(path)
        path.unlink()
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')
        self.review()
        value['input_hash']='0'*64;atomic_json(path,value)
        state=read_state(self.root);state['jobs']['image-001']['review_receipt']=str(path.relative_to(self.root))
        save_state(self.root,state)
        self.assertEqual(production.delivery(self.root)['status'],'review_pending')
        self.review(status='fail');self.review(status='pass')
        self.assertEqual(production.delivery(self.root)['status'],'rejected')

    def test_changed_image_reference_blocks_entire_plan_before_request(self):
        reference=self.root/'assets/reference.png';reference.parent.mkdir(parents=True);reference.write_bytes(PNG)
        import hashlib
        bundle=self.bundle();job=bundle['generation-plan']['image_jobs'][0]
        job.update(operation='image-edit',references=[{'path':'assets/reference.png','sha256':hashlib.sha256(PNG).hexdigest()}])
        atomic_json(self.root/'generation-plan.json',bundle['generation-plan'])
        self.assertTrue(validate_plan(bundle,self.root)['ok'])
        reference.write_bytes(PNG+b'changed')
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send:
            with self.assertRaises(ConfigError):images.run(self.root,bundle,self.config,self.store)
            send.assert_not_called()
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_cli_offline_compile_route_review_status_and_page_support_pure_image(self):
        for action in ('compile','route'):
            with mock.patch('videocreate.cli.read_config',return_value=self.config),redirect_stdout(io.StringIO()) as captured:
                self.assertEqual(plan_command([action,str(self.root)]),0)
            value=json.loads(captured.getvalue());self.assertEqual(value['paid_creates'],0)
            self.assertEqual(value['jobs'][0]['prepared']['operation'],'text-to-image')
        self.run_images()
        for action in ('status','page'):
            with redirect_stdout(io.StringIO()) as captured:self.assertEqual(review_command([action,str(self.root)]),0)
            value=json.loads(captured.getvalue());self.assertTrue(value['ok'])
        page=images.page(self.root,self.bundle())
        text=Path(page['page']).read_text(encoding='utf-8')
        self.assertIn('image-001',text);self.assertIn('approves nothing',text)
        self.assertEqual(report(self.root)['images']['completed_current'],1)

    def test_unselected_image_plan_returns_selection_required_without_any_create(self):
        from videocreate.config.management import migrate
        from videocreate.selection import SelectionRequired
        self.config=migrate(self.config)
        # Migration's existing ask policy is authoritative; remove any project selection.
        from videocreate.selection import policy
        self.assertEqual(policy(self.config,'image'),'ask')
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send:
            with self.assertRaises(SelectionRequired):images.run(self.root,self.bundle(),self.config,self.store)
            send.assert_not_called()
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_image_brief_export_is_read_only_and_preserves_request_contract(self):
        before=self.bundle()['generation-plan']
        output=production.script_export(self.root)
        self.assertTrue(output['read_only'])
        self.assertIn('A boat at sunset',Path(output['reading_copy']).read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ConfigError,'read-only'):production.import_script(self.root,{})
        self.assertEqual(self.bundle()['generation-plan'],before)

    def test_manager_pure_image_status_and_review_page_have_no_video_dependency_offscreen(self):
        import tkinter as tk
        from videocreate.manager import Manager
        from videocreate.manager_projects import open_panel
        from videocreate.config.management import migrate
        self.run_images()
        window=tk.Tk();window.withdraw();self.addCleanup(window.destroy)
        path=self.store/'config.json';atomic_json(path,migrate(self.config));before=path.read_bytes()
        manager=Manager(window,path)
        with mock.patch.object(manager,'error') as error, mock.patch('urllib.request.urlopen') as network:
            panel=open_panel(manager,self.root);panel.withdraw();window.update_idletasks()
            error.assert_not_called();network.assert_not_called()
            panel.destroy()
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
