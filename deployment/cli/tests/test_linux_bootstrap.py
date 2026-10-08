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
        cls.raw_script = BOOTSTRAP_PATH.read_bytes()
        cls.script = cls.raw_script.decode("utf-8")

    def test_uses_unix_line_endings(self):
        self.assertNotIn(b"\r\n", self.raw_script)

    def test_requires_root_systemd_and_host_commands(self):
        self.assertIn("WEAVE CBT bootstrap must be run as root.", self.script)
        self.assertIn("systemd must be PID 1.", self.script)
        self.assertIn("Checking required host commands.", self.script)

    def test_supports_only_explicit_apt_distributions(self):
        self.assertIn("ubuntu)", self.script)
        self.assertIn("debian)", self.script)
        self.assertIn("Unsupported Linux distribution", self.script)

    def test_uses_docker_official_repository_with_resilience(self):
        self.assertIn(
            "https://download.docker.com/linux/$DOCKER_REPOSITORY_DISTRO",
            self.script,
        )
        self.assertIn("DPkg::Lock::Timeout=120", self.script)
        self.assertIn("Acquire::Retries=3", self.script)
        self.assertIn("--retry 5", self.script)
        self.assertIn("docker-ce candidate", self.script)
        self.assertIn(
            "Resetting existing Docker apt source before repository bootstrap.",
            self.script,
        )

    def test_checks_complete_docker_package_set(self):
        for package in (
            "docker-ce",
            "docker-ce-cli",
            "containerd.io",
            "docker-buildx-plugin",
            "docker-compose-plugin",
        ):
            self.assertIn(package, self.script)

    def test_enables_and_verifies_services_with_diagnostics(self):
        self.assertIn("systemctl enable docker.service", self.script)
        self.assertIn("systemctl start docker.service", self.script)
        self.assertIn("systemctl is-active --quiet docker.service", self.script)
        self.assertIn("journalctl -u", self.script)
        self.assertIn("docker info", self.script)
        self.assertIn("docker compose version", self.script)

    def test_download_watchdog_separates_download_and_install(self):
        self.assertIn("WEAVE_DOWNLOAD_STALL_SECONDS=120", self.script)
        self.assertIn("WEAVE_DOWNLOAD_MAX_ATTEMPTS=3", self.script)
        self.assertIn("apt_cache_bytes()", self.script)
        self.assertIn("setsid", self.script)
        self.assertIn("stop_apt_download", self.script)
        self.assertIn("--download-only install -y", self.script)
        self.assertIn("--no-download install -y", self.script)
        self.assertIn("completed cached packages are preserved", self.script)

    def test_writes_runtime_marker(self):
        self.assertIn("/etc/weave-cbt-runtime", self.script)
        self.assertIn("runtime_type=linux", self.script)
        self.assertIn("runtime_name=native", self.script)
        self.assertIn("distribution_version=%s", self.script)
        self.assertIn("architecture=%s", self.script)


if __name__ == "__main__":
    unittest.main()
