#!/usr/bin/env python3
import os
import subprocess
import sys
import shutil
from pathlib import Path

# --- DYNAMIC CONFIGURATION ---
BASE_DIR = Path(__file__).resolve().parent
VENV_PATH = BASE_DIR / "venv"
PYTHON_BIN = VENV_PATH / "bin" / "python3"
REQ_FILE = BASE_DIR / "requirements.txt"

# Detect the actual user
REAL_USER = os.getenv("SUDO_USER") or os.getlogin() or "rock"

# Service Definitions
SERVICES = {
    "eposter-admin": {
        "description": "ePoster Admin Web Interface & DNS",
        "exec": f"{PYTHON_BIN} {BASE_DIR}/config_portal.py",
        "user": "root", 
        "after": "network.target"
    },
    "eposter-display": {
        "description": "ePoster Pygame Display Controller",
        "exec": f"{PYTHON_BIN} {BASE_DIR}/RunThis.py",
        "user": REAL_USER,
        "after": "graphical.target display-manager.service network-online.target",
        "env": [
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
    except Exception as e:
        print(f"Non-critical error: {e}")

def setup():
    print(f"Installing ePoster from: {BASE_DIR}")
    os.chdir(BASE_DIR)

    # Detect UID for XDG_RUNTIME_DIR
    import pwd
    try:
        user_info = pwd.getpwnam(REAL_USER)
        user_id = user_info.pw_uid
    except KeyError:
        user_id = 1000

    # 1. Ensure system dependencies
    run(["apt-get", "update", "-y"])
    run(["apt-get", "install", "-y", "python3-venv", "python3-pip", "x11-xserver-utils", "network-manager", "polkitd"])

    # 2. Virtual Env & Requirements
    if not os.path.exists(VENV_PATH):
        run(["python3", "-m", "venv", str(VENV_PATH)])
    
    pip_bin = VENV_PATH / "bin" / "pip"
    if REQ_FILE.exists():
        run([str(pip_bin), "install", "-r", str(REQ_FILE)])
    else:
        run([str(pip_bin), "install", "flask", "dnslib", "pygame", "requests", "Pillow"])

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
    # Update the environment with the detected UID
    SERVICES["eposter-display"]["env"] = [
        "DISPLAY=:0",
        f"XAUTHORITY=/home/{REAL_USER}/.Xauthority",
        f"XDG_RUNTIME_DIR=/run/user/{user_id}"
    ]

    # --- 4. Systemd Services ---
    for name, info in SERVICES.items():
        print(f"Creating systemd service: {name}")
        env_lines = "\n".join([f"Environment={e}" for e in info.get("env", [])])
        
        # Ensure log directory exists
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        run(["chown", f"{REAL_USER}:{REAL_USER}", str(log_dir)])

        service_content = f"""[Unit]
Description={info['description']}
After={info['after']}
Wants=network-online.target

[Service]
User={info['user']}
WorkingDirectory={BASE_DIR}
ExecStartPre=/bin/sleep 10
ExecStart={info['exec']}
Restart=always
RestartSec=10
{env_lines}
StandardOutput=append:{BASE_DIR}/logs/output.log
StandardError=append:{BASE_DIR}/logs/error.log

[Install]
WantedBy=graphical.target
"""
        with open(f"/etc/systemd/system/{name}.service", "w") as f:
            f.write(service_content)

    # 5. X11 & Refresh
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "eposter-admin.service"])
    run(["systemctl", "enable", "eposter-display.service"])
    
    print(f"\n[SUCCESS] Setup finished. Wi-Fi permissions granted to '{REAL_USER}'.")
    print("Hotspot autostart disabled. Please reboot.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Error: Run with sudo.")
        sys.exit(1)
    setup()