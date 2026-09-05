#!/usr/bin/env python3
import os
import subprocess
import sys
import json
import shutil
from pathlib import Path

# --- BOARD DEPLOYMENT CONFIGURATION ---
BASE_DIR = Path("/home/rock/eposter")
VENV_PATH = BASE_DIR / "venv"
PYTHON_BIN = VENV_PATH / "bin" / "python3"
REQ_FILE = BASE_DIR / "requirements.txt"
SERVICE_FILES_DIR = BASE_DIR / "service_files"

REAL_USER = "rock"

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
        "description": "ePoster Pygame Display Controller",
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
        subprocess.run(cmd, check=not ignore_fail, shell=isinstance(cmd, str))
        return True
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

    api_url = config.get("api", {}).get("poster_api_url")
    if api_url:
        print(f"Poster API configured: {api_url}")
    else:
        print("Warning: api.poster_api_url is empty in config.json")

    config_lock_path.touch(exist_ok=True)
    shared_files = [config_path, config_lock_path]
    for optional_name in ("api_data.json", "event_data.json"):
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


def install_service_units(restart=True):
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
        "SDL_VIDEODRIVER=x11",
        "SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0",
        "PYGAME_HIDE_SUPPORT_PROMPT=1",
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

def setup():
    print(f"Installing ePoster from: {BASE_DIR}")
    os.chdir(BASE_DIR)

    # 1. Ensure system dependencies
    run(["apt-get", "update", "-y"])
    run([
        "apt-get", "install", "-y", "python3-venv", "python3-pip",
        "x11-xserver-utils", "network-manager", "polkitd", "ffmpeg", "jq",
        "fonts-dejavu-core",
    ])

    # 2. Virtual Env & Requirements
    if not os.path.exists(VENV_PATH):
        run(["python3", "-m", "venv", str(VENV_PATH)])

    # Do not update an environment while the old services are importing it.
    run(["systemctl", "stop", "eposter-admin.service", "eposter-display.service"], ignore_fail=True)

    pip_bin = VENV_PATH / "bin" / "pip"
    if REQ_FILE.exists():
        run([str(pip_bin), "install", "-r", str(REQ_FILE)])
    else:
        run([str(pip_bin), "install", "flask", "dnslib", "pygame", "requests", "Pillow"])

    for script in SERVICE_FILES_DIR.glob("*.sh"):
        run(["chmod", "755", str(script)])

    # --- 3. WIFI & PERMISSIONS (RAKSA OS FIX) ---
    print(f"Configuring Wi-Fi permissions for {REAL_USER}...")
    
    # Ensure the user is in the correct groups
    run(["usermod", "-aG", "netdev,audio,video,sudo", REAL_USER])

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
    if not install_service_units(restart=True):
        raise RuntimeError("Failed to install ePoster services")
    
    print(f"\n[SUCCESS] Setup finished. Wi-Fi permissions granted to '{REAL_USER}'.")
    print("Hotspot autostart disabled. Please reboot.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Error: Run with sudo.")
        sys.exit(1)
    if "--services-only" in sys.argv:
        if not install_service_units(restart=True):
            sys.exit(1)
    else:
        setup()
