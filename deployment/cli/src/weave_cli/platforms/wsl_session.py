"""Manage a user-owned Windows task that keeps a dedicated WSL session alive."""

from __future__ import annotations

import base64
import subprocess

from weave_cli.platforms.base import PlatformError


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def task_script(distribution: str, *, remove: bool = False) -> str:
    """Generate PowerShell without interpolating values into shell expressions."""
    task_name = _literal(f"WEAVE CBT Runtime - {distribution}")
    preamble = f"""$ErrorActionPreference = 'Stop'
$taskName = {task_name}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {{
    $owner = $task.Principal.UserId
    try {{
        if ($owner -match '^S-1-') {{
            $ownerSid = [Security.Principal.SecurityIdentifier]::new($owner)
        }} else {{
            $ownerAccount = [Security.Principal.NTAccount]::new($owner)
            $ownerSid = $ownerAccount.Translate([Security.Principal.SecurityIdentifier])
        }}
    }} catch {{
        throw 'Unable to resolve the WEAVE runtime task owner. Use the installation owner account.'
    }}
    if ($ownerSid.Value -ne $identity.User.Value) {{
        throw 'The WEAVE runtime task belongs to another Windows user. Use the installation owner account.'
    }}
}}
"""
    if remove:
        return preamble + """
if ($task) {
    Stop-ScheduledTask -TaskName $taskName
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
exit 0
"""
    keeper = rf"""
$ErrorActionPreference = 'Stop'
$wslExecutable = Join-Path $env:SystemRoot 'System32\wsl.exe'
while ($true) {{
    & $wslExecutable --distribution {_literal(distribution)} --user root --exec /bin/sh -c 'systemctl start docker'
    $manager = Join-Path $env:ProgramFiles 'WeaveCBT\weave.exe'
    if ((Test-Path -LiteralPath $manager) -and $LASTEXITCODE -eq 0) {{
        # The CLI returns successfully when LAN forwarding was never enabled.
        # A forwarding error must not terminate the session keeping Docker alive.
        & $manager lan --refresh | Out-Null
    }}
    & $wslExecutable --distribution {_literal(distribution)} --user root --exec /bin/sh -c 'exec sleep infinity'
    Start-Sleep -Seconds 5
}}
"""
    return preamble + rf"""
# Task Scheduler can briefly display powershell.exe even with -WindowStyle Hidden.
# Use the stock Windows Script Host GUI executable as the windowless launcher.
$wscriptExecutable = Join-Path $env:SystemRoot 'System32\wscript.exe'
$helperDirectory = Join-Path $env:ProgramFiles 'WeaveCBT'
$helperPath = Join-Path $helperDirectory 'weave-wsl-keeper.vbs'
$arguments = '//B //NoLogo "' + $helperPath + '"'
$needsUpdate = -not $task
if ($task) {{
    $needsUpdate = @($task.Actions).Count -ne 1 -or
        $task.Actions[0].Execute -ne $wscriptExecutable -or
        $task.Actions[0].Arguments -ne $arguments -or
        -not (Test-Path -LiteralPath $helperPath)
}}
if ($needsUpdate) {{
    $principalCheck = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
        throw 'Run weave start as Administrator once to configure WSL session persistence.'
    }}
    if ($task) {{ Stop-ScheduledTask -TaskName $taskName }}
    New-Item -ItemType Directory -Path $helperDirectory -Force | Out-Null
    # Only Administrators and SYSTEM may modify the script that runs elevated.
    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $commandLine = '"' + $powerShell + '" -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand {_encoded(keeper)}'
    $vbCommand = $commandLine.Replace('"', '""')
    $vbBody = 'Set shell = CreateObject("WScript.Shell")' + [Environment]::NewLine +
        'result = shell.Run("' + $vbCommand + '", 0, True)' + [Environment]::NewLine
    Set-Content -LiteralPath $helperPath -Value $vbBody -Encoding Ascii
    & icacls.exe $helperPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
    if ($LASTEXITCODE -ne 0) {{ throw 'Unable to secure the windowless runtime launcher.' }}
    $action = New-ScheduledTaskAction -Execute $wscriptExecutable -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
    $principal = New-ScheduledTaskPrincipal -UserId $identity.User.Value -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Description 'Keeps the user-owned WEAVE WSL Docker runtime alive.' -Force | Out-Null
}}
if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') {{
    Start-ScheduledTask -TaskName $taskName
}}
$running = $false
for ($attempt = 0; $attempt -lt 10; $attempt++) {{
    Start-Sleep -Seconds 1
    if ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {{
        $running = $true
        break
    }}
}}
if (-not $running) {{ throw 'The WEAVE WSL session task did not start.' }}
"""


def manage_session(distribution: str, *, remove: bool = False) -> None:
    script = (
        "$ProgressPreference = 'SilentlyContinue'\ntry {\n"
        + task_script(distribution, remove=remove)
        + "\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\n"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-OutputFormat", "Text", "-EncodedCommand", _encoded(script)],
            capture_output=True, text=True, timeout=45, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlatformError(f"Unable to manage the WEAVE WSL session task: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PlatformError(f"Unable to manage the WEAVE WSL session task: {detail}")
