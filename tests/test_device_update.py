"""Exercise sequencing and recovery without modifying the host system."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import device_update as update


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        (self.root / "config.json").write_text('{"device": "preserve"}')

    def execute(self, dirty=False, pull_fails=False, install_fails=False):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            output = ""
            if "--show-current" in command:
                output = "main\n"
            if "--porcelain" in command:
                output = " M RunThis.py\n" if dirty else ""
            if (pull_fails and "pull" in command) or (install_fails and command[0] == "/usr/bin/python3"):
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, stdout=output)

        with patch("device_update.subprocess.run", side_effect=run):
            if dirty or pull_fails or install_fails:
                with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                    update.perform_update(self.root)
            else:
                update.perform_update(self.root)
        self.assertEqual((self.root / "config.json").read_text(), '{"device": "preserve"}')
        return commands

    def test_success_pulls_before_full_installer(self):
        commands = self.execute()
        pull = next(i for i, cmd in enumerate(commands) if "pull" in cmd)
        self.assertEqual(commands[pull][-4:], ["pull", "--ff-only", "origin", "main"])
        self.assertEqual(commands[pull + 1], ["/usr/bin/python3", str(self.root / "installer.py")])
        self.assertEqual(update.update_status(self.root)["state"], "complete")

    def test_pull_failure_skips_installer(self):
        commands = self.execute(pull_fails=True)
        self.assertFalse(any(cmd[0] == "/usr/bin/python3" for cmd in commands))
        self.assertEqual(update.update_status(self.root)["state"], "failed")

    def test_dirty_checkout_skips_pull(self):
        commands = self.execute(dirty=True)
        self.assertFalse(any("pull" in cmd for cmd in commands))

    def test_installer_failure_recovers_services(self):
        commands = self.execute(install_fails=True)
        self.assertEqual(commands[-1], ["systemctl", "start", "eposter-admin.service", "eposter-display.service"])
        self.assertEqual(update.update_status(self.root)["state"], "failed")
