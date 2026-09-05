#!/usr/bin/env python3
"""Local management portal with bounded requests and no display imports."""
import copy
import errno
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from helper.json_utils import atomic_write_json

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_LIMIT = 256 * 1024
DEFAULTS = {
    "ID": 0,
    "wifi": {"ssid1": "", "password1": "", "ssid2": "", "password2": "", "connect_timeout": 20},
    "api": {"poster_api_url": "", "poster_token": "", "request_timeout": 15, "max_media_size_mb": 512},
    "display": {"device_id": 1, "rotation_degree": 0, "Mode": "Menu", "Auto_Scroll": 5, "cache_refresh": 60},
}


class PortalError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status = status
        self.fields = fields or {}


def read_config(project_dir):
    """Fail visibly rather than substituting credentials for unreadable state."""
    try:
        with (project_dir / "config.json").open("rb") as handle:
            raw = handle.read(CONFIG_LIMIT + 1)
        if len(raw) > CONFIG_LIMIT:
            raise PortalError("config.json exceeds the 256 KB limit.", 503)
        data = json.loads(raw)
    except FileNotFoundError:
        raise PortalError("config.json is missing. Run the installer on the board to create it.", 503) from None
    except PermissionError:
        raise PortalError("Cannot read config.json. Run the installer to repair its permissions.", 503) from None
    except (ValueError, UnicodeError):
        raise PortalError("config.json contains invalid JSON. Correct the file on the board; no settings were overwritten.", 503) from None
    except OSError:
        raise PortalError("Cannot read config.json. Check the board's storage and permissions.", 503) from None
    if not isinstance(data, dict):
        raise PortalError("config.json must contain a JSON object.", 503)
    for key, default in DEFAULTS.items():
        if isinstance(default, dict):
            if key in data and not isinstance(data[key], dict):
                raise PortalError("The '{}' section of config.json must be an object.".format(key), 503)
            section = copy.deepcopy(default)
            section.update(data.get(key, {}))
            data[key] = section
        else:
            data.setdefault(key, default)
    if not all(isinstance(data.get(key), str) and data[key] for key in ("username", "password")):
        raise PortalError("Admin credentials are missing from config.json. Set username and password on the board.", 503)
    return data, hashlib.sha256(raw).hexdigest()


def same_text(first, second):
    return isinstance(first, str) and isinstance(second, str) and hmac.compare_digest(first.encode(), second.encode())


def credential_version(config, secret):
    # Flask cookies are signed, not encrypted. Do not expose an unkeyed
    # password fingerprint that could be used for offline guessing.
    value = json.dumps([config["username"], config["password"]]).encode()
    return hmac.new(secret.encode(), value, hashlib.sha256).hexdigest()


def session_secret(project_dir):
    path = project_dir / ".portal_secret"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    except FileNotFoundError:
        pass
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(value)
    return value


def validate_form(form):
    errors, values = {}, {}
    for field, lower, upper in (
        ("device_id", 0, 999999), ("rotation", 0, 270),
        ("auto_scroll", 1, 3600), ("cache_refresh", 30, 3600),
        ("request_timeout", 3, 120), ("connect_timeout", 5, 120),
        ("max_media_size_mb", 1, 2048),
    ):
        try:
            value = int(form.get(field, ""))
            if not lower <= value <= upper:
                raise ValueError
            values[field] = value
        except (ValueError, TypeError):
            errors[field] = "Enter a whole number from {} to {}.".format(lower, upper)
    if "rotation" not in errors and values["rotation"] not in (0, 90, 180, 270):
        errors["rotation"] = "Choose 0, 90, 180, or 270 degrees."
    values["mode"] = form.get("mode")
    if values["mode"] not in ("Time", "Menu", "Scroll"):
        errors["mode"] = "Choose a supported display mode."
    values["poster_api_url"] = form.get("poster_api_url", "").strip()
    try:
        url = urlsplit(values["poster_api_url"])
        if (len(values["poster_api_url"]) > 2048 or url.scheme not in ("http", "https")
                or not url.hostname or url.username or url.password or url.fragment
                or any(ch.isspace() for ch in values["poster_api_url"])):
            raise ValueError
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError
    except ValueError:
        errors["poster_api_url"] = "Enter a valid http:// or https:// API URL without embedded credentials."
    for field in ("ssid1", "ssid2"):
        values[field] = form.get(field, "")
        if len(values[field].encode()) > 32:
            errors[field] = "Network names must be no more than 32 bytes."
    for field in ("pass1", "pass2", "poster_token"):
        values[field] = form.get(field, "")
        if len(values[field]) > 512:
            errors[field] = "This value is too long (maximum 512 characters)."
        if values[field] and form.get("clear_" + field) == "1":
            errors[field] = "Choose either a new value or Clear saved value."
    if errors:
        raise PortalError("Check the highlighted fields. Your settings have not been saved.", 422, errors)
    return values


