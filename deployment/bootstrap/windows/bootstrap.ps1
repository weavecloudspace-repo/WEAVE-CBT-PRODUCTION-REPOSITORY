[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$RootfsArchive
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

    Write-Host "[WEAVE] $Message"
}


function Write-WeaveCheck {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][CHECK] $Message"
}


function Write-WeaveAction {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][ACTION] $Message"
}


function Write-WeaveSuccess {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][OK] $Message"
}


function Write-WeaveSkip {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][SKIP] $Message"
}


function Write-WeaveWait {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][WAIT] $Message"
}


function Write-WeaveWarning {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WEAVE][WARN] $Message"
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
            [IO.File]::Replace($temporaryPath, $script:BootstrapStatePath, $null, $true)
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

        if ($startInfo.RedirectStandardInput) {
            $process.StandardInput.Write($InputText)
            $process.StandardInput.Close()
        }

        # Read stderr concurrently so diagnostic output cannot fill its pipe
        # while we display Docker/apt stdout as it arrives.
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $stdoutText = ""

        if ($CaptureOutput -or $Quiet) {
            $stdoutTask = $process.StandardOutput.ReadToEndAsync()
            $process.WaitForExit()
            $stdoutText = $stdoutTask.GetAwaiter().GetResult()
        }
        else {
            # Stream each line from WSL in this PowerShell thread. Using
            # ReadLineAsync permits a visible heartbeat even if apt is silent.
            $outputLineTask = $process.StandardOutput.ReadLineAsync()
            $idleWatch = [Diagnostics.Stopwatch]::StartNew()
            $elapsedWatch = [Diagnostics.Stopwatch]::StartNew()

            while ($true) {
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

            while (-not $process.WaitForExit(1000)) {
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

function Ensure-WslAvailable {
    Write-WeaveStep "Checking Windows Subsystem for Linux."

    $bootstrapState = Read-BootstrapState

    $statusResult = Invoke-WeaveWslCommand -Arguments @("--status") -Quiet

    if ($statusResult.ExitCode -eq 0) {
        Write-WeaveSuccess "WSL is available."

        if ($null -ne $bootstrapState -and $bootstrapState.stage -eq "wsl_reboot_required") {
            Write-WeaveSuccess "Windows restart completed; resuming WEAVE CBT provisioning."
            Remove-BootstrapState
        }

        return
    }

    if ($null -ne $bootstrapState -and $bootstrapState.stage -eq "wsl_reboot_required") {
        $currentBootMarker = Get-SystemBootMarker
        $recordedBootMarker = $bootstrapState.boot_marker

        if ($recordedBootMarker -and $currentBootMarker -and $recordedBootMarker -ne $currentBootMarker) {
            Remove-BootstrapState
            throw (
                "Windows restarted, but WSL is still unavailable. " +
                "This is no longer treated as a pending reboot. Check 'wsl --status', " +
                "virtualization support, and Windows optional-feature state before retrying."
            )
        }

        Exit-RebootRequired -Message "Windows still needs to restart before WSL can be used by WEAVE CBT."
    }

    Write-WeaveAction "WSL is not initialized. Installing WSL prerequisites."

    Write-BootstrapState -Stage "wsl_prerequisites_installing" -RebootRequired $false -Message "Installing Windows Subsystem for Linux prerequisites."

    $installResult = Invoke-WeaveWslCommand -Arguments @(
        "--install",
        "--no-distribution"
    )
    $installExitCode = $installResult.ExitCode

    if ($installExitCode -ne 0 -and $installExitCode -ne $script:RebootRequiredExitCode) {
        Remove-BootstrapState
        throw (
            "Failed to install Windows Subsystem for Linux. " +
            "wsl.exe exited with code $installExitCode."
        )
    }

    $statusResult = Invoke-WeaveWslCommand -Arguments @("--status") -Quiet

    if ($statusResult.ExitCode -eq 0) {
        Remove-BootstrapState
        Write-WeaveSuccess "WSL prerequisites are ready."
        return
    }

    Exit-RebootRequired -Message (
        "WSL prerequisites were installed successfully, but Windows must " +
        "restart before WEAVE CBT provisioning can continue."
    )
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

    if (-not $RootfsArchive) {
        throw (
            "The '$script:DistroName' WSL distribution is not installed. " +
            "A staged Ubuntu root filesystem must be supplied with -RootfsArchive."
        )
    }

    if (-not (Test-Path -LiteralPath $RootfsArchive -PathType Leaf)) {
        throw "WSL root filesystem archive '$RootfsArchive' does not exist."
    }

    $resolvedRootfs = (Resolve-Path -LiteralPath $RootfsArchive).Path

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

    Write-WeaveAction "Importing dedicated '$script:DistroName' WSL2 distribution into '$script:DistroInstallDirectory'."

    $importResult = Invoke-WeaveWslCommand -Arguments @(
        "--import",
        $script:DistroName,
        $script:DistroInstallDirectory,
        $resolvedRootfs,
        "--version",
        "2"
    )

    if ($importResult.ExitCode -ne 0) {
        throw "Failed to import the '$script:DistroName' WSL distribution."
    }

    Write-WeaveSuccess "'$script:DistroName' was imported successfully."
    Assert-WeaveDistroIsUbuntu
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
    apt-get update
    apt-get install -y dbus-user-session libpam-systemd
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
systemctl start user@0.service

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
    systemctl start docker.service
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
apt_weave update
echo "[WEAVE][ACTION] Installing repository prerequisites."
apt_weave install -y ca-certificates curl

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
apt_weave update

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
systemctl start docker.service
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
Ensure-WslAvailable
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
