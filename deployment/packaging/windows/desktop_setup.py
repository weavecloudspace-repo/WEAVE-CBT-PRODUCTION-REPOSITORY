"""Native Windows GUI bootstrapper, delivering the matching CLI and Qt app."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

def notify(text, failed=False):
    ctypes.windll.user32.MessageBoxW(None, str(text), "WEAVE CBT Setup", 0x10 if failed else 0x40)

def verify(root):
    for name, command in (("weave.exe", "release"), ("WEAVE-CBT-Desktop.exe", "--smoke-test")):
        proc = subprocess.run([str(root / name), command], check=False, timeout=60,
                              capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode:
            raise RuntimeError("Cannot launch bundled " + name)

def extract(payload, root):
    with zipfile.ZipFile(payload) as archive:
        required = {"weave.exe", "WEAVE-CBT-Desktop.exe", "assets/compose.yaml",
                    "assets/release-manifest.json"}
        if not required.issubset(archive.namelist()):
            raise RuntimeError("Incomplete setup archive.")
        for file in archive.namelist():
            name = file.replace("\\", "/")
            if name.startswith("/") or ":" in name or ".." in Path(name).parts:
                raise RuntimeError("Unsafe path inside setup archive.")
        archive.extractall(root)
    release = json.loads((root / "assets/release-manifest.json").read_text(encoding="utf-8"))
    if (release.get("channel") not in ("staging", "production")
            or "@sha256:" not in release.get("cbt_image", "")
            or not release.get("manager_version")):
        raise RuntimeError("Invalid or unpinned release manifest.")
    return release

def deploy(root, release):
    directory = Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "WeaveCBT"
    previous = directory / "assets/release-manifest.json"
    if previous.exists() and json.loads(previous.read_text(encoding="utf-8")).get("channel") != release["channel"]:
        raise RuntimeError("A manager from a different release channel already exists.")
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("weave.exe", "WEAVE-CBT-Desktop.exe"):
        staged = directory / (name + ".new")
        shutil.copy2(root / name, staged)
        os.replace(staged, directory / name)
    shutil.copytree(root / "assets", directory / "assets", dirs_exist_ok=True)
    start = Path(os.getenv("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs/WEAVE CBT"
    start.mkdir(parents=True, exist_ok=True)
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    shortcut = start / "WEAVE CBT Desktop Manager.lnk"
    exe = directory / "WEAVE-CBT-Desktop.exe"
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" +
              literal(shortcut) + "); $s.TargetPath=" + literal(exe) + "; $s.Save()")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, timeout=30, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    import winreg
    key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0,
                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as registry:
        value, kind = winreg.QueryValueEx(registry, "Path")
        parts = [os.path.normcase(os.path.normpath(os.path.expandvars(item.strip(' "'))))
                 for item in value.split(";") if item.strip()]
        if os.path.normcase(str(directory)) not in parts:
            winreg.SetValueEx(registry, "Path", 0, kind, value.rstrip(";") + ";" + str(directory))
    notify("WEAVE CBT Desktop Manager installed.\n\nLaunch it from the Start Menu to install or manage your CBT server.")

def main():
    if sys.platform != "win32":
        return 1
    payload = Path(__file__).resolve().parent / "payload.zip"
    try:
        if not payload.exists():
            raise RuntimeError("The release payload is missing.")
        if "--verify-payload" not in sys.argv[1:] and not ctypes.windll.shell32.IsUserAnAdmin():
            code = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(Path(sys.argv[0]).resolve()), "--elevated", None, 1)
            return 0 if int(code) > 32 else 1
        with tempfile.TemporaryDirectory(prefix="weave-desktop-") as folder:
            root = Path(folder)
            release = extract(payload, root)
            verify(root)
            if "--verify-payload" not in sys.argv[1:]:
                deploy(root, release)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired,
            subprocess.CalledProcessError) as exc:
        notify(f"Setup failed:\n{exc}", failed=True)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
