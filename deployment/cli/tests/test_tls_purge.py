"""Purge validation must detect stale TLS volumes before any new install."""

import unittest
from unittest.mock import Mock

from weave_cli.commands.purge_safety import PurgeSafetyError, verify_purged_resources


def result(*, stdout: str = "", successful: bool = True):
    value = Mock()
    value.stdout = stdout
    value.successful = successful
    return value


class TlsPurgeSafetyTests(unittest.TestCase):
    def test_clean_purge_allows_new_install(self):
        runtime = Mock()
        runtime.run_docker_command.side_effect = [result(), result(), result()]
        verify_purged_resources(runtime)
        self.assertEqual(runtime.run_docker_command.call_count, 3)

    def test_stale_tls_certificate_volume_blocks_reset_without_deletion(self):
        runtime = Mock()
        runtime.run_docker_command.side_effect = [
            result(), result(), result(stdout="other_volume\nweave-cbt_tls_certificates\n"),
        ]
        with self.assertRaisesRegex(PurgeSafetyError, "tls_certificates"):
            verify_purged_resources(runtime)
        self.assertNotIn("rm", str(runtime.run_docker_command.call_args_list))

    def test_stale_tls_snippet_volume_blocks_reset(self):
        runtime = Mock()
        runtime.run_docker_command.side_effect = [
            result(), result(), result(stdout="weave-cbt_tls_snippets\n"),
        ]
        with self.assertRaisesRegex(PurgeSafetyError, "tls_snippets"):
            verify_purged_resources(runtime)

    def test_unrelated_volume_never_blocks_reset(self):
        runtime = Mock()
        runtime.run_docker_command.side_effect = [
            result(), result(), result(stdout="other_school_tls_certificates\n"),
        ]
        verify_purged_resources(runtime)

    def test_stale_project_resources_block_without_scanning_unlabeled_names(self):
        runtime = Mock()
        runtime.run_docker_command.side_effect = [result(stdout="old-api-container\n")]
        with self.assertRaisesRegex(PurgeSafetyError, "containers remain"):
            verify_purged_resources(runtime)
        self.assertEqual(runtime.run_docker_command.call_count, 1)

    def test_docker_query_failure_fails_closed(self):
        runtime = Mock()
        runtime.run_docker_command.side_effect = [result(successful=False)]
        with self.assertRaisesRegex(PurgeSafetyError, "Cannot verify"):
            verify_purged_resources(runtime)


if __name__ == "__main__":
    unittest.main()
