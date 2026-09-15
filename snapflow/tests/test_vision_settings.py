"""Upgrade regressions: fake local credentials, no network/model calls."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from test_app import ARTIFACTS
from server import App
from vision_settings import discover, remember


class VisionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.base = ARTIFACTS / self._testMethodName
        self.root = self.base / 'SnapFlow-Windows-ConfigFix-test'
        self.root.mkdir(parents=True)
        self.key = {'BASE_URL': 'https://fixture.invalid/v1', 'API_KEY': 'fixture-private-key'}
        self.direct = {'VISION_BASE_URL': 'https://fixture.invalid/v1', 'VISION_API_KEY': 'fixture-private-key', 'VISION_MODEL': 'gemini-3.8-flash'}

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8-sig')

    def old(self, name='SnapFlow-Windows-FolderFix-old'):
        path = self.base / name
        path.mkdir()
        (path / 'server.py').touch()
        (path / 'launcher.py').touch()
        return path

    def app(self, config=None):
        with patch.dict(os.environ, {}, clear=True), patch('server.ROOT', self.root):
            return App(self.root / 'data', config=config)

    def test_nested_extraction_finds_existing_parent_key(self):
        nested = self.root / self.root.name
        nested.mkdir()
        self.write(self.base / 'api_key.json', self.key)
        _, path, error = discover(nested)
        self.assertEqual(path, self.base / 'api_key.json')
        self.assertFalse(error)

    def test_upgrade_recovers_old_direct_model_and_keeps_secrets_private(self):
        self.write(self.old() / 'data/vision-private.json', self.direct)
        app = self.app()
        public = app.public_config()
        self.assertTrue(public['vision'])
        self.assertEqual(public['vision_model'], 'gemini-3.8-flash')
        self.assertNotIn('fixture-private-key', json.dumps(public))
        self.assertTrue((self.base / '.snapflow-config/vision-private.json').is_file())

    def test_upgrade_gateway_survives_old_config_removal(self):
        old_key = self.old() / 'api_key.json'
        self.write(old_key, self.key)
        self.assertTrue(self.app().public_config()['vision'])
        old_key.unlink()  # Fake fixture only; simulates retiring an old release.
        app = self.app()
        self.assertTrue(app.public_config()['vision'])
        self.assertEqual(app.public_config()['vision_model'], 'gemini-3.8-flash')
        self.assertEqual(app.gateway_config.parent.name, '.snapflow-config')

    def test_current_explicit_config_wins_over_old_version(self):
        other = dict(self.direct, VISION_MODEL='other-model')
        self.write(self.old() / 'data/vision-private.json', other)
        self.write(self.root / 'data/vision-private.json', self.direct)
        self.assertEqual(self.app().public_config()['vision_model'], 'gemini-3.8-flash')

    def test_conflicting_old_accounts_are_not_silently_selected(self):
        self.write(self.old() / 'data/vision-private.json', self.direct)
        self.write(self.old('SnapFlow-Windows-Album-old') / 'data/vision-private.json', dict(self.direct, VISION_API_KEY='other-private-key'))
        app = self.app()
        self.assertFalse(app.public_config()['vision'])
        self.assertIn('多个旧版', app.public_config()['vision_config_error'])

    def test_missing_config_keeps_default_model_instructions_and_user_data(self):
        app = self.app()
        self.assertFalse(app.public_config()['vision'])
        self.assertIn('api_key.json', app.public_config()['vision_config_error'])
        self.assertFalse((self.base / '.snapflow-config').exists())

    def test_malformed_local_settings_do_not_crash_startup(self):
        p = self.root / 'data/vision-private.json'
        p.parent.mkdir(); p.write_text('{invalid')
        self.assertFalse(self.app().public_config()['vision'])
        self.assertEqual(p.read_text(), '{invalid')

    def test_explicit_test_config_never_reads_or_copies_real_credentials(self):
        self.write(self.base / 'api_key.json', self.key)
        self.assertFalse(self.app(config={}).public_config()['vision'])
        self.assertFalse((self.base / '.snapflow-config').exists())

    def test_disabled_does_not_reenable_or_copy_credentials(self):
        self.write(self.base / 'api_key.json', self.key)
        with patch.dict(os.environ, {'VISION_DISABLED': '1'}, clear=True), patch('server.ROOT', self.root):
            app = App(self.root / 'data')
        self.assertFalse(app.public_config()['vision'])
        self.assertFalse((self.base / '.snapflow-config').exists())

    def test_saving_new_settings_updates_shared_configuration(self):
        app = self.app()
        with patch('server.ROOT', self.root):
            result = app.configure_vision({'base_url': self.direct['VISION_BASE_URL'], 'api_key': self.direct['VISION_API_KEY'], 'model': self.direct['VISION_MODEL']})
        self.assertTrue(result['vision'])
        self.assertFalse(result['vision_config_error'])
        p = self.base / '.snapflow-config/vision-private.json'
        self.assertEqual(json.loads(p.read_text()), self.direct)
        if os.name != 'nt':
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_unrelated_folders_are_not_used_as_configuration_sources(self):
        self.write(self.base / 'OtherApp/data/vision-private.json', self.direct)
        self.write(self.base / 'SnapFlow-not-an-install/api_key.json', self.key)
        settings, gateway, error = discover(self.root)
        self.assertFalse(settings or gateway)
        self.assertTrue(error)
