"""Real Tk repair forms, including replacing the startup panel after a commit."""
import gc
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate import manager,manager_lifecycle as ui
from videocreate.config import management,repair
from videocreate.config.storage import atomic_json,load_json
from videocreate.manager_repair import RepairPanel


class ManagerRepairTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'bad.json';self.raw=b'{"schema_version":4,"api_key":"local-fixture",}'
        self.path.write_bytes(self.raw);self.text=json.dumps(management.migrate(config()))
        self.root=tk.Tk();self.root.withdraw();self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.panel=RepairPanel(self.root,self.path);self.root.update_idletasks()
        def cleanup():
            try:self.root.update_idletasks();self.root.destroy()
            except tk.TclError:pass
            gc.collect();ui.reap_interpreters();self.assertEqual(self.errors,[])
        self.addCleanup(cleanup)

    def wait(self,done):
        deadline=time.monotonic()+10
        while not done() and time.monotonic()<deadline:self.root.update();time.sleep(.005)
        self.assertTrue(done())

    def draft(self):
        self.panel.editor.delete('1.0','end');self.panel.editor.insert('1.0',self.text);self.root.update()

    def preview(self):
        self.draft();self.panel.buttons['预览修复'].invoke();self.wait(lambda:not self.panel.call.busy)
        self.assertIsNotNone(self.panel.pending)

    def test_original_is_not_exposed_automatically_and_guard_keeps_only_digest(self):
        self.assertEqual(self.panel.editor.get('1.0','end-1c'),'')
        self.assertNotIn('local-fixture',self.panel.report.get('1.0','end'))
        self.panel.original();self.assertIn('local-fixture',self.panel.editor.get('1.0','end'))
        self.assertNotIn('local-fixture',str(self.panel.guard.initial));self.assertFalse(self.panel.guard.dirty())

    def test_native_preview_and_apply_back_up_original_and_disable_further_repair(self):
        self.preview();p=self.panel.pending;self.assertEqual(self.path.read_bytes(),self.raw)
        self.panel.buttons['按此预览保存修复'].invoke();self.wait(lambda:not self.panel.call.busy)
        self.assertEqual(Path(p['original_backup']).read_bytes(),self.raw)
        self.assertEqual(load_json(self.path)['schema_version'],4);self.assertFalse(self.panel.guard.dirty())
        self.assertTrue(self.panel.buttons['按此预览保存修复'].instate(['disabled']))

    def test_editing_or_changing_baseline_invalidates_native_preview(self):
        self.preview();self.panel.editor.insert('end',' ');self.root.update()
        self.assertIsNone(self.panel.pending);self.assertTrue(self.panel.buttons['按此预览保存修复'].instate(['disabled']))
        self.panel.preview();self.wait(lambda:not self.panel.call.busy);self.assertIsNotNone(self.panel.pending)
        self.panel.baseline.set('a-different-baseline');self.assertIsNone(self.panel.pending)

    def test_cancelled_reload_preserves_draft_and_source(self):
        self.draft();before=self.panel.editor.get('1.0','end-1c')
        baseline=self.path.parent/'backup.json';atomic_json(baseline,management.migrate(config()))
        with mock.patch('videocreate.manager_repair.messagebox.askyesno',return_value=False):
            self.panel.original();self.panel.backup(baseline)
        self.assertEqual(self.panel.editor.get('1.0','end-1c'),before);self.assertEqual(self.path.read_bytes(),self.raw)

    def test_loading_backup_is_unsaved_draft_and_close_cancellation_keeps_window(self):
        baseline=self.path.parent/'backup.json';atomic_json(baseline,management.migrate(config()))
        self.panel.backup(baseline);self.assertTrue(self.panel.guard.dirty())
        self.assertEqual(self.panel.baseline.get(),str(baseline.resolve()))
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):self.panel.guard.close()
        self.assertTrue(self.panel.body.winfo_exists());self.assertEqual(self.path.read_bytes(),self.raw)

    def test_busy_repair_blocks_close_and_runs_callback_on_ui_thread(self):
        self.draft();release=threading.Event();entered=threading.Event();called=[]
        def service(*args,**kwargs):entered.set();release.wait(5);return {'ok':True}
        self.panel.start(service,lambda result:called.append(threading.get_ident()))
        self.assertTrue(entered.wait(1))
        with mock.patch('videocreate.manager_drafts.messagebox.showinfo') as notice:
            self.panel.guard.close();notice.assert_called_once()
        self.assertTrue(self.panel.body.winfo_exists());release.set();self.wait(lambda:not self.panel.call.busy)
        self.assertEqual(called,[threading.get_ident()])

    def test_unknown_version_is_read_only_even_with_syntax_error(self):
        self.panel.dispose();self.path.write_text('{"schema_version":99,"tail":',encoding='utf-8')
        self.panel=RepairPanel(self.root,self.path)
        self.assertEqual(self.panel.snapshot['status'],'read-only')
        self.assertTrue(all(b.instate(['disabled']) for b in self.panel.buttons.values()))
        self.assertEqual(self.panel.editor.cget('state'),'disabled')

    def test_changed_original_rejects_apply_without_destroying_draft(self):
        self.preview();before=self.panel.editor.get('1.0','end-1c');self.path.write_bytes(self.raw+b' ')
        self.panel.apply();self.wait(lambda:not self.panel.call.busy)
        self.assertIn('bytes changed',self.panel.note.get());self.assertIsNone(self.panel.pending)
        self.assertEqual(self.panel.editor.get('1.0','end-1c'),before)

    def test_real_launch_repairs_then_constructs_manager_without_tcl_callback_error(self):
        self.root.destroy();root=tk.Tk();root.withdraw();self.root=root
        root.report_callback_exception=lambda *args:self.errors.append(args)
        actual_panel=RepairPanel;made=[];actual_manager=manager.Manager
        def panel(*args,**kwargs):
            value=actual_panel(*args,**kwargs);self.panel=value;return value
        def opened(*args,**kwargs):
            value=actual_manager(*args,**kwargs);made.append(value);return value
        def loop():
            self.preview();self.panel.apply();self.wait(lambda:bool(made))
            self.assertEqual(made[0].value['schema_version'],4)
            self.assertFalse(self.panel.body.winfo_exists());self.assertTrue(self.panel.call.closed)
            self.assertIsNot(getattr(root,'draft_guard',None),self.panel.guard)
        with mock.patch.object(manager.tk,'Tk',return_value=root),mock.patch.object(root,'mainloop',side_effect=loop),\
                mock.patch('videocreate.manager_repair.RepairPanel',side_effect=panel),\
                mock.patch.object(manager,'Manager',side_effect=opened),mock.patch.object(manager.messagebox,'showerror') as error:
            self.assertEqual(manager.launch(self.path),0);error.assert_not_called()
        self.assertEqual(Path(repair.inspect(self.path)['path']),self.path.resolve());self.assertEqual(self.errors,[])


if __name__=='__main__':unittest.main()
