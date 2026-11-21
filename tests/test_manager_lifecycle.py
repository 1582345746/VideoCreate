"""Exercise real Tcl cleanup, worker GC and closing during service transactions."""
import gc
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

from videocreate import manager_lifecycle as ui
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json
from videocreate.manager import Manager
from videocreate.manager_forms import Fields
from tkinter import ttk
from test_v3_config import config


class ManagerLifecycleTests(unittest.TestCase):
    def test_theme_events_do_not_outlive_an_immediately_destroyed_manager(self):
        script = '''
import tempfile
import tkinter as tk
from pathlib import Path
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json
from videocreate.manager import Manager
from test_v3_config import config
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'config.json';atomic_json(path,migrate(config()))
    for _ in range(3):
        root=tk.Tk();root.withdraw();manager=Manager(root,path)
        root.destroy()
    last=tk.Tk();last.withdraw();last.update_idletasks();last.destroy()
print('immediate teardown passed')
'''
        result=subprocess.run([sys.executable,'-B','-X','utf8','-c',script],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stderr,'')
        self.assertIn('immediate teardown passed',result.stdout)

    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        def cleanup():
            self.root.update_idletasks(); self.root.destroy()
            gc.collect(); ui.reap_interpreters()
            self.assertEqual(self.errors, [])
        self.addCleanup(cleanup)

    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.assertTrue(predicate())

    def button(self, parent, text):
        for child in parent.winfo_children():
            if child.winfo_class() == 'TButton' and child.cget('text') == text:
                return child
            value = self.button(child, text)
            if value is not None: return value

    def manager(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'config.json'
        atomic_json(path, migrate(config()))
        return Manager(self.root, path)

    def test_owner_destroy_removes_real_tcl_traces_and_variables_without_unset_callbacks(self):
        owner = ttk.Frame(self.root)
        value = ui.StringVar(owner, value='before')
        enabled = ui.BooleanVar(owner, value=True)
        seen = []
        write = value.trace_add('write', lambda *_: seen.append(value.get()))
        unset = value.trace_add('unset', lambda *_: seen.append('UNSET UI CALLBACK'))
        value.set('after'); self.assertEqual(seen, ['after']); self.assertTrue(enabled.get())
        names = [str(value), str(enabled)]
        child = ttk.Frame(owner); child.destroy()
        self.assertEqual(value.get(), 'after')
        owner.destroy()
        for name in names:
            self.assertEqual(int(self.root.tk.call('info', 'exists', name)), 0)
        for command in (write, unset):
            self.assertFalse(self.root.tk.call('info', 'commands', command))
        self.assertEqual(seen, ['after'])
        # Retaining Python values after closure no longer retains Tcl/root.
        self.assertIsNone(value._tk); self.assertIsNone(value._root)

    def test_two_interpreters_and_reopened_forms_use_their_explicit_owner(self):
        other = tk.Tk(); other.withdraw(); other.update_idletasks()
        try:
            for index in range(4):
                owner = ttk.Frame(other); book = ttk.Notebook(owner)
                form = Fields(book, 'fields', {'name': str(index)}, [('name', 'name', 'text')])
                value = form.fields[0][1]
                self.assertIs(value._tk, other.tk)
                self.assertFalse(self.root.tk.call('info', 'exists', str(value)))
                self.assertEqual(form.read(), {'name': str(index)})
                owner.destroy(); self.assertIsNone(value._tk)
        finally:
            other.update_idletasks()
            other.destroy()

    def test_closed_form_cycles_can_be_collected_on_worker_without_tcl_calls(self):
        owner = ttk.Frame(self.root)
        value = ui.StringVar(owner, value='retained')
        retained = [value]; retained.append(retained)
        reference = weakref.ref(value)
        owner.destroy(); del value, owner, retained
        errors = []
        with patch.object(sys, 'unraisablehook', lambda event: errors.append(str(event.exc_value))):
            worker = threading.Thread(target=gc.collect); worker.start(); worker.join(8)
        self.assertFalse(worker.is_alive()); self.assertIsNone(reference()); self.assertEqual(errors, [])

    def test_destroyed_interpreter_is_released_on_ui_after_worker_gc_in_subprocess(self):
        source = r'''
import gc, sys, threading, tkinter as tk
from tkinter import ttk
sys.path.insert(0,sys.argv[1])
from videocreate import manager_lifecycle as ui
from videocreate.manager_forms import Fields
gc.disable()
for iteration in range(3):
    root=tk.Tk(); root.withdraw(); book=ttk.Notebook(root)
    form=Fields(book,'test',{'name':'value'},[('name','name','text')])
    cycle=[root,book,form];cycle.append(cycle)
    root.destroy();del root,book,form,cycle
    worker=threading.Thread(target=gc.collect);worker.start();worker.join()
    ui.reap_interpreters()
    assert not ui._interpreters, len(ui._interpreters)
print('worker GC and UI interpreter release passed')
'''
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', source,
                                 str(Path(ui.__file__).resolve().parents[1])],
                                capture_output=True, text=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('passed', result.stdout)

    def test_background_success_and_error_callbacks_run_only_on_ui(self):
        owner = ttk.Frame(self.root); background = ui.BackgroundCall(owner, interval=5)
        main = threading.get_ident(); calls = []; results = []
        def service(value):
            calls.append(threading.get_ident())
            if value < 0: raise ValueError('expected fixture error')
            return value + 1
        def completed(value): results.append((threading.get_ident(), value))
        self.assertTrue(background.start(service, 4, completed=completed, failed=completed))
        self.assertFalse(background.start(service, 9, completed=completed, failed=completed))
        self.wait(lambda: len(results) == 1)
        self.assertEqual(results, [(main, 5)]); self.assertFalse(background.busy)
        self.assertTrue(background.start(service, -1, completed=completed, failed=completed))
        self.wait(lambda: len(results) == 2)
        self.assertEqual(results[1][0], main); self.assertIsInstance(results[1][1], ValueError)
        self.assertTrue(all(thread != main for thread in calls)); owner.destroy()

    def test_close_cancels_poll_drops_ui_callbacks_and_finishes_exactly_one_transaction(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        owner = ttk.Frame(self.root); background = ui.BackgroundCall(owner, interval=5)
        calls = []
        class Completion:
            def __call__(self, value): calls.append('UI callback after close')
        completed = Completion(); reference = weakref.ref(completed)
        def service():
            entered.set()
            try:
                if not release.wait(8): raise RuntimeError('missing release')
                calls.append('transaction committed')
                return 'done'
            finally: done.set()
        try:
            background.start(service, completed=completed, failed=completed)
            self.wait(entered.is_set); scheduled = background.scheduled
            self.assertIn(scheduled, self.root.tk.call('after', 'info'))
            owner.destroy(); del completed; gc.collect()
            self.assertIsNone(reference()); self.assertIsNone(background.owner)
            self.assertNotIn(scheduled, self.root.tk.call('after', 'info'))
            self.assertFalse(background.start(service, completed=lambda _: None, failed=lambda _: None))
        finally: release.set()
        self.wait(done.is_set); self.root.update()
        self.assertEqual(calls, ['transaction committed'])

    def test_catalog_close_during_read_never_mutates_configuration_or_calls_tk_worker(self):
        manager = self.manager(); manager.current_upstream = 'primary-sub2api'
        before = manager.path.read_bytes(); entered = threading.Event(); release = threading.Event(); done = threading.Event()
        def models(value, uid, store_root):
            entered.set()
            try:
                if not release.wait(8): raise RuntimeError('missing release')
                return {'ids': ['fixture-model']}
            finally: done.set()
        try:
            with patch('videocreate.catalog.discovery.models', side_effect=models):
                window = manager.discover(); self.wait(entered.is_set); window.destroy()
                release.set(); self.wait(done.is_set); self.root.update()
        finally: release.set()
        self.assertEqual(manager.path.read_bytes(), before); self.assertFalse(manager.dirty)

    def test_media_close_during_start_finishes_service_without_persistent_ui_poll(self):
        from videocreate.manager_media import open_panel
        manager = self.manager(); before = manager.path.read_bytes()
        entered = threading.Event(); release = threading.Event(); done = threading.Event(); calls = []
        def start(path):
            calls.append(path); entered.set()
            try:
                if not release.wait(8): raise RuntimeError('missing release')
                return {'running': True}
            finally: done.set()
        with patch('videocreate.media_server.published', return_value=[]), patch('videocreate.media_server.status', return_value={'running': False}):
            window = open_panel(manager); window.withdraw()
            try:
                with patch('videocreate.media_server.start', side_effect=start):
                    self.button(window, '启动服务').invoke(); self.button(window, '启动服务').invoke()
                    self.wait(entered.is_set); window.destroy(); release.set(); self.wait(done.is_set)
            finally: release.set()
        self.root.update(); self.assertEqual(calls, [manager.path]); self.assertEqual(manager.path.read_bytes(), before)

    def test_gif_window_close_removes_its_pending_poll_while_conversion_finishes(self):
        from videocreate.manager_gifs import open_form
        manager = self.manager(); entered = threading.Event(); release = threading.Event(); done = threading.Event()
        calls = []
        def build(*args, **kwargs):
            calls.append(kwargs['gif_id']); entered.set()
            try:
                if not release.wait(8): raise RuntimeError('missing release')
                return {'completed': True}
            finally: done.set()
        with patch('videocreate.local_gifs.build', side_effect=build):
            window = open_form(manager, manager.path.parent, paths=[manager.path.parent/'fixture.mp4'])
            try:
                existing = set(self.root.tk.call('after', 'info'))
                self.button(window, '本地转换并登记到项目').invoke(); self.wait(entered.is_set)
                pending = set(self.root.tk.call('after', 'info')) - existing
                self.assertTrue(pending); window.destroy()
                self.assertFalse(pending & set(self.root.tk.call('after', 'info')))
                self.assertIn(manager.recovery.timer, self.root.tk.call('after', 'info'))
            finally: release.set()
            self.wait(done.is_set); self.root.update()
        self.assertEqual(calls, ['gif-001'])

    def test_clip_import_close_removes_pending_poll_and_keeps_one_started_transaction(self):
        from videocreate.manager_projects import open_panel
        from videocreate.planning.profiles import create
        from videocreate.planning.project import save_bundle
        manager = self.manager(); project = manager.path.parent/'edit-only'; save_bundle(project, create('edit-only'))
        entered = threading.Event(); release = threading.Event(); done = threading.Event(); calls = []
        def import_clip(*args, **kwargs):
            calls.append(kwargs['source_id']); entered.set()
            try:
                if not release.wait(8): raise RuntimeError('missing release')
                return {'source': {'id': kwargs['source_id']}}
            finally: done.set()
        parent = open_panel(manager, project); parent.withdraw()
        with patch('tkinter.filedialog.askopenfilename', return_value=str(project/'fixture.mp4')), patch('videocreate.local_sources.import_clip', side_effect=import_clip):
            self.button(parent, '导入本地视频').invoke()
            window = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
                          and w.title() == '导入本地视频（仅剪辑 / 混合项目）')
            try:
                existing = set(self.root.tk.call('after', 'info'))
                self.button(window, '导入并加入时间线').invoke(); self.wait(entered.is_set)
                pending = set(self.root.tk.call('after', 'info')) - existing
                self.assertTrue(pending); window.destroy()
                self.assertFalse(pending & set(self.root.tk.call('after', 'info')))
                self.assertIn(manager.recovery.timer, self.root.tk.call('after', 'info'))
            finally: release.set()
            self.wait(done.is_set); self.root.update()
        self.assertEqual(calls, ['source-001']); parent.destroy()


if __name__ == '__main__': unittest.main()