def save_config(project_dir, form):
    values = validate_form(form)
    lock_path = project_dir / ".config.json.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise PortalError("Settings are busy in another process. Try saving again shortly.", 503)
                time.sleep(0.05)
        try:
            config, revision = read_config(project_dir)
            if not same_text(form.get("admin_password"), config["password"]):
                raise PortalError("The admin password is incorrect.", 403, {"admin_password": "Enter the current admin password."})
            if not same_text(form.get("revision"), revision):
                raise PortalError("Settings changed on the board or in another tab. Reload before saving; your edits are still shown here.", 409)
            config["display"].update({
                "device_id": values["device_id"], "Mode": values["mode"],
                "rotation_degree": values["rotation"], "Auto_Scroll": values["auto_scroll"],
                "cache_refresh": values["cache_refresh"],
            })
            config["api"].update({key: values[key] for key in ("poster_api_url", "request_timeout", "max_media_size_mb")})
            config["wifi"].update({key: values[key] for key in ("ssid1", "ssid2", "connect_timeout")})
            for field, section, key in (("pass1", "wifi", "password1"), ("pass2", "wifi", "password2"), ("poster_token", "api", "poster_token")):
                if form.get("clear_" + field) == "1":
                    config[section][key] = ""
                elif values[field]:
                    config[section][key] = values[field]
            if os.geteuid() == 0:
                owner = (project_dir / "config.json").stat()
                os.fchown(lock.fileno(), owner.st_uid, owner.st_gid)
                os.fchmod(lock.fileno(), 0o660)
            atomic_write_json(project_dir / "config.json", config)
            encoded = json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8")
            return config, hashlib.sha256(encoded).hexdigest()
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def device_snapshot(project_dir):
    result = {"checked_at": datetime.now().astimezone().isoformat(timespec="seconds"), "ip": "Unavailable"}
    warnings = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            result["ip"] = sock.getsockname()[0]
    except OSError:
        warnings.append("No routed network address detected. Local access may still work.")
    try:
        memory = {}
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                if key in ("MemTotal", "MemAvailable"):
                    memory[key] = int(value.split()[0])
        result["memory_used_percent"] = round(100 * (1 - memory["MemAvailable"] / memory["MemTotal"]))
        if result["memory_used_percent"] >= 90:
            warnings.append("Memory usage is above 90%; video playback may slow down.")
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        result["memory_used_percent"] = None
    try:
        result["uptime_seconds"] = int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        result["uptime_seconds"] = None
    try:
        disk = shutil.disk_usage(project_dir)
        result["disk_free_mb"] = disk.free // (1024 * 1024)
        if result["disk_free_mb"] < 256:
            warnings.append("Less than 256 MB of storage is free. New media may not download.")
    except OSError:
        result["disk_free_mb"] = None
    try:
        feed = (project_dir / "api_data.json").stat()
        result["feed_updated_at"] = datetime.fromtimestamp(feed.st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        result["feed_updated_at"] = None
        warnings.append("No saved API feed found. Check the API URL and display service logs.")
    count = 0
    try:
        with os.scandir(project_dir / "eposter_cache") as entries:
            for scanned, entry in enumerate(entries):
                if scanned >= 2048:
                    result["cache_capped"] = True
                    break
                if entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".mov", ".mp4", ".m4v", ".webm", ".mkv", ".avi"}:
                    count += 1
        result["cache_files"] = count
        if not count:
            warnings.append("Media cache is empty. The display may still be downloading its first files.")
    except OSError:
        result["cache_files"] = None
        warnings.append("Media cache is missing or unreadable.")
    result["video_player"] = next((name for name in ("ffplay", "omxplayer", "mpv", "cvlc") if shutil.which(name)), None)
    if not result["video_player"]:
        warnings.append("No video player found. Install ffmpeg on the board to enable video.")
    result["display_service"] = "unknown"
    if shutil.which("systemctl"):
        try:
            process = subprocess.run(["systemctl", "show", "eposter-display.service", "--property=ActiveState", "--value"], capture_output=True, text=True, timeout=2, check=False)
            state = process.stdout.strip()
            if process.returncode == 0 and state in {"active", "inactive", "failed", "activating", "deactivating", "reloading"}:
                result["display_service"] = state
        except (OSError, subprocess.TimeoutExpired):
            pass
    if result["display_service"] in ("failed", "inactive"):
        warnings.append("Display service is {}. Check its journal on the board.".format(result["display_service"]))
    result["warnings"] = warnings
    return result


