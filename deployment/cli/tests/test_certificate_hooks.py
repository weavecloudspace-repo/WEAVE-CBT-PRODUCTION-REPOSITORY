"""Offline unit tests for the Certbot DNS-01 hook and safe Nginx activation."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4


HOOK_PATH = pathlib.Path(__file__).resolve().parents[2] / "certificates" / "hooks.py"
spec = importlib.util.spec_from_file_location("weave_certificate_hooks", HOOK_PATH)
assert spec is not None and spec.loader is not None
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


class CertificateHookTests(unittest.TestCase):
    def setUp(self):
        self.hostname = "main-lab.greenfield.cbt-staging.weavecloudspace.com"
        self.identity = {"hostname": self.hostname, "server_credential": "dummy-only"}

    def test_auth_sends_only_dns_digest_and_request_id(self):
        calls = []
        challenge_id = uuid4()

        def request(method, path, *, payload=None):
            calls.append((method, path, payload))
            return {
                "id": str(challenge_id),
                "hostname": self.hostname,
                "fqdn": "_acme-challenge." + self.hostname,
            }

        with (
            patch.dict(
                os.environ,
                {"CERTBOT_DOMAIN": self.hostname, "CERTBOT_VALIDATION": "A" * 43},
            ),
            patch.object(hooks, "_identity", return_value=self.identity),
            patch.object(hooks, "_call", side_effect=request),
            patch.object(hooks, "_await_dns") as public_dns,
            contextlib.redirect_stdout(io.StringIO()) as printed,
        ):
            hooks.auth()

        self.assertEqual(printed.getvalue().strip(), str(challenge_id))
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "/api/v1/cbt/certificates/dns-challenges")
        self.assertEqual(calls[0][2]["value"], "A" * 43)
        self.assertEqual(len(calls[0][2]), 2)
        public_dns.assert_called_once_with("_acme-challenge." + self.hostname, "A" * 43)

    def test_auth_rejects_other_domains_before_provider_call(self):
        with (
            patch.dict(os.environ, {"CERTBOT_DOMAIN": "api.weavecloudspace.com", "CERTBOT_VALIDATION": "A" * 43}),
            patch.object(hooks, "_identity", return_value=self.identity),
            patch.object(hooks, "_call") as cloud,
        ):
            with self.assertRaises(RuntimeError):
                hooks.auth()
            cloud.assert_not_called()

    def test_cleanup_uses_returned_challenge_id_only(self):
        challenge_id = uuid4()
        with (
            patch.dict(os.environ, {"CERTBOT_DOMAIN": self.hostname, "CERTBOT_AUTH_OUTPUT": str(challenge_id)}),
            patch.object(hooks, "_identity", return_value=self.identity),
            patch.object(hooks, "_call") as cloud,
        ):
            hooks.cleanup()
            cloud.assert_called_once_with(
                "DELETE", f"/api/v1/cbt/certificates/dns-challenges/{challenge_id}"
            )

    def test_issue_dry_run_does_not_install_nginx_vhost(self):
        with (
            patch.dict(os.environ, {"WEAVE_ACME_DRY_RUN": "true"}),
            patch.object(hooks, "_identity", return_value=self.identity),
            patch.object(hooks, "_write_nginx") as write,
            patch.object(hooks.subprocess, "run", return_value=Mock(returncode=0)) as run,
        ):
            hooks.issue()
            write.assert_not_called()
            self.assertIn("--dry-run", run.call_args.args[0])

    def test_nginx_snippet_has_matching_hostname_and_websocket_upgrade(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            hooks, "SNIPPET", pathlib.Path(folder) / "node.conf"
        ):
            hooks._write_nginx(self.hostname)
            config = hooks.SNIPPET.read_text(encoding="utf-8")
            self.assertIn(f"server_name {self.hostname};", config)
            self.assertIn("listen 443 ssl;", config)
            self.assertIn("proxy_set_header Upgrade $http_upgrade;", config)
            self.assertIn("ssl_certificate_key /etc/letsencrypt/live/weave-cbt-node/privkey.pem;", config)

    def test_renew_reports_nonzero_exit(self):
        with patch.object(hooks.subprocess, "run", return_value=Mock(returncode=2)):
            with self.assertRaises(RuntimeError):
                hooks.renew()
