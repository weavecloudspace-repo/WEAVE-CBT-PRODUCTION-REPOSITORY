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

    def test_nginx_supports_long_assigned_hostnames(self):
        nginx = (Path(__file__).resolve().parents[2] / "nginx" / "nginx.conf").read_text()
        self.assertIn("server_names_hash_bucket_size 128;", nginx)

    def test_existing_certificate_can_be_activated_without_reissuing(self):
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
                tls.tls(dry_run=False, renew=False, activate=True)
            calls = [
                c.kwargs.get("command")
                for c in stack.compose._run_compose_command.call_args_list
            ]
            self.assertNotIn(
                ["--profile", "tls-issue", "run", "--rm", "--no-deps", "certbot"],
                calls,
            )
            self.assertTrue(any(
                "test -s /etc/letsencrypt/live/weave-cbt-node/fullchain.pem" in " ".join(call)
                for call in calls if call
            ))
            self.assertIn(["run", "--rm", "--no-deps", "nginx", "nginx", "-t"], calls)
            self.assertTrue((data / "tls.enabled").exists())
            stack.compose.start.assert_called_once()

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

    def test_windows_activation_requires_admin_before_contacting_certbot(self):
        import typer

        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / "lan.json").write_text("{}")
            stack = SimpleNamespace(
                installation=SimpleNamespace(data_directory=data, runtime_type="wsl2"),
                platform=SimpleNamespace(is_admin=lambda: False),
                runtime=SimpleNamespace(docker_engine_running=lambda: True),
                compose=Mock(),
            )
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch.object(tls, "banner"),
            ):
                with self.assertRaises(typer.Exit):
                    tls.tls(dry_run=False, renew=False)
            stack.compose._run_compose_command.assert_not_called()
            self.assertFalse((data / "tls.enabled").exists())

    def test_windows_activation_requires_existing_scoped_lan_listener(self):
        import typer

        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            stack = SimpleNamespace(
                installation=SimpleNamespace(data_directory=data, runtime_type="wsl2"),
                platform=SimpleNamespace(is_admin=lambda: True),
                runtime=SimpleNamespace(docker_engine_running=lambda: True),
                compose=Mock(),
            )
            with (
                patch.object(tls, "get_stack", return_value=stack),
                patch.object(tls, "guard_pending_update"),
                patch.object(tls, "banner"),
            ):
                with self.assertRaises(typer.Exit):
                    tls.tls(dry_run=False, renew=False)
            stack.compose._run_compose_command.assert_not_called()

    def test_conflicting_flags_are_rejected_before_docker_start(self):
        import typer

        with patch.object(tls, "get_stack") as get_stack, patch.object(tls, "banner"):
            with self.assertRaises(typer.Exit):
                tls.tls(dry_run=True, renew=True)
            get_stack.assert_not_called()

    def test_issuance_profile_is_separate_from_autostart_renewer(self):
        compose_text = (
            Path(__file__).resolve().parents[2] / "compose.yaml"
        ).read_text(encoding="utf-8")
        issuer = compose_text.split("\n  certbot:\n", 1)[1]
        renewal = compose_text.split("\n  certbot-renew:\n", 1)[1].split("\n  certbot:\n", 1)[0]
        self.assertIn('profiles: ["tls-issue"]', issuer)
        self.assertIn('profiles: ["tls"]', renewal)

    def test_remove_lan_tears_down_owned_https_forwarding(self):
        source = (
            Path(__file__).resolve().parents[1] / "src" / "weave_cli"
            / "commands" / "lan.py"
        ).read_text(encoding="utf-8")
        self.assertIn('reconcile(data, remove=True)', source)
