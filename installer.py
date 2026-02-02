import os
import subprocess
import sys
from pathlib import Path

# --- DYNAMIC CONFIGURATION ---
# Detects the directory where THIS script is saved
BASE_DIR = Path(__file__).resolve().parent
VENV_PATH = BASE_DIR / "venv"
PYTHON_BIN = VENV_PATH / "bin" / "python3"
REQ_FILE = BASE_DIR / "requirements.txt"

# Detect the actual user (even if running via sudo)
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
        "after": "graphical.target",
        "env": [
            "DISPLAY=:0",
            f"XAUTHORITY=/home/{REAL_USER}/.Xauthority"
        ]
    }
}

def run(cmd):
    print(f"--> Executing: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    subprocess.run(cmd, check=True, shell=isinstance(cmd, str))

def setup():
    print(f"Installing ePoster from: {BASE_DIR}")
    os.chdir(BASE_DIR)

    # 1. Ensure system dependencies are met
    print("Checking for python3-venv...")
    run(["apt-get", "update", "-y"])
    run(["apt-get", "install", "-y", "python3-venv", "python3-pip", "x11-xserver-utils"])

    # 2. Create Virtual Environment
    if not os.path.exists(VENV_PATH):
        print(f"Creating virtual environment in {VENV_PATH}...")
        run(["python3", "-m", "venv", str(VENV_PATH)])

    # 3. Install Requirements
    pip_bin = VENV_PATH / "bin" / "pip"
    print("Installing python requirements...")
    if REQ_FILE.exists():
        run([str(pip_bin), "install", "-r", str(REQ_FILE)])
    else:
        print("requirements.txt not found! Installing defaults...")
        run([str(pip_bin), "install", "flask", "dnslib", "pygame", "requests", "Pillow"])

    # 4. Create Systemd Service Files
    for name, info in SERVICES.items():
        print(f"Creating systemd service: {name}")
        env_lines = "\n".join([f"Environment={e}" for e in info.get("env", [])])
        
        service_content = f"""[Unit]
Description={info['description']}
After={info['after']}
After=display-manager.service
#Wants=network-online.target

[Service]
User={info['user']}
WorkingDirectory={BASE_DIR}
ExecStartPre=/bin/sleep 10
ExecStart={info['exec']}
Restart=always
RestartSec=10
{env_lines}

[Install]
WantedBy=graphical.target
"""
        service_path = f"/etc/systemd/system/{name}.service"
        with open(service_path, "w") as f:
            f.write(service_content)

    # 5. X11 Permissions
    print(f"Setting up X11 permissions for {REAL_USER}...")
    profile_path = f"/home/{REAL_USER}/.profile"
    xhost_line = f"xhost +SI:localuser:{REAL_USER} > /dev/null 2>&1"
    
    if os.path.exists(profile_path):
        with open(profile_path, "a+") as f:
            f.seek(0)
            if xhost_line not in f.read():
                f.write(f"\n{xhost_line}\n")

    # 6. Refresh and Enable
    print("Activating services...")
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "eposter-admin.service"])
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "eposter-display.service"])
    run(["systemctl", "start", "eposter-display.service"])
    
    print(f"\n[SUCCESS] Setup finished for user '{REAL_USER}'.")
    print("Please reboot your device to   start the display and admin portal.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Error: You must run this installer with sudo.")
        sys.exit(1)
    setup()