def wifi_power(enable=None):
    binary = shutil.which("nmcli")
    if not binary:
        raise PortalError("NetworkManager (nmcli) is unavailable on this device.", 503)

    def command(arguments):
        try:
            result = subprocess.run([binary] + arguments, capture_output=True, text=True, timeout=4, check=False)
        except subprocess.TimeoutExpired:
            raise PortalError("NetworkManager did not answer within 4 seconds. Try again later.", 504) from None
        if result.returncode:
            raise PortalError("NetworkManager could not complete this action. Check the active Wi-Fi profile and service permissions.", 503)
        return result.stdout.strip()

    profiles = command(["-t", "-f", "UUID,TYPE", "connection", "show", "--active"])
    profile = next((row.split(":", 1)[0] for row in profiles.splitlines() if row.endswith(":802-11-wireless")), None)
    if not profile:
        raise PortalError("There is no active NetworkManager Wi-Fi profile. Ethernet-only devices do not need this setting.", 409)
    if enable is None:
        output = command(["-g", "802-11-wireless.powersave", "connection", "show", "uuid", profile])
        code = output.split()[0] if output else ""
        return {"0": "DEFAULT", "1": "UNCHANGED", "2": "OFF", "3": "ON"}.get(code, "UNKNOWN")
    command(["connection", "modify", "uuid", profile, "802-11-wireless.powersave", "3" if enable else "2"])
    return "ON" if enable else "OFF"


