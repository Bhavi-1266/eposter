#!/usr/bin/env python3
import os
import subprocess
import sys
import json
import shutil
import pwd
import grp
import uuid
import time
from helper.configuration import migrate_config
from helper.json_utils import atomic_write_json
from pathlib import Path

# --- BOARD DEPLOYMENT CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent
VENV_PATH = BASE_DIR / "venv"
PYTHON_BIN = VENV_PATH / "bin" / "python3"
REQ_FILE = BASE_DIR / "requirements.txt"
SERVICE_FILES_DIR = BASE_DIR / "service_files"

def display_user():
    explicit = os.environ.get("EPOSTER_USER") or os.environ.get("SUDO_USER")
    if explicit and explicit != "root":
        return explicit
    owner = pwd.getpwuid(BASE_DIR.stat().st_uid).pw_name
    return owner if owner != "root" else "rock"


REAL_USER = display_user()

# Service Definitions
SERVICES = {
    "eposter-admin": {
        "description": "ePoster Admin Web Interface & DNS",
        "exec": f"{PYTHON_BIN} {BASE_DIR}/config_portal.py",
        "template": SERVICE_FILES_DIR / "eposter-admin.service.template",
        "user": "root", 
        "after": "network.target"
    },
    "eposter-display": {
        "description": "ePoster Persistent Media Display",
        "exec": f"{PYTHON_BIN} {BASE_DIR}/RunThis.py",
        "template": SERVICE_FILES_DIR / "eposter-display.service.template",
        "user": REAL_USER,
        "after": "graphical.target display-manager.service network-online.target",
        "env": [
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "DISPLAY=:0",
            f"XAUTHORITY=/home/{REAL_USER}/.Xauthority",
            "XDG_RUNTIME_DIR=/run/user/1000" # Common ID for first user
        ]
    }
}

def run(cmd, ignore_fail=False):
    print(f"--> Executing: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        result = subprocess.run(cmd, check=not ignore_fail, shell=isinstance(cmd, str))
        return result.returncode == 0
    except Exception as e:
        if ignore_fail:
            print(f"Non-critical error: {e}")
            return False
        raise


def prepare_runtime_state(user_info):
    """Preserve configuration and make runtime state writable by the display."""
    config_path = BASE_DIR / "config.json"
    example_path = BASE_DIR / "config.example.json"
    config_lock_path = BASE_DIR / ".config.json.lock"

    if not config_path.exists():
        if not example_path.exists():
            print(f"Error: neither {config_path} nor {example_path} exists")
            return False
        shutil.copyfile(example_path, config_path)
        print(f"Created {config_path} from config.example.json")

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"Error: config.json is not valid/readable: {error}")
        return False

    backup_path = BASE_DIR / "config.json.before-player-update"
    if not backup_path.exists():
        shutil.copy2(config_path, backup_path)
        backup_path.chmod(0o600)
    try:
        config = migrate_config(config_path)
    except (OSError, ValueError) as error:
        print(f"Configuration migration failed: {error}")
        return False

    api_url = config.get("api", {}).get("poster_api_url")
    if api_url:
        print(f"Poster API configured: {api_url}")
    else:
        print("Warning: api.poster_api_url is empty in config.json")

    config_lock_path.touch(exist_ok=True)
    shared_files = [config_path, config_lock_path]
    for optional_name in ("api_data.json", "event_data.json", ".playback-status.json"):
        optional_path = BASE_DIR / optional_name
        if optional_path.exists():
            shared_files.append(optional_path)

    for shared_path in shared_files:
        os.chown(shared_path, user_info.pw_uid, user_info.pw_gid)
        shared_path.chmod(0o660 if shared_path == config_lock_path else 0o640)

    for directory_name in ("eposter_cache", "local_test"):
        directory = BASE_DIR / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        for path in [directory] + list(directory.rglob("*")):
            if path.is_symlink():
                continue
            os.chown(path, user_info.pw_uid, user_info.pw_gid)
            path.chmod(0o750 if path.is_dir() else 0o640)

    print(f"Runtime files are owned by {REAL_USER}:{user_info.pw_gid}")
    return True


