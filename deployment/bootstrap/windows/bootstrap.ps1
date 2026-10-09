[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$RootfsArchive,
    [string]$UbuntuUrl = "https://cloud-images.ubuntu.com/wsl/releases/noble/20240423/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz",
    [string]$UbuntuSha256 = "2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$DistroName = "WeaveCBT"

$programData = $env:ProgramData
if (-not $programData) {
    $programData = "C:\ProgramData"
}

$WeaveDataDirectory = Join-Path $programData "WeaveCBT"
$DistroInstallDirectory = Join-Path $WeaveDataDirectory "wsl"
$BootstrapStatePath = Join-Path $WeaveDataDirectory "bootstrap-state.json"

$BootstrapStateSchemaVersion = 1
$RebootRequiredExitCode = 3010


function Write-WeaveStep {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-Host "[WEAVE] $Message" -ForegroundColor Cyan
}


function Write-WeaveCheck {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][CHECK] $Message" -ForegroundColor Cyan
}


function Write-WeaveAction {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][ACTION] $Message" -ForegroundColor Blue
}


function Write-WeaveSuccess {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][OK] $Message" -ForegroundColor Green
}


function Write-WeaveSkip {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][SKIP] $Message" -ForegroundColor DarkGray
}


function Write-WeaveWait {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][WAIT] $Message" -ForegroundColor Yellow
}


function Write-WeaveWarning {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][WARN] $Message" -ForegroundColor Yellow
}






function Get-SystemBootMarker {
    try {
        $lastBoot = (Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
        return $lastBoot.ToUniversalTime().ToString("o")
    }
    catch {
        return $null
    }
}


function Write-BootstrapState {
    param(
        [Parameter(Mandatory)]
        [string]$Stage,

        [Parameter(Mandatory)]
        [bool]$RebootRequired,

        [Parameter(Mandatory = $false)]
        [string]$Message = ""
    )

    if (-not (Test-Path -LiteralPath $script:WeaveDataDirectory)) {
        New-Item -ItemType Directory -Path $script:WeaveDataDirectory -Force | Out-Null
    }

    $state = [ordered]@{
        schema_version = $script:BootstrapStateSchemaVersion
        stage = $Stage
        reboot_required = $RebootRequired
        message = $Message
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        boot_marker = Get-SystemBootMarker
    }

    $temporaryPath = Join-Path $script:WeaveDataDirectory (".bootstrap-state.{0}.tmp" -f [Guid]::NewGuid().ToString("N"))

    try {
        $json = $state | ConvertTo-Json -Depth 4
        [IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

        if (Test-Path -LiteralPath $script:BootstrapStatePath) {
            $backupPath = Join-Path $script:WeaveDataDirectory (".bootstrap-state.{0}.bak" -f [Guid]::NewGuid().ToString("N"))
            [IO.File]::Replace($temporaryPath, $script:BootstrapStatePath, $backupPath, $true)
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        }
        else {
            [IO.File]::Move($temporaryPath, $script:BootstrapStatePath)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}


function Read-BootstrapState {
    if (-not (Test-Path -LiteralPath $script:BootstrapStatePath -PathType Leaf)) {
        return $null
    }

    try {
        $state = Get-Content -LiteralPath $script:BootstrapStatePath -Raw | ConvertFrom-Json
    }
    catch {
        throw (
            "Bootstrap state file '$script:BootstrapStatePath' is invalid. " +
            "Remove it only after verifying no WEAVE CBT installation is in progress."
        )
    }

    if ($null -eq $state.schema_version -or [int]$state.schema_version -ne $script:BootstrapStateSchemaVersion) {
        throw (
            "Unsupported WEAVE CBT bootstrap state schema in " +
            "'$script:BootstrapStatePath'."
        )
    }

    if (-not $state.stage) {
        throw "WEAVE CBT bootstrap state is missing the required stage field."
    }

    return $state
}


function Remove-BootstrapState {
    if (Test-Path -LiteralPath $script:BootstrapStatePath -PathType Leaf) {
        Remove-Item -LiteralPath $script:BootstrapStatePath -Force
    }
}


function Exit-RebootRequired {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-BootstrapState -Stage "wsl_reboot_required" -RebootRequired $true -Message $Message

    Write-Warning $Message
    Write-WeaveStep "After Windows restarts, run the WEAVE CBT installation again to resume."
    exit $script:RebootRequiredExitCode
}


function Assert-Administrator {
    Write-WeaveCheck "Checking Administrator privileges."

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)

    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "WEAVE CBT bootstrap must be run from an elevated Administrator session."
    }

    Write-WeaveSuccess "Administrator privileges confirmed."
}


function ConvertTo-NativeArgument {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Value
    )

    if ($Value.Length -eq 0) {
        return '""'
    }

    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0

    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }

        if ($character -eq '"') {
            if ($backslashes -gt 0) {
                [void]$builder.Append(('\' * ($backslashes * 2)))
                $backslashes = 0
            }

            [void]$builder.Append('\"')
            continue
        }

        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }

        [void]$builder.Append($character)
    }

    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }

    [void]$builder.Append('"')
    return $builder.ToString()
}


