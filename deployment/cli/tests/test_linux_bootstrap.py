from pathlib import Path
import unittest


BOOTSTRAP_PATH = (
    Path(__file__).resolve().parents[2]
    / "bootstrap"
    / "linux"
    / "bootstrap.sh"
)


class LinuxBootstrapContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = BOOTSTRAP_PATH.read_text(encoding="utf-8")

    def test_requires_root_and_systemd(self):
        self.assertIn('WEAVE CBT bootstrap must be run as root.', self.script)
        self.assertIn('systemd must be PID 1.', self.script)

    def test_supports_only_explicit_apt_distributions(self):
        self.assertIn('ubuntu)', self.script)
        self.assertIn('debian)', self.script)
        self.assertIn('Unsupported Linux distribution', self.script)

    def test_uses_docker_official_repository(self):
        self.assertIn(
            'https://download.docker.com/linux/$DOCKER_REPOSITORY_DISTRO',
            self.script,
        )
        self.assertIn('docker-ce', self.script)
        self.assertIn('docker-compose-plugin', self.script)

    def test_enables_and_verifies_docker(self):
        self.assertIn('systemctl enable docker.service', self.script)
        self.assertIn('systemctl start docker.service', self.script)
        self.assertIn('docker info', self.script)
        self.assertIn('docker compose version', self.script)

    def test_writes_runtime_marker(self):
        self.assertIn('/etc/weave-cbt-runtime', self.script)
        self.assertIn('runtime_type=linux', self.script)
        self.assertIn('runtime_name=native', self.script)


if __name__ == "__main__":
    unittest.main()
