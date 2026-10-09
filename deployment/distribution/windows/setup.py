"""Console-only self-extracting Windows WEAVE CBT CLI Manager installer."""
from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import subprocess
import tempfile
import atexit
import zipfile
import sys
from pathlib import Path
from colorama import Fore, Style, just_fix_windows_console

just_fix_windows_console()
BLUE, GREEN, RED, RESET = Fore.LIGHTBLUE_EX, Fore.LIGHTGREEN_EX, Fore.LIGHTRED_EX, Style.RESET_ALL


def output(label: str, message: str) -> None:
    tint = GREEN if label == "OK" else RED if label == "ERROR" else BLUE
    print(f"{tint}[WEAVE][{label}]{RESET} {message}", flush=True)


def admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def independent_console() -> bool:
    try:
        processes = (ctypes.c_ulong * 16)()
        return ctypes.windll.kernel32.GetConsoleProcessList(processes, 16) <= 1
    except (AttributeError, OSError):
        return False


def perform_install() -> None:
    bundle = Path(__file__).resolve().parent / "payload.zip"
    if not bundle.is_file():
        raise RuntimeError("Embedded WEAVE CBT payload.zip is missing.")
    staging = tempfile.TemporaryDirectory(prefix="weave-cbt-manager-")
    atexit.register(staging.cleanup)
    payload = Path(staging.name)
    with zipfile.ZipFile(bundle) as archive:
        for member in archive.namelist():
            # Never unpack a path that can escape the temporary directory.
            if member.startswith("/") or ".." in Path(member.replace("\\", "/")).parts:
                raise RuntimeError("Unsafe path in embedded installer payload.")
        archive.extractall(payload)
    source = payload / "weave.exe"
    assets = payload / "assets"
    if not source.is_file() or not (assets / "compose.yaml").is_file() or not (assets / "release-manifest.json").is_file():
        raise RuntimeError("Installer payload incomplete. Redownload from the official WEAVE release.")

    directory = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WeaveCBT"
    # A staging setup cannot silently replace an existing production manager.
    old_release = directory / "assets" / "release-manifest.json"
    if old_release.is_file():
        try:
            existing = json.loads(old_release.read_text(encoding="utf-8"))
            incoming = json.loads((assets / "release-manifest.json").read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise RuntimeError(f"Cannot verify existing installation channel: {exc}") from exc
        if existing.get("channel") != incoming.get("channel"):
            raise RuntimeError("Existing WEAVE CBT Manager belongs to another channel. Refusing to overwrite staging/production assets.")
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, directory / "weave.exe")
    shutil.copytree(assets, directory / "assets", dirs_exist_ok=True)
    output("OK", f"Installed WEAVE manager into {directory}")

    import winreg
    path_key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path_key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        entries = {os.path.normcase(os.path.normpath(item.strip().strip('"'))) for item in current.split(";") if item.strip()}
        if os.path.normcase(os.path.normpath(str(directory))) not in entries:
            result = (current.rstrip(";") + ";" if current else "") + str(directory)
            winreg.SetValueEx(key, "Path", 0, kind if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else winreg.REG_EXPAND_SZ, result)

    try:
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))
    except (AttributeError, OSError):
        pass
    output("OK", "Machine PATH configured.")

    check = subprocess.run([str(directory / "weave.exe"), "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=45, check=False)
    if check.returncode != 0:
        raise RuntimeError("Installed CLI did not start: " + (check.stderr or "")[-400:])
    output("OK", "CLI validation completed.")
    print(f"\n{GREEN}SETUP COMPLETED SUCCESSFULLY{RESET}\n")
    print("NEXT STEP: Open a NEW PowerShell window as Administrator and run:")
    print(f"    {BLUE}weave install{RESET}")
    print("\nWEAVE is available from any directory.")


def request_elevation_and_wait() -> int:
    # Windows PowerShell 5.1 ships with supported Windows desktops/servers.
    # Start-Process -Verb RunAs is the supported UAC path; -Wait -PassThru
    # propagates the elevated child's real exit code to the caller.
    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    command = (
        "$ErrorActionPreference = 'Stop'; "
        "try { $child = Start-Process -FilePath " + literal(sys.executable)
    )
    if len(sys.argv) > 1:
        command += " -ArgumentList " + literal(subprocess.list2cmdline(sys.argv[1:]))
    command += (
        " -Verb RunAs -Wait -PassThru; exit $child.ExitCode } "
        "catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
    )
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        check=False,
    )
    return result.returncode


def main() -> int:
    if sys.platform != "win32":
        output("ERROR", "This setup program is for Windows.")
        return 1
    print(f"\n{BLUE}WEAVE CBT CLI MANAGER SETUP{RESET}\n")
    if not admin():
        output("STEP", "Requesting Administrator elevation through Windows UAC...")
        try:
            code = request_elevation_and_wait()
        except OSError as exc:
            output("ERROR", f"Unable to launch elevated setup: {exc}")
            return 1
        if code != 0:
            output("ERROR", "Elevated setup failed or Windows UAC approval was unavailable.")
        return code
    try:
        perform_install()
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        output("ERROR", str(exc))
        return 1
    finally:
        if independent_console() and "--no-pause" not in sys.argv:
            try:
                input("\nPress Enter to close...")
            except EOFError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
