"""Failure paths that must preserve the running device and its saved schedule."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import installer
import RunThis
from helper import api_handler, cache_handler
from helper.configuration import load_config, normalize_config


class ConfigRecoveryTests(unittest.TestCase):
    def test_invalid_reload_raises_instead_of_resetting_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            for value in ('{broken', 'null', '[]', '{"api": null}', '{"wifi": []}'):
                with self.subTest(value=value):
                    path.write_text(value)
                    with self.assertRaises(ValueError):
                        load_config(path)
                    self.assertEqual(path.read_text(), value)
            path.unlink()
            with self.assertRaises(ValueError):
                load_config(path)

    def test_mode_change_does_not_overwrite_broken_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text('{broken')
            with patch.object(RunThis, 'CONFIG_FILE', path):
                with self.assertRaises(ValueError):
                    RunThis.update_config_mode('Time')
            self.assertEqual(path.read_text(), '{broken')

    def test_non_object_config_is_rejected(self):
        for value in (None, [], 'invalid', 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_config(value)


class ScheduleRecoveryTests(unittest.TestCase):
    def test_bad_rows_do_not_discard_valid_slots(self):
        row = {'id': 1, 'screen_number': 7, 'file': 'one.png',
               'start_date_time': '2026-09-15T10:00:00Z',
               'end_date_time': '2026-09-15T10:05:00Z'}
        feed = {
            'screens': [None, {'screen_number': 7, 'records': None},
                        {'screen_number': 7, 'records': [row]},
                        {'screen_number': 7, 'records': [dict(row, id=2)]}],
            'booking_slot': [None, {'records': [None, dict(row, file=[]), dict(row, id=3)]}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'api_data.json'
            path.write_text(json.dumps(feed))
            with patch.object(RunThis, 'API_DATA_JSON', path), patch.object(RunThis, 'load_config', return_value={}):
                records, _ = RunThis.get_device_records(7)
        self.assertEqual([r['id'] for r in records], [1, 2, 3])

    def test_null_containers_allow_legacy_records(self):
        row = {'screen_number': 7, 'file': 'one.png',
               'start_date_time': '2026-09-15T10:00:00Z',
               'end_date_time': '2026-09-15T10:05:00Z'}
        with patch.object(RunThis, 'load_config', return_value={}), \
                patch.object(RunThis, 'load_json_file', return_value={'screens': None, 'booking_slot': None, 'data': [None, row]}), \
                patch.object(Path, 'exists', return_value=True):
            records, _ = RunThis.get_device_records(7)
        self.assertEqual(len(records), 1)


class FeedRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'api_data.json'
        self.saved = {'data': [{'id': 1}], 'fetched_at': 'previous'}
        self.path.write_text(json.dumps(self.saved))

    def fetch(self, response_data):
        response = Mock()
        response.json.return_value = copy.deepcopy(response_data)
        request = Mock()
        request.__enter__ = Mock(return_value=response)
        request.__exit__ = Mock(return_value=False)
        with patch.object(api_handler, 'API_DATA_JSON', self.path), \
                patch.object(api_handler, '_api_settings', return_value=('http://example.test/api', 3)), \
                patch.object(api_handler.requests, 'get', return_value=request):
            return api_handler.fetch_posters(None)

    def test_error_payload_keeps_last_valid_feed(self):
        for data in (None, [], {'message': 'Unavailable'}, {'status': False, 'data': []}, {'data': None}):
            with self.subTest(data=data):
                self.assertIsNone(self.fetch(data))
                self.assertEqual(json.loads(self.path.read_text()), self.saved)

    def test_explicit_empty_schedule_is_saved(self):
        self.assertIsNotNone(self.fetch({'status': True, 'data': []}))
        self.assertEqual(json.loads(self.path.read_text())['data'], [])

    def test_unchanged_schedule_does_not_rewrite_flash(self):
        before = self.path.stat().st_mtime_ns
        self.assertIsNotNone(self.fetch({'data': [{'id': 1}]}))
        self.assertEqual(self.path.stat().st_mtime_ns, before)


class CacheRecoveryTests(unittest.TestCase):
    def test_removed_media_is_treated_as_missing(self):
        with patch.object(cache_handler, 'ensure_cache'), \
                patch.object(Path, 'is_file', return_value=True), \
                patch.object(Path, 'stat', side_effect=FileNotFoundError):
            self.assertIsNone(cache_handler.get_media_path('http://example.test/one.png'))


class InstallerCommandTests(unittest.TestCase):
    def test_rollback_keeps_settings_saved_while_services_are_stopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'config.json'
            path.write_text(json.dumps({'display': {'device_id': 1}}))
            latest = {'display': {'device_id': 2}, 'password': 'saved-before-stop'}
            stopping = False

            def command(args, **kwargs):
                nonlocal stopping
                if args[:2] == ['systemctl', 'stop'] and not stopping:
                    path.write_text(json.dumps(latest))
                    stopping = True
                return True

            def fail_install():
                path.write_text(json.dumps({'display': {'hardware_ID': 2}}))
                raise RuntimeError('activation failed')

            with patch.object(installer, 'BASE_DIR', root), \
                    patch.object(installer.os, 'chdir'), \
                    patch.object(installer, 'run', side_effect=command), \
                    patch.object(installer, 'stage_environment'), \
                    patch.object(installer, 'activate_environment', return_value=False), \
                    patch.object(installer, 'restore_environment'), \
                    patch.object(installer, 'finish_install', side_effect=fail_install):
                with self.assertRaisesRegex(RuntimeError, 'activation failed'):
                    installer.setup()
            self.assertEqual(json.loads(path.read_text()), latest)

    def test_optional_command_reports_nonzero_exit(self):
        self.assertFalse(installer.run([sys.executable, '-c', 'raise SystemExit(3)'], ignore_fail=True))
        self.assertTrue(installer.run([sys.executable, '-c', 'raise SystemExit(0)'], ignore_fail=True))

    def test_required_command_raises_on_failure(self):
        with self.assertRaises(subprocess.CalledProcessError):
            installer.run([sys.executable, '-c', 'raise SystemExit(3)'])

    def test_failed_stop_of_active_service_prevents_environment_switch(self):
        def command(args, **kwargs):
            code = 1 if args[:2] == ['systemctl', 'stop'] else 0
            return subprocess.CompletedProcess(args, code)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(installer, 'BASE_DIR', Path(tmp)), \
                patch.object(installer.os, 'chdir'), \
                patch.object(installer, 'stage_environment'), \
                patch.object(installer, 'activate_environment') as activate, \
                patch.object(installer.subprocess, 'run', side_effect=command):
            with self.assertRaisesRegex(RuntimeError, 'Could not stop'):
                installer.setup()
            activate.assert_not_called()
