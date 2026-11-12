"""Real authoring saves preserve task truth and reject stale form previews."""
import copy
import gc
import io
import json
import sys
import tempfile
import time
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'videocreate/scripts'),str(ROOT/'tests')]
from videocreate import authoring,production
from videocreate.cli import main
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.profiles import PROFILES
from videocreate.planning.project import load_project,save_bundle,compile_job
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state,save_state
from test_v3_config import config


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.parent=Path(temp.name);self.root=self.parent/'原始项目';save_bundle(self.root,smart_car())

    def change(self,layer='brief',**fields):
        current=authoring.describe(self.root,layer);value=copy.deepcopy(current['value']);value.update(fields)
        report=authoring.preview(self.root,layer,value,source_token=current['source_token'])
        return current,value,report

    def apply(self,current,value,report):
        return authoring.save(self.root,current['layer'],value,source_token=current['source_token'],preview_token=report['preview_token'])

    def task(self):
        bundle=load_project(self.root);job=bundle['generation-plan']['jobs'][0]
        compiled=compile_job(bundle,job,max_bytes=4096,root=self.root)
        record={'status':'queued','task_id':'known-original-task','input_hash':jobs.generation_inputs(self.root,bundle,job,compiled),
            'history':[{'candidate_id':'older-candidate'}]}
        save_state(self.root,{'schema_version':3,'jobs':{job['id']:record},'ledger':[]})
        return job['id']

    def test_all_profiles_create_separate_topic_audience_and_viewer_goal_without_config(self):
        with mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            for profile in PROFILES:
                target=self.parent/profile
                result=authoring.create(target,profile=profile,title='测试制作',topic='古代计算机',audience='大学生',viewer_goal='理解一个笑点')
                self.assertTrue(result['ok']);self.assertEqual(result['paid_creates'],0)
                brief=load_project(target)['brief']
                self.assertEqual((brief['topic'],brief['audience'],brief['viewer_goal']),('古代计算机','大学生','理解一个笑点'))
                self.assertFalse((target/'state.json').exists());self.assertFalse((target/'production/stages.json').exists())

    def test_creation_preserves_existing_empty_or_populated_destinations_and_rejects_bad_input_first(self):
        empty=self.parent/'already-there';empty.mkdir()
        for target in (empty,self.root):
            before={p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ConfigError,'already exists'):authoring.create(target,profile='mixed-video',title='New')
            self.assertEqual({p.relative_to(target).as_posix():p.read_bytes() for p in target.rglob('*') if p.is_file()},before)
        invalid=self.parent/'invalid'
        with self.assertRaises(ConfigError):authoring.create(invalid,profile='image-only',title='New',seconds=5)
        self.assertFalse(invalid.exists())
        with self.assertRaises(ConfigError):authoring.create(invalid,profile='mixed-video',title=' ')
        self.assertFalse(invalid.exists())

    def test_show_and_preview_are_offline_and_create_no_production_or_task_records(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        with mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            _,_,report=self.change(topic='新的主题')
        self.assertEqual(report['paid_creates'],0);self.assertTrue(report['changed_paths'])
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)
        self.assertFalse((self.root/'production').exists());self.assertFalse((self.root/'state.json').exists())

    def test_concurrent_project_creation_claims_one_directory_without_overwriting_the_winner(self):
        target=self.parent/'shared-destination'
        def create(title):
            try:
                authoring.create(target,profile='mixed-video',title=title)
                return title
            except ConfigError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,['First','Second']))
        winners=[title for title in results if title is not None]
        self.assertEqual(len(winners),1);self.assertEqual(load_project(target)['project']['title'],winners[0])

    def test_save_backs_up_only_edited_layer_and_preserves_tasks_candidates_ledger_and_stage_decisions(self):
        jid=self.task();before={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        stage=production.status(self.root)['stages'][0]
        production.checkpoint(self.root,'theme',reason='Prior specification',expected_hash=stage['input_hash'])
        decisions=(self.root/'production/stages.json').read_bytes()
        current,value,report=self.change(topic='电脑修复',audience='新观众',viewer_goal='记住反转')
        self.assertFalse(report['existing_tasks'][0]['inputs_changed'])
        result=self.apply(current,value,report)
        self.assertTrue(result['changed']);self.assertEqual(load_json(Path(result['backup'])),current['value'])
        self.assertEqual(load_json(self.root/'brief.json'),value)
        for name,data in before.items():
            if name!='brief.json':self.assertEqual((self.root/name).read_bytes(),data)
        self.assertEqual((self.root/'production/stages.json').read_bytes(),decisions)
        after=production.status(self.root);self.assertEqual(after['stages'][0]['status'],'stale')
        self.assertEqual(read_state(self.root)['jobs'][jid]['task_id'],'known-original-task')

    def test_generation_spec_preview_reports_existing_task_changes_without_mutating_or_recreating(self):
        jid=self.task();before=(self.root/'state.json').read_bytes()
        current,value,report=self.change(aspect_ratio='16:9')
        self.assertIn(jid,report['impact']['changed_job_inputs'])
        self.assertTrue(report['existing_tasks'][0]['inputs_changed'])
        with mock.patch('videocreate.runtime.jobs.client') as client:
            self.apply(current,value,report);client.assert_not_called()
        self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_semantically_incomplete_outline_saves_as_draft_but_generation_remains_blocked(self):
        self.task();current,value,report=self.change('story',beats=[])
        self.assertFalse(report['plan_validation']['ok'])
        self.assertEqual(self.apply(current,value,report)['status'],'authoring_saved')
        before=(self.root/'state.json').read_bytes()
        with mock.patch('videocreate.runtime.jobs.client') as client:
            with self.assertRaises(ConfigError):jobs.generate(self.root,config(),store_root=self.parent/'config')
            client.assert_not_called()
        self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_schema_invalid_edits_and_workflow_switch_are_rejected_before_any_write(self):
        current=authoring.describe(self.root,'brief');before=(self.root/'brief.json').read_bytes()
        for update in ({'unexpected':'bad'},{'target_seconds':0},{'workflow_profile':'mixed-video'}):
            value={**current['value'],**update}
            with self.assertRaises(ConfigError):authoring.preview(self.root,'brief',value,source_token=current['source_token'])
        self.assertEqual((self.root/'brief.json').read_bytes(),before);self.assertFalse((self.root/'production').exists())

    def test_unrelated_plan_change_invalidates_form_and_preserves_newer_content(self):
        current,value,report=self.change(topic='Stale form')
        timeline=load_json(self.root/'timeline.json');timeline['subtitles']=[{'text':'Newer edit','start':0,'end':1}]
        atomic_json(self.root/'timeline.json',timeline);before=(self.root/'brief.json').read_bytes()
        with self.assertRaisesRegex(ConfigError,'content changed'):self.apply(current,value,report)
        self.assertEqual((self.root/'brief.json').read_bytes(),before)
        self.assertEqual(load_json(self.root/'timeline.json'),timeline)

    def test_changed_form_value_or_task_state_after_preview_requires_new_preview(self):
        self.task();current,value,report=self.change(topic='Previewed topic')
        with self.assertRaisesRegex(ConfigError,'after preview'):self.apply(current,{**value,'topic':'Another topic'},report)
        state=read_state(self.root);state['jobs']['job-001']['status']='in_progress';save_state(self.root,state)
        with self.assertRaisesRegex(ConfigError,'after preview'):self.apply(current,value,report)
        self.assertNotEqual(load_json(self.root/'brief.json').get('topic'),value['topic'])
        updated=authoring.preview(self.root,'brief',value,source_token=current['source_token'])
        self.assertTrue(self.apply(current,value,updated)['changed'])

    def test_failed_atomic_save_keeps_current_layer_and_original_backup(self):
        current,value,report=self.change(topic='A failed save');target=self.root/'brief.json';before=target.read_bytes()
        original=authoring.atomic_json
        def fail(path,payload):
            if path==target:raise OSError('Synthetic save failure')
            return original(path,payload)
        with mock.patch.object(authoring,'atomic_json',side_effect=fail):
            with self.assertRaises(OSError):self.apply(current,value,report)
        self.assertEqual(target.read_bytes(),before)
        backups=list((self.root/'production/backups').glob('*.brief.json'))
        self.assertEqual(len(backups),1);self.assertEqual(load_json(backups[0]),current['value'])

    def test_task_change_between_preparation_and_commit_is_rejected_and_probe_stays_outside_lock(self):
        self.task();current,value,report=self.change(topic='Prepared topic');original=authoring.state_lock;inside=[]
        before=(self.root/'brief.json').read_bytes()
        @contextmanager
        def changed(root):
            state=read_state(root);state['jobs']['job-001']['status']='in_progress';save_state(root,state)
            with original(root):
                inside.append(True)
                yield
                inside.pop()
        validate=authoring.validate_plan
        def outside(*args):
            self.assertFalse(inside,'Media validation must not hold the task-state lock')
            return validate(*args)
        with mock.patch.object(authoring,'state_lock',side_effect=changed),mock.patch.object(authoring,'validate_plan',side_effect=outside):
            with self.assertRaisesRegex(ConfigError,'during save preparation'):self.apply(current,value,report)
        self.assertEqual((self.root/'brief.json').read_bytes(),before)

    def test_custom_layer_path_is_respected_and_noop_save_does_not_create_backup(self):
        project=load_json(self.root/'project.json');project['files']['brief']='layers/specification.json'
        (self.root/'layers').mkdir();(self.root/'brief.json').rename(self.root/'layers/specification.json')
        atomic_json(self.root/'project.json',project)
        current,value,report=self.change()
        self.assertFalse(self.apply(current,value,report)['changed']);self.assertFalse((self.root/'production').exists())
        current,value,report=self.change(topic='Mapped specification');self.apply(current,value,report)
        self.assertEqual(load_json(self.root/'layers/specification.json')['topic'],'Mapped specification')
        self.assertFalse((self.root/'brief.json').exists())

    def test_outline_is_readonly_projection_and_includes_cause_state_evidence_and_shot_coverage(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')};result=authoring.outline(self.root)
        reading=Path(result['reading_copy']).read_text(encoding='utf-8');bundle=load_project(self.root)
        self.assertIn(bundle['story']['beats'][0]['id'],reading);self.assertIn('发生前',reading)
        self.assertIn(bundle['director']['shots'][0]['id'],reading)
        Path(result['reading_copy']).write_text('Edited reading copy',encoding='utf-8')
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)

    def test_animation_outline_uses_its_authoring_source(self):
        project=load_json(self.root/'project.json');project['files']['animation']='animation.json'
        atomic_json(self.root/'animation.json',{});atomic_json(self.root/'project.json',project)
        with self.assertRaisesRegex(ConfigError,'animation sidecar'):authoring.describe(self.root,'story')

    def test_cli_roundtrip_uses_explicit_preview_token_and_never_reads_config(self):
        def call(args):
            with redirect_stdout(io.StringIO()) as output:
                code=main(['authoring',*args])
            return code,json.loads(output.getvalue())
        target=self.parent/'CLI 新项目'
        with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No config')):
            code,result=call(['create',str(target),'--profile','mixed-video','--title','CLI draft','--topic','计算机'])
            self.assertEqual(code,0)
            _,current=call(['show',str(target),'--layer','brief']);value=current['value'];value['audience']='大学生'
            exchange=self.parent/'brief-edit.json';atomic_json(exchange,value)
            args=[str(target),'--layer','brief','--file',str(exchange),'--source-token',current['source_token']]
            code,report=call(['preview',*args]);self.assertEqual(code,0)
            code,saved=call(['save',*args,'--preview-token',report['preview_token']]);self.assertEqual(code,0)
            self.assertTrue(saved['changed']);self.assertEqual(load_json(target/'brief.json')['audience'],'大学生')
            code,reading=call(['outline',str(target)]);self.assertEqual(code,0)
            self.assertTrue(Path(reading['reading_copy']).is_file());self.assertEqual(read_state(target)['ledger'],[])


class AuthoringFormsTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from videocreate.manager import Manager
        from videocreate.config.management import migrate
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.parent=Path(temp.name)
        self.window=tk.Tk();self.window.withdraw()
        def dispose():
            self.window.update_idletasks();self.window.destroy()
            self.manager=None
            gc.collect()
        self.addCleanup(dispose)
        self.path=self.parent/'config.json';atomic_json(self.path,migrate(config()));self.before=self.path.read_bytes()
        self.manager=Manager(self.window,self.path)

    def widgets(self,parent):
        for child in parent.winfo_children():yield child;yield from self.widgets(child)

    def button(self,parent,text):
        from tkinter import ttk
        return next(w for w in self.widgets(parent) if isinstance(w,ttk.Button) and w.cget('text')==text)

    def field(self,form,key,value):
        for path,var,kind in form.fields:
            if path==key:
                if kind=='multiline':var.delete('1.0','end');var.insert('1.0',value)
                else:var.set(value)
                return
        self.fail('Missing field '+key)

    def pump(self,win):
        deadline=time.monotonic()+5
        def check():
            if not win.winfo_exists() or not win.authoring_busy or time.monotonic()>=deadline:self.window.quit()
            else:self.window.after(10,check)
        self.window.after(0,check);self.window.mainloop()
        self.assertFalse(win.winfo_exists() and win.authoring_busy,'Authoring background action did not complete')

    def test_native_new_project_form_creates_draft_and_preserves_config(self):
        from videocreate.manager_authoring import open_new
        results=[]
        with mock.patch.object(self.manager,'error') as error,mock.patch('urllib.request.urlopen') as network:
            win=open_new(self.manager,completed=results.append);win.withdraw()
            win.authoring_parent.set(str(self.parent));win.authoring_name.set('新建项目')
            self.field(win.authoring_form,'title','表单创建');self.field(win.authoring_form,'topic','程序员穿越')
            self.field(win.authoring_form,'audience','大学生');self.field(win.authoring_form,'viewer_goal','理解反转')
            self.button(win,'创建草稿项目').invoke();self.window.update_idletasks()
            error.assert_not_called();network.assert_not_called()
        self.assertEqual(len(results),1);brief=load_project(self.parent/'新建项目')['brief']
        self.assertEqual(brief['topic'],'程序员穿越');self.assertEqual(brief['audience'],'大学生')
        self.assertEqual(self.path.read_bytes(),self.before);self.assertFalse((self.parent/'新建项目/state.json').exists())

    def test_theme_form_roundtrip_and_actual_preview_save_buttons(self):
        from videocreate.manager_authoring import open_editor
        target=self.parent/'theme';authoring.create(target,profile='mixed-video',title='Blank metadata')
        original=load_project(target)['brief'];saved=[]
        original_preview=authoring.preview;threads=[]
        def background_preview(*args,**kwargs):
            threads.append(threading.get_ident());return original_preview(*args,**kwargs)
        with mock.patch.object(self.manager,'error') as error,mock.patch('urllib.request.urlopen') as network,\
                mock.patch.object(authoring,'preview',side_effect=background_preview):
            win=open_editor(self.manager,target,'brief',completed=saved.append);win.withdraw()
            self.assertEqual(win.authoring_read(),original)
            self.field(win.authoring_form,'topic','测试主题')
            self.button(win,'预览修改影响').invoke();self.pump(win)
            self.button(win,'保存当前创作层').invoke();self.pump(win)
            self.window.update_idletasks();error.assert_not_called();network.assert_not_called()
        self.assertTrue(saved[0]['changed']);self.assertEqual(load_project(target)['brief']['topic'],'测试主题')
        self.assertTrue(threads);self.assertNotIn(threading.get_ident(),threads)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_outline_form_state_types_event_order_and_save_preserve_director_and_jobs(self):
        from videocreate.manager_authoring import open_editor
        target=self.parent/'outline';save_bundle(target,smart_car());original=load_project(target);saved=[]
        with mock.patch.object(self.manager,'error') as error:
            win=open_editor(self.manager,target,'story',completed=saved.append);win.withdraw()
            self.assertEqual(win.authoring_read(),original['story'])
            events=win.authoring_events;events.move(1)
            self.field(events.form,'audience_learns','Updated event observation')
            # Adding a typed condition must survive real widget extraction.
            events.effects.add('doors_open',True)
            win.authoring_states.add('nested',{'positions':[1,2],'active':True})
            self.button(win,'预览修改影响').invoke();self.pump(win)
            self.button(win,'保存当前创作层').invoke();self.pump(win)
            self.window.update_idletasks();error.assert_not_called()
        after=load_project(target)
        self.assertEqual(after['director'],original['director']);self.assertEqual(after['generation-plan'],original['generation-plan'])
        self.assertEqual(after['story']['beats'][1]['effects']['doors_open'],True)
        self.assertEqual(after['story']['initial_state']['nested'],{'positions':[1,2],'active':True})
        self.assertFalse(saved[0]['plan_validation']['ok']);self.assertFalse((target/'state.json').exists())

    def test_state_editor_rejects_duplicate_keys_and_nonfinite_numbers(self):
        from tkinter import ttk
        from videocreate.manager_authoring import StateMap
        pane=ttk.Frame(self.window);states=StateMap(pane,{'count':1,'known':None})
        self.assertEqual(states.read(),{'count':1,'known':None})
        states.add('count',2)
        with self.assertRaises(ConfigError):states.read()
        states.rows[-1][1].set('other');states.rows[-1][3].set('1e10000')
        with self.assertRaises(ConfigError):states.read()
        states.rows[-1][3].set('true')
        with self.assertRaises(ConfigError):states.read()

    def test_form_conflict_keeps_newer_disk_content_and_the_users_unsaved_input(self):
        from videocreate.manager_authoring import open_editor
        target=self.parent/'conflict';authoring.create(target,profile='mixed-video',title='Concurrent edit')
        with mock.patch.object(self.manager,'error') as error:
            win=open_editor(self.manager,target,'brief');win.withdraw()
            self.field(win.authoring_form,'topic','My unsaved topic');self.button(win,'预览修改影响').invoke()
            self.pump(win)
            newer=load_project(target)['brief'];newer['audience']='Another editor';atomic_json(target/'brief.json',newer)
            self.button(win,'保存当前创作层').invoke();self.pump(win);error.assert_called_once()
            self.assertEqual(win.authoring_read()['topic'],'My unsaved topic')
            self.assertEqual(load_project(target)['brief'],newer);win.destroy()

    def test_destroyed_form_cancels_pending_poll_callback_while_worker_finishes(self):
        from videocreate.manager_authoring import open_editor
        target=self.parent/'closing';authoring.create(target,profile='mixed-video',title='Closing form')
        started=threading.Event();release=threading.Event();finished=threading.Event();original=authoring.preview
        def delayed(*args,**kwargs):
            started.set();release.wait(2)
            try:return original(*args,**kwargs)
            finally:finished.set()
        with mock.patch.object(authoring,'preview',side_effect=delayed):
            win=open_editor(self.manager,target,'brief');win.withdraw()
            self.button(win,'预览修改影响').invoke();self.assertTrue(started.wait(1))
            timers=self.window.tk.call('after','info')
            polls=[timer for timer in timers if 'receive' in self.window.tk.call('after','info',timer)[0]]
            self.assertTrue(polls);win.destroy()
            self.assertFalse(set(polls)&set(self.window.tk.call('after','info')))
            deadline=time.monotonic()+3
            def check():
                if finished.is_set() or time.monotonic()>=deadline:self.window.quit()
                else:self.window.after(10,check)
            self.window.after(0,release.set);self.window.after(10,check);self.window.mainloop()
            self.assertTrue(finished.is_set());self.window.update_idletasks()
        self.assertFalse((target/'production').exists());self.assertFalse((target/'state.json').exists())


if __name__=='__main__':unittest.main()
