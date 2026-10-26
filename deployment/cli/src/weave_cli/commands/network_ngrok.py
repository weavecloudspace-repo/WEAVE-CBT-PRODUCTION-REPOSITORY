"""Opt-in ngrok Docker tunnel. No host ports, no CLI argument credentials."""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import typer

from weave_cli.commands._shared import error, get_stack, info, success, warning
from weave_cli.networking.state import load_or_import, save

app = typer.Typer(help="Manage optional public CBT access using Docker ngrok.")
_TOKEN = re.compile(r"^[A-Za-z0-9_.\-]{10,512}$")
_PROFILE = "remote-access"


class NgrokError(RuntimeError):
    pass


def _config(stack) -> Path:
    return stack.installation.install_directory / "ngrok" / "ngrok.yml"


def _secure_file(path: Path, content: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise NgrokError("Unsafe ngrok configuration path.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=".ngrok-", encoding="utf-8",
            delete=False,
        ) as f:
            tmp = Path(f.name)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if os.name == "nt":
            # Inherit no broad Users/Everyone grants for the saved authtoken.
            acl = subprocess.run(
                ["icacls", str(tmp), "/inheritance:r", "/grant:r",
                 "*S-1-5-18:F", "*S-1-5-32-544:F"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            if acl.returncode:
                raise NgrokError("Could not protect ngrok credentials with Windows ACLs.")
        else:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _compose(stack, args: list[str]):
    # Always activate profile explicitly; normal WEAVE Compose startup doesn't.
    return stack.compose._run_compose_command(
        command=["--profile", _PROFILE, *args], timeout=120,
    )


def _policy(stack) -> dict:
    return load_or_import(
        stack.installation.data_directory,
        runtime_type=stack.installation.runtime_type,
    )


def _ensure_owner(stack):
    if not stack.platform.is_admin():
        raise NgrokError("Administrator privileges are required to change online access.")


def _container_state(stack) -> str:
    try:
        rows = _compose(stack, ["ps", "-a", "--format", "json", "ngrok"]).stdout.strip()
    except Exception:
        return "unavailable"
    if not rows:
        return "not-created"
    try:
        record = json.loads(rows)
        if isinstance(record, list):
            record = record[0] if record else {}
        return str(record.get("State", "unknown")).lower()
    except (ValueError, TypeError, AttributeError):
        return "unknown"


def _public_url(stack, *, attempts: int = 1) -> str | None:
    """Read the agent's local tunnel API without exposing its inspection port."""
    for attempt in range(attempts):
        for fetch in (["wget", "-qO-", "http://127.0.0.1:4040/api/tunnels"],
                      ["curl", "-fsS", "http://127.0.0.1:4040/api/tunnels"]):
            try:
                result = _compose(stack, ["exec", "-T", "ngrok", *fetch])
                payload = json.loads(result.stdout)
                urls = [
                    item.get("public_url") for item in payload.get("tunnels", [])
                    if isinstance(item, dict)
                    and isinstance(item.get("public_url"), str)
                    and item["public_url"].startswith("https://")
                ]
                if urls:
                    return urls[0]
            except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
                continue
        if attempt + 1 < attempts:
            time.sleep(2)
    return None


def _read_authtoken() -> str:
    """Use Windows' native secure prompt; getpass can lose pasted console input."""
    if os.name != "nt":
        return getpass.getpass("Ngrok agent authtoken (hidden): ")
    # The script is constant: credentials are never passed as command arguments.
    script = (
        "$s = Read-Host 'Ngrok agent authtoken (hidden)' -AsSecureString; "
        "$p = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); "
        "try { [Console]::Out.WriteLine("
        "[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)) } "
        "finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p) }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        raise NgrokError("Could not read ngrok authtoken securely from Windows console.")
    return result.stdout.rstrip("\r\n")



def _domain(value: str) -> str:
    value = value.strip().lower().removeprefix("https://").rstrip("/")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value) or not value.endswith((".ngrok-free.dev", ".ngrok-free.app", ".ngrok.app", ".ngrok.dev")) or ".." in value:
        raise NgrokError("Enter a valid ngrok-assigned static domain without a path.")
    return value


def _credentials(stack) -> tuple[str, str | None]:
    path = _config(stack)
    if not path.is_file() or path.is_symlink():
        raise NgrokError("Configure ngrok first: weave network ngrok auth.")
    lines = path.read_text(encoding="utf-8").splitlines()
    values = {}
    for line in lines:
        for key in ("authtoken", "domain"):
            if line.strip().startswith(key + ": "):
                values[key] = json.loads(line.split(": ", 1)[1])
    token = values.get("authtoken")
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise NgrokError("Saved ngrok authtoken is invalid.")
    domain = _domain(values["domain"]) if values.get("domain") else None
    return token, domain


def _configuration(token: str, domain: str | None) -> str:
    content = "version: 3\\nagent:\\n  authtoken: " + json.dumps(token) + "\\ntunnels:\\n  weave:\\n    proto: http\\n    addr: http://nginx:8080\\n"
    if domain:
        content += "    domain: " + json.dumps(domain) + "\\n"
    return content


def _ensure_tunnel_config(stack) -> None:
    """Migrate old token-only agent configuration on first startup."""
    token, domain = _credentials(stack)
    path = _config(stack)
    if "tunnels:" not in path.read_text(encoding="utf-8"):
        _secure_file(path, _configuration(token, domain))


def _staff(url: str | None) -> str | None:
    return url.rstrip("/") + "/staff" if url else None


@app.command("domain")
def ngrok_domain(value: str = typer.Argument(..., help="Ngrok-assigned static domain")) -> None:
    """Update the saved domain without changing the existing authtoken."""
    try:
        stack = get_stack()
        _ensure_owner(stack)
        token, _ = _credentials(stack)
        domain = _domain(value)
        _secure_file(_config(stack), _configuration(token, domain))
        success("Saved static ngrok domain: " + domain)
        info("Staff URL: https://" + domain + "/staff")
        if _policy(stack)["remote_enabled"] and stack.runtime.docker_engine_running():
            from weave_cli.networking.deployment import apply
            apply(stack)
            _compose(stack, ["up", "-d", "--no-deps", "--force-recreate", "ngrok"])
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("auth")
def ngrok_auth(stdin: bool = typer.Option(False, "--stdin", hidden=True)) -> None:
    """Read an authtoken via hidden input, never arguments or the Docker env."""
    try:
        stack = get_stack()
        _ensure_owner(stack)
        # The GUI uses a private QProcess stdin pipe, never a command argument.
        token = (sys.stdin.readline() if stdin else _read_authtoken()).strip()
        if not _TOKEN.fullmatch(token):
            raise NgrokError("Invalid ngrok agent authtoken format.")
        domain = _domain(typer.prompt("Ngrok-assigned static domain")) if not stdin else (_credentials(stack)[1] if _config(stack).is_file() else None)
        content = _configuration(token, domain)
        _secure_file(_config(stack), content)
        success("Ngrok agent credentials stored. Internet access remains disabled.")
        if domain:
            info("Configured staff URL: https://" + domain + "/staff")
        info("Run 'weave network ngrok enable' to expose CBT.")
    except (OSError, RuntimeError, EOFError) as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("enable")
def ngrok_enable(yes: bool = typer.Option(False, "--yes")) -> None:
    try:
        stack = get_stack()
        _ensure_owner(stack)
        config = _config(stack)
        if not config.is_file() or config.is_symlink():
            raise NgrokError("Configure ngrok first: weave network ngrok auth.")
        if not yes and not typer.confirm(
            "Expose this CBT server over the public internet?", default=False
        ):
            return
        if not stack.runtime.docker_engine_running():
            raise NgrokError("Start WEAVE Docker first.")
        from weave_cli.networking.deployment import apply
        _ensure_tunnel_config(stack)
        apply(stack)  # New manager upgrades old installed Compose on first use.
        _compose(stack, ["up", "-d", "--no-deps", "--force-recreate", "ngrok"])
        if _container_state(stack) != "running":
            raise NgrokError("Ngrok container did not reach the running state.")
        state = _policy(stack)
        state["remote_enabled"] = True
        save(stack.installation.data_directory, state)
        success("Ngrok container started; public access requested.")
        public_url = _public_url(stack, attempts=10)
        if public_url:
            info("Public CBT staff URL: " + _staff(public_url))
        else:
            warning("Ngrok public URL is not yet available; check tunnel logs and status.")
        warning("Verify public endpoint, login, redirects and access controls before an exam.")
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("disable")
def ngrok_disable(yes: bool = typer.Option(False, "--yes")) -> None:
    try:
        stack = get_stack()
        _ensure_owner(stack)
        if not yes and not typer.confirm("Disable public access?", default=False):
            return
        _compose(stack, ["stop", "ngrok"])
        state = _policy(stack)
        state["remote_enabled"] = False
        save(stack.installation.data_directory, state)
        success("Ngrok disabled. School LAN and application services are unchanged.")
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("status")
def ngrok_status() -> None:
    try:
        stack = get_stack()
        state = _policy(stack)
        typer.echo(json.dumps({
            "bundled": True,
            "authenticated": _config(stack).is_file(),
            "enabled": state["remote_enabled"],
            "container": _container_state(stack),
            "upstream": "http://nginx:8080",
            "configured_domain": _credentials(stack)[1] if _config(stack).is_file() else None,
            "public_url": _staff(_public_url(stack)) if _container_state(stack) == "running" else None,
            "public_connectivity_verified": False,
        }, indent=2))
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("logs")
def ngrok_logs() -> None:
    try:
        stack = get_stack()
        output = _compose(stack, ["logs", "--tail", "60", "ngrok"]).stdout
        # Avoid re-emitting any accidental credential in service diagnostics.
        output = re.sub(r"(?i)(authtoken\s*[:=]\s*)\S+", r"\1[REDACTED]", output)
        typer.echo(output)
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


@app.command("logout")
def ngrok_logout(yes: bool = typer.Option(False, "--yes")) -> None:
    try:
        stack = get_stack()
        _ensure_owner(stack)
        if not yes and not typer.confirm(
            "Disable ngrok and delete the stored authtoken?", default=False
        ):
            return
        _compose(stack, ["stop", "ngrok"])
        state = _policy(stack)
        state["remote_enabled"] = False
        save(stack.installation.data_directory, state)
        config = _config(stack)
        if config.is_symlink():
            raise NgrokError("Refusing to delete a linked credential file.")
        config.unlink(missing_ok=True)
        success("Ngrok credentials deleted and public tunnel stopped.")
    except Exception as exc:
        error(str(exc))
        raise typer.Exit(code=1) from exc


def reconcile(stack) -> None:
    """Restore only a previously enabled optional tunnel after WSL login."""
    if _policy(stack)["remote_enabled"]:
        if not _config(stack).is_file():
            raise NgrokError("Ngrok enabled but saved credentials are missing.")
        _ensure_tunnel_config(stack)
        if _container_state(stack) != "running":
            _compose(stack, ["up", "-d", "--no-deps", "ngrok"])


def remove(stack, *, purge: bool) -> None:
    """Stop the optional tunnel before Compose project removal."""
    # A purge/reinstall preflight may have only installation + runtime,
    # without a constructed Compose manager; build it from owned paths.
    installation = stack.installation
    compose_path = installation.install_directory / "compose.yaml"
    env_path = installation.data_directory / "runtime.env"
    if compose_path.is_file() and "  ngrok:" in compose_path.read_text(encoding="utf-8"):
        if hasattr(stack, "compose"):
            compose = stack.compose
        elif env_path.is_file() and hasattr(stack, "runtime"):
            from weave_cli.docker.compose import DockerCompose
            compose = DockerCompose(
                compose_file=compose_path,
                env_file=env_path,
                runtime=stack.runtime,
                project_name="weave-cbt",
            )
        else:
            raise NgrokError("Cannot verify optional tunnel ownership before cleanup.")
        compose._run_compose_command(
            command=["--profile", _PROFILE, "stop", "ngrok"], timeout=120,
        )
        compose._run_compose_command(
            command=["--profile", _PROFILE, "rm", "-f", "-s", "ngrok"], timeout=120,
        )
    if purge:
        config = _config(stack)
        if config.is_symlink():
            raise NgrokError("Cannot purge a linked ngrok credential.")
        config.unlink(missing_ok=True)


def register(network_app: typer.Typer) -> None:
    network_app.add_typer(app, name="ngrok")
