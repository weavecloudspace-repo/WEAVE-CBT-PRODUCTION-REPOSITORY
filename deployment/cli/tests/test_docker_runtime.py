import sys
import tempfile
import time
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from weave_cli.docker.provider import DockerCommandProvider
from weave_cli.docker.runtime import DockerRuntime, DockerRuntimeError


class PythonCommandProvider(DockerCommandProvider):
    def build_command(self, arguments: Sequence[str]) -> list[str]:
        return [sys.executable, *arguments]

    def translate_path(self, path: Path) -> str:
        return str(path)


class DockerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = DockerRuntime(PythonCommandProvider())

    def test_captures_output_and_nonzero_exit(self):
        result = self.runtime.run_docker_command(
            [
                "-c",
                "import sys; print('output'); print('error', file=sys.stderr); sys.exit(7)",
            ]
        )
        self.assertEqual(
            (result.return_code, result.stdout, result.stderr), (7, "output", "error")
        )

    def test_timeout_stops_descendant_holding_output_handles(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child-finished"
            child = (
                "import time; from pathlib import Path; "
                f"time.sleep(3); Path({str(marker)!r}).touch()"
            )
            launcher = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
            )

            with self.assertRaisesRegex(DockerRuntimeError, "timed out"):
                self.runtime.run_docker_command(["-c", launcher], timeout=1)

            time.sleep(3)
            self.assertFalse(marker.exists(), "The descendant survived command timeout")

    def test_stream_does_not_capture_output(self):
        result = self.runtime.run_docker_command(
            ["-c", "print('stream-visible')"],
            stream=True,
        )
        self.assertTrue(result.successful)
        self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_interrupt_cleans_up_and_propagates(self):
        with (
            patch("weave_cli.docker.runtime.subprocess.Popen") as spawn,
            patch.object(self.runtime, "_stop_process_tree") as stop,
        ):
            spawn.return_value.wait.side_effect = KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                self.runtime.run_docker_command(
                    ["--version"],
                    stream=True,
                    timeout=None,
                )

            stop.assert_called_once_with(spawn.return_value)


if __name__ == "__main__":
    unittest.main()
