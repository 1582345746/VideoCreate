import copy
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate.catalog import discovery,observations
from videocreate.config.management import migrate
from videocreate.config.storage import ConfigError,atomic_json
from videocreate.manager import Manager


class CatalogObservationUITests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.root.update_idletasks();self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(str(args[1]))
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'config.json';self.uid='primary-sub2api'
        self.value=migrate(config());atomic_json(self.path,self.value);self.original=self.path.read_bytes()
        self.manager=Manager(self.root,self.path);self.manager.current_upstream=self.uid
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.root.update_idletasks();self.root.destroy();self.assertEqual(self.errors,[])

    def record(self,ids):return observations.record(self.value,self.uid,ids,store_root=self.path.parent)

    def wait(self,predicate):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            self.root.update()
            if predicate():return
            time.sleep(.005)
        self.fail('Catalog operation did not finish')

    def panel(self):
        window=self.manager.discover(refresh=False);window.withdraw()
        panel=window.catalog_panel;self.wait(lambda:not panel.background.busy)
        return panel

    def select(self,panel,remote):
        panel.tree.selection_set(next(key for key,name in panel.items.items() if name==remote))

    def test_cached_native_table_filters_historical_absence_separately_from_local(self):
        local=next(b['remote_model'] for b in self.value['bindings'].values() if b['upstream']==self.uid)
        self.record([local,'never-imported','stable']);self.record(['stable','New-V'])
        with mock.patch('urllib.request.build_opener',side_effect=AssertionError('No network')),\
             mock.patch('videocreate.catalog.discovery.resolve_key',side_effect=AssertionError('No key')):
            panel=self.panel()
            panel.view.set('相比上次未再出现')
            self.assertEqual(set(panel.items.values()),{local,'never-imported'})
            panel.view.set('本地未出现在目录')
            self.assertNotIn('never-imported',panel.items.values());self.assertIn(local,panel.items.values())
            panel.view.set('相比上次新增');self.assertEqual(list(panel.items.values()),['New-V'])
            panel.view.set('可导入');panel.query.set('NEW-v');self.assertEqual(list(panel.items.values()),['New-V'])
            self.assertIn('observation_hash',panel.details.get('1.0','end'))
        self.assertEqual(self.path.read_bytes(),self.original);self.assertFalse(self.manager.dirty)

    def test_import_is_source_bound_disabled_memory_draft_until_main_save(self):
        self.record(['Seedance-V']);panel=self.panel();self.select(panel,'Seedance-V')
        panel.family.set('seedance');panel.apply()
        draft=next(b for b in self.manager.value['bindings'].values() if b['remote_model']=='Seedance-V')
        self.assertFalse(draft['enabled']);self.assertEqual(draft['adapter'],'unconfigured')
        self.assertEqual(draft['declared_capabilities']['source']['kind'],'catalog')
        self.assertTrue(self.manager.dirty);self.assertFalse(panel.win.draft_guard.dirty())
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse(next(row for row in panel.result['rows'] if row['remote_model']=='Seedance-V')['importable'])

    def test_repeated_import_of_existing_exact_id_does_not_mark_dirty(self):
        local=next(b['remote_model'] for b in self.value['bindings'].values() if b['upstream']==self.uid)
        self.record([local]);panel=self.panel();self.select(panel,local);before=copy.deepcopy(self.manager.value)
        panel.apply();self.assertEqual(self.manager.value,before);self.assertFalse(self.manager.dirty)

    def test_changed_config_blocks_stale_import_until_reload(self):
        self.record(['new']);panel=self.panel();self.select(panel,'new')
        self.manager.value['upstreams'][self.uid]['notes']='changed elsewhere'
        before=copy.deepcopy(self.manager.value)
        with mock.patch.object(self.manager,'error') as error:panel.apply();error.assert_called_once()
        self.assertEqual(self.manager.value,before);self.assertFalse(self.manager.dirty)
        panel.saved();self.wait(lambda:not panel.background.busy);self.select(panel,'new');panel.apply()
        self.assertTrue(self.manager.dirty)

    def test_changed_observation_file_blocks_import_and_keeps_memory_untouched(self):
        report=self.record(['new']);panel=self.panel();self.select(panel,'new')
        Path(report['evidence']).write_text('{}',encoding='utf-8');before=copy.deepcopy(self.manager.value)
        with mock.patch.object(self.manager,'error') as error:panel.apply();error.assert_called_once()
        self.assertEqual(self.manager.value,before);self.assertFalse(self.manager.dirty)

    def test_absent_history_row_cannot_be_imported_as_current_catalog(self):
        self.record(['gone']);self.record(['current']);panel=self.panel();self.select(panel,'gone')
        before=copy.deepcopy(self.manager.value)
        with mock.patch.object(self.manager,'error') as error:panel.apply();error.assert_called_once()
        self.assertEqual(self.manager.value,before);self.assertFalse(self.manager.dirty)

    def test_duplicate_refresh_is_one_get_and_close_detaches_after_observation_commit(self):
        entered=threading.Event();release=threading.Event();done=threading.Event();calls=[]
        def service(value,uid,store_root):
            calls.append(uid);entered.set()
            try:
                if not release.wait(5):raise RuntimeError('missing release')
                return observations.record(value,uid,['committed-after-close'],store_root=store_root)
            finally:done.set()
        try:
            with mock.patch('videocreate.catalog.discovery.models',side_effect=service):
                window=self.manager.discover();window.withdraw();panel=window.catalog_panel
                self.wait(entered.is_set);panel.refresh();panel.saved();panel.apply()
                self.assertTrue(panel.refresh_button.instate(['disabled']))
                self.assertTrue(panel.import_button.instate(['disabled']))
                window.destroy();self.assertIsNone(panel.background.scheduled)
                self.assertIsNone(panel.background.completed)
                release.set();self.wait(done.is_set)
        finally:release.set()
        self.assertEqual(calls,[self.uid]);self.assertEqual(self.path.read_bytes(),self.original)
        self.assertEqual(observations.show(self.value,self.uid,store_root=self.path.parent)['ids'],['committed-after-close'])

    def test_refresh_failure_preserves_disk_baseline_and_cached_recovery(self):
        first=self.record(['keep']);panel=self.panel()
        with mock.patch('videocreate.catalog.discovery.models',side_effect=ConfigError('read failed')):
            panel.refresh();self.wait(lambda:not panel.background.busy)
        self.assertIsNone(panel.result);self.assertTrue(panel.import_button.instate(['disabled']))
        self.assertIn('read failed',panel.note.get());self.assertTrue(Path(first['evidence']).exists())
        panel.saved();self.wait(lambda:not panel.background.busy);self.assertEqual(panel.result['ids'],['keep'])

    def test_no_cached_observation_offers_refresh_without_implicit_get(self):
        with mock.patch('videocreate.catalog.discovery.models',side_effect=AssertionError('No implicit refresh')) as get:
            panel=self.panel();get.assert_not_called()
        self.assertEqual(panel.result['status'],'no-observation')
        self.assertFalse(panel.items);self.assertTrue(panel.import_button.instate(['disabled']))

    def test_import_form_close_cancellation_preserves_unapplied_family(self):
        self.record(['new']);panel=self.panel();panel.family.set('my-family')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):panel.win.draft_guard.close()
        self.assertTrue(panel.win.winfo_exists());self.assertEqual(panel.family.get(),'my-family')
        self.assertFalse(self.manager.dirty);self.assertEqual(self.path.read_bytes(),self.original)


if __name__=='__main__':unittest.main()