function Invoke-WeaveWslCommand {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [switch]$CaptureOutput,

        [switch]$Quiet,

        [ValidateRange(0, 3600)]
        [int]$TimeoutSeconds = 0,

        [AllowNull()]
        [string]$InputText = $null
    )

    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $script:WslExecutable
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true

    # Windows PowerShell 5.1 does not expose ProcessStartInfo.ArgumentList,
    # so build a correctly quoted native command line explicitly.
    $quotedArguments = @(
        $Arguments |
            ForEach-Object {
                ConvertTo-NativeArgument -Value $_
            }
    )
    $startInfo.Arguments = $quotedArguments -join ' '

    # Explicitly redirect both streams. With CreateNoWindow, leaving stdout
    # inherited can hide every Linux installation message from PowerShell.
    $startInfo.RedirectStandardError = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardInput = ($null -ne $InputText)

    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo

    try {
        if (-not $process.Start()) {
            throw "Failed to start wsl.exe."
        }

        # Write Bash script input asynchronously. Synchronous Write() before
        # reading output can deadlock if Bash prints while still reading stdin.
        # Windows PowerShell 5.1 supports StreamWriter.WriteAsync() via .NET.
        $inputTask = $null
        $inputClosed = -not $startInfo.RedirectStandardInput
        if ($startInfo.RedirectStandardInput) {
            $inputTask = $process.StandardInput.WriteAsync($InputText)
        }

        # Read stderr concurrently so diagnostic output cannot fill its pipe
        # while we display Docker/apt stdout as it arrives.
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $stdoutText = ""

        if ($CaptureOutput -or $Quiet) {
            $stdoutTask = $process.StandardOutput.ReadToEndAsync()
            if (-not $inputClosed) {
                $inputTask.GetAwaiter().GetResult()
                $process.StandardInput.Close()
                $inputClosed = $true
            }
            if ($TimeoutSeconds -gt 0) {
                if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
                    $process.Kill()
                    $process.WaitForExit()
                    throw "WSL operation timed out after $TimeoutSeconds seconds."
                }
            }
            else {
                $process.WaitForExit()
            }
            $stdoutText = $stdoutTask.GetAwaiter().GetResult()
        }
        else {
            # Stream each line from WSL in this PowerShell thread. Using
            # ReadLineAsync permits a visible heartbeat even if apt is silent.
            $outputLineTask = $process.StandardOutput.ReadLineAsync()
            $idleWatch = [Diagnostics.Stopwatch]::StartNew()
            $elapsedWatch = [Diagnostics.Stopwatch]::StartNew()

            while ($true) {
                if (-not $inputClosed -and $inputTask.IsCompleted) {
                    $inputTask.GetAwaiter().GetResult()
                    $process.StandardInput.Close()
                    $inputClosed = $true
                }
                if ($TimeoutSeconds -gt 0 -and $elapsedWatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                    $process.Kill()
                    $process.WaitForExit()
                    throw "WSL operation timed out after $TimeoutSeconds seconds."
                }
                if ($outputLineTask.Wait(1000)) {
                    $line = $outputLineTask.GetAwaiter().GetResult()

                    if ($null -eq $line) {
                        break
                    }

                    Write-Host $line
                    $idleWatch.Restart()
                    $outputLineTask = $process.StandardOutput.ReadLineAsync()
                }
                elseif ($idleWatch.Elapsed.TotalSeconds -ge 30) {
                    $seconds = [int]$elapsedWatch.Elapsed.TotalSeconds
                    Write-WeaveWait "Linux provisioning command is still running ($seconds seconds elapsed)."
                    $idleWatch.Restart()
                }
            }

            if (-not $inputClosed) {
                $inputTask.GetAwaiter().GetResult()
                $process.StandardInput.Close()
                $inputClosed = $true
            }

            while (-not $process.WaitForExit(1000)) {
                if ($TimeoutSeconds -gt 0 -and $elapsedWatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                    $process.Kill()
                    $process.WaitForExit()
                    throw "WSL operation timed out after $TimeoutSeconds seconds."
                }
                if ($idleWatch.Elapsed.TotalSeconds -ge 30) {
                    $seconds = [int]$elapsedWatch.Elapsed.TotalSeconds
                    Write-WeaveWait "Waiting for WSL command to finish ($seconds seconds elapsed)."
                    $idleWatch.Restart()
                }
            }
        }

        $stderrText = $stderrTask.GetAwaiter().GetResult()
        $exitCode = $process.ExitCode
    }
    finally {
        $process.Dispose()
    }

    $stdoutLines = @()

    if ($stdoutText) {
        $stdoutLines = @(
            $stdoutText -split "\r?\n" |
                Where-Object {
                    $_ -ne ""
                }
        )
    }

    $stderrLines = @()

    if ($stderrText) {
        $stderrLines = @(
            $stderrText -split "\r?\n" |
                ForEach-Object {
                    $_.Trim()
                } |
                Where-Object {
                    $_
                }
        )
    }

    if ($stderrLines.Count -gt 0) {
        foreach ($line in $stderrLines) {
            $isRootSessionWarning = $line -like "*Failed to start the systemd user session for 'root'*"

            if ($exitCode -eq 0 -and $isRootSessionWarning) {
                if (-not $script:RootSessionWarningShown) {
                    Write-WeaveWarning (
                        "WSL reported that root's systemd user session is unhealthy. " +
                        "The WSL command itself succeeded; bootstrap will repair and verify " +
                        "the root user manager before Docker provisioning."
                    )
                    $script:RootSessionWarningShown = $true
                }

                continue
            }

            if ($exitCode -eq 0) {
                Write-WeaveWarning "WSL reported: $line"
            }
            else {
                Write-WeaveWarning "WSL error output: $line"
            }
        }
    }

    return [PSCustomObject]@{
        ExitCode = $exitCode
        Output = $stdoutLines
        ErrorOutput = $stderrLines
    }
}

function Invoke-WeaveWslScript {
    param(
        [Parameter(Mandatory)]
        [string]$Script,

        [Parameter(Mandatory)]
        [string]$FailureMessage
    )

    # PowerShell strings on Windows commonly use CRLF. Bash inside WSL
    # expects Unix LF line endings; CR characters can corrupt shell syntax,
    # here-doc terminators, and paths such as /etc/os-release.
    $normalizedScript = $Script -replace "`r`n", "`n"
    $normalizedScript = $normalizedScript -replace "`r", "`n"

    $result = Invoke-WeaveWslCommand -Arguments @(
        "--distribution",
        $script:DistroName,
        "--user",
        "root",
        "--",
        "/bin/bash",
        "-s"
    ) -InputText $normalizedScript

    if ($result.ExitCode -ne 0) {
        throw "$FailureMessage WSL exited with code $($result.ExitCode)."
    }
}

