"""Real native controls: close/reload never silently discards an unapplied draft."""
import copy
import gc
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from test_v3_config import config
from videocreate.config import management
from videocreate.config.storage import atomic_json, load_json
from videocreate.manager import Manager
from videocreate.manager_drafts import DraftGuard, confirm_close, controls
from videocreate import manager_lifecycle as ui
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle


class ManagerDraftTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.directory=Path(temp.name);self.path=self.directory/'config.json'
        atomic_json(self.path,management.migrate(config()))
        self.before=self.path.read_bytes();self.manager=Manager(self.root,self.path)
        self.project=self.directory/'project';save_bundle(self.project,smart_car())
        self.root.update_idletasks()
        def cleanup():
            try:self.root.update_idletasks();self.root.destroy()
            except tk.TclError:pass
            gc.collect();ui.reap_interpreters();self.assertEqual(self.errors,[])
        self.addCleanup(cleanup)

    def widgets(self,parent):
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self,parent,text):
        return next(w for w in self.widgets(parent) if isinstance(w,ttk.Button) and w.cget('text')==text)

    def last_window(self):
        return [w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)][-1]

    def upstream(self):
        self.manager.edit_upstream('primary-sub2api');return self.last_window()

    def edit_entry(self,win):
        entry=next(w for w in self.widgets(win) if isinstance(w,ttk.Entry) and not w.instate(['readonly']))
        entry.delete(0,'end');entry.insert(0,'changed draft');return entry

    def wait(self,done):
        deadline=time.monotonic()+10
        while not done() and time.monotonic()<deadline:self.root.update();time.sleep(.005)
        self.assertTrue(done())

    def test_untouched_upstream_closes_without_prompt_or_disk_changes(self):
        win=self.upstream()
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno') as question:
            win.draft_guard.close();question.assert_not_called()
        self.assertFalse(win.winfo_exists());self.assertEqual(self.path.read_bytes(),self.before)

    def test_unapplied_upstream_cancel_keeps_exact_input_and_main_config(self):
        win=self.upstream();entry=self.edit_entry(win);expected=copy.deepcopy(self.manager.value)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):
            self.root.tk.call(win.protocol('WM_DELETE_WINDOW'))
        self.assertTrue(win.winfo_exists());self.assertEqual(entry.get(),'changed draft')
        self.assertEqual(self.manager.value,expected);self.assertFalse(self.manager.dirty)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_invalid_binding_json_is_a_draft_and_close_does_not_validate_or_save(self):
        self.manager.edit_binding('grok-on-sub2api');win=self.last_window()
        texts=[w for w in self.widgets(win) if isinstance(w,tk.Text) and w.cget('state')!='disabled']
        texts[-1].insert('end','{broken JSON')
        with mock.patch.object(self.manager,'save') as saved, mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):
            win.draft_guard.close();saved.assert_not_called()
        self.assertTrue(win.winfo_exists());self.assertTrue(win.draft_guard.dirty())
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_child_price_cancel_preserves_every_window_when_closing_parent(self):
        from videocreate.manager_pricing import Prices
        forms=[]
        def capture(*args,**kwargs):
            form=Prices(*args,**kwargs);forms.append(form);return form
        with mock.patch('videocreate.manager_pricing.Prices',side_effect=capture):self.manager.edit_binding('grok-on-sub2api')
        outer=self.last_window();price=forms[0].edit();entry=self.edit_entry(price)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False) as question:
            outer.draft_guard.close();self.assertEqual(question.call_count,1)
        self.assertTrue(price.winfo_exists());self.assertTrue(outer.winfo_exists());self.assertEqual(entry.get(),'changed draft')
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_price_apply_stays_in_binding_draft_until_parent_apply(self):
        from videocreate.manager_pricing import Prices
        forms=[]
        def capture(*args,**kwargs):
            form=Prices(*args,**kwargs);forms.append(form);return form
        with mock.patch('videocreate.manager_pricing.Prices',side_effect=capture):self.manager.edit_binding('grok-on-sub2api')
        outer=self.last_window();price=forms[0].edit()
        entries=[w for w in self.widgets(price) if isinstance(w,ttk.Entry)]
        entries[-2].insert(0,'2.5');self.button(price,'应用档位').invoke()
        self.assertFalse(price.winfo_exists());self.assertTrue(outer.draft_guard.dirty());self.assertFalse(self.manager.dirty)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):outer.draft_guard.close()
        self.assertTrue(outer.winfo_exists());self.assertEqual(self.path.read_bytes(),self.before)

    def test_apply_then_save_remains_two_distinct_steps(self):
        win=self.upstream();self.edit_entry(win)
        self.button(win,'应用到待保存配置').invoke()
        self.assertFalse(win.winfo_exists());self.assertTrue(self.manager.dirty);self.assertEqual(self.path.read_bytes(),self.before)
        with mock.patch('videocreate.manager.messagebox.askyesno',return_value=True):self.assertTrue(self.manager.save())
        self.assertFalse(self.manager.dirty);self.assertNotEqual(self.path.read_bytes(),self.before)
        self.assertEqual(load_json(self.path)['upstreams']['primary-sub2api']['display_name'],'changed draft')

    def test_root_close_cancellation_never_partially_destroys_other_drafts(self):
        first=self.upstream();self.edit_entry(first)
        second=self.upstream();self.edit_entry(second)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',side_effect=[True,False]):self.manager.close()
        self.assertTrue(first.winfo_exists());self.assertTrue(second.winfo_exists());self.assertEqual(self.path.read_bytes(),self.before)

    def test_root_config_save_cancellation_retains_earlier_discard_approved_form(self):
        self.manager.value['bindings']['grok-on-sub2api']['notes']='pending';self.manager.changed()
        win=self.upstream();self.edit_entry(win)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=True), mock.patch('videocreate.manager.messagebox.askyesnocancel',return_value=None):
            self.manager.close()
        self.assertTrue(win.winfo_exists());self.assertTrue(self.manager.dirty);self.assertEqual(self.path.read_bytes(),self.before)

    def test_raw_controls_track_checkboxes_and_tiers_but_ignore_tree_selection_and_report(self):
        win=tk.Toplevel(self.root);flag=ui.BooleanVar(win,value=False)
        ttk.Checkbutton(win,variable=flag).pack();tree=ttk.Treeview(win);tree.pack()
        tree.insert('','end',iid='one',text='a');tree.insert('','end',iid='two',text='b')
        report=tk.Text(win);report.insert('1.0','old report');report.configure(state='disabled');report.pack()
        guard=DraftGuard(win)
        tree.selection_set('two');report.configure(state='normal');report.insert('end','new');report.configure(state='disabled')
        self.assertFalse(guard.dirty());flag.set(True);self.assertTrue(guard.dirty())
        guard.reset();tree.item('two',text='edited tier');self.assertTrue(guard.dirty())

    def test_credentials_remain_unwritten_and_prompt_never_contains_secret(self):
        self.manager.current_upstream='primary-sub2api';self.manager.credential();win=self.last_window()
        entry=next(w for w in self.widgets(win) if isinstance(w,ttk.Entry) and w.cget('show'))
        entry.insert(0,'draft-secret-test-only')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False) as question:
            self.manager.close()
        self.assertTrue(win.winfo_exists());self.assertNotIn('draft-secret',str(question.call_args))
        self.assertNotIn('draft-secret',str(win.draft_guard.initial));self.assertFalse((self.directory/'secrets.dpapi').exists())

    def test_reload_cancel_keeps_config_draft_and_success_closes_stale_config_form(self):
        win=self.upstream();entry=self.edit_entry(win)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):self.manager.reload()
        self.assertTrue(win.winfo_exists());self.assertEqual(entry.get(),'changed draft')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=True):self.manager.reload()
        self.assertFalse(win.winfo_exists());self.assertFalse(self.manager.dirty);self.assertEqual(self.path.read_bytes(),self.before)

    def test_failed_reload_preserves_form_even_after_discard_confirmation(self):
        win=self.upstream();self.edit_entry(win);self.path.write_text('{broken',encoding='utf-8')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=True),mock.patch.object(self.manager,'error') as error:
            self.manager.reload();error.assert_called_once()
        self.assertTrue(win.winfo_exists());self.assertTrue(win.draft_guard.dirty())

    def test_restore_cancel_stops_before_backup_picker_and_configuration_write(self):
        win=self.upstream();self.edit_entry(win)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False), \
                mock.patch('videocreate.manager.filedialog.askopenfilename') as picker, \
                mock.patch('videocreate.manager.service.restore') as restore:
            self.manager.restore();picker.assert_not_called();restore.assert_not_called()
        self.assertTrue(win.winfo_exists());self.assertEqual(self.path.read_bytes(),self.before)

    def test_root_close_checks_existing_authoring_form_without_saving_project(self):
        from videocreate.manager_authoring import open_editor
        before={p.name:p.read_bytes() for p in self.project.glob('*.json')}
        win=open_editor(self.manager,self.project,'brief');var=next(v for k,v,t in win.authoring_form.fields if k=='topic');var.insert('end','changed')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):self.manager.close()
        self.assertTrue(win.winfo_exists());self.assertEqual(before,{p.name:p.read_bytes() for p in self.project.glob('*.json')})

    def test_local_busy_prevents_exit_before_any_discard_question(self):
        win=self.upstream();self.edit_entry(win)
        busywin=tk.Toplevel(self.root);DraftGuard(busywin,read=lambda:None,busy=lambda:True)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno') as question, mock.patch('videocreate.manager_drafts.messagebox.showinfo') as info:
            self.manager.close();question.assert_not_called();info.assert_called_once()
        self.assertTrue(win.winfo_exists());self.assertTrue(busywin.winfo_exists())

    def test_media_service_refresh_does_not_dirty_settings_and_cancel_keeps_port(self):
        from videocreate.manager_media import open_panel
        win=open_panel(self.manager);self.assertFalse(win.draft_guard.dirty())
        self.button(win,'刷新').invoke();self.assertFalse(win.draft_guard.dirty())
        entry=next(w for w in self.widgets(win) if isinstance(w,ttk.Entry));entry.insert('end','changed')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):win.draft_guard.close()
        self.assertTrue(win.winfo_exists());self.assertEqual(self.path.read_bytes(),self.before)

    def test_policy_reloading_or_close_requires_discard_and_saved_load_resets_baseline(self):
        from videocreate.manager_policy import open_panel
        win=open_panel(self.manager,self.project);panel=win.policy_panel;self.wait(lambda:not panel.busy)
        self.assertFalse(win.draft_guard.dirty());panel.reason.set('unsaved reason')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):
            panel.reload();self.button(win,'关闭').invoke()
        self.assertTrue(win.winfo_exists());self.assertEqual(panel.reason.get(),'unsaved reason');self.assertFalse(panel.busy)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=True):panel.reload()
        self.wait(lambda:not panel.busy);self.assertFalse(win.draft_guard.dirty())

    def test_static_gif_and_legacy_forms_register_local_draft_guards(self):
        from videocreate.manager_stills import open_form as still
        from videocreate.manager_gifs import open_form as gif
        from videocreate.manager_legacy_edit import open_form as legacy
        windows=[still(self.manager,self.project,source=self.directory/'input.png'),
            gif(self.manager,self.project,paths=[self.directory/'input.mp4']),
            legacy(self.manager,source=self.project)]
        for win in windows:
            self.assertFalse(win.draft_guard.dirty());self.assertTrue(confirm_close(win));win.destroy()

    def test_successful_root_discard_closes_every_form_without_config_write(self):
        win=self.upstream();self.edit_entry(win)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=True):self.manager.close()
        with self.assertRaises(tk.TclError):self.root.winfo_exists()
        self.assertEqual(self.path.read_bytes(),self.before)


if __name__=='__main__':unittest.main()
