"""Contract tests for cross-platform releases and manual production promotion."""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci-cd.yml"


class ReleaseWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_only_staging_and_master_can_publish(self):
        self.assertIn("github.ref == 'refs/heads/staging'", self.workflow)
        self.assertIn("github.ref == 'refs/heads/master'", self.workflow)
        self.assertNotIn("github.ref == 'refs/heads/implementing-services'", self.workflow)

    def test_explicit_master_production_approval(self):
        self.assertIn("approve_production:", self.workflow)
        self.assertIn("inputs.approve_production == true", self.workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.workflow)

    def test_compilation_overlaps_image_build(self):
        self.assertIn("  compile-cli:", self.workflow)
        self.assertIn("    needs: [image, compile-cli]", self.workflow)
        self.assertIn("compiled-cli-${{ runner.os }}", self.workflow)

    def test_anonymous_image_check_before_installer_release(self):
        self.assertIn('DOCKER_CONFIG="$anonymous_config" docker manifest inspect', self.workflow)


if __name__ == "__main__":
    unittest.main()
