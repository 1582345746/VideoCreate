"""Recover actual raw controls, tier state and pending config after editor loss."""
import copy
import gc
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from test_v3_config import config
from videocreate import manager_lifecycle as ui
from videocreate.config import drafts, management
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.manager import Manager
from videocreate.manager_recovery import capture, children, controls


@unittest.skipUnless(os.name=='nt','Encrypted native recovery requires Windows')
class ManagerRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.folder=Path(temp.name);self.path=self.folder/'config.json'
        atomic_json(self.path,management.migrate(config()));self.before=self.path.read_bytes()
        self.roots=[];self.errors=[];self.manager=self.create()
        def cleanup():
            for root in self.roots:
                try:root.destroy()
                except tk.TclError:pass
            gc.collect();ui.reap_interpreters();self.assertEqual(self.errors,[])
        self.addCleanup(cleanup)

    def create(self):
        root=tk.Tk();root.withdraw();self.roots.append(root)
        root.report_callback_exception=lambda *args:self.errors.append(args)
        return Manager(root,self.path)

    def widgets(self,parent):
        for child in parent.winfo_children():yield child;yield from self.widgets(child)

    def entry(self,win):
        return next(w for w in self.widgets(win) if isinstance(w,ttk.Entry) and not w.instate(['readonly']))

    def edit(self,win,text='unapplied-recovery-中文'):
        entry=self.entry(win);entry.delete(0,'end');entry.insert(0,text)

    def button(self,win,title):
        return next(w for w in self.widgets(win) if isinstance(w,ttk.Button) and w.cget('text')==title)

    def recover(self):
        self.manager.recovery.checkpoint();session=self.manager.recovery.store.session
        self.manager.window.destroy();new=self.create()
        with mock.patch.object(drafts,'owner_status',return_value='stopped'):new.recovery.restore(session)
        return new

    def test_upstream_raw_unicode_invalid_numbers_restore_without_applying(self):
        win=self.manager.edit_upstream('primary-sub2api');self.edit(win)
        expected=controls(win);new=self.recover();restored=children(new.window)[0]
        self.assertEqual(controls(restored),expected);self.assertTrue(restored.draft_guard.dirty())
        self.assertFalse(new.dirty);self.assertEqual(self.path.read_bytes(),self.before)

    def test_pending_configuration_restores_but_save_remains_explicit(self):
        self.manager.value['bindings']['grok-on-sub2api']['notes']='applied-unsaved'
        self.manager.changed();new=self.recover()
        self.assertTrue(new.dirty);self.assertEqual(new.value['bindings']['grok-on-sub2api']['notes'],'applied-unsaved')
        self.assertEqual(self.path.read_bytes(),self.before)
        with mock.patch('videocreate.manager.messagebox.askyesno',return_value=True):self.assertTrue(new.save())
        self.assertFalse(new.dirty);self.assertNotEqual(self.path.read_bytes(),self.before)

    def test_binding_invalid_advanced_text_and_checkbox_preserved(self):
        win=self.manager.edit_binding('grok-on-sub2api')
        text=next(w for w in self.widgets(win) if isinstance(w,tk.Text) and w.cget('state')!='disabled')
        text.insert('end','{incomplete JSON')
        check=next(w for w in self.widgets(win) if isinstance(w,ttk.Checkbutton));check.invoke()
        expected=controls(win);new=self.recover()
        self.assertEqual(controls(children(new.window)[0]),expected);self.assertFalse(new.dirty)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_applied_tier_and_nested_unapplied_tier_are_both_restored(self):
        win=self.manager.edit_binding('grok-on-sub2api')
        first=win.recovery_price();entries=[w for w in self.widgets(first) if isinstance(w,ttk.Entry)]
        entries[-2].insert(0,'2.5');self.button(first,'应用档位').invoke()
        second=win.recovery_price();self.edit(second,'not-a-valid-operation')
        expected=capture(win);new=self.recover();actual=capture(children(new.window)[0])
        self.assertEqual(actual,expected);self.assertFalse(new.dirty);self.assertEqual(self.path.read_bytes(),self.before)

    def test_credential_input_is_excluded_even_with_other_drafts(self):
        self.manager.value['bindings']['grok-on-sub2api']['notes']='pending';self.manager.changed()
        self.manager.current_upstream='primary-sub2api';self.manager.credential()
        win=next(w for w in self.manager.window.winfo_children() if isinstance(w,tk.Toplevel))
        entry=next(w for w in self.widgets(win) if isinstance(w,ttk.Entry) and w.cget('show'))
        entry.insert(0,'never-persist-this-credential')
        self.manager.recovery.checkpoint();value=self.manager.recovery.store.read(self.manager.recovery.store.session)
        self.assertNotIn('never-persist',str(value));self.assertEqual(value['forms'],[])
        self.assertFalse((self.folder/'secrets.dpapi').exists())

    def test_clean_forms_and_credentials_only_create_no_snapshot(self):
        self.manager.edit_binding('grok-on-sub2api');self.manager.recovery.checkpoint()
        self.assertFalse(self.manager.recovery.store.target.exists())
        self.manager.current_upstream='primary-sub2api';self.manager.credential();self.manager.recovery.checkpoint()
        self.assertFalse(self.manager.recovery.store.target.exists())

    def test_recovery_refuses_current_edits_or_changed_disk(self):
        win=self.manager.edit_upstream('primary-sub2api');self.edit(win);self.manager.recovery.checkpoint()
        session=self.manager.recovery.store.session;other=self.create()
        other.value['bindings']['grok-on-sub2api']['notes']='new local edit';other.changed()
        with self.assertRaises(ConfigError):other.recovery.restore(session)
        other.dirty=False;other.value=copy.deepcopy(other.record['config'])
        value=copy.deepcopy(other.value);value['revision']+=1;atomic_json(self.path,value)
        with mock.patch.object(drafts,'owner_status',return_value='stopped'):
            with self.assertRaises(ConfigError):other.recovery.restore(session)
        self.assertTrue(self.manager.recovery.store.target.exists())

    def test_failed_layout_recovery_rolls_back_all_windows_and_keeps_original(self):
        win=self.manager.edit_upstream('primary-sub2api');self.edit(win);self.manager.recovery.checkpoint()
        session=self.manager.recovery.store.session;packet=self.manager.recovery.store.read(session)
        packet['forms'][0]['controls'].pop()
        self.manager.recovery.store.save(self.manager.record['token'],packet['value'],packet['forms'])
        new=self.create();before=copy.deepcopy(new.value)
        with mock.patch.object(drafts,'owner_status',return_value='stopped'):
            with self.assertRaises(ConfigError):new.recovery.restore(session)
        self.assertEqual(new.value,before);self.assertEqual(children(new.window),[]);self.assertFalse(new.dirty)
        self.assertTrue(self.manager.recovery.store.target.exists())

    def test_normal_discard_exit_removes_only_own_snapshot_cancel_keeps_it(self):
        self.manager.value['bindings']['grok-on-sub2api']['notes']='pending';self.manager.changed()
        self.manager.recovery.checkpoint();path=self.manager.recovery.store.target
        with mock.patch('videocreate.manager.messagebox.askyesnocancel',return_value=None):self.manager.close()
        self.assertTrue(path.exists())
        with mock.patch('videocreate.manager.messagebox.askyesnocancel',return_value=False):self.manager.close()
        self.assertFalse(path.exists());self.assertEqual(self.path.read_bytes(),self.before)

    def test_media_settings_restore_does_not_publish_start_or_check_network(self):
        win=self.manager.media_panel();self.edit(win,'https://media.example.test');expected=controls(win)
        with mock.patch('videocreate.media_server.start') as start,mock.patch('videocreate.media_server.publish') as publish:
            new=self.recover();start.assert_not_called();publish.assert_not_called()
        self.assertEqual(controls(children(new.window)[0]),expected);self.assertFalse(new.dirty)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_timer_failure_is_visible_retains_input_and_retries(self):
        win=self.manager.edit_upstream('primary-sub2api');self.edit(win)
        recovery=self.manager.recovery
        recovery.manager.window.after_cancel(recovery.timer);recovery.timer=None
        with mock.patch.object(recovery.store,'save',side_effect=OSError('disk unavailable')):
            recovery.tick()
        self.assertTrue(recovery.error);self.assertIn('失败',recovery.note.get())
        self.assertTrue(win.draft_guard.dirty());self.assertEqual(self.path.read_bytes(),self.before)
        recovery.checkpoint();self.assertIsNone(recovery.error);self.assertTrue(recovery.store.target.exists())

    def test_multiple_windows_for_same_binding_preserve_distinct_original_inputs(self):
        first=self.manager.edit_binding('grok-on-sub2api');self.edit(first,'first draft')
        second=self.manager.edit_binding('grok-on-sub2api');self.edit(second,'second draft')
        expected=[capture(first),capture(second)];new=self.recover()
        self.assertEqual([capture(w) for w in children(new.window)],expected)
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_recovery_encryption_failure_rolls_back_but_retains_old_draft(self):
        win=self.manager.edit_upstream('primary-sub2api');self.edit(win);self.manager.recovery.checkpoint()
        session=self.manager.recovery.store.session;new=self.create()
        with mock.patch.object(drafts,'owner_status',return_value='stopped'), \
                mock.patch.object(new.recovery.store,'save',side_effect=OSError('disk unavailable')):
            with self.assertRaises(ConfigError):new.recovery.restore(session)
        self.assertEqual(children(new.window),[]);self.assertFalse(new.dirty)
        self.assertTrue(self.manager.recovery.store.target.exists())

    def test_form_discard_and_successful_reload_remove_current_snapshot(self):
        win=self.manager.edit_upstream('primary-sub2api');self.edit(win);self.manager.recovery.checkpoint()
        target=self.manager.recovery.store.target;self.assertTrue(target.exists())
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=True):self.manager.reload()
        self.manager.recovery.checkpoint();self.assertFalse(target.exists())
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_v3_automatic_migration_does_not_block_its_original_draft(self):
        self.manager.window.destroy();atomic_json(self.path,config());self.before=self.path.read_bytes()
        self.manager=self.create();self.assertTrue(self.manager.dirty)
        self.manager.value['bindings']['grok-on-sub2api']['notes']='pending v3 migration'
        self.manager.changed();new=self.recover()
        self.assertTrue(new.dirty);self.assertEqual(new.value['schema_version'],4)
        self.assertEqual(new.value['bindings']['grok-on-sub2api']['notes'],'pending v3 migration')
        self.assertEqual(self.path.read_bytes(),self.before)


if __name__=='__main__':unittest.main()
