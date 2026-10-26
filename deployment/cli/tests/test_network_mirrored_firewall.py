"""Host-safe regression tests for mirrored Windows and WSL firewall ownership."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weave_cli.commands import network_mirrored as mirror
from weave_cli.commands import network_mode, network_runtime

IP = "192.168.1.44"
SUBNET = "192.168.1.0/24"
GUID = "{4DAE214D-2B4A-45D1-8E23-0B55633209F3}"


def approved():
    return {
        "transport": "mirrored", "address": IP, "subnet": SUBNET,
        "interface_name": "Ethernet", "interface_guid": GUID,
        "restore_private": True,
    }


def stack(directory):
    return SimpleNamespace(
        installation=SimpleNamespace(runtime_type="wsl2", data_directory=directory),
        platform=SimpleNamespace(is_admin=lambda: True),
    )


def windows():
    return {
        "Direction": "Inbound", "Action": "Allow", "Enabled": "True",
        "Protocol": "TCP", "Profile": "Private, Domain",
        "Ports": ["80", "443"], "Local": [IP], "Remote": ["192.168.1.0/255.255.255.0"],
        "Interface": ["Ethernet"],
    }


def hyperv(remote=None):
    return {
        "Direction": "Inbound", "Action": "Allow", "Enabled": "True",
        "Protocol": "TCP", "Creator": mirror.WSL_GUID,
        "Ports": ["80", "443"], "Remote": remote or [SUBNET],
    }


class MirroredFirewallTests(unittest.TestCase):
    def test_real_wsl_guid_and_no_global_allow_defaults(self):
        self.assertEqual(mirror.WSL_GUID, "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}")
        self.assertEqual(mirror.WINDOWS_RULE, "WEAVE-CBT-MIRRORED-LAN")
        self.assertEqual(mirror.HYPERV_RULE, "WEAVE-CBT-MIRRORED")

    def test_rejects_untrusted_school_adapter_before_touching_firewall(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = approved()
            state["restore_private"] = False
            with patch.object(mirror.sys, "platform", "win32"), \
                 patch.object(mirror, "_snapshot") as snapshot:
                with self.assertRaisesRegex(mirror.MirroredFirewallError, "Approve"):
                    mirror.configure(stack(Path(tmp)), state)
                snapshot.assert_not_called()

    def test_rejects_changed_interface_identity_before_rule_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mirror.sys, "platform", "win32"), \
                 patch("weave_cli.commands.network_prefer._candidate", return_value={
                     "name": "Ethernet", "address": IP, "network": SUBNET,
                     "guid": "unexpected", "category": "Private"
                 }), patch.object(mirror, "_snapshot") as snapshot:
                with self.assertRaisesRegex(mirror.MirroredFirewallError, "identity"):
                    mirror.configure(stack(Path(tmp)), approved())
                snapshot.assert_not_called()

    def test_windows_rule_must_match_ip_ports_remote_subnet_and_profile(self):
        bad = windows()
        bad["Remote"] = ["Any"]
        with patch.object(mirror, "_snapshot", return_value={"windows": bad, "hyperv": hyperv()}):
            with self.assertRaisesRegex(mirror.MirroredFirewallError, "unsafe scope"):
                mirror.verify(IP, SUBNET)
        bad = windows()
        bad["Profile"] = "Public"
        with patch.object(mirror, "_snapshot", return_value={"windows": bad, "hyperv": hyperv()}):
            with self.assertRaises(mirror.MirroredFirewallError):
                mirror.verify(IP, SUBNET)

    def test_hyperv_wrong_creator_refuses_to_touch_foreign_rule(self):
        bad = hyperv()
        bad["Creator"] = "{40E0AC32-46A5-43A1-A68E-17B7C1D4C7D1}"
        with patch.object(mirror, "_snapshot", return_value={"windows": windows(), "hyperv": bad}), \
             patch.object(mirror.lan, "_powershell") as run:
            with self.assertRaisesRegex(mirror.MirroredFirewallError, "modified"):
                mirror.remove(IP, SUBNET)
            run.assert_not_called()

    def test_missing_rules_created_with_restricted_scope(self):
        empty = {"windows": None, "hyperv": None}
        ready = {"windows": windows(), "hyperv": hyperv()}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(mirror.sys, "platform", "win32"), \
             patch("weave_cli.commands.network_prefer._candidate", return_value={
                 "name": "Ethernet", "address": IP, "network": SUBNET,
                 "guid": GUID, "category": "Private",
             }), patch.object(mirror, "_snapshot", side_effect=[empty, ready]), \
             patch.object(mirror.lan, "_powershell") as run:
            mirror.configure(stack(Path(tmp)), approved())
            self.assertEqual(run.call_count, 2)
            commands = "\n".join(call.args[0] for call in run.call_args_list)
            self.assertIn("-VMCreatorId '" + mirror.WSL_GUID + "'", commands)
            self.assertIn("-RemoteAddresses '" + SUBNET + "'", commands)
            self.assertIn("-RemoteAddress '" + SUBNET + "'", commands)
            self.assertIn("-InterfaceAlias 'Ethernet'", commands)
            self.assertNotIn("DefaultInboundAction Allow", commands)

    def test_legacy_hyperv_unrestricted_remote_is_narrowed_not_recreated(self):
        legacy = {"windows": windows(), "hyperv": hyperv(["Any"])}
        ready = {"windows": windows(), "hyperv": hyperv()}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(mirror.sys, "platform", "win32"), \
             patch("weave_cli.commands.network_prefer._candidate", return_value={
                 "name": "Ethernet", "address": IP, "network": SUBNET,
                 "guid": GUID, "category": "Private",
             }), patch.object(mirror, "_snapshot", side_effect=[legacy, ready]), \
             patch.object(mirror.lan, "_powershell") as run:
            mirror.configure(stack(Path(tmp)), approved())
            run.assert_called_once()
            self.assertIn("Set-NetFirewallHyperVRule", run.call_args.args[0])
            self.assertIn("-RemoteAddresses '" + SUBNET + "'", run.call_args.args[0])

    def test_remove_checks_ownership_then_removes_only_two_weave_rules(self):
        ready = {"windows": windows(), "hyperv": hyperv()}
        empty = {"windows": None, "hyperv": None}
        with patch.object(mirror, "_snapshot", side_effect=[ready, empty]), \
             patch.object(mirror.lan, "_powershell") as run:
            mirror.remove(IP, SUBNET)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all("WEAVE-CBT-MIRRORED" in c.args[0] for c in run.call_args_list))

    def test_startup_and_boot_both_reconcile_mirrored(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = stack(Path(tmp))
            state = approved()
            with patch.object(network_runtime, "load_or_import", return_value=state), \
                 patch("weave_cli.commands.network_prefer.restore"), \
                 patch("weave_cli.commands.network_ngrok.reconcile"), \
                 patch.object(network_runtime, "_reconcile_mirrored_firewall") as owned, \
                 patch.object(network_runtime, "upgrade_deployment"), \
                 patch("weave_cli.commands.network._startup_reconcile") as nat:
                network_runtime.reconcile_access(st)
                network_runtime.reconcile(st)
                self.assertEqual(owned.call_count, 2)
                nat.assert_not_called()

    def test_owned_wsl_config_restores_only_when_content_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            user_config = data / ".wslconfig"
            original = b"[wsl2]\nnetworkingMode=nat\n"
            user_config.write_bytes(network_mode.edit_config(original.decode(), "mirrored").encode("utf-8"))
            (data / network_mode.OWNER).write_text(json.dumps({
                "target": "mirrored",
                "original": base64.b64encode(original).decode("ascii"),
                "original_exists": True,
            }))
            with patch.object(network_mode, "_config", return_value=user_config):
                self.assertTrue(network_mode.restore_owned_wsl_config(stack(data), check_only=True))
                self.assertTrue(network_mode.restore_owned_wsl_config(stack(data)))
                self.assertEqual(user_config.read_bytes(), original)
                self.assertFalse((data / network_mode.OWNER).exists())

    def test_modified_wsl_config_is_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            user_config = data / ".wslconfig"
            user_config.write_text("[wsl2]\nnetworkingMode=mirrored\nprocessors=6\n")
            (data / network_mode.OWNER).write_text(json.dumps({
                "target": "mirrored",
                "original": base64.b64encode(b"[wsl2]\nnetworkingMode=nat\n").decode("ascii"),
                "original_exists": True,
            }))
            with patch.object(network_mode, "_config", return_value=user_config):
                with self.assertRaises(network_mode.ModeError):
                    network_mode.restore_owned_wsl_config(stack(data))
            self.assertTrue((data / network_mode.OWNER).exists())


    def test_orphan_wrong_guid_is_removed_only_after_correct_rule_verified(self):
        wrong = {
            "Direction": "Inbound", "Action": "Allow", "Enabled": "True",
            "Protocol": "TCP", "Creator": mirror.LEGACY_WRONG_GUID,
            "Ports": ["80"], "Remote": [SUBNET],
        }
        old = {"windows": windows(), "hyperv": hyperv(), "orphan": wrong}
        ready = {"windows": windows(), "hyperv": hyperv(), "orphan": None}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(mirror, "_approved", return_value=(IP, SUBNET, "Ethernet")), \
             patch.object(mirror, "_snapshot", side_effect=[old, old, ready]), \
             patch.object(mirror.lan, "_powershell") as run:
            mirror.configure(stack(Path(tmp)), approved())
            run.assert_called_once()
            self.assertIn("Remove-NetFirewallHyperVRule", run.call_args.args[0])
            self.assertIn(mirror.LEGACY_WRONG_RULE, run.call_args.args[0])

    def test_wrong_guid_orphan_with_unexpected_scope_is_not_removed(self):
        wrong = {
            "Direction": "Inbound", "Action": "Allow", "Enabled": "True",
            "Protocol": "TCP", "Creator": mirror.LEGACY_WRONG_GUID,
            "Ports": ["80"], "Remote": ["Any"],
        }
        with patch.object(mirror, "_snapshot", return_value={
            "windows": windows(), "hyperv": hyperv(), "orphan": wrong,
        }), patch.object(mirror.lan, "_powershell") as run:
            with self.assertRaisesRegex(mirror.MirroredFirewallError, "legacy"):
                mirror.remove(IP, SUBNET)
            run.assert_not_called()

    def test_mirrored_purge_preflights_before_removing_firewall(self):
        from weave_cli.commands import purge_cleanup
        from weave_cli.networking import state
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            policy = state.load_or_import(directory, runtime_type="wsl2")
            policy.update(approved())
            state.save(directory, policy)
            st = stack(directory)
            with patch.object(purge_cleanup.sys, "platform", "win32"), \
                 patch.object(purge_cleanup.lan, "_read_state", return_value=None), \
                 patch.object(purge_cleanup, "_windows_unowned_resources"), \
                 patch.object(mirror, "verify") as verified, \
                 patch.object(network_mode, "restore_owned_wsl_config", return_value=True) as restore:
                snapshot = purge_cleanup.preflight(st)
            self.assertTrue(snapshot.mirrored)
            verified.assert_called_once_with(IP, SUBNET)
            restore.assert_called_once_with(st, check_only=True)

            with patch.object(purge_cleanup.sys, "platform", "win32"), \
                 patch("weave_cli.commands.network_ngrok.remove"), \
                 patch.object(purge_cleanup, "remove_if_configured"), \
                 patch.object(mirror, "remove") as remove, \
                 patch.object(network_mode, "restore_owned_wsl_config") as restore:
                purge_cleanup.cleanup_host(st)
            remove.assert_called_once_with(IP, SUBNET)
            restore.assert_called_once_with(st)

            with patch.object(purge_cleanup.sys, "platform", "win32"), \
                 patch.object(purge_cleanup.lan, "_firewall_exists", return_value=False), \
                 patch("weave_cli.commands.lan_tls._firewall_exists", return_value=False), \
                 patch("weave_cli.commands.network_dns._service_exists", return_value=False), \
                 patch.object(mirror, "_snapshot", return_value={
                     "windows": None, "hyperv": None, "orphan": None,
                 }):
                purge_cleanup.verify_host(st, snapshot)


if __name__ == "__main__":
    unittest.main()