function Get-InstalledWslDistributions {
    $result = Invoke-WeaveWslCommand -Arguments @(
        "--list",
        "--quiet"
    ) -CaptureOutput

    if ($result.ExitCode -ne 0) {
        throw "Failed to list installed WSL distributions."
    }

    $names = @(
        $result.Output |
            ForEach-Object {
                ($_ -replace [char]0, "").Trim()
            } |
            Where-Object {
                $_
            }
    )

    return $names
}

function Assert-WeaveDistroIsUbuntu {
    Write-WeaveCheck "Checking Linux distribution inside '$script:DistroName'."

    $result = Invoke-WeaveWslCommand -Arguments @(
        "--distribution",
        $script:DistroName,
        "--user",
        "root",
        "--",
        "cat",
        "/etc/os-release"
    ) -CaptureOutput

    if ($result.ExitCode -ne 0) {
        throw "Failed to read /etc/os-release inside '$script:DistroName'."
    }

    $idLine = $result.Output |
        Where-Object {
            $_ -match '^ID='
        } |
        Select-Object -First 1

    if (-not $idLine) {
        throw (
            "The '$script:DistroName' WSL distribution does not expose an ID " +
            "in /etc/os-release."
        )
    }

    $distributionId = (
        ($idLine -replace '^ID=', '').Trim().Trim('"').Trim("'")
    ).ToLowerInvariant()

    if ($distributionId -ne "ubuntu") {
        throw (
            "The '$script:DistroName' WSL distribution must be Ubuntu. " +
            "Detected '$distributionId'."
        )
    }

    Write-WeaveSuccess "'$script:DistroName' is running Ubuntu."
}

function Test-WindowsServicingRebootPending {
    # Optional Windows features can display Enabled while Windows still
    # requires a restart to activate them. Check servicing state explicitly.
    $rebootKeys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    )

    foreach ($key in $rebootKeys) {
        if (Test-Path -LiteralPath $key) {
            return $true
        }
    }

    return $false
}


function Assert-WindowsWsl2Compatibility {
    Write-WeaveCheck "Checking Windows WSL2 compatibility."
    $operatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    $build = [int]$operatingSystem.BuildNumber
    if ($build -lt 19041) {
        throw (
            "Windows build $build does not meet the WEAVE CBT WSL2 baseline. " +
            "Use Windows 10 version 2004 or later, Windows 11, or Windows Server 2022/2025. " +
            "Windows Server 2019 does not support this WSL2 Docker architecture."
        )
    }
    if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
        throw "This installer requires AMD64 Windows and supported virtualization."
    }
    try {
        $processor = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
        if ($null -ne $processor -and $processor.VirtualizationFirmwareEnabled -eq $false) {
            Write-WeaveWarning "Virtualization may be disabled or hidden by a VM. Check firmware settings or nested virtualization."
        }
    }
    catch {
        Write-WeaveWarning "Cannot inspect virtualization firmware. WSL2 import will verify this requirement."
    }
    Write-WeaveSuccess "Windows host build and architecture are compatible."
}


function Ensure-WslWindowsFeatures {
    Write-WeaveCheck "Checking Windows features required by WSL2."

    $features = @(
        "Microsoft-Windows-Subsystem-Linux",
        "VirtualMachinePlatform"
    )

    $restartNeeded = $false

    foreach ($featureName in $features) {
        try {
            $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName -ErrorAction Stop
        }
        catch {
            throw (
                "Cannot inspect Windows feature '$featureName'. " +
                "Verify that this Windows Server edition supports WSL2. " +
                "Details: $($_.Exception.Message)"
            )
        }

        $featureState = [string]$feature.State

        switch ($featureState) {
            "Enabled" {
                Write-WeaveSkip "Windows feature '$featureName' is already enabled."
            }

            "EnablePending" {
                Write-WeaveWait "Windows feature '$featureName' is pending a restart."
                $restartNeeded = $true
            }

            "Disabled" {
                Write-WeaveAction "Enabling Windows feature '$featureName'."

                try {
                    # Installing these features can require a Windows reboot.
                    # Do not reboot automatically; the operator must reconnect
                    # and rerun this resumable bootstrap afterward.
                    Enable-WindowsOptionalFeature -Online -FeatureName $featureName -All -NoRestart -ErrorAction Stop | Out-Null
                }
                catch {
                    throw (
                        "Failed to enable Windows feature '$featureName'. " +
                        "Details: $($_.Exception.Message)"
                    )
                }

                $restartNeeded = $true
                Write-WeaveSuccess "Windows feature '$featureName' was enabled or scheduled for enablement."
            }

            default {
                throw (
                    "Windows feature '$featureName' is in state '$featureState'. " +
                    "Resolve any pending Windows servicing operations before retrying."
                )
            }
        }
    }

    if ($restartNeeded -or (Test-WindowsServicingRebootPending)) {
        Exit-RebootRequired -Message (
            "Windows feature activation or servicing requires a restart. " +
            "Restart this Windows server, reconnect, and rerun the bootstrap."
        )
    }

    Write-WeaveSuccess "WSL2 Windows features are enabled."
}


