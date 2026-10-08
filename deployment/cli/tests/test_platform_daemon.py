import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from weave_cli.platforms.base import PlatformError
from weave_cli.platforms.linux import LinuxPlatform
from weave_cli.platforms.windows import WindowsPlatform


class PlatformDockerDaemonTests(unittest.TestCase):
    def test_windows_starts_docker_in_configured_wsl_distribution(self):
        platform = WindowsPlatform(wsl_distribution="Ubuntu")

        with (
            patch(
                "weave_cli.platforms.windows.shutil.which",
                return_value=r"C:\\Windows\\System32\\wsl.exe",
            ),
            patch("weave_cli.platforms.windows.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""

            platform.start_docker_engine()

        self.assertEqual(
            run.call_args.args[0],
            [
                r"C:\\Windows\\System32\\wsl.exe",
                "--distribution",
                "Ubuntu",
                "--user",
                "root",
                "--",
                "systemctl",
                "start",
                "docker",
            ],
        )

    def test_windows_rejects_missing_wsl(self):
        with patch("weave_cli.platforms.windows.shutil.which", return_value=None):
            with self.assertRaises(PlatformError):
                WindowsPlatform().start_docker_engine()

    def test_linux_starts_docker_with_systemctl(self):
        with (
            patch(
                "weave_cli.platforms.linux.shutil.which",
                return_value="/usr/bin/systemctl",
            ),
            patch("weave_cli.platforms.linux.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""

            LinuxPlatform().start_docker_engine()

        self.assertEqual(
            run.call_args.args[0],
            ["/usr/bin/systemctl", "start", "docker"],
        )


if __name__ == "__main__":
    unittest.main()
