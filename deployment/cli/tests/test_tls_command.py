"""Opt-in TLS orchestration contract, without a running Docker daemon."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from weave_cli.commands import tls
from weave_cli.docker.compose import DockerCompose


class TLSTests(unittest.TestCase):
    def test_profile_only_activated_after_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / "runtime.env"
            compose = root / "compose.yaml"
            env.write_text("ENVIRONMENT=stg\n", encoding="utf-8")
            compose.write_text("services: {}\n", encoding="utf-8")
            runtime = Mock()
            runtime.translate_path.side_effect = lambda path: str(path)
            runtime.run_docker_command.return_value = SimpleNamespace(successful=True)
            stack = DockerCompose(compose_file=compose, env_file=env, runtime=runtime)
            stack._run_compose_command(command=["ps"])
            args = runtime.run_docker_command.call_args.kwargs["arguments"]
            self.assertNotIn("tls", args)
            (root / "tls.enabled").write_text("enabled\n", encoding="utf-8")
            stack._run_compose_command(command=["ps"])
            args = runtime.run_docker_command.call_args.kwargs["arguments"]
            self.assertIn("--profile", args)
            self.assertIn("tls", args)

    def test_dry_run_does_not_enable_real_certificate(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = SimpleNamespace(
                installation=SimpleNamespace(data_directory=data, runtime_type="native"),
                runtime=SimpleNamespace(docker_engine_running=lambda: True),
                compose=Mock(),
            )
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch.object(tls, "banner"),
                patch.object(tls, "info"),
                patch.object(tls, "success"),
            ):
                tls.tls(dry_run=True, renew=False)
            self.assertFalse((data / "tls.enabled").exists())
            stack.compose._run_compose_command.assert_called_once()