function Ensure-WslAvailable {
    Write-WeaveStep "Checking Windows Subsystem for Linux."

    $bootstrapState = Read-BootstrapState

    if ($null -ne $bootstrapState -and $bootstrapState.stage -eq "wsl_reboot_required") {
        $currentBootMarker = Get-SystemBootMarker
        $recordedBootMarker = $bootstrapState.boot_marker

        if ($recordedBootMarker -and $currentBootMarker -and $recordedBootMarker -eq $currentBootMarker) {
            Exit-RebootRequired -Message "Windows must restart before WEAVE CBT can continue WSL provisioning."
        }

        # After reboot, the Windows features may be ready while WSL itself
        # still needs initialization. Resume instead of treating that as an
        # irrecoverable error.
        Write-WeaveStep "Windows restart detected; continuing WSL prerequisite checks."
        Remove-BootstrapState
    }

    # A successful wsl --status alone does not prove servicing has completed.
    Ensure-WslWindowsFeatures
    $statusResult = Invoke-WeaveWslCommand -Arguments @("--status") -Quiet -TimeoutSeconds 90
    if ($statusResult.ExitCode -eq 0) {
        Remove-BootstrapState
        Write-WeaveSuccess "WSL runtime is available."
        return
    }
    Write-BootstrapState -Stage "wsl_prerequisites_installing" -RebootRequired $false -Message "Installing official Microsoft WSL runtime."

    # Only initialize wsl.exe after both optional Windows features are active.
    # Fresh Windows Server machines may reject --install until these features
    # have been enabled and the host restarted.
    Write-WeaveAction "Installing Microsoft WSL without a default Linux distribution."
    try {
        $installResult = Invoke-WeaveWslCommand -Arguments @("--install", "--no-distribution") -TimeoutSeconds 600
    }
    catch {
        Write-WeaveWarning "Normal WSL installation timed out: $($_.Exception.Message). Trying official web-download fallback."
        $installResult = [PSCustomObject]@{ ExitCode = -1 }
    }
    if ($installResult.ExitCode -ne 0 -and $installResult.ExitCode -ne $script:RebootRequiredExitCode) {
        Write-WeaveWarning "Default WSL installation failed; retrying official web-download method."
        $installResult = Invoke-WeaveWslCommand -Arguments @("--install", "--no-distribution", "--web-download") -TimeoutSeconds 600
    }
    if ($installResult.ExitCode -eq $script:RebootRequiredExitCode) {
        Exit-RebootRequired -Message "Windows needs a restart to finish Microsoft WSL installation."
    }
    if ($installResult.ExitCode -ne 0) {
        throw (
            "Microsoft WSL installation failed (exit code $($installResult.ExitCode)). " +
            "Check Windows build, Windows Update/network access, and hardware virtualization. " +
            "If this Windows host is a virtual machine, verify nested virtualization is enabled."
        )
    }
    $statusResult = Invoke-WeaveWslCommand -Arguments @("--status") -Quiet -TimeoutSeconds 90
    if ($statusResult.ExitCode -ne 0) {
        Exit-RebootRequired -Message "Microsoft WSL installation finished but is not ready; restart Windows and rerun weave install."
    }
    Remove-BootstrapState
    Write-WeaveSuccess "Microsoft WSL runtime initialized."

}

function Ensure-WslSystemdSupport {
    # Docker Engine runs as a systemd service in our dedicated distro.
    # Microsoft's inbox/older WSL can report --status successfully but cannot
    # support systemd. Modern WSL 0.67.6+ is a hard prerequisite.
    Write-WeaveCheck "Verifying modern Microsoft WSL with systemd support."
    $version = Invoke-WeaveWslCommand -Arguments @("--version") -CaptureOutput -TimeoutSeconds 90
    $wslVersion = $null
    if ($version.ExitCode -eq 0) {
        $versionText = (($version.Output -join " ") -replace [char]0, "")
        $match = [Regex]::Match($versionText, '(\d+)\.(\d+)\.(\d+)')
        if ($match.Success) {
            $wslVersion = [Version]::new(
                [int]$match.Groups[1].Value, [int]$match.Groups[2].Value, [int]$match.Groups[3].Value
            )
        }
    }
    if ($null -ne $wslVersion -and $wslVersion -ge [Version]::new(0, 67, 6)) {
        Write-WeaveSuccess "WSL version $wslVersion supports systemd."
        return
    }

    Write-WeaveAction "Updating the official Microsoft WSL runtime for systemd support."
    try {
        $updated = Invoke-WeaveWslCommand -Arguments @("--update", "--web-download") -TimeoutSeconds 600
    }
    catch {
        Write-WeaveWarning "WSL web-download update timed out or failed: $($_.Exception.Message)"
        $updated = [PSCustomObject]@{ ExitCode = -1 }
    }
    if ($updated.ExitCode -ne 0 -and $updated.ExitCode -ne $script:RebootRequiredExitCode) {
        Write-WeaveWarning "WSL web-download update was not successful; trying standard Microsoft update."
        $updated = Invoke-WeaveWslCommand -Arguments @("--update") -TimeoutSeconds 600
    }
    if ($updated.ExitCode -eq $script:RebootRequiredExitCode) {
        Exit-RebootRequired -Message "Microsoft WSL update needs a Windows restart before Docker provisioning."
    }
    if ($updated.ExitCode -ne 0) {
        throw "Unable to update Microsoft WSL (exit $($updated.ExitCode)). WSL 0.67.6+ is required for systemd. Check Windows build, HTTPS access and Microsoft WSL availability."
    }

    $version = Invoke-WeaveWslCommand -Arguments @("--version") -CaptureOutput -TimeoutSeconds 90
    if ($version.ExitCode -ne 0) {
        throw "Microsoft WSL does not recognize --version after update. A modern WSL release with systemd support is required."
    }
    $versionText = (($version.Output -join " ") -replace [char]0, "")
    $match = [Regex]::Match($versionText, '(\d+)\.(\d+)\.(\d+)')
    if (-not $match.Success) {
        throw "Cannot verify WSL version after update; refusing to enable systemd without an identifiable runtime."
    }
    $actual = [Version]::new(
        [int]$match.Groups[1].Value, [int]$match.Groups[2].Value, [int]$match.Groups[3].Value
    )
    if ($actual -lt [Version]::new(0, 67, 6)) {
        throw "WSL version $actual does not support systemd. Update to WSL 0.67.6 or newer."
    }
    Write-WeaveSuccess "Microsoft WSL updated to $actual with systemd support."
}


