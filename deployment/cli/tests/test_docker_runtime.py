import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from weave_cli.docker.compose import DockerCompose
from weave_cli.docker.runtime import CommandResult, DockerRuntime, DockerRuntimeError


class DockerRuntimeTests(unittest.TestCase):
    def test_captures_output_and_nonzero_exit(self):
        with patch(
            "weave_cli.docker.runtime.shutil.which", return_value=sys.executable
        ):
            result = DockerRuntime.run_docker_command(
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
            child = f"import time; from pathlib import Path; time.sleep(3); Path({str(marker)!r}).touch()"
            launcher = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
            )
            with (
                patch(
                    "weave_cli.docker.runtime.shutil.which", return_value=sys.executable
                ),
                self.assertRaisesRegex(DockerRuntimeError, "timed out"),
            ):
                DockerRuntime.run_docker_command(["-c", launcher], timeout=1)
            time.sleep(3)
            self.assertFalse(marker.exists(), "The descendant survived command timeout")

    def test_follow_streams_without_a_command_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "compose.yaml"
            file.touch()
            compose = DockerCompose(compose_file=file, env_file=file)
            with patch.object(
                DockerRuntime,
                "run_docker_command",
                return_value=CommandResult(0, "", ""),
            ) as run:
                compose.logs(service="api", follow=True)
            self.assertEqual(
                run.call_args.kwargs["arguments"][-3:], ["logs", "-f", "api"]
            )
            self.assertTrue(run.call_args.kwargs["stream"])
            self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_stream_does_not_capture_output(self):
        with patch(
            "weave_cli.docker.runtime.shutil.which", return_value=sys.executable
        ):
            result = DockerRuntime.run_docker_command(
                ["-c", "print('stream-visible')"], stream=True
            )
        self.assertTrue(result.successful)
        self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_interrupt_cleans_up_and_propagates(self):
        with (
            patch("weave_cli.docker.runtime.shutil.which", return_value=sys.executable),
            patch("weave_cli.docker.runtime.subprocess.Popen") as spawn,
            patch.object(DockerRuntime, "_stop_process_tree") as stop,
        ):
            spawn.return_value.wait.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                DockerRuntime.run_docker_command(
                    ["--version"], stream=True, timeout=None
                )
            stop.assert_called_once_with(spawn.return_value)


if __name__ == "__main__":
    unittest.main()
