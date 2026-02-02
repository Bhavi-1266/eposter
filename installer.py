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

    # --- 3. WIFI & PERMISSIONS (NEW) ---
    print(f"Configuring Wi-Fi permissions for {REAL_USER}...")
    
    # Add user to necessary groups
    run(["usermod", "-aG", "netdev,audio,video", REAL_USER])

    # Create Polkit rule for NetworkManager
    polkit_path = Path("/etc/polkit-1/localauthority/50-local.d/10-eposter-wifi.pkla")
    polkit_path.parent.mkdir(parents=True, exist_ok=True)
    
    pkla_content = f"""[Allow {REAL_USER} to modify network]
Identity=unix-user:{REAL_USER}
Action=org.freedesktop.NetworkManager.*
ResultAny=yes
ResultInactive=yes
ResultActive=yes
"""
    with open(polkit_path, "w") as f:
        f.write(pkla_content)

    # Disable Hotspot Autostart if it exists
    print("Checking for existing Hotspot profiles to disable autostart...")
    run("nmcli connection modify Hotspot connection.autoconnect no", ignore_fail=True)

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