function Ensure-UbuntuRootfs {
    if ($RootfsArchive) {
        if (-not (Test-Path -LiteralPath $RootfsArchive -PathType Leaf)) {
            throw "Specified Ubuntu rootfs archive '$RootfsArchive' does not exist."
        }
        Write-WeaveSkip "Using supplied Ubuntu rootfs archive."
        return (Resolve-Path -LiteralPath $RootfsArchive).Path
    }
    if ($UbuntuUrl -notlike "https://cloud-images.ubuntu.com/*") {
        throw "Ubuntu rootfs must be downloaded from the official Canonical HTTPS host."
    }
    if ($UbuntuSha256.Length -ne 64 -or $UbuntuSha256 -notmatch '^[0-9a-fA-F]+$') {
        throw "Ubuntu image SHA-256 must be a verified 64-character hex digest."
    }

    $cache = Join-Path $script:WeaveDataDirectory "downloads"
    New-Item -ItemType Directory -Path $cache -Force | Out-Null
    $archive = Join-Path $cache "ubuntu-noble-wsl-amd64.rootfs.tar.gz"
    $partial = "$archive.partial"
    $expected = $UbuntuSha256.ToLowerInvariant()
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    if (-not (Test-Path -LiteralPath $curl -PathType Leaf)) {
        throw "curl.exe is missing. Use a supported Windows release or -RootfsArchive."
    }

    foreach ($attempt in 1..3) {
        if (Test-Path -LiteralPath $archive -PathType Leaf) {
            if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expected) {
                Write-WeaveSkip "Official Ubuntu image verified in cache."
                return $archive
            }
            Remove-Item -LiteralPath $archive -Force
        }
        Write-WeaveAction "Downloading Ubuntu 24.04 LTS WSL rootfs (attempt $attempt/3)."
        & $curl --fail --show-error --location --proto "=https" --proto-redir "=https" --connect-timeout 30 --speed-limit 1024 --speed-time 120 --max-time 1200 --continue-at - --output $partial $UbuntuUrl
        $curlCode = $LASTEXITCODE
        if ($curlCode -ne 0) {
            Write-WeaveWarning "Ubuntu download attempt failed with curl exit code $curlCode."
            if ($curlCode -eq 33 -and (Test-Path -LiteralPath $partial)) {
                Remove-Item -LiteralPath $partial -Force
            }
            Start-Sleep -Seconds (5 * $attempt)
            continue
        }
        Move-Item -LiteralPath $partial -Destination $archive -Force
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expected) {
            Write-WeaveSuccess "Canonical Ubuntu rootfs verified (SHA-256)."
            return $archive
        }
        Remove-Item -LiteralPath $archive -Force
        Write-WeaveWarning "Ubuntu checksum mismatch; refusing unverified archive."
    }
    throw "Ubuntu download and verification failed. Check network access then rerun weave install."
}


function Ensure-WeaveDistro {
    Write-WeaveCheck "Checking for dedicated WSL distribution '$script:DistroName'."

    $installedDistros = Get-InstalledWslDistributions

    if ($installedDistros.Count -gt 0) {
        Write-WeaveStep ("Installed WSL distributions: " + ($installedDistros -join ", "))
    }
    else {
        Write-WeaveStep "No WSL distributions are currently installed."
    }

    if ($installedDistros -contains $script:DistroName) {
        Write-WeaveSkip "'$script:DistroName' already exists; distro import is not required."
        Assert-WeaveDistroIsUbuntu
        return
    }

    $resolvedRootfs = Ensure-UbuntuRootfs

    if (Test-Path -LiteralPath $script:DistroInstallDirectory) {
        $existingItems = @(Get-ChildItem -LiteralPath $script:DistroInstallDirectory -Force)

        if ($existingItems.Count -gt 0) {
            throw (
                "WSL runtime directory '$script:DistroInstallDirectory' is not empty. " +
                "Refusing to overwrite existing data."
            )
        }
    }
    else {
        New-Item -ItemType Directory -Path $script:DistroInstallDirectory -Force | Out-Null
    }

    # Imported ext4.vhdx contains school exam data and database volumes.
    # Restrict this directory before importing; never recurse existing VHDs.
    $icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
    if (-not (Test-Path -LiteralPath $icacls -PathType Leaf)) {
        throw "Windows icacls.exe is required to secure WSL data storage."
    }
    & $icacls $script:DistroInstallDirectory "/inheritance:r" "/grant:r" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to protect the WSL data directory ACL; import was not started."
    }
    Write-WeaveAction "Importing dedicated '$script:DistroName' WSL2 distribution into '$script:DistroInstallDirectory'."

    $importResult = Invoke-WeaveWslCommand -Arguments @(
        "--import",
        $script:DistroName,
        $script:DistroInstallDirectory,
        $resolvedRootfs,
        "--version",
        "2"
    ) -TimeoutSeconds 1800

    if ($importResult.ExitCode -ne 0) {
        throw "Failed to import the '$script:DistroName' WSL distribution."
    }

    Write-WeaveSuccess "'$script:DistroName' was imported successfully."
    Assert-WeaveDistroIsUbuntu

    # A successful WSL import owns its own VHDX. Only remove the verified
    # automatically downloaded archive; never delete an operator's override.
    if (-not $RootfsArchive -and (Test-Path -LiteralPath $resolvedRootfs -PathType Leaf)) {
        try {
            Remove-Item -LiteralPath $resolvedRootfs -Force -ErrorAction Stop
            Write-WeaveSuccess "Removed temporary Canonical Ubuntu archive after WSL import."
        }
        catch {
            Write-WeaveWarning "Ubuntu was imported successfully, but archive cache cleanup failed: $($_.Exception.Message)"
        }
    }
}