def install_service_units(restart=True, validated=False):
    """Render and install both systemd units for the current repo location."""
    import pwd

    if not PYTHON_BIN.exists():
        print(f"Error: virtualenv Python not found at {PYTHON_BIN}")
        print("Run 'sudo python3 installer.py' once for the full installation.")
        return False

    try:
        user_info = pwd.getpwnam(REAL_USER)
    except KeyError:
        print(f"Error: display user '{REAL_USER}' does not exist")
        return False

    if not validated:
        validate_environment(PYTHON_BIN)

    user_id = user_info.pw_uid
    user_home = user_info.pw_dir

    if not prepare_runtime_state(user_info):
        return False

    SERVICES["eposter-display"]["env"] = [
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        f"HOME={user_home}",
        "DISPLAY=:0",
        f"XAUTHORITY={user_home}/.Xauthority",
        f"XDG_RUNTIME_DIR=/run/user/{user_id}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{user_id}/bus",
    ]

    for name, info in SERVICES.items():
        print(f"Installing systemd service: {name}")
        env_lines = "\n".join(f"Environment={value}" for value in info.get("env", []))
        with open(info["template"], "r", encoding="utf-8") as handle:
            service_content = handle.read().format(
                description=info["description"],
                after=info["after"],
                user=info["user"],
                base_dir=BASE_DIR,
                exec_start=info["exec"],
                python_bin=PYTHON_BIN,
                environment=env_lines,
                service_name=name,
            )
        service_path = Path("/etc/systemd/system") / f"{name}.service"
        service_path.write_text(service_content, encoding="utf-8")

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "eposter-admin.service", "eposter-display.service"])
    if restart:
        run(["systemctl", "restart", "eposter-admin.service", "eposter-display.service"])
    return True

def validate_environment(python):
    prefix = ["runuser", "-u", REAL_USER, "--"] if os.geteuid() == 0 else []
    run(prefix + [str(python), "-c",
                  "import config_portal, RunThis; from helper.media_controller import Controller"])
    run(prefix + [str(python), str(BASE_DIR / "tools/playback_smoke.py"), "--quick"])


def stage_environment():
    """Versioned paths keep pip entry-point shebangs valid after activation."""
    staged = BASE_DIR / ".venvs" / uuid.uuid4().hex
    staged.parent.mkdir(exist_ok=True)
    try:
        run(["python3", "-m", "venv", str(staged)])
        run([str(staged / "bin/pip"), "install", "-r", str(REQ_FILE)])
        user = pwd.getpwnam(REAL_USER)
        # The webpage updater runs as root with umask 0027. Make the staged
        # environment traversable by the actual display user before activation.
        for path in [staged.parent, staged] + list(staged.rglob("*")):
            os.chown(path, user.pw_uid, user.pw_gid, follow_symlinks=False)
        validate_environment(staged / "bin/python3")
        return staged
    except Exception:
        if staged.exists():
            shutil.rmtree(staged)
        raise


def activate_environment(staged):
    """Switch only after staging succeeds; keep the old environment for recovery."""
    previous = BASE_DIR / (".venv-previous-" + uuid.uuid4().hex)
    if VENV_PATH.exists() or VENV_PATH.is_symlink():
        VENV_PATH.rename(previous)
    else:
        previous = False
    try:
        VENV_PATH.symlink_to(staged, target_is_directory=True)
    except Exception:
        if previous:
            previous.rename(VENV_PATH)
        raise
    return previous


def restore_environment(previous):
    if VENV_PATH.is_symlink():
        VENV_PATH.unlink()
    if previous:
        previous.rename(VENV_PATH)


def prune_environments(previous):
    """Retain the current and previous version; only remove installer-owned paths."""
    keep = {VENV_PATH.resolve()}
    if previous:
        keep.add(previous.resolve())
    for marker in BASE_DIR.glob(".venv-previous-*"):
        if marker == previous or len(marker.name.removeprefix(".venv-previous-")) != 32:
            continue
        if marker.is_symlink():
            marker.unlink()
        elif marker.is_dir():
            shutil.rmtree(marker)
    versions = BASE_DIR / ".venvs"
    if versions.exists():
        for version in versions.iterdir():
            if (version.is_dir() and not version.is_symlink() and version.resolve() not in keep
                    and len(version.name) == 32 and all(c in "0123456789abcdef" for c in version.name)):
                shutil.rmtree(version)


