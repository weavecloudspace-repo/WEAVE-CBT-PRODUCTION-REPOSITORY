"""Regression tests for the network update bootstrap and opt-in public tunnel."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
import typer

from weave_cli.networking import state
from weave_cli.networking import deployment
from weave_cli.commands import network_ngrok


class PolicyMigrationTests(unittest.TestCase):
    def test_legacy_nat_is_preserved_without_inventing_profile_trust(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "lan.json").write_text(json.dumps({
                "listen_address": "192.168.1.44",
                "client_subnet": "192.168.1.0/24",
                "wsl_address": "172.19.2.3",
            }), encoding="utf-8")
            imported = state.load_or_import(directory, runtime_type="wsl2")
            self.assertEqual(imported["transport"], "nat")
            self.assertEqual(imported["address"], "192.168.1.44")
            self.assertIsNone(imported["interface_guid"])
            self.assertFalse(imported["restore_private"])
            self.assertFalse(imported["remote_enabled"])
            self.assertEqual(state.load(directory), imported)

    def test_existing_policy_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            original = state.load_or_import(directory, runtime_type="wsl2")
            original["remote_enabled"] = True
            state.save(directory, original)
            self.assertTrue(state.load_or_import(directory, runtime_type="wsl2")["remote_enabled"])

    def test_invalid_legacy_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "lan.json").write_text("{broken")
            with self.assertRaises(state.NetworkPolicyError):
                state.load_or_import(directory, runtime_type="wsl2")


class DeploymentUpgradeTests(unittest.TestCase):
    def make_stack(self, root):
        directory = Path(root)
        install, data, assets = directory / "installed", directory / "data", directory / "package"
        install.mkdir()
        data.mkdir()
        assets.mkdir()
        for relative in deployment.ASSETS:
            old, new = install / relative, assets / relative
            old.parent.mkdir(parents=True, exist_ok=True)
            new.parent.mkdir(parents=True, exist_ok=True)
            old.write_text("old:" + relative)
            new.write_text("new:" + relative)
        compose = MagicMock()
        compose.config.return_value = None
        compose.start.return_value = None
        stack = SimpleNamespace(
            installation=SimpleNamespace(
                install_directory=install, data_directory=data, runtime_type="wsl2"
            ),
            platform=SimpleNamespace(is_admin=lambda: True),
            compose=compose,
            runtime=MagicMock(),
        )
        return stack, assets

    def test_first_start_changes_assets_without_reinstalling_database(self):
        with tempfile.TemporaryDirectory() as root:
            stack, assets = self.make_stack(root)
            with patch("weave_cli.commands.install._assets_root", return_value=assets), \
                 patch("weave_cli.commands.install._read_release_manifest",
                       return_value={"version": "2.0.0"}), \
                 patch("weave_cli.commands.install._verify_started_stack"):
                self.assertTrue(deployment.apply(stack))
                stack.compose.start.assert_called_once()
                self.assertTrue((stack.installation.data_directory / deployment.RECORD).is_file())
                self.assertFalse((stack.installation.data_directory / deployment.JOURNAL).exists())
                self.assertFalse(deployment.apply(stack))
                stack.compose.start.assert_called_once()

    def test_failed_compose_validation_restores_old_assets(self):
        with tempfile.TemporaryDirectory() as root:
            stack, assets = self.make_stack(root)
            stack.compose.config.side_effect = [RuntimeError("invalid YAML"), None]
            with patch("weave_cli.commands.install._assets_root", return_value=assets), \
                 patch("weave_cli.commands.install._read_release_manifest",
                       return_value={"version": "2.0.0"}):
                with self.assertRaises(RuntimeError):
                    deployment.ensure_current(stack)
            for relative in deployment.ASSETS:
                self.assertEqual(
                    (stack.installation.install_directory / relative).read_text(),
                    "old:" + relative,
                )
            self.assertFalse((stack.installation.data_directory / deployment.JOURNAL).exists())


class NgrokOptInTests(unittest.TestCase):
    def test_default_policy_does_not_start_optional_container(self):
        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            policy = state.load_or_import(data, runtime_type="wsl2")
            stack = SimpleNamespace(installation=SimpleNamespace(
                data_directory=data, install_directory=data, runtime_type="wsl2"
            ))
            with patch.object(network_ngrok, "_compose") as run:
                network_ngrok.reconcile(stack)
            run.assert_not_called()
            self.assertFalse(policy["remote_enabled"])

    def test_disabled_profile_and_internal_nginx_origin(self):
        root = Path(__file__).resolve().parents[2]
        compose = (root / "compose.yaml").read_text()
        nginx = (root / "nginx" / "nginx.conf").read_text()
        self.assertIn('profiles: ["remote-access"]', compose)
        self.assertIn("http://nginx:8080", compose)
        self.assertNotIn('"8080:8080"', compose)
        self.assertIn("listen 8080;", nginx)
        self.assertIn("proxy_pass http://weave_api;", nginx)


class StartIntegrationTests(unittest.TestCase):
    def test_healthy_server_applies_new_manager_assets_before_early_return(self):
        from weave_cli.commands import start
        stack = MagicMock()
        stack.runtime.docker_engine_running.return_value = True
        with patch.object(start, "get_stack", return_value=stack), \
             patch.object(start, "guard_pending_update"), \
             patch.object(start, "upgrade_deployment") as upgrade, \
             patch.object(start, "_snapshot", return_value={"running": True}) as snapshot, \
             patch.object(start, "reconcile_access"):
            app = typer.Typer()
            start.register(app)
            result = CliRunner().invoke(app, [])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(upgrade.called)
            self.assertTrue(snapshot.called)
            self.assertTrue(stack.platform.ensure_runtime_persistence.called)


if __name__ == "__main__":
    unittest.main()
