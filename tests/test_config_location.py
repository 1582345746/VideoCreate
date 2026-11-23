import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_v3_config import config
from videocreate.config import location, storage
from videocreate.config.management import migrate


class ConfigLocationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patch = mock.patch.object(storage, 'active_config_pointer', return_value=self.root / 'active.json')
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(location, 'active_config_pointer', return_value=self.root / 'active.json')
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.dict(os.environ, {'VIDEOCREATE_CONFIG_DIR': ''})
        patch.start(); self.addCleanup(patch.stop)
        self.path = self.root / 'production/custom.config.json'
        storage.atomic_json(self.path, migrate(config()))

    def test_selected_store_survives_reload_without_copying_keys_and_explicit_flags_win(self):
        before = self.path.read_bytes()
        result = location.use(self.path)
        self.assertEqual(storage.user_config_path(), self.path)
        self.assertEqual(storage.config_root(), self.path.parent)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn('test-only-value', (self.root / 'active.json').read_text())
        explicit = self.root / 'explicit.json'
        self.assertEqual(storage.user_config_path(explicit), explicit)
        with mock.patch.dict(os.environ, {'VIDEOCREATE_CONFIG_DIR': str(self.root / 'environment')}):
            self.assertEqual(storage.user_config_path(), self.root / 'environment/videocreate.config.json')
            self.assertEqual(storage.user_config_path(explicit), explicit)

    def test_missing_active_store_does_not_silently_fall_back_to_another_account(self):
        location.use(self.path); self.path.unlink()
        with self.assertRaisesRegex(storage.ConfigError, 'unavailable'):
            storage.user_config_path()
        self.assertTrue(location.locate()['selection_error'])
        replacement = self.root / 'replacement.json'; storage.atomic_json(replacement, migrate(config()))
        location.use(replacement)
        self.assertEqual(storage.user_config_path(), replacement)

    def test_invalid_config_cannot_replace_saved_selection(self):
        location.use(self.path); before = (self.root / 'active.json').read_bytes()
        invalid = self.root / 'invalid.json'; storage.atomic_json(invalid, {'schema_version': 99})
        with self.assertRaises(storage.ConfigError): location.use(invalid)
        self.assertEqual((self.root / 'active.json').read_bytes(), before)