def wait_for_display(restarted_after, timeout=20):
    """Service 'active' alone doesn't prove the player has initialized."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            status = json.loads((BASE_DIR / ".playback-status.json").read_text())
            if status.get("checked_at", 0) >= restarted_after and status.get("pid") and status.get("ready"):
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Display did not report a fresh player heartbeat. Check journalctl -u eposter-display.service.")


def setup():
    print(f"Installing ePoster from: {BASE_DIR}")
    os.chdir(BASE_DIR)

    # 1. Ensure system dependencies
    run(["apt-get", "update", "-y"])
    run([
        "apt-get", "install", "-y", "python3-venv", "python3-pip",
        "x11-xserver-utils", "network-manager", "polkitd", "ffmpeg", "jq",
        "fonts-dejavu-core", "git", "mpv", "tzdata",
    ])

    # Stage and smoke-test dependencies before interrupting the running services.
    staged = stage_environment()
    previous = None
    stopped = False
    original_config = None
    config_path = BASE_DIR / "config.json"
    try:
        stopped = True
        if not run(["systemctl", "stop", "eposter-admin.service", "eposter-display.service"], ignore_fail=True):
            # A first install has no units yet; an existing active service must
            # actually stop before its Python environment can be switched.
            for service in ("eposter-admin.service", "eposter-display.service"):
                if run(["systemctl", "is-active", "--quiet", service], ignore_fail=True):
                    raise RuntimeError(f"Could not stop {service}; update cancelled")
        # Capture rollback state after the portal can no longer save settings.
        if config_path.exists():
            original_config = json.loads(config_path.read_text())
        previous = activate_environment(staged)
        finish_install()
        try:
            prune_environments(previous)
        except OSError as error:
            print(f"Old environment cleanup deferred: {error}")
    except Exception:
        if stopped:
            run(["systemctl", "stop", "eposter-admin.service", "eposter-display.service"], ignore_fail=True)
        if previous is not None:
            restore_environment(previous)
        if original_config is not None and stopped:
            atomic_write_json(config_path, original_config)
        if stopped:
            run(["systemctl", "start", "eposter-admin.service", "eposter-display.service"], ignore_fail=True)
        raise


def finish_install():
    for script in SERVICE_FILES_DIR.glob("*.sh"):
        run(["chmod", "755", str(script)])

    # --- 3. WIFI & PERMISSIONS (RAKSA OS FIX) ---
    print(f"Configuring Wi-Fi permissions for {REAL_USER}...")
    
    # Ensure the user is in the correct groups
    groups = ["netdev", "audio", "video", "sudo"]
    try:
        grp.getgrnam("render")
        groups.append("render")
    except KeyError:
        pass
    run(["usermod", "-aG", ",".join(groups), REAL_USER])

    # Path for modern Polkit rules
    polkit_dir = Path("/etc/polkit-1/rules.d")
    polkit_rule_path = polkit_dir / "10-eposter-wifi.rules"
    
    # Modern Javascript-based Polkit Rule
    rules_content = f"""
polkit.addRule(function(action, subject) {{
    if ((action.id.indexOf("org.freedesktop.NetworkManager.") == 0 ||
         action.id == "org.freedesktop.nm-dispatcher.action") &&
        subject.user == "{REAL_USER}") {{
        return polkit.Result.YES;
    }}
}});
"""
    try:
        # Ensure directory exists and has correct owner
        run(["mkdir", "-p", str(polkit_dir)])
        run(["chown", "polkitd:root", str(polkit_dir)], ignore_fail=True) # polkitd owns this in modern distros
        
        with open(polkit_rule_path, "w") as f:
            f.write(rules_content)
            
        run(["chown", "root:root", str(polkit_rule_path)])
        run(["chmod", "644", str(polkit_rule_path)])
        
        # Restart Polkit to load new rules
        run(["systemctl", "restart", "polkit"], ignore_fail=True)
    except Exception as e:
        print(f"Failed to write Polkit rule: {e}")

    # Disable Hotspot Autostart
    print("Disabling Hotspot autoconnect...")
    run("nmcli connection modify Hotspot connection.autoconnect no", ignore_fail=True)
    
    # --- 4. Systemd Services ---
    restarted_after = time.time()
    if not install_service_units(restart=True, validated=True):
        raise RuntimeError("Failed to install ePoster services")
    
    run(["timedatectl", "set-ntp", "true"], ignore_fail=True)
    for service in ("eposter-admin.service", "eposter-display.service"):
        run(["systemctl", "is-active", "--quiet", service])
    wait_for_display(restarted_after)
    print("[SUCCESS] Services restarted. Configuration and media cache preserved.")
    print("Inspect journalctl -u eposter-display.service for the active video decoder.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Error: Run with sudo.")
        sys.exit(1)
    if "--services-only" in sys.argv:
        if not install_service_units(restart=True):
            sys.exit(1)
    else:
        setup()
