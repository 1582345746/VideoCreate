"""Native task-filter preview/apply affects only the catalog view."""
import copy
import gc
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from test_v3_config import config
from videocreate import manager_lifecycle as ui
from videocreate.config.management import migrate
from videocreate.config.storage import atomic_json
from videocreate.manager import Manager


class ManagerTaskFilterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'config.json';atomic_json(self.path,migrate(config()))
        self.before=self.path.read_bytes();self.root=tk.Tk();self.root.withdraw();self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.manager=Manager(self.root,self.path);self.root.update_idletasks()
        def cleanup():
            self.root.update_idletasks();self.root.destroy();gc.collect();ui.reap_interpreters()
            self.assertEqual(self.errors,[])
        self.addCleanup(cleanup)

    def form(self):
        win=self.manager.task_filter();return win.task_filter_panel

    def preview(self,panel):
        panel.fields['seconds'].set('5');panel.fields['resolution'].set('720p');panel.fields['aspect_ratio'].set('16:9')
        panel.preview();self.assertIsNotNone(panel.pending)

    def test_preview_and_apply_filter_native_rows_without_saving_or_selecting_route(self):
        value=copy.deepcopy(self.manager.value);panel=self.form();self.preview(panel)
        self.assertIsNone(self.manager.task_scenario);panel.apply()
        self.assertFalse(panel.win.winfo_exists());self.assertIsNotNone(self.manager.task_report)
        self.assertTrue(self.manager.models.get_children())
        self.assertTrue(all(row['task_fit']['matches'] for row in self.manager.task_report['bindings']
            if row['id'] in self.manager.models.get_children()))
        self.assertFalse(self.manager.dirty);self.assertEqual(self.manager.value,value);self.assertEqual(self.path.read_bytes(),self.before)

    def test_include_excluded_displays_reasons_and_clear_restores_catalog(self):
        total=len(self.manager.models.get_children());panel=self.form();panel.excluded.set(True)
        self.preview(panel);panel.apply();self.assertEqual(len(self.manager.models.get_children()),total)
        excluded=next(row for row in self.manager.task_report['bindings'] if row['task_fit']['reasons'])
        self.manager.models.selection_set(excluded['id']);self.manager.show_details()
        self.assertIn(excluded['task_fit']['reasons'][0],self.manager.detail.get('1.0','end'))
        self.manager.clear_task_filter();self.assertIsNone(self.manager.task_report)
        self.assertEqual(len(self.manager.models.get_children()),total);self.assertFalse(self.manager.dirty)

    def test_edit_after_preview_disables_apply_including_exclusion_toggle(self):
        panel=self.form();self.preview(panel);panel.fields['seconds'].set('6')
        self.assertIsNone(panel.pending);self.assertTrue(panel.apply_button.instate(['disabled']))
        panel.preview();panel.excluded.set(True);self.assertIsNone(panel.pending)
        panel.apply();self.assertIsNone(self.manager.task_scenario)

    def test_invalid_numeric_input_and_image_operation_cannot_apply(self):
        panel=self.form()
        for value in ['nan','0','invalid']:
            panel.fields['seconds'].set(value);panel.preview();self.assertIsNone(panel.pending)
        panel.fields['seconds'].set('5');panel.fields['operation'].set('文生图');panel.preview()
        self.assertIsNone(panel.pending);self.assertIn('image tasks',panel.note.get())
        panel.fields['seconds'].set('');panel.preview();self.assertIsNotNone(panel.pending)

    def test_count_checkbox_is_explicit_and_reopening_keeps_applied_scope(self):
        panel=self.form();panel.fields['operation'].set('图生视频');panel.counts['image'].set('2')
        panel.preview();self.assertNotIn('reference_counts',panel.pending)
        panel.check_counts.set(True);panel.preview();self.assertEqual(panel.pending['reference_counts']['image'],2)
        panel.apply();again=self.form()
        self.assertTrue(again.check_counts.get());self.assertEqual(again.counts['image'].get(),'2')
        self.assertEqual(again.fields['operation'].get(),'图生视频')

    def test_cancel_close_keeps_unapplied_filters_and_main_view(self):
        total=self.manager.models.get_children();panel=self.form();panel.fields['seconds'].set('7')
        with mock.patch('videocreate.manager_drafts.messagebox.askyesno',return_value=False):panel.win.draft_guard.close()
        self.assertTrue(panel.win.winfo_exists());self.assertEqual(panel.fields['seconds'].get(),'7')
        self.assertEqual(self.manager.models.get_children(),total);self.assertIsNone(self.manager.task_scenario)

    def test_config_change_between_preview_and_apply_is_reassessed_without_restoring_old_value(self):
        panel=self.form();self.preview(panel)
        self.manager.value['bindings']['grok-on-sub2api']['enabled']=False
        panel.apply();self.assertNotIn('grok-on-sub2api',self.manager.models.get_children())
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_existing_upstream_search_and_family_filters_compose_and_no_results_can_be_cleared(self):
        self.manager.current_upstream='primary-sub2api';self.manager.family_filter.set('grok')
        panel=self.form();self.preview(panel);panel.apply()
        self.assertTrue(self.manager.models.get_children())
        self.assertTrue(all(self.manager.value['bindings'][bid]['upstream']=='primary-sub2api' for bid in self.manager.models.get_children()))
        self.manager.search.set('not-in-this-catalog');self.assertFalse(self.manager.models.get_children())
        self.manager.clear_task_filter();self.assertFalse(self.manager.models.get_children())
        self.manager.search.set('');self.assertTrue(self.manager.models.get_children())


if __name__=='__main__':unittest.main()
