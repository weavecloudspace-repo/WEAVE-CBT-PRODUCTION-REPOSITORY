"""Linux installer contract checks without modifying /usr/local."""
import os
import subprocess
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[2] / "distribution" / "linux" / "install.sh"


@unittest.skipIf(os.name == "nt", "Native Bash installation syntax requires Linux.")
class LinuxManagerInstallerTests(unittest.TestCase):
    def test_installer_is_valid_bash(self):
        result = subprocess.run(["bash", "-n", str(INSTALLER)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_channel_guard_and_atomic_binary_replace(self):
        script = INSTALLER.read_text(encoding="utf-8")
        self.assertIn('manifest_channel()', script)
        self.assertIn('if [ "$incoming_channel" != "$existing_channel" ]; then', script)
        self.assertIn('staged=/usr/local/bin/.weave-setup-$$', script)
        self.assertIn('mv -f -- "$staged" /usr/local/bin/weave', script)
        self.assertIn('"$HERE/weave" --help >/dev/null', script)


if __name__ == "__main__":
    unittest.main()
