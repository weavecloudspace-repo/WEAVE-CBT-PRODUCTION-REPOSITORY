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
        self.assertIn("    needs: [image, compile-cli, compile-gui]", self.workflow)
        self.assertIn("  compile-gui:", self.workflow)
        self.assertIn("compiled-cli-${{ runner.os }}", self.workflow)

    def test_master_maps_to_production_for_installers_and_release(self):
        # make_manifest accepts 'staging' or 'production', never 'master'.
        mapping = "CHANNEL: ${{ github.ref_name == 'master' && 'production' || 'staging' }}"
        self.assertEqual(self.workflow.count(mapping), 4)
        self.assertNotIn("CHANNEL: ${{ github.ref_name }}", self.workflow.split("  package:", 1)[1])

    def test_packaging_does_not_upload_nuitka_build_directories(self):
        # Nuitka writes setup.build/setup.dist beside the finished EXE.
        self.assertIn("path: dist/*.exe", self.workflow)
        self.assertIn("dist/*.tar.gz", self.workflow)
        self.assertIn("dist/*.deb", self.workflow)
        self.assertNotIn("path: dist/*\n", self.workflow)

    def test_release_checksums_only_real_installer_files(self):
        self.assertIn('sha256sum -- *.exe *.tar.gz *.deb > SHA256SUMS', self.workflow)
        self.assertNotIn('sha256sum * > SHA256SUMS', self.workflow)
        self.assertIn('if [ ! -f "$entry" ]', self.workflow)
        self.assertIn('gh release create "$TAG" "${windows[@]}" "${linux[@]}" "${debs[@]}" dist/SHA256SUMS', self.workflow)

    def test_packaging_and_publication_execute_after_only_their_real_dependencies(self):
        self.assertIn("needs.image.result == 'success'", self.workflow)
        self.assertIn("needs.compile-cli.result == 'success'", self.workflow)
        self.assertIn("needs.compile-gui.result == 'success'", self.workflow)
        self.assertIn("needs.package.result == 'success'", self.workflow)
        self.assertIn("always() &&", self.workflow)

    def test_windows_wizard_and_linux_package_have_real_install_smoke_tests(self):
        self.assertIn("deployment/packaging/windows/desktop.iss", self.workflow)
        self.assertIn("Build one-file Windows graphical setup wizard", self.workflow)
        self.assertIn("Smoke test Windows wizard installation and bundled manager", self.workflow)
        self.assertIn("sudo apt-get install -y", self.workflow)
        self.assertIn("QT_QPA_PLATFORM=offscreen /usr/bin/weave-cbt-desktop --smoke-test", self.workflow)

    def test_anonymous_image_check_before_installer_release(self):
        self.assertIn('DOCKER_CONFIG="$anonymous_config" docker manifest inspect', self.workflow)


if __name__ == "__main__":
    unittest.main()
