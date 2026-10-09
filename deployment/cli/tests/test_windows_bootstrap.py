from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest


WINDOWS_BOOTSTRAP = (
    Path(__file__).resolve().parents[2]
    / "bootstrap"
    / "windows"
    / "bootstrap.ps1"
)


@unittest.skipIf(os.name == "nt", "Linux Bash integration tests run on Linux, not Windows WSL.")
class WindowsWslEmbeddedBashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps1 = WINDOWS_BOOTSTRAP.read_text(encoding="utf-8")
        match = re.search(
            r"\$dockerProvisioning = @'\n(.*?)\n'@",
            cls.ps1.replace("\r\n", "\n"),
            re.DOTALL,
        )
        if match is None:
            raise AssertionError("Could not extract embedded WSL Docker script.")
        cls.script = match.group(1) + "\n"

    def test_embedded_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n"],
            input=self.script,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_bootstrap_bounds_docker_download_metadata_and_daemon_start(self):
        self.assertIn(
            'timeout --signal=TERM --kill-after=10s 600s "${APT_GET[@]}" update',
            self.ps1,
        )
        self.assertEqual(
            self.ps1.count(
                "timeout --signal=TERM --kill-after=10s 180s systemctl start docker.service"
            ),
            2,
        )
        self.assertIn('apt_weave --no-download install -y', self.ps1)
    def test_apt_command_is_initialized_before_watchdog(self):
        self.assertIn("APT_GET=(\n    apt-get", self.script)
        self.assertIn('"${APT_GET[@]}" "$@"', self.script)
        self.assertLess(
            self.script.index("APT_GET=("),
            self.script.index("download_docker_packages()"),
        )
        self.assertIn('setsid "${APT_GET[@]}" --download-only install -y "$@"', self.script)
        self.assertIn('apt_weave --no-download install -y', self.script)

    def test_download_watchdog_runs_actual_command_and_recovers(self):
        # Execute embedded WSL watchdog with a fake APT executable so the
        # command-line/setsid behavior is exercised without touching packages.
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            fake_apt = directory / "fake-apt"
            marker = directory / "first_attempt"
            calls = directory / "calls.log"

            fake_apt.write_text(
                r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WEAVE_TEST_CALLS"
if [[ "$*" != *--download-only* ]]; then exit 77; fi
if [ ! -f "$WEAVE_TEST_MARKER" ]; then
    touch "$WEAVE_TEST_MARKER"
    sleep 30
fi
""",
                encoding="utf-8",
            )
            fake_apt.chmod(0o755)

            preamble = self.script[
                self.script.index("APT_GET=("):
                self.script.index('echo "[WEAVE][ACTION] Refreshing Ubuntu package metadata')
            ]
            watchdog = self.script[
                self.script.index("WEAVE_DOWNLOAD_STALL_SECONDS=120"):
                self.script.index('echo "[WEAVE][ACTION] Downloading Docker Engine, Buildx, and Compose packages."')
            ]

            runner = (
                "set -eu\n"
                + preamble
                + "\n"
                + watchdog
                + '\nAPT_GET=("$WEAVE_TEST_APT")\n'
                + "WEAVE_DOWNLOAD_STALL_SECONDS=1\n"
                + "WEAVE_DOWNLOAD_POLL_SECONDS=1\n"
                + "WEAVE_DOWNLOAD_MAX_ATTEMPTS=2\n"
                + "apt_cache_bytes() { printf '0\\n'; }\n"
                + "download_docker_packages docker-ce\n"
            )

            env = os.environ.copy()
            env.update({
                "WEAVE_TEST_APT": str(fake_apt),
                "WEAVE_TEST_MARKER": str(marker),
                "WEAVE_TEST_CALLS": str(calls),
            })

            result = subprocess.run(
                ["bash", "-c", runner],
                capture_output=True,
                text=True,
                env=env,
                timeout=25,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("attempt 2/2", result.stdout)
            self.assertIn("download complete", result.stdout)
            attempts = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(attempts), 2)
            self.assertTrue(all("--download-only" in line for line in attempts))
            self.assertTrue(all("--no-download" not in line for line in attempts))


if __name__ == "__main__":
    unittest.main()
