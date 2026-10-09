import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from weave_cli.docker.compose import DockerCompose, DockerComposeError
from weave_cli.docker.provider import DockerCommandProvider
from weave_cli.docker.runtime import CommandResult, DockerRuntime


class PassthroughProvider(DockerCommandProvider):
    def build_command(self, arguments: Sequence[str]) -> list[str]:
        return ["docker", *arguments]

    def translate_path(self, path: Path) -> str:
        return str(path)


class DockerComposeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        directory = Path(self.temp_dir.name)
        self.compose_file = directory / "compose.yaml"
        self.env_file = directory / "runtime.env"
        self.compose_file.touch()
        self.env_file.touch()
        self.runtime = DockerRuntime(PassthroughProvider())
        self.compose = DockerCompose(
            compose_file=self.compose_file,
            env_file=self.env_file,
            runtime=self.runtime,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _assert_command(
        self,
        method_name: str,
        expected_tail: list[str],
        *,
        expected_timeout: int | None = 30,
    ) -> None:
        with patch.object(
            self.runtime,
            "run_docker_command",
            return_value=CommandResult(0, "", ""),
        ) as run:
            getattr(self.compose, method_name)()

        self.assertEqual(
            run.call_args.kwargs["arguments"][-len(expected_tail):],
            expected_tail,
        )
        self.assertEqual(run.call_args.kwargs["timeout"], expected_timeout)

    def test_pull_weave_image_targets_only_weave_services(self):
        self._assert_command(
            "pull_weave_image",
            ["pull", "bootstrap", "api", "worker"],
            expected_timeout=None,
        )

    def test_pull_infrastructure_images_are_scoped(self):
        self._assert_command(
            "pull_postgres_image",
            ["pull", "postgres"],
            expected_timeout=None,
        )
        self._assert_command(
            "pull_redis_image",
            ["pull", "redis"],
            expected_timeout=None,
        )
        self._assert_command(
            "pull_nginx_image",
            ["pull", "nginx"],
            expected_timeout=None,
        )

    def test_config_validates_quietly(self):
        self._assert_command("config", ["config", "--quiet"])

    def test_destroy_removes_volumes_and_orphans_without_timeout(self):
        self._assert_command(
            "destroy",
            ["down", "--volumes", "--remove-orphans"],
            expected_timeout=None,
        )

    def test_follow_streams_without_a_command_timeout(self):
        with patch.object(
            self.runtime,
            "run_docker_command",
            return_value=CommandResult(0, "", ""),
        ) as run:
            self.compose.logs(service="api", follow=True)

        self.assertEqual(
            run.call_args.kwargs["arguments"][-3:],
            ["logs", "-f", "api"],
        )
        self.assertTrue(run.call_args.kwargs["stream"])
        self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_compose_uses_paths_translated_by_runtime(self):
        with (
            patch.object(
                self.runtime,
                "translate_path",
                side_effect=[
                    "/mnt/c/Program Files/WeaveCBT/compose.yaml",
                    "/mnt/c/ProgramData/WeaveCBT/runtime.env",
                ],
            ),
            patch.object(
                self.runtime,
                "run_docker_command",
                return_value=CommandResult(0, "", ""),
            ) as run,
        ):
            self.compose.status()

        arguments = run.call_args.kwargs["arguments"]
        self.assertEqual(
            arguments[arguments.index("-f") + 1],
            "/mnt/c/Program Files/WeaveCBT/compose.yaml",
        )
        self.assertEqual(
            arguments[arguments.index("--env-file") + 1],
            "/mnt/c/ProgramData/WeaveCBT/runtime.env",
        )


    def test_quiesce_stops_only_writers_and_keeps_database_running(self):
        self._assert_command(
            "stop_application",
            ["stop", "nginx", "api", "worker", "bootstrap"],
            expected_timeout=None,
        )

    def test_snapshot_is_run_inside_local_postgres(self):
        with patch.object(
            self.runtime,
            "run_docker_command",
            return_value=CommandResult(0, "", ""),
        ) as run:
            self.compose.snapshot_database("weave_cbt_rollback_" + "a" * 32)

        arguments = run.call_args.kwargs["arguments"]
        self.assertEqual(arguments[-9:-6], ["exec", "-T", "postgres"])
        self.assertIn("CREATE DATABASE", arguments[-3])
        self.assertEqual(arguments[-1], "weave_cbt_rollback_" + "a" * 32)
        self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_restore_keeps_failed_schema_available_until_verification(self):
        with patch.object(
            self.runtime,
            "run_docker_command",
            return_value=CommandResult(0, "", ""),
        ) as run:
            self.compose.restore_database(
                "weave_cbt_rollback_" + "a" * 32,
                "weave_cbt_failed_" + "a" * 32,
            )

        args = run.call_args.kwargs["arguments"]
        self.assertIn("ALTER DATABASE", args[-4])
        self.assertTrue(args[-2].startswith("weave_cbt_rollback_"))
        self.assertTrue(args[-1].startswith("weave_cbt_failed_"))

    def test_reject_arbitrary_database_identifier(self):
        with patch.object(self.runtime, "run_docker_command") as run:
            with self.assertRaises(ValueError):
                self.compose.snapshot_database("postgres;DROP DATABASE")
            run.assert_not_called()

    def test_missing_compose_file_is_rejected(self):
        self.compose_file.unlink()

        with self.assertRaises(DockerComposeError):
            self.compose.status()

    def test_missing_env_file_is_rejected(self):
        self.env_file.unlink()

        with self.assertRaises(DockerComposeError):
            self.compose.status()


if __name__ == "__main__":
    unittest.main()
