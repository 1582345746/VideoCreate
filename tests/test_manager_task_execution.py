"""The task panel calls the shared service in workers and keeps completed state."""
import base64
import gc
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'tests')]
from videocreate import generation_actions, manager_tasks, selection
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json
from videocreate.manager import Manager
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project, save_bundle
from videocreate.runtime.state import read_state
from test_v3_config import config
from test_image_model_routing import PNG


class ManagerTaskExecutionTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.parent=Path(self.temp.name);self.path=self.parent/'config/config.json'
        atomic_json(self.path,migrate(config()))
        self.window=tk.Tk();self.window.withdraw()
        self.manager=Manager(self.window,self.path)
        self.root=self.parent/'images'
        save_bundle(self.root,create('image-only',title='GUI fixture',topic='A synthetic boat'))
        self.win=manager_tasks.open_panel(self.manager,self.root);self.win.withdraw()
        self.panel=self.win.task_panel;self.panel.tree.selection_set('image-001')
        self.payload={'data':[{'b64_json':base64.b64encode(PNG).decode()}]}
        def dispose():
            self.window.update_idletasks();self.window.destroy()
            self.panel=None;self.win=None;self.manager=None;gc.collect()
        self.addCleanup(dispose)

    def wait_for(self,predicate,timeout=10):
        deadline=time.monotonic()+timeout
        def check():
            if predicate() or time.monotonic()>=deadline:self.window.quit()
            else:self.window.after(10,check)
        self.window.after(0,check);self.window.mainloop()
        self.assertTrue(predicate(),'Task panel did not finish its operation')

    def widgets(self,parent):
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self,parent,label):
        from tkinter import ttk
        return next(w for w in self.widgets(parent) if isinstance(w,ttk.Button) and w.cget('text')==label)

    def prepare(self):
        self.panel.binding.set('image-primary');self.panel.preview()
        self.wait_for(lambda:self.panel.token is not None and not self.panel.busy)

    def test_preview_and_execution_are_background_and_keep_configuration_and_approval(self):
        self.window.attributes('-alpha',0);self.window.deiconify()
        self.win.attributes('-alpha',0);self.win.deiconify()
        self.wait_for(lambda:self.win.winfo_ismapped() and self.win.winfo_width()>1)
        self.window.update_idletasks()
        for button in self.panel.buttons:
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rootx()-self.win.winfo_rootx()+button.winfo_width(),self.win.winfo_width())
            self.assertLessEqual(button.winfo_rooty()-self.win.winfo_rooty()+button.winfo_height(),self.win.winfo_height())
        before=self.path.read_bytes();threads=[];main=threading.get_ident()
        original=generation_actions.preview
        def preview(*args,**kwargs):threads.append(threading.get_ident());return original(*args,**kwargs)
        with mock.patch.object(generation_actions,'preview',side_effect=preview), \
                mock.patch('videocreate.adapters.image.BindingImageClient.create_payload',return_value=self.payload) as send, \
                mock.patch('urllib.request.urlopen',side_effect=AssertionError('No real network')), \
                mock.patch.object(self.manager,'error') as error:
            self.prepare();self.assertEqual(read_state(self.root)['ledger'],[])
            self.panel.execute();self.wait_for(lambda:not self.panel.busy)
            send.assert_called_once();error.assert_not_called()
        self.assertTrue(threads and all(t!=main for t in threads))
        state=read_state(self.root);self.assertEqual(state['jobs']['image-001']['status'],'completed')
        self.assertEqual(state['jobs']['image-001']['content_status'],'unverified')
        self.assertEqual(len(state['ledger']),1);self.assertEqual(before,self.path.read_bytes())
        self.assertIsNone(self.panel.token)

    def test_edit_after_preview_refuses_execution_before_create(self):
        self.prepare()
        generation=load_project(self.root)['generation-plan'];generation['image_jobs'][0]['prompt']='A different boat'
        atomic_json(self.root/'generation-plan.json',generation)
        with mock.patch('videocreate.adapters.image.BindingImageClient.create_payload') as send, \
                mock.patch.object(self.manager,'error') as error:
            self.panel.execute();self.wait_for(lambda:not self.panel.busy)
            self.assertTrue(error.called);send.assert_not_called()
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_numbered_route_form_saves_only_the_chosen_scope_then_requires_new_preview(self):
        before=self.path.read_bytes()
        with mock.patch.object(self.manager,'error') as error:
            self.panel.preview()
            self.wait_for(lambda:not self.panel.busy)
            dialogs=[w for w in self.window.winfo_children() if w.winfo_class()=='Toplevel' and w!=self.win]
            chooser=next(w for w in dialogs if w.title()=='选择缺失的上游与型号')
            from tkinter import ttk
            tree=next(w for w in self.widgets(chooser) if isinstance(w,ttk.Treeview))
            tree.selection_set(tree.get_children()[0])
            self.button(chooser,'使用所选序号').invoke()
            self.wait_for(lambda:'image-001' in self.panel.overrides and not self.panel.busy)
            self.assertIsNone(self.panel.token)
            self.panel.preview();self.wait_for(lambda:self.panel.token is not None and not self.panel.busy)
            error.assert_not_called()
        self.assertEqual(before,self.path.read_bytes())
        self.assertIsNone(selection.project_choice(self.root,'image'))
        self.assertEqual(read_state(self.root)['ledger'],[])

    def test_double_click_and_close_keep_one_started_transaction_and_no_ui_callback(self):
        self.prepare()
        started=threading.Event();release=threading.Event();finished=threading.Event()
        real=manager_tasks._worker
        def worker(*args,**kwargs):
            try:return real(*args,**kwargs)
            finally:finished.set()
        def create_payload(*args,**kwargs):
            started.set();release.wait(5);return self.payload
        try:
            with mock.patch.object(manager_tasks,'_worker',side_effect=worker), \
                    mock.patch('videocreate.adapters.image.BindingImageClient.create_payload',side_effect=create_payload) as send, \
                    mock.patch.object(self.window,'report_callback_exception') as callback_error:
                self.panel.execute();self.wait_for(started.is_set)
                self.panel.execute();self.assertEqual(send.call_count,1)
                self.win.destroy();release.set();self.wait_for(finished.is_set)
                self.window.after(200,self.window.quit);self.window.mainloop()
                callback_error.assert_not_called()
        finally:
            release.set();finished.wait(10)
        self.assertEqual(read_state(self.root)['jobs']['image-001']['status'],'completed')
        self.assertEqual(len(read_state(self.root)['ledger']),1)


if __name__=='__main__':unittest.main()
