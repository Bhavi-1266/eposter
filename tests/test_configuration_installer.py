import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import installer
import RunThis
from helper.configuration import migrate_config, normalize_config


class ConfigurationTests(unittest.TestCase):
    def test_identity_precedence_zero_and_unknown_settings(self):
        config={'username':'admin','password':'secret','display':{'device_id':9,'custom':True},'ID':55}
        converted=normalize_config(config)
        self.assertEqual(converted['display'],{'screen_number':9,'custom':True})
        self.assertEqual(converted['password'],'secret')
        self.assertEqual(converted['hardware_id'],55)
        self.assertNotIn('ID', converted)
        self.assertIn('device_id',config['display'])
        self.assertEqual(normalize_config({'display':{'device_id':9,'hardware_ID':0}})['display']['screen_number'],0)

    def test_separate_hardware_and_screen_identifiers_preserve_values(self):
        for legacy in ('hardware_ID', 'hardware_id', 'device_id'):
            with self.subTest(legacy=legacy):
                source = {'ID': 55, 'display': {legacy: 7}, 'custom': {'keep': True}}
                converted = normalize_config(source)
                self.assertEqual(converted, {'hardware_id': 55, 'display': {'screen_number': 7}, 'custom': {'keep': True}})
                self.assertEqual(normalize_config(converted), converted)
                self.assertIn('ID', source)

    def test_explicit_new_identifiers_win_including_zero(self):
        config = {'ID': 55, 'hardware_id': 0,
                  'display': {'hardware_ID': 7, 'hardware_id': 8, 'device_id': 9, 'screen_number': 0}}
        self.assertEqual(normalize_config(config), {'hardware_id': 0, 'display': {'screen_number': 0}})

    def test_api_screen_number_takes_precedence_over_legacy_alias(self):
        row = {'screen_number': 0, 'hardware_ID': 55, 'file': 'one.png',
               'start_date_time': '2026-09-17T10:00:00Z', 'end_date_time': '2026-09-17T10:05:00Z'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'api_data.json'
            path.write_text(json.dumps({'data': [row]}))
            with patch.object(RunThis, 'API_DATA_JSON', path), patch.object(RunThis, 'load_config', return_value={}):
                self.assertEqual(len(RunThis.get_device_records(0)[0]), 1)
                self.assertEqual(RunThis.get_device_records(55)[0], [])

    def test_atomic_idempotent_migration_preserves_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.json'
            path.write_text(json.dumps({'display':{'device_id':23},'extra':'keep'}))
            path.chmod(0o640)
            migrate_config(path)
            self.assertEqual(json.loads(path.read_text())['display']['screen_number'],23)
            stamp=path.stat().st_mtime_ns
            migrate_config(path)
            self.assertEqual(path.stat().st_mtime_ns,stamp)
            self.assertEqual(path.stat().st_mode & 0o777,0o640)

    def test_invalid_configuration_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.json'
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                migrate_config(path)
            self.assertEqual(path.read_text(),'{broken')

    def test_missing_screen_number_never_matches_unassigned_api_rows(self):
        self.assertEqual(RunThis.get_device_records(None), ([], 5))
        self.assertEqual(RunThis.get_device_records(''), ([], 5))

    def test_legacy_api_screen_fields_still_match_screen_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'api_data.json'
            record={'id':1,'start_date_time':'15-09-2026 10:00:00','end_date_time':'15-09-2026 10:05:00','file':'one.png'}
            path.write_text(json.dumps({'booking_slot':[{'screen_number':23,'records':[record]}]}))
            with patch.object(RunThis,'API_DATA_JSON',path),patch.object(RunThis,'load_config',return_value={'api':{'timezone':'Asia/Kolkata'}}):
                found,_=RunThis.get_device_records(23)
                other,_=RunThis.get_device_records(24)
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]['start_dt'].hour,4)
            self.assertEqual(other,[])


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.env=self.root/'venv'
        self.patches=[patch.object(installer,'BASE_DIR',self.root),patch.object(installer,'VENV_PATH',self.env)]
        for p in self.patches:
            p.start();self.addCleanup(p.stop)

    def test_environment_switch_and_rollback_preserve_old_files(self):
        self.env.mkdir()
        (self.env/'marker').write_text('old')
        staged=self.root/'.venvs'/'new'
        staged.mkdir(parents=True)
        (staged/'marker').write_text('new')
        previous=installer.activate_environment(staged)
        self.assertTrue(self.env.is_symlink())
        self.assertEqual((self.env/'marker').read_text(),'new')
        installer.restore_environment(previous)
        self.assertFalse(self.env.is_symlink())
        self.assertEqual((self.env/'marker').read_text(),'old')

    def test_migration_creates_backup_and_keeps_cache(self):
        config={'display':{'device_id':23},'password':'unchanged','api':{}}
        (self.root/'config.json').write_text(json.dumps(config))
        cache=self.root/'eposter_cache'
        cache.mkdir()
        media=cache/'existing.png'
        media.write_bytes(b'cached-content')
        user=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
        with patch('installer.os.chown'):
            self.assertTrue(installer.prepare_runtime_state(user))
            self.assertTrue(installer.prepare_runtime_state(user))
        self.assertEqual(json.loads((self.root/'config.json.before-player-update').read_text()),config)
        self.assertEqual(json.loads((self.root/'config.json').read_text())['display']['screen_number'],23)
        self.assertEqual(media.read_bytes(),b'cached-content')

    def test_dependency_failure_never_stops_services(self):
        with patch('installer.run') as run,patch('installer.stage_environment',side_effect=RuntimeError('pip failed')),patch('installer.os.chdir'):
            with self.assertRaises(RuntimeError):
                installer.setup()
        self.assertFalse(any(call.args[0][:2]==['systemctl','stop'] for call in run.call_args_list))
        packages=next(call.args[0] for call in run.call_args_list if 'install' in call.args[0])
        self.assertIn('mpv',packages)
        self.assertNotIn('python3-tk',packages)

    def test_failure_after_activation_restores_config_and_environment(self):
        config={'display':{'device_id':44}}
        (self.root/'config.json').write_text(json.dumps(config))
        self.env.mkdir()
        (self.env/'marker').write_text('old')
        staged=self.root/'staged'
        staged.mkdir()
        def fail():
            migrate_config(self.root/'config.json')
            raise RuntimeError('service setup failed')
        with patch('installer.run') as run,patch('installer.stage_environment',return_value=staged),patch('installer.finish_install',side_effect=fail),patch('installer.os.chdir'):
            with self.assertRaises(RuntimeError):
                installer.setup()
        self.assertEqual(json.loads((self.root/'config.json').read_text()),config)
        self.assertEqual((self.env/'marker').read_text(),'old')
        self.assertIn(['systemctl','start','eposter-admin.service','eposter-display.service'],[c.args[0] for c in run.call_args_list])

    def test_service_templates_use_selected_user_and_location(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('eposter-display','eposter-admin'):
            template=(root/'service_files'/f'{name}.service.template').read_text()
            rendered=template.format(description='test',after='graphical.target',user='board',base_dir='/srv/eposter',python_bin='/srv/eposter/venv/bin/python3',environment='',service_name=name)
            self.assertIn('User=board',rendered)
            self.assertIn('WorkingDirectory=/srv/eposter',rendered)
            self.assertNotIn('/home/rock',rendered)


class HeartbeatTests(unittest.TestCase):
    def test_installer_requires_a_fresh_ready_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / '.playback-status.json'
            path.write_text(json.dumps({'checked_at': 200, 'pid': 1, 'ready': True}))
            with patch.object(installer, 'BASE_DIR', root):
                installer.wait_for_display(100, timeout=1)
                path.write_text(json.dumps({'checked_at': 200, 'pid': 1, 'ready': False}))
                with self.assertRaises(RuntimeError):
                    installer.wait_for_display(100, timeout=0)
                path.write_text(json.dumps({'checked_at': 50, 'pid': 1, 'ready': True}))
                with self.assertRaises(RuntimeError):
                    installer.wait_for_display(100, timeout=0)

    def test_only_old_owned_environments_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            versions = root / '.venvs'
            versions.mkdir()
            current, previous, old = [versions / (letter * 32) for letter in 'abc']
            for path in (current, previous, old, versions/'user-directory'):
                path.mkdir()
            (root/'venv').symlink_to(current)
            marker = root / ('.venv-previous-' + '1'*32)
            marker.symlink_to(previous)
            with patch.object(installer, 'BASE_DIR', root), patch.object(installer, 'VENV_PATH', root/'venv'):
                installer.prune_environments(marker)
            self.assertTrue(current.exists())
            self.assertTrue(previous.exists())
            self.assertFalse(old.exists())
            self.assertTrue((versions/'user-directory').exists())
