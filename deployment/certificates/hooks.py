#!/usr/bin/env python3
"""ACME DNS-01 adapter. Certbot owns keys; WEAVE owns Bunny TXT records.

This runs only inside the opt-in Certbot container. The mounted installation
identity is read-only; neither the Bunny key nor the exam database is mounted.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

IDENTITY = Path("/var/lib/weave-cbt/identity/installation.json")
SNIPPET = Path("/var/lib/weave-cbt/tls-snippets/node.conf")
HOSTNAME_PATTERN = re.compile(
    r"[a-z0-9-]+\.[a-z0-9-]+\.cbt(?:-staging)?\.weavecloudspace\.com\Z"
)


def _identity() -> dict:
    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    hostname = identity.get("hostname")
    if not isinstance(hostname, str) or not HOSTNAME_PATTERN.fullmatch(hostname):
        raise RuntimeError("Pair with current WEAVE Cloud and refresh the CBT hostname first")
    if not isinstance(identity.get("server_credential"), str):
        raise RuntimeError("CBT machine credential is missing")
    return identity


def _call(method: str, path: str, *, payload: dict | None = None) -> dict:
    identity = _identity()
    base = os.environ["WEAVE_API_BASE_URL"].rstrip("/")
    if not base.startswith("https://"):
        raise RuntimeError("Certificate issuance requires an HTTPS WEAVE Cloud URL")
    request = urllib.request.Request(
        url=base + path,
        method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Authorization": "Bearer " + identity["server_credential"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("WEAVE certificate verification request failed") from None


def _await_dns(name: str, validation: str) -> None:
    # Query two independent public recursive resolvers via HTTPS, never a LAN
    # resolver that may override this hostname to its private school IP.
    providers = (
        "https://dns.google/resolve?",
        "https://cloudflare-dns.com/dns-query?",
    )
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        ok = False
        for base in providers:
            url = base + urllib.parse.urlencode({"name": name, "type": "TXT"})
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
                with urllib.request.urlopen(req, timeout=8) as response:
                    data = json.load(response)
                answers = data.get("Answer", [])
                if any(
                    item.get("type") == 16
                    and item.get("data", "").strip('"') == validation
                    for item in answers
                ):
                    ok = True
                    break
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                continue
        if ok:
            return
        time.sleep(5)
    raise RuntimeError("Public DNS verification record did not propagate in time")


def auth() -> None:
    identity = _identity()
    domain = os.environ.get("CERTBOT_DOMAIN")
    validation = os.environ.get("CERTBOT_VALIDATION", "")
    if domain != identity["hostname"] or not re.fullmatch(r"[A-Za-z0-9_-]{43}", validation):
        raise RuntimeError("Certbot challenge is not for this paired CBT server")
    request_id = str(uuid.uuid4())
    result = _call(
        "POST",
        "/api/v1/cbt/certificates/dns-challenges",
        payload={"request_id": request_id, "value": validation},
    )
    if result.get("hostname") != domain or result.get("fqdn") != "_acme-challenge." + domain:
        raise RuntimeError("WEAVE challenge response does not match the paired hostname")
    challenge_id = str(uuid.UUID(result["id"]))
    _await_dns(result["fqdn"], validation)
    # Certbot forwards stdout to CERTBOT_AUTH_OUTPUT for the cleanup hook.
    print(challenge_id)


def cleanup() -> None:
    identity = _identity()
    if os.environ.get("CERTBOT_DOMAIN") != identity["hostname"]:
        raise RuntimeError("Unexpected cleanup hostname")
    identifier = os.environ.get("CERTBOT_AUTH_OUTPUT", "").strip()
    try:
        challenge_id = uuid.UUID(identifier)
    except ValueError:
        return
    _call("DELETE", f"/api/v1/cbt/certificates/dns-challenges/{challenge_id}")


def _write_nginx(hostname: str) -> None:
    # Certificate files are in a volume shared read-only with Nginx.
    content = f"""# Generated for the WEAVE-paired CBT hostname.
server {{
    listen 80 default_server;
    server_name {hostname};
    return 308 https://{hostname}$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {hostname};
    ssl_certificate /etc/letsencrypt/live/weave-cbt-node/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/weave-cbt-node/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    client_max_body_size 10m;
    location / {{
        proxy_pass http://weave_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $weave_connection_upgrade;
        proxy_connect_timeout 5s;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }}
}}
"""
    SNIPPET.parent.mkdir(parents=True, exist_ok=True)
    candidate = SNIPPET.with_suffix(".tmp")
    candidate.write_text(content, encoding="utf-8")
    candidate.replace(SNIPPET)


def issue() -> None:
    hostname = _identity()["hostname"]
    args = [
        "certbot", "certonly", "--manual", "--non-interactive",
        "--agree-tos", "--register-unsafely-without-email",
        "--preferred-challenges", "dns",
        "--manual-auth-hook", "python3 /opt/weave/hooks.py auth",
        "--manual-cleanup-hook", "python3 /opt/weave/hooks.py cleanup",
        "--cert-name", "weave-cbt-node", "-d", hostname,
    ]
    if os.environ.get("WEAVE_ACME_DRY_RUN") == "true":
        args.append("--dry-run")
    result = subprocess.run(args, check=False)
    if result.returncode:
        raise RuntimeError("Let's Encrypt certificate issuance failed")
    if os.environ.get("WEAVE_ACME_DRY_RUN") != "true":
        _write_nginx(hostname)
        print("HTTPS certificate provisioned; reload Nginx to activate")


def renew() -> None:
    result = subprocess.run(["certbot", "renew", "--non-interactive", "--quiet"], check=False)
    if result.returncode:
        raise RuntimeError("Certificate renewal failed")


if __name__ == "__main__":
    try:
        command = sys.argv[1]
        commands = {"auth": auth, "cleanup": cleanup, "issue": issue, "renew": renew}
        if command not in commands:
            raise RuntimeError("Unknown certificate operation")
        commands[command]()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        # Do not emit cloud response bodies, authorization tokens, or TXT values.
        sys.stderr.write(f"WEAVE CBT certificate operation failed: {str(exc)}\n")
        sys.exit(1)
