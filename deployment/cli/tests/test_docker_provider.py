import unittest
from pathlib import Path
from unittest.mock import patch

from weave_cli.docker.provider import (
    LinuxDockerProvider,
    WindowsWslDockerProvider,
)


class DockerProviderTests(unittest.TestCase):
    def test_windows_provider_targets_weave_wsl_distribution(self):
        with patch(
            "weave_cli.docker.provider.shutil.which",
            return_value=r"C:\\Windows\\System32\\wsl.exe",
        ):
            command = WindowsWslDockerProvider().build_command(
                ["compose", "ps"]
            )

        self.assertEqual(
            command,
            [
                r"C:\\Windows\\System32\\wsl.exe",
                "--distribution",
                "WeaveCBT",
                "--user",
                "root",
                "--",
                "docker",
                "compose",
                "ps",
            ],
        )

    def test_windows_provider_translates_host_path_for_wsl(self):
        translated = WindowsWslDockerProvider().translate_path(
            Path(r"C:\Program Files\WeaveCBT\compose.yaml")
        )

        self.assertEqual(
            translated,
            "/mnt/c/Program Files/WeaveCBT/compose.yaml",
        )

    def test_linux_provider_uses_native_docker(self):
        with patch(
            "weave_cli.docker.provider.shutil.which",
            return_value="/usr/bin/docker",
        ):
            command = LinuxDockerProvider().build_command(["info"])

        self.assertEqual(command, ["/usr/bin/docker", "info"])

    def test_linux_provider_keeps_host_path(self):
        path = Path("/opt/weave-cbt/compose.yaml")
        self.assertEqual(
            LinuxDockerProvider().translate_path(path),
            "/opt/weave-cbt/compose.yaml",
        )


if __name__ == "__main__":
    unittest.main()
