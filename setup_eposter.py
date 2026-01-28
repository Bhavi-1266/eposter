import os
import subprocess
import sys
from pathlib import Path

# --- CONFIGURATION ---
USER = "rock"
BASE_DIR = "/home/rock/Desktop/eposter_latest/eposter-main"
VENV_PATH = f"{BASE_DIR}/venv"
PYTHON_BIN = f"{VENV_PATH}/bin/python3"
REQ_FILE = f"{BASE_DIR}/requirements.txt"

# Service Definitions
SERVICES = {
    "eposter-admin": {
        "description": "ePoster Admin Web Interface & DNS",
        "exec": f"{PYTHON_BIN} {BASE_DIR}/config_portal.py",
        "user": "root", # Root needed for Port 80 and DNS Port 53
        "after": "network.target"
    },
    "eposter-display": {
        "description": "ePoster Pygame Display Controller",
        "exec": f"{PYTHON_BIN} {BASE_DIR}/RunThis.py",
        "user": USER,
        "after": "graphical.target",
        "env": [
            "DISPLAY=:0",
            f"XAUTHORITY=/home/{USER}/.Xauthority"
        ]
    }
}

def run(cmd):
    print(f"--> Executing: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    subprocess.run(cmd, check=True, shell=isinstance(cmd, str))

def setup():
    # Ensure we are in the right directory
    os.chdir(BASE_DIR)

    # 1. Create Virtual Environment
    if not os.path.exists(VENV_PATH):
        print("Creating virtual environment...")
        run(["python3", "-m", "venv", "venv"])

    # 2. Install Requirements from requirements.txt
    print("Installing requirements...")
    if os.path.exists(REQ_FILE):
        run([f"{VENV_PATH}/bin/pip", "install", "-r", REQ_FILE])
    else:
        print("requirements.txt not found! Installing defaults...")
        run([f"{VENV_PATH}/bin/pip", "install", "flask", "dnslib", "pygame", "requests", "Pillow"])

    # 3. Create Systemd Service Files
    for name, info in SERVICES.items():
        print(f"Creating systemd service: {name}")
        env_lines = "\n".join([f"Environment={e}" for e in info.get("env", [])])
        
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

[Install]
WantedBy=graphical.target
"""
        with open(f"/etc/systemd/system/{name}.service", "w") as f:
            f.write(service_content)

    # 4. Make xhost permissions permanent for the display
    print("Setting up X11 permissions...")
    profile_path = f"/home/{USER}/.profile"
    xhost_line = f"xhost +SI:localuser:{USER} > /dev/null 2>&1"
    
    with open(profile_path, "a+") as f:
        f.seek(0)
        if xhost_line not in f.read():
            f.write(f"\n{xhost_line}\n")

    # 5. Refresh and Enable
    print("Activating services...")
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "eposter-admin.service"])
    run(["systemctl", "enable", "eposter-display.service"])
    
    print("\n[SUCCESS] Setup finished. Please reboot your device.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Error: You must run this setup script with sudo.")
        sys.exit(1)
    setup()