def create_app(project_dir=None):
    project_dir = Path(project_dir or PROJECT_DIR)
    app = Flask(__name__, template_folder=str(PROJECT_DIR / "templates"), static_folder=str(PROJECT_DIR / "static"))
    app.secret_key = session_secret(project_dir)
    app.config.update(MAX_CONTENT_LENGTH=16 * 1024, MAX_FORM_MEMORY_SIZE=16 * 1024, MAX_FORM_PARTS=50,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    snapshot = {"expires": 0, "data": None}
    status_lock, mutation_lock, login_lock = threading.Lock(), threading.Lock(), threading.Lock()
    failures = OrderedDict()
    protected = {"home", "save", "status", "powersave_status", "toggle_powersave"}

    def wants_json():
        return request.endpoint in {"save", "status", "powersave_status", "toggle_powersave"} or request.headers.get("Accept") == "application/json"

    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def guard():
        g.request_id = secrets.token_hex(4)
        if request.endpoint in protected:
            if not session.get("logged_in"):
                if wants_json():
                    raise PortalError("Your session expired. Sign in again; unsaved fields remain on this page.", 401)
                return redirect(url_for("login"))
            config, revision = read_config(project_dir)
            if not same_text(session.get("credential_version"), credential_version(config, app.secret_key)):
                session.clear()
                if wants_json():
                    raise PortalError("Admin credentials changed. Sign in again.", 401)
                return redirect(url_for("login"))
            g.config, g.revision = config, revision
        if request.method == "POST":
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if not same_text(supplied, session.get("csrf_token")):
                raise PortalError("This page's security token expired. Reload the page and try again.", 403)

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(Exception)
    def error_response(error):
        fields = {}
        if isinstance(error, PortalError):
            code, message, fields = error.status, str(error), error.fields
        elif isinstance(error, HTTPException):
            code = error.code or 500
            message = "Request is too large (maximum 16 KB)." if code == 413 else error.name
        elif isinstance(error, OSError):
            code = 503
            message = "The board could not save settings. Check config permissions and free storage."
            if error.errno == errno.ENOSPC:
                message = "Storage is full. Free space on the board before saving again."
            app.logger.error("Storage error %s: %s", g.get("request_id"), type(error).__name__)
        else:
            code, message = 500, "The portal encountered an unexpected error. Check the admin service journal."
            app.logger.exception("Portal error %s", g.get("request_id"))
        if wants_json():
            return jsonify(success=False, message=message, fields=fields, request_id=g.get("request_id")), code
        return render_template("portal_login.html", error=message), code

    @app.route("/login", methods=["GET", "POST"])
    def login():
        config, _ = read_config(project_dir)
        if request.method == "GET":
            return render_template("portal_login.html", error=None)
        address, now = request.remote_addr or "local", time.monotonic()
        with login_lock:
            count, start = failures.get(address, (0, now))
            if now - start >= 300:
                count, start = 0, now
            if count >= 10:
                raise PortalError("Too many sign-in attempts. Wait five minutes before trying again.", 429)
            failures[address] = (count + 1, start)
            failures.move_to_end(address)
            if len(failures) > 128:
                failures.popitem(last=False)
        if not (same_text(request.form.get("username"), config["username"]) and same_text(request.form.get("password"), config["password"])):
            return render_template("portal_login.html", error="Incorrect username or password."), 401
        with login_lock:
            failures.pop(address, None)
        session.clear()
        session.update(logged_in=True, credential_version=credential_version(config, app.secret_key))
        session.permanent = True
        return redirect(url_for("home"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def home():
        config = copy.deepcopy(g.config)
        secret_saved = {"pass1": bool(config["wifi"].get("password1")), "pass2": bool(config["wifi"].get("password2")), "poster_token": bool(config["api"].get("poster_token"))}
        config.pop("password", None)
        for section, field in (("wifi", "password1"), ("wifi", "password2"), ("api", "poster_token")):
            config[section].pop(field, None)
        return render_template("portal.html", settings=config, revision=g.revision, secret_saved=secret_saved)

    @app.post("/save")
    def save():
        if not mutation_lock.acquire(blocking=False):
            raise PortalError("Another settings action is in progress. Try again shortly.", 409)
        try:
            config, revision = save_config(project_dir, request.form)
            snapshot["expires"] = 0
            return jsonify(success=True, message="Settings saved. Display updates after its current playback or refresh cycle. Wi-Fi credentials are used on the next connection attempt.", revision=revision,
                           secret_saved={"pass1": bool(config["wifi"].get("password1")), "pass2": bool(config["wifi"].get("password2")), "poster_token": bool(config["api"].get("poster_token"))})
        finally:
            mutation_lock.release()

    @app.get("/api/status")
    def status():
        if time.monotonic() >= snapshot["expires"]:
            if status_lock.acquire(blocking=False):
                try:
                    snapshot["data"] = device_snapshot(project_dir)
                    snapshot["expires"] = time.monotonic() + 30
                finally:
                    status_lock.release()
            elif snapshot["data"] is None:
                raise PortalError("Device status is being collected. Try again shortly.", 503)
        result = copy.deepcopy(snapshot["data"])
        if not g.config["api"].get("poster_api_url"):
            result["warnings"].append("Poster API URL is not configured.")
        result["mode"] = g.config["display"].get("Mode")
        result["device_id"] = g.config["display"].get("device_id")
        return jsonify(success=True, device=result)

    @app.get("/powersave_status")
    def powersave_status():
        if not mutation_lock.acquire(blocking=False):
            raise PortalError("A device action is already in progress.", 409)
        try:
            return jsonify(success=True, status=wifi_power())
        finally:
            mutation_lock.release()

    @app.post("/toggle_powersave")
    def toggle_powersave():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or type(data.get("enable")) is not bool:
            raise PortalError("Choose whether Wi-Fi power saving should be enabled.", 422)
        if not same_text(data.get("admin_password"), g.config["password"]):
            raise PortalError("Enter your admin password in the Save settings bar first.", 403, {"admin_password": "Current admin password required."})
        if not mutation_lock.acquire(blocking=False):
            raise PortalError("A device action is already in progress.", 409)
        try:
            state = wifi_power(data["enable"])
            return jsonify(success=True, status=state, message="Wi-Fi profile updated. The power setting takes effect on its next reconnect; the current connection was kept running.")
        finally:
            mutation_lock.release()

    return app


if __name__ == "__main__":
    from waitress import serve

    serve(create_app(), host="0.0.0.0", port=80, threads=4, connection_limit=32,
          backlog=32, channel_timeout=20, cleanup_interval=5,
          max_request_body_size=16 * 1024, max_request_header_size=16 * 1024,
          expose_tracebacks=False)
