import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'setup_uart6.sh'


class Uart6SetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.boot = root / 'extlinux.conf'
        self.original = 'label test\n  fdtoverlays /dtbo/other.dtbo # rk3588-uart6-m1.dtbo\n'
        self.boot.write_text(self.original)
        self.boot.chmod(0o640)
        self.dtbo = root / 'rk3588-uart6-m1.dtbo'
        self.dtbo.touch()
        self.backups = root / 'backups'
        self.backups.mkdir()
        self.rsetup = root / 'rsetup'

    def run_setup(self, fake):
        self.rsetup.write_text('#!/usr/bin/env bash\nset -eu\n' + fake)
        self.rsetup.chmod(0o755)
        return subprocess.run(
            ['bash', '-c', 'source "$1"; enable_uart6 "$2" "$3" "$4" "$5"',
             'test-uart6', str(SCRIPT), str(self.boot), str(self.dtbo), str(self.rsetup), str(self.backups)],
            env=os.environ | {'TEST_BOOT_CONFIG': str(self.boot)}, capture_output=True, text=True, timeout=5)

    def test_backs_up_enables_and_verifies_uart6_idempotently(self):
        changed = self.run_setup('[[ "$*" == "enable_overlays rk3588-uart6-m1.dtbo" ]]\n'
                                 'printf "  fdtoverlays /dtbo/rk3588-uart6-m1.dtbo\\n" >> "$TEST_BOOT_CONFIG"\n')
        self.assertEqual(changed.returncode, 0, changed.stderr)
        backup, = self.backups.iterdir()
        self.assertEqual(backup.read_text(), self.original)
        self.assertIn('boot configuration verified', changed.stdout)
        again = self.run_setup('exit 1\n')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(list(self.backups.iterdir()), [backup])

    def test_rolls_back_a_failed_verification(self):
        failed = self.run_setup('printf "corrupt boot config\\n" > "$TEST_BOOT_CONFIG"\n')
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('Restored', failed.stderr)
        self.assertEqual(self.boot.read_text(), self.original)
        self.assertEqual(self.boot.stat().st_mode & 0o777, 0o640)
