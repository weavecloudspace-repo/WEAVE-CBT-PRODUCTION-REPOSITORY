"""Verify channel metadata and generated runtime configuration without Docker."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from weave_cli.commands.install import InstallError, _prepare_environment, _read_environment, _read_release_manifest

IMAGE = "ghcr.io/weavecloudspace-repo/weave-cbt-production-repository@sha256:" + "a" * 64


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.assets = Path(self.tmp.name) / "assets"
        self.assets.mkdir()
        self.data = Path(self.tmp.name) / "data"
        self.manifest = {
            "channel": "staging",
            "manager_version": "1.0.1",
            "cbt_image": IMAGE,
            "weave_api_base_url": "https://weave-staging-api-staging.up.railway.app",
            "ubuntu": {
                "download_url": "https://cloud-images.ubuntu.com/wsl/releases/noble/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz",
                "sha256": "2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934",
            },
        }

    def write_manifest(self):
        (self.assets / "release-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_valid_manifest(self):
        self.write_manifest()
        self.assertEqual(_read_release_manifest(self.assets)["channel"], "staging")

    def test_wrong_digest_rejected(self):
        self.manifest["cbt_image"] = IMAGE[:-1]
        self.write_manifest()
        with self.assertRaises(InstallError):
            _read_release_manifest(self.assets)

    def test_untrusted_ubuntu_domain_rejected(self):
        self.manifest["ubuntu"]["download_url"] = "https://cloud-images.ubuntu.com.attacker.example/archive.tar.gz"
        self.write_manifest()
        with self.assertRaises(InstallError):
            _read_release_manifest(self.assets)

    def test_bad_ubuntu_digest_rejected(self):
        self.manifest["ubuntu"]["sha256"] = "0" * 63
        self.write_manifest()
        with self.assertRaises(InstallError):
            _read_release_manifest(self.assets)

    def test_insecure_api_rejected(self):
        self.manifest["weave_api_base_url"] = "http://staging.example.test"
        self.write_manifest()
        with self.assertRaises(InstallError):
            _read_release_manifest(self.assets)

    @unittest.skipIf(os.name == "nt", "POSIX permission assertions")
    def test_config_preserves_secret_across_restarts(self):
        self.write_manifest()
        release = _read_release_manifest(self.assets)
        path = _prepare_environment(self.data, release)
        values = _read_environment(path)
        self.assertEqual(values["WEAVE_API_BASE_URL"], release["api"])
        self.assertEqual(values["WEAVE_IMAGE"], IMAGE)
        self.assertEqual(values["ENVIRONMENT"], "stg")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        original = path.read_bytes()
        self.assertEqual(_prepare_environment(self.data, release).read_bytes(), original)
        release["image"] = IMAGE[:-1] + "b"
        with self.assertRaises(InstallError):
            _prepare_environment(self.data, release)


if __name__ == "__main__":
    unittest.main()
