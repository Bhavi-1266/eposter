"""Portal regression checks use temporary state and mocked device commands."""
import copy
import errno
import fcntl
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import config_portal as portal


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = copy.deepcopy(portal.DEFAULTS)
        self.config.update(username="admin", password="test-admin-private")
        self.config["api"].update(poster_api_url="http://127.0.0.1:8080/api/posters", poster_token="api-private-token")
        self.config["wifi"]["password1"] = "wifi-private-password"
        self.config["custom_setting"] = {"keep": True}
        self.path = self.root / "config.json"
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        self.path.chmod(0o640)
        self.app = portal.create_app(self.root)
        self.app.testing = True
        self.client = self.app.test_client()

    def token(self):
        with self.client.session_transaction() as sess:
            return sess["csrf_token"]

    def login(self):
        self.assertEqual(self.client.get("/login").status_code, 200)
        response = self.client.post("/login", data={
            "username": "admin", "password": "test-admin-private", "csrf_token": self.token()
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)

    def form(self):
        return dict(
            csrf_token=self.token(), revision=portal.read_config(self.root)[1],
            admin_password="test-admin-private", device_id="1", mode="Scroll",
            rotation="90", auto_scroll="15", cache_refresh="60", request_timeout="15",
            max_media_size_mb="512", connect_timeout="20",
            poster_api_url="http://192.168.1.4:8080/api/posters",
            ssid1="Conference", ssid2="", pass1="", pass2="", poster_token="",
        )

    def test_authentication_and_csrf_are_required(self):
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.client.get("/login")
        self.assertEqual(self.client.post("/login", data={"username": "admin", "password": "test-admin-private"}).status_code, 403)
        self.login()
        form = self.form()
        form.pop("csrf_token")
        self.assertEqual(self.client.post("/save", data=form).status_code, 403)

    def test_page_hides_saved_secrets_and_serves_local_assets(self):
        self.login()
        response = self.client.get("/")
        for secret in ("test-admin-private", "api-private-token", "wifi-private-password"):
            self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        for path in ("/static/portal.css", "/static/portal.js"):
            with self.client.get(path) as asset:
                self.assertEqual(asset.status_code, 200)

    def test_save_preserves_secrets_unknown_fields_and_file_permissions(self):
        self.login()
        response = self.client.post("/save", data=self.form())
        self.assertEqual(response.status_code, 200, response.json)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["display"]["Mode"], "Scroll")
        self.assertEqual(saved["wifi"]["password1"], "wifi-private-password")
        self.assertEqual(saved["api"]["poster_token"], "api-private-token")
        self.assertEqual(saved["custom_setting"], {"keep": True})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(response.json["revision"], portal.read_config(self.root)[1])

    def test_invalid_fields_never_write_config(self):
        self.login()
        before = self.path.read_bytes()
        form = self.form()
        form.update(rotation="45", auto_scroll="0", poster_api_url="file:///etc/passwd")
        response = self.client.post("/save", data=form)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(set(response.json["fields"]), {"rotation", "auto_scroll", "poster_api_url"})
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_tab_cannot_overwrite_display_mode_change(self):
        self.login()
        form = self.form()
        updated = copy.deepcopy(self.config)
        updated["display"]["Mode"] = "Time"
        self.path.write_text(json.dumps(updated))
        response = self.client.post("/save", data=form)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(self.path.read_text())["display"]["Mode"], "Time")

    def test_clearing_secret_requires_explicit_flag(self):
        self.login()
        form = self.form()
        form["clear_poster_token"] = "1"
        response = self.client.post("/save", data=form)
        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["api"]["poster_token"], "")
        self.assertEqual(saved["wifi"]["password1"], "wifi-private-password")

    def test_bad_config_never_falls_back_to_default_admin(self):
        self.path.write_text("{invalid")
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 503)
        self.assertIn("invalid JSON", response.get_data(as_text=True))
        self.assertEqual(self.path.read_text(), "{invalid")

    def test_permission_failure_is_visible(self):
        with patch("config_portal.Path.open", side_effect=PermissionError):
            with self.assertRaises(portal.PortalError) as context:
                portal.read_config(self.root)
        self.assertEqual(context.exception.status, 503)
        self.assertIn("permissions", str(context.exception))

    def test_full_storage_returns_actionable_error(self):
        self.login()
        before = self.path.read_bytes()
        with patch("config_portal.atomic_write_json", side_effect=OSError(errno.ENOSPC, "full")):
            response = self.client.post("/save", data=self.form())
        self.assertEqual(response.status_code, 503)
        self.assertIn("Storage is full", response.json["message"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_lock_contention_is_bounded(self):
        self.login()
        with (self.root / ".config.json.lock").open("w") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            start = time.monotonic()
            response = self.client.post("/save", data=self.form())
            elapsed = time.monotonic() - start
        self.assertEqual(response.status_code, 503)
        self.assertLess(elapsed, 3.5)
        self.assertIn("busy", response.json["message"])

    def test_status_is_cached_and_does_not_report_unknown_as_healthy(self):
        self.login()
        with patch("config_portal.device_snapshot", return_value={"display_service": "unknown", "warnings": []}) as snapshot:
            first = self.client.get("/api/status")
            second = self.client.get("/api/status")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json["device"]["display_service"], "unknown")
        snapshot.assert_called_once()

    def test_password_change_invalidates_old_session(self):
        self.login()
        self.config["password"] = "changed-on-board"
        self.path.write_text(json.dumps(self.config))
        self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_wrong_save_password_and_large_requests_are_rejected(self):
        self.login()
        form = self.form()
        form["admin_password"] = "wrong"
        self.assertEqual(self.client.post("/save", data=form).status_code, 403)
        response = self.client.post("/save", data="x" * 20000, headers={"X-CSRF-Token": self.token()}, content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 413)

    def test_nmcli_timeout_does_not_hang_or_report_off(self):
        with patch("config_portal.shutil.which", return_value="/usr/bin/nmcli"), patch(
            "config_portal.subprocess.run", side_effect=subprocess.TimeoutExpired("nmcli", 4)
        ):
            with self.assertRaises(portal.PortalError) as context:
                portal.wifi_power()
        self.assertEqual(context.exception.status, 504)

    def test_power_update_does_not_reconnect_wifi(self):
        replies = [
            subprocess.CompletedProcess([], 0, stdout="profile-uuid:802-11-wireless", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
        with patch("config_portal.shutil.which", return_value="/usr/bin/nmcli"), patch(
            "config_portal.subprocess.run", side_effect=replies
        ) as run:
            self.assertEqual(portal.wifi_power(False), "OFF")
        self.assertEqual(run.call_args_list[1].args[0], [
            "/usr/bin/nmcli", "connection", "modify", "uuid", "profile-uuid",
            "802-11-wireless.powersave", "2",
        ])
        self.assertTrue(all(call.kwargs["timeout"] == 4 for call in run.call_args_list))

    def test_power_change_requires_password_and_boolean(self):
        self.login()
        headers = {"X-CSRF-Token": self.token()}
        self.assertEqual(self.client.post("/toggle_powersave", headers=headers, json={"enable": "false"}).status_code, 422)
        self.assertEqual(self.client.post("/toggle_powersave", headers=headers, json={"enable": False}).status_code, 403)

    def test_signin_attempts_are_limited_without_sleep(self):
        self.client.get("/login")
        data = {"username": "admin", "password": "wrong", "csrf_token": self.token()}
        for _ in range(10):
            self.assertEqual(self.client.post("/login", data=data).status_code, 401)
        self.assertEqual(self.client.post("/login", data=data).status_code, 429)


if __name__ == "__main__":
    unittest.main()
