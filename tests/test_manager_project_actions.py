"""Project-panel local actions stay offline and keep Tk work on its UI thread."""
import gc
import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'videocreate/src'), str(ROOT / 'tests')]

from videocreate.config.management import migrate
from videocreate.config.storage import ConfigError, atomic_json
from videocreate.local_sources import import_clip
from videocreate.manager import Manager
from videocreate.manager_projects import open_panel
from videocreate.planning.profiles import create
from videocreate.planning.project import load_project, save_bundle
from videocreate.runtime.state import read_state, save_state
from test_v3_config import config


class ProjectPanelLocalActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.TemporaryDirectory()
        cls.source = Path(cls.media.name) / 'source.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-nostdin', '-v', 'error', '-y',
            '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=24:duration=2',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(cls.source)],
            capture_output=True, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.media.cleanup()

    def setUp(self):
        import tkinter as tk
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.window = tk.Tk()
        self.window.withdraw()
        def dispose():
            self.window.update_idletasks()
            self.window.destroy()
            self.manager = None
            gc.collect()
        self.addCleanup(dispose)
        self.config_path = self.parent / 'config.json'
        atomic_json(self.config_path, migrate(config()))
        self.manager = Manager(self.window, self.config_path)

    def widgets(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self, parent, text):
        from tkinter import ttk
        return next(widget for widget in self.widgets(parent)
                    if isinstance(widget, ttk.Button) and widget.cget('text') == text)

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        def check():
            if predicate() or time.monotonic() >= deadline:
                self.window.quit()
            else:
                self.window.after(10, check)
        self.window.after(0, check)
        self.window.mainloop()
        self.assertTrue(predicate(), 'background panel action did not finish')

    def test_render_and_delivery_controls_follow_media_profile(self):
        self.window.attributes('-alpha', 0);self.window.deiconify()
        for profile in ('scenic', 'mixed-video', 'edit-only'):
            root = self.parent / profile
            save_bundle(root, create(profile, title='Panel local actions'))
            panel = open_panel(self.manager, root)
            panel.withdraw()
            labels = [widget.cget('text') for widget in self.widgets(panel)
                      if widget.winfo_class() == 'TButton']
            self.assertIn('导出交付清单', labels)
            self.assertIn('渲染当前时间线', labels)
            self.assert_controls_visible(panel)
            panel.destroy()
        for profile in ('image-only', 'gif-only', 'gif-local'):
            root = self.parent / profile
            save_bundle(root, create(profile, title='Panel local actions', topic='Offline collection'))
            panel = open_panel(self.manager, root)
            panel.withdraw()
            labels = [widget.cget('text') for widget in self.widgets(panel)
                      if widget.winfo_class() == 'TButton']
            self.assertIn('导出交付清单', labels)
            self.assertNotIn('渲染当前时间线', labels)
            self.assert_controls_visible(panel)
            panel.destroy()

    def assert_controls_visible(self, panel):
        from tkinter import ttk
        panel.attributes('-alpha', 0);panel.deiconify()
        self.wait_for(lambda: panel.winfo_ismapped() and panel.winfo_width() > 1)
        self.window.update_idletasks()
        self.assertEqual((panel.winfo_width(), panel.winfo_height()), (1040, 760))
        for widget in self.widgets(panel):
            if not isinstance(widget, ttk.Button):
                continue
            self.assertTrue(widget.winfo_ismapped(), widget.cget('text'))
            x = widget.winfo_rootx() - panel.winfo_rootx()
            y = widget.winfo_rooty() - panel.winfo_rooty()
            self.assertGreater(widget.winfo_width(), 1, widget.cget('text'))
            self.assertGreaterEqual(x, 0);self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + widget.winfo_width(), panel.winfo_width())
            self.assertLessEqual(y + widget.winfo_height(), panel.winfo_height())

    def test_render_is_background_local_action_and_does_not_read_provider_config(self):
        root = self.parent / 'edit-only'
        save_bundle(root, create('edit-only', title='Panel render'))
        import_clip(root, self.source, source_id='local', start=0, end=1)
        panel = open_panel(self.manager, root)
        panel.withdraw()
        calls = []
        main_thread = threading.get_ident()

        def fake_render(project, bundle, state, **kwargs):
            calls.append((threading.get_ident(), project, kwargs))
            return {'ok': True, 'path': str(project / 'deliverables' / 'preview.mp4')}

        with mock.patch('videocreate.timeline.render.render', side_effect=fake_render), \
                mock.patch('videocreate.cli.read_config', side_effect=AssertionError('provider config is not needed')), \
                mock.patch.object(self.manager, 'error') as error:
            self.button(panel, '渲染当前时间线').invoke()
            self.wait_for(lambda: '时间线渲染完成：' in self._message_text(panel))
            error.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0][0], main_thread)
        self.assertEqual(calls[0][2]['output_name'], 'preview.mp4')
        panel.destroy()

    def local_project(self):
        root = self.parent / 'real-render'
        save_bundle(root, create('edit-only', title='Current local timeline'))
        import_clip(root, self.source, source_id='local', start=0, end=1)
        timeline = load_project(root)['timeline']
        timeline.update(width=128, height=72)
        atomic_json(root / 'timeline.json', timeline)
        save_state(root, {'schema_version': 3, 'jobs': {}, 'ledger': []})
        return root

    def test_real_render_and_delivery_use_latest_saved_timeline_and_preserve_inputs(self):
        import json
        root = self.local_project()
        panel = open_panel(self.manager, root);panel.withdraw()
        timeline = load_project(root)['timeline']
        timeline['subtitles'] = [{'text': 'Caption saved after panel opened', 'start': .1, 'end': .8}]
        atomic_json(root / 'timeline.json', timeline)
        before = {path.name: path.read_bytes() for path in root.glob('*.json')}
        config_before = self.config_path.read_bytes()
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('No network')), \
                mock.patch('videocreate.cli.read_config', side_effect=AssertionError('No provider config')), \
                mock.patch('videocreate.runtime.jobs.client', side_effect=AssertionError('No task client')), \
                mock.patch.object(self.manager, 'error') as error:
            self.button(panel, '渲染当前时间线').invoke()
            self.wait_for(lambda: '时间线渲染完成：' in self._message_text(panel), timeout=20)
            rendered = root / 'deliverables/preview.mp4'
            self.assertTrue(rendered.is_file())
            self.assertIn('Caption saved after panel opened', rendered.with_suffix('.srt').read_text(encoding='utf-8'))
            self.assertIn('完整解码：pass', self._message_text(panel))
            self.button(panel, '导出交付清单').invoke()
            self.wait_for(lambda: '交付清单导出完成：' in self._message_text(panel))
            delivered = json.loads((root / 'deliverables/preview.delivery.json').read_text(encoding='utf-8'))
            self.assertEqual(delivered['status'], 'review_pending')
            self.assertEqual(delivered['video']['sha256'], hashlib.sha256(rendered.read_bytes()).hexdigest())
            self.assertEqual(delivered['budget']['requests'], 0)
            self.assertTrue(delivered['unverified'])
            error.assert_not_called()
        self.assertEqual(config_before, self.config_path.read_bytes())
        self.assertEqual(before, {path.name: path.read_bytes() for path in root.glob('*.json')})
        self.assertEqual(read_state(root)['ledger'], [])
        panel.destroy()

    def test_failed_render_keeps_previous_output_and_can_retry(self):
        root = self.local_project()
        panel = open_panel(self.manager, root);panel.withdraw()
        target = root / 'deliverables/preview.mp4';target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'previous local output')
        before = {path.name: path.read_bytes() for path in root.glob('*.json')}
        with mock.patch('videocreate.timeline.render.run', side_effect=ConfigError('Synthetic FFmpeg failure')), \
                mock.patch.object(self.manager, 'error') as error:
            self.button(panel, '渲染当前时间线').invoke()
            self.wait_for(lambda: error.called)
            self.assertIn('Synthetic FFmpeg failure', str(error.call_args[0][0]))
        self.assertEqual(target.read_bytes(), b'previous local output')
        self.assertEqual(before, {path.name: path.read_bytes() for path in root.glob('*.json')})
        self.assertEqual(str(self.button(panel, '渲染当前时间线').cget('state')), 'normal')
        panel.destroy()

    def test_double_click_is_single_action_and_closing_cancels_only_ui_polling(self):
        root = self.local_project()
        panel = open_panel(self.manager, root);panel.withdraw()
        started = threading.Event();release = threading.Event();finished = threading.Event()
        calls = []
        from videocreate.manager_projects import local_action as real_action
        def action(*args, **kwargs):
            try:
                return real_action(*args, **kwargs)
            finally:
                # The helper rechecks production status after render returns.
                # Keep fixture files alive until that whole transaction ends.
                finished.set()
        def render(*args, **kwargs):
            started.set();calls.append(threading.get_ident())
            release.wait(5)
            return {'ok': True, 'path': 'local.mp4'}
        try:
            with mock.patch('videocreate.timeline.render.render', side_effect=render), \
                    mock.patch('videocreate.manager_projects.local_action', side_effect=action), \
                    mock.patch.object(self.manager, 'error') as error, \
                    mock.patch.object(self.window, 'report_callback_exception') as callback_error:
                self.button(panel, '渲染当前时间线').invoke()
                self.wait_for(started.is_set)
                self.button(panel, '渲染当前时间线').invoke()
                self.assertEqual(len(calls), 1)
                self.assertEqual(str(self.button(panel, '导出交付清单').cget('state')), 'disabled')
                panel.destroy();release.set()
                self.wait_for(finished.is_set)
                self.window.after(300, self.window.quit)
                self.window.mainloop()
                callback_error.assert_not_called();error.assert_not_called()
        finally:
            release.set()
            finished.wait(10)

    def test_delivery_is_background_local_action_and_preserves_project_files(self):
        root = self.parent / 'scenic'
        save_bundle(root, create('scenic', title='Panel delivery'))
        before = {path.name: path.read_bytes() for path in root.glob('*.json')}
        panel = open_panel(self.manager, root)
        panel.withdraw()
        calls = []

        def fake_delivery(project, **kwargs):
            calls.append((threading.get_ident(), project, kwargs))
            return {'ok': True, 'manifest': str(project / 'deliverables' / 'preview.delivery.json')}

        with mock.patch('videocreate.production.delivery', side_effect=fake_delivery), \
                mock.patch('videocreate.cli.read_config', side_effect=AssertionError('provider config is not needed')), \
                mock.patch.object(self.manager, 'error') as error:
            self.button(panel, '导出交付清单').invoke()
            self.wait_for(lambda: '交付清单导出完成：' in self._message_text(panel))
            error.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0][0], threading.get_ident())
        self.assertEqual(calls[0][2]['output_name'], 'preview.mp4')
        self.assertEqual(before, {path.name: path.read_bytes() for path in root.glob('*.json')})
        panel.destroy()

    def _message_text(self, panel):
        # The status label is the only StringVar-backed label in the panel
        # whose value contains an action completion marker.
        for widget in self.widgets(panel):
            if widget.winfo_class() == 'TLabel':
                value = widget.cget('text')
                if isinstance(value, str) and ('完成：' in value or '未完成：' in value):
                    return value
        return ''

    def test_continue_renders_latest_local_edit_then_opens_actual_review_without_approval(self):
        from videocreate import production
        root = self.local_project()
        production.policy(root, 'auto-within-authorization', 'Continue local edit')
        panel = open_panel(self.manager, root);panel.withdraw()
        before = {p.name:p.read_bytes() for p in root.glob('*.json')}
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('No network')), \
                mock.patch('videocreate.cli.read_config', side_effect=AssertionError('No provider config')), \
                mock.patch('videocreate.runtime.jobs.client', side_effect=AssertionError('No task client')), \
                mock.patch('videocreate.manager_projects.webbrowser.open') as browser, \
                mock.patch.object(self.manager, 'error') as error:
            self.button(panel, '继续制作').invoke()
            self.wait_for(lambda: '本地下一步完成：' in self._message_text(panel), timeout=20)
            self.assertTrue((root / 'deliverables/preview.mp4').is_file())
            self.assertEqual(production.status(root)['next']['id'], 'review')
            self.button(panel, '继续制作').invoke()
            self.wait_for(lambda: browser.called)
            self.assertTrue((root / 'reviews/viewer.html').is_file())
            self.assertEqual(production.status(root)['review']['status'], 'review_pending')
            error.assert_not_called()
        self.assertEqual(before, {p.name:p.read_bytes() for p in root.glob('*.json')})
        panel.destroy()

    def test_continue_authoring_requires_reason_and_rejects_changed_content(self):
        from tkinter import ttk
        from videocreate import production, production_continue
        from videocreate.manager_continuation import open_inspection
        root = self.parent / 'authored'
        save_bundle(root, create('scenic', title='Plan checks', topic='A real scene'))
        completed = mock.Mock();edit = mock.Mock()
        decision = production_continue.describe(root)
        dialog = open_inspection(self.manager, root, decision, edit_layer=edit, completed=completed)
        dialog.withdraw()
        self.button(dialog, '登记本阶段计划已核对').invoke()
        self.assertFalse((root / 'production/stages.json').exists())
        entry = next(w for w in self.widgets(dialog) if isinstance(w, ttk.Entry))
        entry.insert(0, 'Checked intended audience and viewing goal')
        value = load_project(root)['brief'];value['audience'] = 'Saved after inspection'
        atomic_json(root / 'brief.json', value)
        with mock.patch.object(self.manager, 'error') as error:
            self.button(dialog, '登记本阶段计划已核对').invoke()
            self.wait_for(lambda:error.called)
        self.assertFalse((root / 'production/stages.json').exists())
        completed.assert_not_called();dialog.destroy()
        dialog = open_inspection(self.manager, root, production_continue.describe(root), edit_layer=edit, completed=completed)
        dialog.withdraw()
        entry = next(w for w in self.widgets(dialog) if isinstance(w, ttk.Entry))
        entry.insert(0, 'Checked the current saved plan')
        self.button(dialog, '登记本阶段计划已核对').invoke()
        self.wait_for(lambda:completed.called)
        self.assertEqual(production.status(root)['stages'][0]['status'], 'complete')
        self.assertEqual(production.status(root)['review']['status'], 'draft_preview')


if __name__ == '__main__':
    unittest.main()
