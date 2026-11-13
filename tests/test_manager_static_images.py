"""Actual import controls keep UI responsive and source transactions intact."""
import gc
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'tests')]
from PIL import Image
from videocreate import local_sources, manager_stills
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json
from videocreate.manager import Manager
from videocreate.manager_projects import open_panel
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project, save_bundle
from videocreate.runtime.state import read_state
from test_v3_config import config


class ManagerStaticImageTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.parent=Path(self.temp.name);self.path=self.parent/'config.json'
        atomic_json(self.path,migrate(config()))
        self.source=self.parent/'static.png';Image.new('RGB',(80,48),'red').save(self.source)
        self.project=self.parent/'edit';save_bundle(self.project,create('edit-only'))
        self.window=tk.Tk();self.window.withdraw();self.manager=Manager(self.window,self.path)
        def dispose():
            self.window.update_idletasks();self.window.destroy();self.manager=None;gc.collect()
        self.addCleanup(dispose)

    def wait_for(self,predicate,timeout=10):
        deadline=time.monotonic()+timeout
        def check():
            if predicate() or time.monotonic()>=deadline:self.window.quit()
            else:self.window.after(10,check)
        self.window.after(0,check);self.window.mainloop();self.assertTrue(predicate())

    def set_field(self,form,key,value):
        next(var for path,var,kind in form.fields if path==key).set(value)

    def widgets(self,parent):
        for child in parent.winfo_children():yield child;yield from self.widgets(child)

    def test_mapped_project_button_imports_in_background_without_config_or_task_changes(self):
        from tkinter import ttk
        panel=open_panel(self.manager,self.project)
        self.window.attributes('-alpha',0);self.window.deiconify();panel.attributes('-alpha',0);panel.deiconify()
        self.wait_for(lambda:panel.winfo_ismapped() and panel.winfo_width()>1)
        self.window.update_idletasks()
        button=next(w for w in self.widgets(panel) if isinstance(w,ttk.Button) and w.cget('text')=='导入静态图片')
        self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(button.winfo_rootx()-panel.winfo_rootx()+button.winfo_width(),panel.winfo_width())
        self.assertLessEqual(button.winfo_rooty()-panel.winfo_rooty()+button.winfo_height(),panel.winfo_height())
        with mock.patch('tkinter.filedialog.askopenfilename',return_value=str(self.source)):
            button.invoke()
        dialog=next(w for w in self.window.winfo_children() if hasattr(w,'still_form'))
        self.set_field(dialog.still_form,'seconds','.5')
        before=self.path.read_bytes();threads=[];original=local_sources.import_image
        def run(*args,**kwargs):threads.append(threading.get_ident());return original(*args,**kwargs)
        with mock.patch.object(local_sources,'import_image',side_effect=run), \
                mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            dialog.still_submit.invoke();self.wait_for(lambda:not dialog.winfo_exists())
        self.assertEqual(len(threads),1);self.assertNotEqual(threads[0],threading.get_ident())
        self.assertEqual(load_project(self.project)['generation-plan']['local_sources'][0]['kind'],'image')
        self.assertEqual(read_state(self.project)['ledger'],[]);self.assertEqual(before,self.path.read_bytes())

    def test_invalid_hold_stays_open_and_keeps_original_project(self):
        dialog=manager_stills.open_form(self.manager,self.project,source=self.source)
        self.set_field(dialog.still_form,'seconds','0')
        before={p.name:p.read_bytes() for p in self.project.glob('*.json')}
        with mock.patch.object(self.manager,'error') as error:
            dialog.still_submit.invoke();self.wait_for(lambda:error.called)
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.project.glob('*.json')})

    def test_double_click_and_close_finish_one_import_without_destroyed_callback(self):
        dialog=manager_stills.open_form(self.manager,self.project,source=self.source)
        started,release,finished=threading.Event(),threading.Event(),threading.Event()
        original=local_sources.import_image;calls=[]
        def run(*args,**kwargs):
            calls.append(1);started.set();release.wait(5)
            try:return original(*args,**kwargs)
            finally:finished.set()
        try:
            with mock.patch.object(local_sources,'import_image',side_effect=run), \
                    mock.patch.object(self.window,'report_callback_exception') as error:
                dialog.still_submit.invoke();self.wait_for(started.is_set)
                dialog.still_submit.invoke();dialog.destroy();release.set();self.wait_for(finished.is_set)
                self.window.after(200,self.window.quit);self.window.mainloop();error.assert_not_called()
        finally:release.set();finished.wait(10)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(load_project(self.project)['generation-plan']['local_sources']),1)


if __name__=='__main__':unittest.main()
