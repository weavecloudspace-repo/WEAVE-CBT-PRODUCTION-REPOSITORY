"""Prevent a first-run Docker volume copy-up race among CBT API replicas."""
import unittest
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"


class ComposeVolumeBootstrapTests(unittest.TestCase):
    def test_single_bootstrap_populates_shared_volume_before_api_and_worker(self):
        source = COMPOSE.read_text(encoding="utf-8")
        bootstrap = source.split("\n  bootstrap:\n", 1)[1].split("\n  api:\n", 1)[0]
        api = source.split("\n  api:\n", 1)[1].split("\n  worker:\n", 1)[0]
        worker = source.split("\n  worker:\n", 1)[1].split("\n  nginx:\n", 1)[0]
        volume = "- weave_data:/var/lib/weave-cbt"
        for name, service in (("bootstrap", bootstrap), ("api", api), ("worker", worker)):
            with self.subTest(service=name):
                self.assertIn(volume, service)
        self.assertIn("condition: service_completed_successfully", api)
        self.assertIn("condition: service_completed_successfully", worker)


if __name__ == "__main__":
    unittest.main()
