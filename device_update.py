#!/usr/bin/env python3
"""Run outside the portal service so installer restarts cannot kill the update."""
import fcntl
import json
import os
import pwd
import subprocess
from pathlib import Path

from helper.json_utils import atomic_write_json

PROJECT_DIR = Path(__file__).resolve().parent
UNIT = "eposter-update.service"
STATE_FILE = ".update-status.json"


def update_status(project_dir):
    try:
        return json.loads((project_dir / STATE_FILE).read_text())
    except (OSError, ValueError):
        return {"state": "idle", "message": "No update has been run yet."}


def write_status(project_dir, state, message):
    atomic_write_json(project_dir / STATE_FILE, {"state": state, "message": message})


def perform_update(project_dir=PROJECT_DIR):
    project_dir = Path(project_dir)
    with (project_dir / ".update.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stage = "Checking repository"
        try:
            owner = pwd.getpwuid((project_dir / ".git").stat().st_uid)
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0", HOME=owner.pw_dir,
                       GIT_SSH_COMMAND="ssh -oBatchMode=yes -oConnectTimeout=15")
            prefix = ["runuser", "-u", owner.pw_name, "--"] if os.geteuid() == 0 else []

            def git(*args):
                return subprocess.run(prefix + ["git", "-C", str(project_dir), *args],
                                      env=env, check=True, text=True, capture_output=True, timeout=180)

            write_status(project_dir, "running", stage)
            if git("branch", "--show-current").stdout.strip() != "main":
                raise RuntimeError("Switch the device checkout to main before updating.")
            if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
                raise RuntimeError("Tracked files have local edits. Resolve them on the device before updating.")
            stage = "Pulling origin main"
            write_status(project_dir, "running", stage)
            git("pull", "--ff-only", "origin", "main")
            stage = "Running installer; the portal and display may be temporarily offline"
            write_status(project_dir, "running", stage)
            subprocess.run(["/usr/bin/python3", str(project_dir / "installer.py")],
                           cwd=project_dir, env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"),
                           check=True, timeout=1800)
            write_status(project_dir, "complete", "Update installed. Reload the portal to use the latest version.")
        except Exception as error:
            # Git output can include credential-bearing remote URLs; keep it out of the API.
            detail = str(error) if isinstance(error, RuntimeError) else "Check sudo journalctl -u eposter-update.service on the device."
            write_status(project_dir, "failed", stage + " failed. " + detail)
            # Installer may have stopped both services before failing.
            subprocess.run(["systemctl", "start", "eposter-admin.service", "eposter-display.service"],
                           check=False, timeout=30)
            raise


if __name__ == "__main__":
    perform_update()