function Ensure-WeaveDistroUsesWsl2 {
    Write-WeaveCheck "Checking WSL version for '$script:DistroName'."

    $listResult = Invoke-WeaveWslCommand -Arguments @(
        "--list",
        "--verbose"
    ) -CaptureOutput

    $verboseOutput = @(
        $listResult.Output |
            ForEach-Object {
                $_ -replace [char]0, ""
            }
    )

    if ($listResult.ExitCode -ne 0) {
        throw "Failed to inspect the '$script:DistroName' WSL version."
    }

    $escapedName = [Regex]::Escape($script:DistroName)
    $distroLine = $verboseOutput |
        Where-Object {
            $_ -match "^\s*\*?\s*$escapedName\s+"
        } |
        Select-Object -First 1

    if (-not $distroLine) {
        throw "Unable to find '$script:DistroName' in the WSL distribution list."
    }

    if ($distroLine -match "\s+2\s*$") {
        Write-WeaveSkip "'$script:DistroName' is already WSL2."
        return
    }

    Write-WeaveAction "Converting '$script:DistroName' to WSL2."

    $setVersionResult = Invoke-WeaveWslCommand -Arguments @(
        "--set-version",
        $script:DistroName,
        "2"
    )

    if ($setVersionResult.ExitCode -ne 0) {
        throw "Failed to convert '$script:DistroName' to WSL2."
    }

    Write-WeaveSuccess "'$script:DistroName' is now using WSL2."
}


function Configure-Systemd {
    Write-WeaveAction "Configuring systemd inside '$script:DistroName'."

    $systemdConfiguration = @'
set -eu

cat > /etc/wsl.conf <<'EOF'
[boot]
systemd=true
EOF
'@

    Invoke-WeaveWslScript -Script $systemdConfiguration -FailureMessage "Failed to configure systemd inside '$script:DistroName'."

    Write-WeaveAction "Restarting '$script:DistroName' so the systemd configuration takes effect."
    $terminateResult = Invoke-WeaveWslCommand -Arguments @(
        "--terminate",
        $script:DistroName
    ) -Quiet

    if ($terminateResult.ExitCode -ne 0) {
        throw "Failed to restart the '$script:DistroName' WSL distribution."
    }

    $systemdReady = $false

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        $pidResult = Invoke-WeaveWslCommand -Arguments @(
            "--distribution",
            $script:DistroName,
            "--user",
            "root",
            "--",
            "cat",
            "/proc/1/comm"
        ) -CaptureOutput

        if ($pidResult.ExitCode -eq 0) {
            $pidOne = (($pidResult.Output -join "").Trim())

            if ($pidOne -eq "systemd") {
                $systemdReady = $true
                break
            }
        }

        Write-WeaveWait "Waiting for systemd to become PID 1 (attempt $attempt/10)."
        Start-Sleep -Seconds 1
    }

    if (-not $systemdReady) {
        throw (
            "systemd did not start inside '$script:DistroName'. " +
            "Update WSL with 'wsl --update', restart Windows if requested, " +
            "and retry WEAVE CBT installation."
        )
    }

    Write-WeaveSuccess "systemd is running inside '$script:DistroName'."
}


