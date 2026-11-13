"""Real Tk controls exercise policy preview/save and plan-only checkpoints."""
import gc
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'videocreate/src'),str(ROOT/'tests')]
from videocreate import production,production_policy
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json,load_json
from videocreate.manager import Manager
from videocreate.manager_projects import open_panel as project_panel
from videocreate.manager_policy import open_panel,MODES
from videocreate.planning.examples import smart_car
from videocreate.planning.project import save_bundle,load_project
from videocreate.runtime.state import read_state
from test_v3_config import config


class ManagerProductionPolicyTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.parent=Path(self.temp.name);self.root=self.parent/'project';save_bundle(self.root,smart_car())
        self.window=tk.Tk();self.window.withdraw()
        self.path=self.parent/'config.json';atomic_json(self.path,migrate(config()))
        self.manager=Manager(self.window,self.path)
        self.errors=patch.object(self.manager,'error');self.error=self.errors.start();self.addCleanup(self.errors.stop)
        self.network=patch('urllib.request.urlopen',side_effect=AssertionError('No real network'))
        self.network.start();self.addCleanup(self.network.stop)
        def dispose():
            self.window.update_idletasks();self.window.destroy();self.manager=None;gc.collect()
        self.addCleanup(dispose)

    def widgets(self,parent):
        for child in parent.winfo_children():
            yield child;yield from self.widgets(child)

    def button(self,parent,label):
        return next(w for w in self.widgets(parent) if w.winfo_class()=='TButton' and w.cget('text')==label)

    def wait(self,predicate):
        deadline=time.monotonic()+10
        def check():
            if predicate() or time.monotonic()>=deadline:self.window.quit()
            else:self.window.after(10,check)
        self.window.after(0,check);self.window.mainloop();self.assertTrue(predicate())

    def open(self):
        win=open_panel(self.manager,self.root);win.withdraw();panel=win.policy_panel
        self.wait(lambda:panel.snapshot is not None and not panel.busy)
        return win,panel

    def draft(self,panel):
        label=next(k for k,v in MODES.items() if v=='auto-within-authorization')
        panel.mode.set(label);panel.selector.event_generate('<<ComboboxSelected>>')
        panel.checks[list(production.AUTHORING).index('script')].invoke()
        panel.reason.set('User requests automatic progression with a script checkpoint')
        self.button(panel.win,'预览策略变化').invoke()
        self.wait(lambda:not panel.busy and panel.preview_result is not None)

    def test_actual_project_entry_loads_shared_service_off_thread_and_fits_window(self):
        calls=[];real=production_policy.describe;main=threading.get_ident();before=self.path.read_bytes()
        def read(root):calls.append(threading.get_ident());return real(root)
        with patch('videocreate.production_policy.describe',side_effect=read),patch('videocreate.cli.read_config',side_effect=AssertionError('No provider config')):
            project=project_panel(self.manager,self.root);project.withdraw()
            self.button(project,'制作流程与检查点').invoke()
            wins=[w for w in self.window.winfo_children() if hasattr(w,'policy_panel')]
            self.assertEqual(len(wins),1);win=wins[0];panel=win.policy_panel
            self.wait(lambda:panel.snapshot is not None and not panel.busy)
        self.assertEqual(len(calls),1);self.assertNotEqual(calls[0],main)
        self.window.attributes('-alpha',0);self.window.deiconify()
        project.attributes('-alpha',0);project.deiconify()
        win.attributes('-alpha',0);win.deiconify();self.wait(lambda:win.winfo_ismapped())
        self.window.update_idletasks()
        for w in self.widgets(win):
            if w.winfo_class()!='TButton':continue
            self.assertTrue(w.winfo_ismapped(),w.cget('text'))
            x=w.winfo_rootx()-win.winfo_rootx();y=w.winfo_rooty()-win.winfo_rooty()
            self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
            self.assertLessEqual(x+w.winfo_width(),win.winfo_width(),w.cget('text'))
            self.assertLessEqual(y+w.winfo_height(),win.winfo_height(),w.cget('text'))
        self.assertEqual(self.path.read_bytes(),before);self.assertFalse((self.root/'production').exists())
        self.error.assert_not_called();win.destroy();project.destroy()

    def test_actual_preview_save_and_selected_stage_checkpoint_preserve_tasks_and_approvals(self):
        win,panel=self.open();before={p.name:p.read_bytes() for p in self.root.glob('*.json')};config_before=self.path.read_bytes()
        self.assertTrue(self.button(win,'保存已预览策略').instate(['disabled']))
        self.draft(panel)
        self.assertEqual(panel.preview_result['after']['next']['id'],'script')
        self.assertFalse((self.root/'production').exists())
        self.button(win,'保存已预览策略').invoke()
        self.wait(lambda:not panel.busy and panel.snapshot['policy']=='auto-within-authorization')
        self.assertEqual(production.status(self.root)['next']['id'],'script')
        self.assertEqual(load_json(self.root/'production/stages.json')['decisions'],{})
        panel.tree.selection_set('script');self.button(win,'核对选中策划阶段').invoke()
        self.wait(lambda:not panel.busy)
        inspection=next(w for w in self.window.winfo_children() if hasattr(w,'title') and w.title()=='继续制作 · 剧本与对白')
        entry=next(w for w in self.widgets(inspection) if w.winfo_class()=='TEntry')
        entry.insert(0,'Inspected actual fixture screenplay; not media acceptance')
        self.button(inspection,'登记本阶段计划已核对').invoke()
        self.wait(lambda:not inspection.winfo_exists() and not panel.busy)
        self.assertEqual(production.status(self.root)['next']['id'],'generation')
        self.assertEqual(production.status(self.root)['review']['status'],'draft_preview')
        self.assertEqual(read_state(self.root)['jobs'],{});self.assertEqual(read_state(self.root)['ledger'],[])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.glob('*.json')})
        self.assertEqual(self.path.read_bytes(),config_before);self.error.assert_not_called();win.destroy()

    def test_changed_source_rejects_save_and_changed_controls_invalidate_preview(self):
        win,panel=self.open();self.draft(panel)
        panel.reason.set('A revised basis')
        self.assertIsNone(panel.preview_result);self.assertTrue(self.button(win,'保存已预览策略').instate(['disabled']))
        self.button(win,'预览策略变化').invoke();self.wait(lambda:not panel.busy and panel.preview_result is not None)
        brief=load_project(self.root)['brief'];brief['audience']='A new audience';atomic_json(self.root/'brief.json',brief)
        self.button(win,'保存已预览策略').invoke();self.wait(lambda:not panel.busy)
        self.error.assert_called_once();self.assertFalse((self.root/'production/stages.json').exists())
        self.assertIsNone(panel.preview_result);win.destroy()

    def test_double_click_and_close_complete_one_save_without_tk_worker_callbacks(self):
        win,panel=self.open();self.draft(panel)
        entered,release,done=threading.Event(),threading.Event(),threading.Event();calls=[]
        real=production_policy.save;main=threading.get_ident();callback_errors=[]
        self.window.report_callback_exception=lambda *args:callback_errors.append(args)
        def delayed(*args,**kwargs):
            calls.append(threading.get_ident());entered.set()
            try:
                if not release.wait(8):raise RuntimeError('Test release missing')
                return real(*args,**kwargs)
            finally:done.set()
        with patch('videocreate.production_policy.save',side_effect=delayed):
            self.button(win,'保存已预览策略').invoke();self.button(win,'保存已预览策略').invoke()
            self.wait(entered.is_set);win.destroy();release.set();self.wait(done.is_set)
        self.assertEqual(len(calls),1);self.assertNotEqual(calls[0],main)
        self.assertEqual(len(load_json(self.root/'production/stages.json')['history']),1)
        self.assertEqual(callback_errors,[]);self.assertEqual(read_state(self.root)['ledger'],[])
        self.error.assert_not_called()


if __name__=='__main__':unittest.main()
