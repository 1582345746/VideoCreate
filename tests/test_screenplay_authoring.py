"""Editable scenes/actions/dialogue keep one source and preserve task recovery."""
import copy
import gc
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
from videocreate import authoring,production
from videocreate.cli import main
from videocreate.config.storage import ConfigError,atomic_json,load_json
from videocreate.planning.examples import smart_car
from videocreate.planning.project import compile_job,load_project,save_bundle
from videocreate.runtime import jobs
from videocreate.runtime.state import read_state,save_state
from test_v3_config import config


class ScreenplayTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.parent=Path(temporary.name);self.root=self.parent/'剧本项目';save_bundle(self.root,smart_car())

    def tasks(self):
        bundle=load_project(self.root);records={}
        for job in bundle['generation-plan']['jobs']:
            compiled=compile_job(bundle,job,max_bytes=10000,root=self.root)
            records[job['id']]={'status':'queued','task_id':'original-'+job['id'],
                'input_hash':jobs.generation_inputs(self.root,bundle,job,compiled),'history':[{'candidate_id':'retained'}]}
        save_state(self.root,{'schema_version':3,'jobs':records,'ledger':[{'event':'existing-fixture'}]})

    def change(self,edit):
        current=authoring.describe(self.root,'director');value=copy.deepcopy(current['value']);edit(value)
        preview=authoring.preview(self.root,'director',value,source_token=current['source_token'])
        return current,value,preview

    def save(self,current,value,preview):
        return authoring.save(self.root,'director',value,source_token=current['source_token'],preview_token=preview['preview_token'])

    def test_local_dialogue_edit_invalidates_only_consuming_job_and_keeps_task_ledger_and_stages(self):
        self.tasks();stage=next(s for s in production.status(self.root)['stages'] if s['id']=='script')
        production.checkpoint(self.root,'script',reason='Prior authored screenplay',expected_hash=stage['input_hash'])
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')};decisions=(self.root/'production/stages.json').read_bytes()
        def edit(d):d['shots'][1]['audio']['lines'][0]['text']='走不通。'
        current,value,preview=self.change(edit)
        self.assertEqual(preview['impact']['changed_job_inputs'],['job-002'])
        self.assertTrue(preview['plan_validation']['ok'])
        with mock.patch('videocreate.runtime.jobs.client') as client:
            result=self.save(current,value,preview);client.assert_not_called()
        self.assertEqual(load_json(Path(result['backup'])),current['value'])
        for name,data in before.items():
            if name!='director.json':self.assertEqual((self.root/name).read_bytes(),data)
        self.assertEqual((self.root/'production/stages.json').read_bytes(),decisions)
        self.assertEqual(next(s for s in production.status(self.root)['stages'] if s['id']=='script')['status'],'stale')
        exported=production.script_export(self.root);exchange=load_json(Path(exported['script']))
        self.assertEqual(exchange['shots'],value['shots'])
        job=load_project(self.root)['generation-plan']['jobs'][1]
        self.assertIn('走不通。',compile_job(load_project(self.root),job,max_bytes=10000,root=self.root)['prompt'])

    def test_scene_geography_changes_all_consuming_shots_but_no_other_scene(self):
        self.tasks()
        current,value,preview=self.change(lambda d:d['scenes'][0].update(map='新布局：石块在右侧，角色在左侧。'))
        self.assertEqual(preview['impact']['changed_job_inputs'],['job-001','job-002','job-003','job-004','job-005'])
        self.save(current,value,preview)
        self.assertEqual(read_state(self.root)['jobs']['job-006']['task_id'],'original-job-006')

    def test_deleted_or_renamed_shot_is_a_draft_error_without_remapping_jobs_or_timeline(self):
        self.tasks();before={name:(self.root/name).read_bytes() for name in ('generation-plan.json','timeline.json','state.json')}
        current,value,preview=self.change(lambda d:d['shots'].pop(0))
        self.assertFalse(preview['plan_validation']['ok']);self.save(current,value,preview)
        with mock.patch('videocreate.runtime.jobs.client') as client:
            with self.assertRaises(ConfigError):jobs.generate(self.root,config(),store_root=self.parent/'config')
            client.assert_not_called()
        for name,data in before.items():self.assertEqual((self.root/name).read_bytes(),data)

    def test_empty_actions_and_invalid_dialogue_types_are_rejected_without_writes(self):
        before=(self.root/'director.json').read_bytes()
        for edit in (lambda d:d['shots'][0].update(actions=[]),
                     lambda d:d['shots'][1]['audio']['lines'][0].update(on_screen='yes')):
            with self.assertRaises(ConfigError):self.change(edit)
        self.assertEqual((self.root/'director.json').read_bytes(),before)

    def test_missing_scene_is_reported_as_incomplete_draft_for_every_consuming_task(self):
        self.tasks();before=(self.root/'state.json').read_bytes()
        current,value,preview=self.change(lambda d:d['scenes'].pop(0))
        self.assertFalse(preview['plan_validation']['ok'])
        self.assertEqual(preview['impact']['changed_job_inputs'],['job-001','job-002','job-003','job-004','job-005'])
        self.save(current,value,preview)
        self.assertEqual((self.root/'state.json').read_bytes(),before)

    def test_exchange_import_keeps_stricter_complete_plan_gate_than_draft_editor(self):
        exchange=production.script_projection(load_project(self.root));before=(self.root/'director.json').read_bytes()
        exchange['shots'].pop(0)
        with self.assertRaises(ConfigError):production.import_script(self.root,exchange)
        self.assertEqual((self.root/'director.json').read_bytes(),before)
        with self.assertRaisesRegex(ConfigError,'object'):production.import_script(self.root,[])

    def test_director_save_respects_custom_layer_path_and_noop_creates_no_backup(self):
        current,value,preview=self.change(lambda d:None)
        self.assertFalse(self.save(current,value,preview)['changed']);self.assertFalse((self.root/'production').exists())
        (self.root/'layers').mkdir();(self.root/'director.json').rename(self.root/'layers/camera.json')
        project=load_json(self.root/'project.json');project['files']['director']='layers/camera.json';atomic_json(self.root/'project.json',project)
        current,value,preview=self.change(lambda d:d['shots'][0]['actions'][0].update(description='车轮停止转动。'))
        self.save(current,value,preview)
        self.assertEqual(load_json(self.root/'layers/camera.json'),value);self.assertFalse((self.root/'director.json').exists())

    def test_animation_director_and_script_import_stay_owned_by_sidecar(self):
        exchange=production.script_projection(load_project(self.root));project=load_json(self.root/'project.json')
        project['files']['animation']='animation.json';atomic_json(self.root/'animation.json',{});atomic_json(self.root/'project.json',project)
        before=(self.root/'director.json').read_bytes()
        with self.assertRaisesRegex(ConfigError,'animation sidecar'):authoring.describe(self.root,'director')
        with self.assertRaisesRegex(ConfigError,'animation sidecar'):production.import_script(self.root,exchange)
        self.assertEqual((self.root/'director.json').read_bytes(),before)

    def test_script_import_shares_preview_save_and_rejects_concurrent_task_transition(self):
        self.tasks();exchange=production.script_projection(load_project(self.root));exchange['shots'][0]['actions'][0]['description']+=' He waits.'
        before=(self.root/'director.json').read_bytes();original=authoring.preview
        def transitioned(*args,**kwargs):
            result=original(*args,**kwargs);state=read_state(self.root);state['jobs']['job-001']['status']='processing';save_state(self.root,state)
            return result
        with mock.patch.object(authoring,'preview',side_effect=transitioned):
            with self.assertRaisesRegex(ConfigError,'after preview'):production.import_script(self.root,exchange)
        self.assertEqual((self.root/'director.json').read_bytes(),before)
        self.assertEqual(read_state(self.root)['jobs']['job-001']['status'],'processing')
        self.assertTrue(production.import_script(self.root,exchange)['changed'])

    def test_reading_copy_has_scene_beat_and_timed_dialogue_without_modifying_sources(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*.json')};result=production.script_export(self.root)
        reading=Path(result['reading_copy']).read_text(encoding='utf-8')
        for text in ('## 场景 valley','落石在画面右侧','对应事件：b-obstacle','镜头内 0.4','导演层版本：','实际声音、口型与动作仍需播放核验'):
            self.assertIn(text,reading)
        Path(result['reading_copy']).write_text('Changed reader',encoding='utf-8')
        self.assertEqual({p.name:p.read_bytes() for p in self.root.glob('*.json')},before)

    def test_director_cli_does_not_need_config_and_saves_only_after_exact_preview(self):
        def call(args):
            with redirect_stdout(io.StringIO()) as output:code=main(['authoring',*args])
            return code,json.loads(output.getvalue())
        with mock.patch('videocreate.cli.read_config',side_effect=AssertionError('No config')),mock.patch('urllib.request.urlopen') as network:
            _,current=call(['show',str(self.root),'--layer','director']);value=current['value']
            value['shots'][0]['information_goal']='看清挡住道路的石块';path=self.parent/'director-edits.json';atomic_json(path,value)
            args=[str(self.root),'--layer','director','--file',str(path),'--source-token',current['source_token']]
            _,preview=call(['preview',*args]);code,saved=call(['save',*args,'--preview-token',preview['preview_token']])
            self.assertEqual(code,0);self.assertTrue(saved['changed']);network.assert_not_called()
        self.assertEqual(load_project(self.root)['director'],value)


class ScreenplayFormsTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from videocreate.manager import Manager
        from videocreate.config.management import migrate
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.parent=Path(temporary.name)
        self.root=self.parent/'form-project';save_bundle(self.root,smart_car())
        self.window=tk.Tk();self.window.withdraw()
        def dispose():
            self.window.update_idletasks();self.window.destroy();self.manager=None;gc.collect()
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
        import time
        deadline=time.monotonic()+8
        def check():
            if not win.winfo_exists() or not win.authoring_busy or time.monotonic()>=deadline:self.window.quit()
            else:self.window.after(10,check)
        self.window.after(0,check);self.window.mainloop()
        self.assertFalse(win.winfo_exists() and win.authoring_busy)

    def test_all_shots_roundtrip_without_coercing_optional_empty_numbers_whitespace_or_nested_state(self):
        from videocreate.manager_authoring import open_editor
        bundle=load_project(self.root);shot=bundle['director']['shots'][0]
        shot.update(planned_seconds=5,entry_state={'nested':{'x':[1,False]}},exit_state={},performance={},
            timing={'motion_tempo':'brisk','action_start_by':0,'action_complete_by':2,'max_reaction_hold':1},
            contacts=[],opening_frame='  keep original spacing\n',audio={'mode':'ambience','lines':[],'ambience':''})
        bundle['director']['scenes'][0]['positions']['nested']={'paths':[1,2]};atomic_json(self.root/'director.json',bundle['director'])
        win=open_editor(self.manager,self.root,'director');win.withdraw()
        self.assertEqual(win.authoring_read(),bundle['director'])
        shots=win.authoring_director.shots
        for index in range(len(shots.items)):
            shots.commit();shots.refresh(index)
            self.assertEqual(win.authoring_read(),bundle['director'])
        self.button(win,'预览修改影响').invoke();self.pump(win)
        self.button(win,'保存当前创作层').invoke();self.pump(win)
        self.assertEqual(load_project(self.root)['director'],bundle['director'])
        self.assertFalse((self.root/'production/backups').exists())

    def test_real_dialogue_and_performance_widgets_save_through_preview_and_keep_config(self):
        from videocreate.manager_authoring import open_editor
        saved=[];original=load_project(self.root)
        with mock.patch.object(self.manager,'error') as error,mock.patch('urllib.request.urlopen') as network:
            win=open_editor(self.manager,self.root,'director',completed=saved.append);win.withdraw()
            shots=win.authoring_director.shots;shots.commit();shots.refresh(1);editor=shots.editor
            self.field(editor.audio.lines.editor,'text','另寻一条路。')
            self.field(editor.performance.form,'visible_response','先皱眉，再抬眼看向山路。')
            self.button(win,'预览修改影响').invoke();self.pump(win)
            self.button(win,'保存当前创作层').invoke();self.pump(win)
            error.assert_not_called();network.assert_not_called()
        after=load_project(self.root)
        self.assertEqual(after['director']['shots'][1]['audio']['lines'][0]['text'],'另寻一条路。')
        self.assertEqual(after['generation-plan'],original['generation-plan']);self.assertEqual(after['timeline'],original['timeline'])
        self.assertTrue(saved[0]['changed']);self.assertEqual(self.path.read_bytes(),self.before)

    def test_scene_and_shot_add_reorder_delete_keep_id_links_and_do_not_invent_jobs(self):
        from videocreate.manager_authoring import open_editor
        original=load_project(self.root);saved=[]
        with mock.patch.object(self.manager,'error') as error:
            win=open_editor(self.manager,self.root,'director',completed=saved.append);win.withdraw()
            editor=win.authoring_director
            editor.scenes.add();self.field(editor.scenes.editor.form,'map','一座空旷的古代大殿')
            self.field(editor.scenes.editor.form,'axis','门朝南');editor.scenes.move(-1)
            editor.shots.add();sid=editor.shots.editor.form.original['id']
            self.field(editor.shots.editor.form,'information_goal','看清大殿中突然出现的电脑')
            self.field(editor.shots.editor.actions.editor,'description','书生合上笔记本电脑。')
            editor.shots.move(-1);editor.shots.add();editor.shots.delete()
            self.button(win,'预览修改影响').invoke();self.pump(win)
            self.button(win,'保存当前创作层').invoke();self.pump(win);error.assert_not_called()
        after=load_project(self.root);added=next(s for s in after['director']['shots'] if s['id']==sid)
        self.assertEqual(added['information_goal'],'看清大殿中突然出现的电脑')
        self.assertEqual(after['generation-plan'],original['generation-plan']);self.assertEqual(after['timeline'],original['timeline'])
        self.assertFalse(saved[0]['plan_validation']['ok']);self.assertFalse((self.root/'state.json').exists())

    def test_audio_option_and_structured_states_are_explicit_and_do_not_change_timeline_sound(self):
        from videocreate.manager_authoring import open_editor
        original=load_project(self.root)
        win=open_editor(self.manager,self.root,'director');win.withdraw();editor=win.authoring_director.shots.editor
        editor.audio.enabled.set(False);editor.entry.mode.set('状态表');editor.entry.states.add('door_open',True)
        editor.exit.mode.set('文字描述');editor.exit.text.delete('1.0','end');editor.exit.text.insert('1.0','门被关上')
        value=win.authoring_read();self.assertNotIn('audio',value['shots'][0])
        self.assertEqual(value['shots'][0]['entry_state'],{'door_open':True});self.assertEqual(value['shots'][0]['exit_state'],'门被关上')
        self.assertEqual(load_project(self.root)['timeline'],original['timeline']);win.destroy()

    def test_invalid_dialogue_number_keeps_row_selected_and_unsaved_close_needs_discard(self):
        from videocreate.manager_authoring import open_editor
        with mock.patch.object(self.manager,'error') as error:
            win=open_editor(self.manager,self.root,'director');win.withdraw();shots=win.authoring_director.shots
            shots.commit();shots.refresh(1);self.field(shots.editor.audio.lines.editor,'start','bad-number')
            shots.tree.selection_set('2');shots.select()
            self.assertEqual(shots.current,1);error.assert_called()
            with mock.patch('videocreate.manager_authoring.messagebox.askyesno',return_value=False) as question:
                win.tk.call(win.protocol('WM_DELETE_WINDOW'));self.assertTrue(win.winfo_exists());question.assert_called_once()
            win.destroy()


if __name__=='__main__':unittest.main()