function Repair-RootSystemdUserSession {
    Write-WeaveCheck "Checking root systemd user session inside '$script:DistroName'."

    $checkResult = Invoke-WeaveWslCommand -Arguments @(
        "--distribution",
        $script:DistroName,
        "--user",
        "root",
        "--",
        "systemctl",
        "is-active",
        "user@0.service"
    ) -CaptureOutput

    if ($checkResult.ExitCode -eq 0 -and (($checkResult.Output -join "").Trim()) -eq "active") {
        Write-WeaveSkip "root systemd user session is already healthy."
        return
    }

    Write-WeaveAction "Repairing root systemd user session prerequisites."

    $repairScript = @'
set -eu

export DEBIAN_FRONTEND=noninteractive

needs_packages=0

for package in dbus-user-session libpam-systemd; do
    if ! dpkg -s "$package" >/dev/null 2>&1; then
        needs_packages=1
        break
    fi
done

if [ "$needs_packages" -eq 1 ]; then
    echo "[WEAVE][ACTION] Installing systemd user-session prerequisites."
    # Apply a bounded deadline only to network metadata/downloads, never dpkg.
    APT_PREREQ=(apt-get -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
    timeout --signal=TERM --kill-after=10s 600s "${APT_PREREQ[@]}" update
    timeout --signal=TERM --kill-after=10s 600s "${APT_PREREQ[@]}" --download-only install -y dbus-user-session libpam-systemd
    "${APT_PREREQ[@]}" --no-download install -y dbus-user-session libpam-systemd
else
    echo "[WEAVE][SKIP] systemd user-session prerequisite packages are already installed."
fi

echo "[WEAVE][ACTION] Enabling persistent root user manager."
loginctl enable-linger root

mkdir -p /run/user/0
chown root:root /run/user/0
chmod 0700 /run/user/0

systemctl reset-failed user@0.service >/dev/null 2>&1 || true

echo "[WEAVE][ACTION] Starting root systemd user manager."
timeout --signal=TERM --kill-after=10s 180s systemctl start user@0.service

if ! systemctl is-active --quiet user@0.service; then
    echo "[WEAVE][ERROR] user@0.service failed to become active." >&2
    systemctl status user@0.service --no-pager >&2 || true
    journalctl -b -u user@0.service --no-pager -n 50 >&2 || true
    exit 31
fi

echo "[WEAVE][OK] root systemd user session is active."
'@

    try {
        Invoke-WeaveWslScript -Script $repairScript -FailureMessage "Failed to repair root systemd user session inside '$script:DistroName'."
    }
    catch {
        throw (
            "WEAVE CBT repaired the standard Ubuntu systemd user-session prerequisites, " +
            "but WSL still could not start root's user manager. " +
            $_.Exception.Message
        )
    }

    Write-WeaveSuccess "root systemd user session is healthy."
}


function Install-DockerEngine {
    Write-WeaveAction "Checking and provisioning Docker Engine inside '$script:DistroName'."

    $dockerProvisioning = @'
set -eu

echo "[WEAVE][CHECK] Reading Ubuntu runtime metadata."
. /etc/os-release

if [ "$ID" != "ubuntu" ]; then
    echo "WEAVE CBT requires an Ubuntu WSL runtime." >&2
    exit 20
fi

echo "[WEAVE][CHECK] Checking Docker CLI, daemon, Compose plugin, and systemd service."
if command -v docker >/dev/null 2>&1 \
    && command -v dockerd >/dev/null 2>&1 \
    && docker compose version >/dev/null 2>&1 \
    && systemctl cat docker.service >/dev/null 2>&1; then
    echo "[WEAVE][SKIP] Docker components are already installed; package installation is not required."
    echo "[WEAVE][ACTION] Enabling and starting Docker services."
    systemctl enable docker.service >/dev/null
    systemctl enable containerd.service >/dev/null 2>&1 || true
    timeout --signal=TERM --kill-after=10s 180s systemctl start docker.service
    echo "[WEAVE][OK] Existing Docker installation is ready."
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive

# Keep APT arguments in one array shared by normal provisioning and
# the isolated download watchdog. Functions cannot be passed to setsid.
APT_GET=(
    apt-get
    -o DPkg::Lock::Timeout=120
    -o Acquire::Retries=3
    -o Acquire::http::Timeout=30
    -o Acquire::https::Timeout=30
)

apt_weave() {
    "${APT_GET[@]}" "$@"
}

echo "[WEAVE][ACTION] Refreshing Ubuntu package metadata (network retries enabled)."
timeout --signal=TERM --kill-after=10s 600s "${APT_GET[@]}" update
echo "[WEAVE][ACTION] Downloading repository prerequisites with a bounded network phase."
timeout --signal=TERM --kill-after=10s 600s "${APT_GET[@]}" --download-only install -y ca-certificates curl
echo "[WEAVE][ACTION] Installing repository prerequisites from local cache."
apt_weave --no-download install -y ca-certificates curl

echo "[WEAVE][CHECK] Removing packages that can conflict with Docker CE."
for package in \
    docker.io \
    docker-compose \
    docker-compose-v2 \
    docker-doc \
    podman-docker \
    containerd \
    runc
do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -qx "install ok installed"; then
        echo "[WEAVE][ACTION] Removing conflicting package '$package'."
        apt_weave remove -y "$package"
    fi
done

echo "[WEAVE][ACTION] Configuring Docker's official Ubuntu repository."
install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
    --retry-connrefused --connect-timeout 20 --max-time 120 \
    https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release

codename="${UBUNTU_CODENAME:-$VERSION_CODENAME}"

architecture="$(dpkg --print-architecture)"

cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF

echo "[WEAVE][ACTION] Refreshing package metadata with Docker repository enabled."
timeout --signal=TERM --kill-after=10s 600s "${APT_GET[@]}" update

# Only package downloads are interruptible. Never interrupt dpkg configuration.
WEAVE_DOWNLOAD_STALL_SECONDS=120
WEAVE_DOWNLOAD_POLL_SECONDS=5
WEAVE_DOWNLOAD_MAX_ATTEMPTS=3
WEAVE_ACTIVE_DOWNLOAD_PID=""

apt_cache_bytes() {
    find /var/cache/apt/archives -type f \( -name '*.deb' -o -path '*/partial/*' \) -printf '%s\n' 2>/dev/null \
        | awk '{ size += $1 } END { printf "%.0f\n", size + 0 }'
}

stop_apt_download() {
    local download_pid=$1
    local process_group
    process_group="$(ps -o pgid= -p "$download_pid" 2>/dev/null | tr -d '[:space:]' || true)"

    # setsid isolates the download. Never signal the bootstrap's own group.
    if [ "$process_group" = "$download_pid" ]; then
        kill -TERM -- "-$download_pid" 2>/dev/null || true
        sleep 2
        kill -KILL -- "-$download_pid" 2>/dev/null || true
    else
        kill -TERM "$download_pid" 2>/dev/null || true
    fi
}

cleanup_active_download() {
    if [ -n "$WEAVE_ACTIVE_DOWNLOAD_PID" ]; then
        stop_apt_download "$WEAVE_ACTIVE_DOWNLOAD_PID"
        wait "$WEAVE_ACTIVE_DOWNLOAD_PID" 2>/dev/null || true
        WEAVE_ACTIVE_DOWNLOAD_PID=""
    fi
}

trap 'cleanup_active_download; exit 130' INT
trap 'cleanup_active_download; exit 143' TERM

download_docker_packages() {
    if [ "${#APT_GET[@]}" -eq 0 ]; then
        echo "[WEAVE][ERROR] Internal bootstrap error: APT_GET command is not configured." >&2
        return 1
    fi

    local attempt download_pid before_bytes current_bytes
    local start_seconds last_progress_seconds last_report_seconds now
    local stalled exit_code delay_seconds

    for ((attempt = 1; attempt <= WEAVE_DOWNLOAD_MAX_ATTEMPTS; attempt++)); do
        echo "[WEAVE][ACTION] Downloading Docker packages (attempt $attempt/$WEAVE_DOWNLOAD_MAX_ATTEMPTS)."
        echo "[WEAVE][CHECK] Watching APT archive growth; restarting after $WEAVE_DOWNLOAD_STALL_SECONDS seconds without progress."

        before_bytes="$(apt_cache_bytes)"
        start_seconds="$(date +%s)"
        last_progress_seconds="$start_seconds"
        last_report_seconds="$start_seconds"
        stalled=0
        exit_code=0

        # APT downloads without unpacking or configuring any packages.
        # A separate session allows safely stopping all apt HTTP workers.
        setsid "${APT_GET[@]}" --download-only install -y "$@" &
        download_pid=$!
        WEAVE_ACTIVE_DOWNLOAD_PID="$download_pid"

        while kill -0 "$download_pid" 2>/dev/null; do
            sleep "$WEAVE_DOWNLOAD_POLL_SECONDS"

            # APT may finish while this watchdog is asleep. Never classify
            # a completed download as stalled merely because the poll timer fired.
            if ! kill -0 "$download_pid" 2>/dev/null; then
                break
            fi

            now="$(date +%s)"
            current_bytes="$(apt_cache_bytes)"

            if [ "$current_bytes" -gt "$before_bytes" ]; then
                before_bytes="$current_bytes"
                last_progress_seconds="$now"
            fi

            if [ $((now - last_report_seconds)) -ge 30 ]; then
                echo "[WEAVE][WAIT] Docker download attempt $attempt/$WEAVE_DOWNLOAD_MAX_ATTEMPTS: $(( (now - start_seconds) ))s elapsed; cache $((current_bytes / 1048576)) MiB; last progress $((now - last_progress_seconds))s ago."
                last_report_seconds="$now"
            fi

            if [ $((now - last_progress_seconds)) -ge "$WEAVE_DOWNLOAD_STALL_SECONDS" ]; then
                echo "[WEAVE][WARN] Docker download has not advanced for $WEAVE_DOWNLOAD_STALL_SECONDS seconds; restarting this download attempt." >&2
                stop_apt_download "$download_pid"
                stalled=1
                break
            fi
        done

        if wait "$download_pid"; then
            exit_code=0
        else
            exit_code=$?
        fi
        WEAVE_ACTIVE_DOWNLOAD_PID=""

        # A zero exit code wins even if the completion raced the idle check.
        if [ "$exit_code" -eq 0 ]; then
            echo "[WEAVE][OK] Docker package download complete. Installation can proceed offline from the APT cache."
            return 0
        fi

        echo "[WEAVE][WARN] Docker download attempt $attempt/$WEAVE_DOWNLOAD_MAX_ATTEMPTS did not complete (exit code $exit_code)." >&2
        if [ "$attempt" -lt "$WEAVE_DOWNLOAD_MAX_ATTEMPTS" ]; then
            delay_seconds=$((5 * attempt))
            echo "[WEAVE][WAIT] Retrying Docker downloads in $delay_seconds seconds; retaining cached packages."
            sleep "$delay_seconds"
        fi
    done

    echo "[WEAVE][ERROR] Docker package downloads failed after $WEAVE_DOWNLOAD_MAX_ATTEMPTS attempts. Check the network and retry bootstrap; completed cached packages are preserved." >&2
    return 1
}

echo "[WEAVE][ACTION] Downloading Docker Engine, Buildx, and Compose packages."
download_docker_packages \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

echo "[WEAVE][ACTION] Installing Docker packages using local cache without network."
apt_weave --no-download install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

echo "[WEAVE][ACTION] Enabling Docker and containerd services."
systemctl enable docker.service
systemctl enable containerd.service
echo "[WEAVE][ACTION] Starting Docker service."
timeout --signal=TERM --kill-after=10s 180s systemctl start docker.service
echo "[WEAVE][OK] Docker Engine installation completed."
'@

    Invoke-WeaveWslScript -Script $dockerProvisioning -FailureMessage "Failed to provision Docker Engine inside '$script:DistroName'."
}


function Assert-DockerRuntimeHealthy {
    Write-WeaveCheck "Verifying Docker Engine connectivity."

    $dockerReady = $false

    for ($attempt = 1; $attempt -le 15; $attempt++) {
        $dockerResult = Invoke-WeaveWslCommand -Arguments @(
            "--distribution",
            $script:DistroName,
            "--user",
            "root",
            "--",
            "docker",
            "info"
        ) -Quiet

        if ($dockerResult.ExitCode -eq 0) {
            $dockerReady = $true
            break
        }

        Write-WeaveWait "Waiting for Docker Engine to become reachable (attempt $attempt/15)."
        Start-Sleep -Seconds 1
    }

    if (-not $dockerReady) {
        throw "Docker Engine did not become reachable inside '$script:DistroName'."
    }

    Write-WeaveSuccess "Docker Engine is reachable."

    Write-WeaveCheck "Verifying Docker Compose plugin."
    $composeResult = Invoke-WeaveWslCommand -Arguments @(
        "--distribution",
        $script:DistroName,
        "--user",
        "root",
        "--",
        "docker",
        "compose",
        "version"
    ) -CaptureOutput

    if ($composeResult.ExitCode -ne 0) {
        throw "Docker Compose plugin is not available inside '$script:DistroName'."
    }

    Write-WeaveSuccess (($composeResult.Output -join " ").Trim())
}


function Write-RuntimeMarker {
    Write-WeaveAction "Writing WEAVE runtime marker inside '$script:DistroName'."

    $markerScript = @'
set -eu

cat > /etc/weave-cbt-runtime <<'EOF'
runtime_name=WeaveCBT
schema_version=1
EOF

chmod 0644 /etc/weave-cbt-runtime
'@

    Invoke-WeaveWslScript -Script $markerScript -FailureMessage "Failed to write WEAVE CBT runtime marker."
    Write-WeaveSuccess "WEAVE runtime marker is present."
}


Assert-Administrator

Write-WeaveCheck "Locating wsl.exe."
$wslCommand = Get-Command "wsl.exe" -ErrorAction SilentlyContinue

if (-not $wslCommand) {
    throw (
        "wsl.exe is unavailable. WEAVE CBT requires a supported Windows " +
        "version with Windows Subsystem for Linux."
    )
}

Write-WeaveSuccess "Using WSL executable '$($wslCommand.Source)'."

$script:WslExecutable = $wslCommand.Source
$script:DistroName = $DistroName
$script:WeaveDataDirectory = $WeaveDataDirectory
$script:DistroInstallDirectory = $DistroInstallDirectory
$script:BootstrapStatePath = $BootstrapStatePath
$script:BootstrapStateSchemaVersion = $BootstrapStateSchemaVersion
$script:RebootRequiredExitCode = $RebootRequiredExitCode
$script:RootSessionWarningShown = $false

Write-WeaveStep "Starting Windows runtime bootstrap for WEAVE CBT."
Assert-WindowsWsl2Compatibility
Ensure-WslAvailable
Ensure-WslSystemdSupport
Ensure-WeaveDistro
Ensure-WeaveDistroUsesWsl2
Configure-Systemd
Repair-RootSystemdUserSession
Install-DockerEngine
Assert-DockerRuntimeHealthy
Write-RuntimeMarker
Remove-BootstrapState

Write-WeaveSuccess (
    "Windows runtime provisioning complete. " +
    "Docker is running inside WSL distribution '$DistroName'."
)

exit 0
