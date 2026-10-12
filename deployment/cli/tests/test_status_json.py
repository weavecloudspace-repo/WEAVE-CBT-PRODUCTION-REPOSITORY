"""Desktop machine-readable status contract and noninteractive update safeguards."""
import json
import unittest
from unittest.mock import patch, Mock
from weave_cli.commands import status as status_module


class StatusJsonTests(unittest.TestCase):
    def test_parse_ndjson_and_array(self):
        rows = [{"Service": "api", "State": "running"}, {"Service": "postgres", "State": "running"}]
        self.assertEqual(status_module._container_rows("\n".join(json.dumps(row) for row in rows)), rows)
        self.assertEqual(status_module._container_rows(json.dumps(rows)), rows)

    def test_snapshot_reports_stopped_docker_without_secrets(self):
        stack = Mock()
        stack.installation.installed_version = "1.0"
        stack.installation.runtime_type = "wsl2"
        stack.runtime.docker_engine_running.return_value = False
        with patch.object(status_module, "get_stack", return_value=stack):
            record = status_module._snapshot()
        self.assertFalse(record["running"])
        self.assertTrue(record["installed"])
        self.assertEqual(record["services"], [])
        self.assertNotIn("password", json.dumps(record).lower())

    def test_snapshot_reports_services_by_real_state(self):
        stack = Mock()
        stack.installation.installed_version = "1.0"
        stack.installation.runtime_type = "native"
        stack.runtime.docker_engine_running.return_value = True
        stack.runtime.docker_compose_available.return_value = True
        stack.compose._run_compose_command.return_value.stdout = json.dumps([
            {"Service": "api", "State": "running", "Health": "healthy"},
            {"Service": "postgres", "State": "exited", "Health": ""}
        ])
        with patch.object(status_module, "get_stack", return_value=stack):
            record = status_module._snapshot()
        self.assertFalse(record["running"])
        self.assertEqual(record["services"][1]["state"], "exited")


if __name__ == "__main__":
    unittest.main()
