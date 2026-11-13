import copy
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate import diagnostics
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json,load_json
from videocreate.manager import Manager


class ManagerDiagnosticTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'config.json';self.output=self.path.parent/'report.json'
        value=migrate(config());value['upstreams']['primary-sub2api']['notes']='private-note-canary'
        atomic_json(self.path,value);self.original=self.path.read_bytes()
        self.root=tk.Tk();self.root.withdraw();self.root.update_idletasks();self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(str(args[1]))
        self.manager=Manager(self.root,self.path);self.manager.current_upstream='primary-sub2api'
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.root.update_idletasks();self.root.destroy();self.assertEqual(self.errors,[])

    def panel(self):
        window=self.manager.diagnostics_panel();window.withdraw();return window.diagnostics_panel

    def wait(self,predicate):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            self.root.update()
            if predicate():return
            time.sleep(.005)
        self.fail('Diagnostic background action did not finish')

    def preview(self,panel):panel.preview();self.wait(lambda:not panel.call.busy)

    def test_native_preview_displays_exact_anonymous_report_and_exports_new_file(self):
        panel=self.panel();self.assertIsNone(panel.pending);self.assertFalse(panel.tree.get_children())
        with mock.patch('videocreate.config.storage.resolve_key',side_effect=AssertionError('No key')),\
             mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')):
            self.preview(panel);self.assertIsNotNone(panel.pending)
            report=json.loads(panel.editor.get('1.0','end'));self.assertEqual(report,panel.pending['report'])
            self.assertNotIn('private-note-canary',json.dumps(report));self.assertNotIn('primary-sub2api',json.dumps(report))
            self.assertTrue(panel.tree.get_children());panel.export(self.output);self.wait(lambda:not panel.call.busy)
        self.assertEqual(load_json(self.output),report);self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse(self.manager.dirty)

    def test_changed_disclosure_or_scope_clears_preview_and_export_permission(self):
        panel=self.panel();self.preview(panel);panel.names.set(True)
        self.assertIsNone(panel.pending);self.assertTrue(panel.export_button.instate(['disabled']))
        self.assertEqual(panel.editor.get('1.0','end').strip(),'')
        self.preview(panel);self.assertEqual(panel.pending['report']['disclosure'],'identifiers')
        self.assertIn('primary-sub2api',panel.editor.get('1.0','end'))
        panel.one.set(False);self.assertIsNone(panel.pending);self.preview(panel)
        self.assertEqual(panel.pending['report']['configuration']['scope'],'all-upstreams')

    def test_unsaved_manager_edits_are_excluded_and_preserved(self):
        self.manager.value['bindings']['grok-on-sub2api']['enabled']=False;self.manager.dirty=True
        original=copy.deepcopy(self.manager.value);panel=self.panel();self.preview(panel)
        row=next(row for row in panel.pending['report']['bindings'] if row['ref']=='binding-001')
        self.assertTrue(row['enabled']);self.assertEqual(self.manager.value,original);self.assertTrue(self.manager.dirty)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_changed_saved_config_blocks_export_and_requires_fresh_preview(self):
        panel=self.panel();self.preview(panel)
        value=load_json(self.path);value['upstreams']['primary-sub2api']['notes']='changed on disk';atomic_json(self.path,value)
        panel.export(self.output);self.wait(lambda:not panel.call.busy)
        self.assertFalse(self.output.exists());self.assertIsNone(panel.pending)
        self.assertIn('changed',panel.summary.get());self.preview(panel);panel.export(self.output);self.wait(lambda:not panel.call.busy)
        self.assertTrue(self.output.is_file())

    def test_existing_output_is_preserved_and_cancelled_file_dialog_writes_nothing(self):
        panel=self.panel();self.preview(panel)
        with mock.patch('videocreate.manager_diagnostics.filedialog.asksaveasfilename',return_value=''):
            panel.export()
        self.assertFalse(self.output.exists());self.assertIsNotNone(panel.pending)
        self.output.write_bytes(b'existing-user-file');panel.export(self.output);self.wait(lambda:not panel.call.busy)
        self.assertEqual(self.output.read_bytes(),b'existing-user-file');self.assertIsNone(panel.pending)

    def test_duplicate_preview_click_is_one_read_and_close_detaches_without_write(self):
        entered=threading.Event();release=threading.Event();done=threading.Event();calls=[];function=diagnostics.preview
        def preview(*args,**kwargs):
            entered.set();calls.append('preview')
            try:
                if not release.wait(8):raise RuntimeError('missing release')
                return function(*args,**kwargs)
            finally:done.set()
        panel=self.panel()
        try:
            with mock.patch('videocreate.manager_diagnostics.diagnostics.preview',side_effect=preview):
                panel.preview();self.wait(entered.is_set);panel.preview();panel.export(self.output)
                panel.guard.close();self.assertFalse(panel.win.winfo_exists())
                self.assertIsNone(panel.call.scheduled);self.assertIsNone(panel.call.completed)
                release.set();self.wait(done.is_set)
        finally:release.set()
        self.assertEqual(calls,['preview']);self.assertFalse(self.output.exists());self.assertEqual(self.path.read_bytes(),self.original)

    def test_export_transaction_blocks_user_close_and_double_click_writes_once(self):
        panel=self.panel();self.preview(panel);entered=threading.Event();release=threading.Event();done=threading.Event();calls=[]
        function=diagnostics.export
        def export(*args,**kwargs):
            entered.set();calls.append('export')
            try:
                if not release.wait(8):raise RuntimeError('missing release')
                return function(*args,**kwargs)
            finally:done.set()
        try:
            with mock.patch('videocreate.manager_diagnostics.diagnostics.export',side_effect=export):
                panel.export(self.output);self.wait(entered.is_set);panel.export(self.output)
                with mock.patch('videocreate.manager_drafts.messagebox.showinfo') as shown:
                    panel.guard.close();shown.assert_called_once()
                self.assertTrue(panel.win.winfo_exists());release.set();self.wait(done.is_set);self.wait(lambda:not panel.call.busy)
        finally:release.set()
        self.assertEqual(calls,['export']);self.assertTrue(self.output.exists());self.assertFalse(panel.guard.dirty())

    def test_options_changed_during_read_do_not_show_outdated_report(self):
        panel=self.panel();entered=threading.Event();release=threading.Event();done=threading.Event();function=diagnostics.preview
        def preview(*args,**kwargs):
            entered.set()
            try:
                if not release.wait(8):raise RuntimeError('missing release')
                return function(*args,**kwargs)
            finally:done.set()
        try:
            with mock.patch('videocreate.manager_diagnostics.diagnostics.preview',side_effect=preview):
                panel.preview();self.wait(entered.is_set);panel.names.set(True);release.set()
                self.wait(done.is_set);self.wait(lambda:not panel.call.busy)
        finally:release.set()
        self.assertIsNone(panel.pending);self.assertTrue(panel.export_button.instate(['disabled']))

    def test_all_upstreams_initial_scope_does_not_invent_current_selection(self):
        self.manager.current_upstream=None;panel=self.panel();self.assertFalse(panel.one.get())
        self.assertTrue(panel.scope_button.instate(['disabled']));self.preview(panel)
        self.assertEqual(panel.pending['report']['configuration']['scope'],'all-upstreams')

    def test_close_cancel_preserves_unapplied_disclosure_setting(self):
        panel=self.panel();panel.names.set(True)
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):panel.guard.close()
        self.assertTrue(panel.win.winfo_exists());self.assertTrue(panel.names.get())
        self.assertFalse(self.output.exists());self.assertEqual(self.path.read_bytes(),self.original)


if __name__=='__main__':unittest.main()
