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

$DistroInstallDirectory = Join-Path $programData "WeaveCBT\wsl"


function Write-WeaveStep {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )

    Write-Host "[WEAVE] $Message"
}


function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)

    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "WEAVE CBT bootstrap must be run from an elevated Administrator session."
    }
}


function Invoke-WeaveWslScript {
    param(
        [Parameter(Mandatory)]
        [string]$Script,

        [Parameter(Mandatory)]
        [string]$FailureMessage
    )

    $scriptBytes = [Text.Encoding]::UTF8.GetBytes($Script)
    $encodedScript = [Convert]::ToBase64String($scriptBytes)

    & $script:WslExecutable --distribution $script:DistroName --user root -- /bin/sh -lc "printf '%s' '$encodedScript' | base64 -d | /bin/bash"

    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}


function Get-InstalledWslDistributions {
    $names = @(
        & $script:WslExecutable --list --quiet 2>$null |
            ForEach-Object {
                ($_ -replace [char]0, "").Trim()
            } |
            Where-Object {
                $_
            }
    )

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to list installed WSL distributions."
    }

    return $names
}


function Assert-WeaveDistroIsUbuntu {
    $distributionId = & $script:WslExecutable --distribution $script:DistroName --user root -- /bin/sh -lc '. /etc/os-release; printf "%s" "$ID"' 2>$null

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect the '$script:DistroName' WSL distribution."
    }

    $distributionId = (($distributionId -join "").Trim()).ToLowerInvariant()

    if ($distributionId -ne "ubuntu") {
        throw (
            "The '$script:DistroName' WSL distribution must be Ubuntu. " +
            "Detected '$distributionId'."
        )
    }
}


function Ensure-WslAvailable {
    Write-WeaveStep "Checking Windows Subsystem for Linux."

    & $script:WslExecutable --status *> $null

    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-WeaveStep "WSL is not initialized. Installing WSL prerequisites."

    & $script:WslExecutable --install --no-distribution

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Windows Subsystem for Linux."
    }

    & $script:WslExecutable --status *> $null

    if ($LASTEXITCODE -ne 0) {
        Write-Error (
            "WSL prerequisites were installed, but Windows must be restarted " +
            "before WEAVE CBT provisioning can continue."
        )

        exit 3010
    }
}


function Ensure-WeaveDistro {
    $installedDistros = Get-InstalledWslDistributions

    if ($installedDistros -contains $script:DistroName) {
        Write-WeaveStep "Using existing '$script:DistroName' WSL distribution."
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

    Write-WeaveStep "Importing dedicated '$script:DistroName' WSL2 distribution."

    & $script:WslExecutable --import $script:DistroName $script:DistroInstallDirectory $resolvedRootfs --version 2

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to import the '$script:DistroName' WSL distribution."
    }

    Assert-WeaveDistroIsUbuntu
}


function Ensure-WeaveDistroUsesWsl2 {
    $verboseOutput = @(
        & $script:WslExecutable --list --verbose 2>$null |
            ForEach-Object {
                $_ -replace [char]0, ""
            }
    )

    if ($LASTEXITCODE -ne 0) {
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
        return
    }

    Write-WeaveStep "Converting '$script:DistroName' to WSL2."

    & $script:WslExecutable --set-version $script:DistroName 2

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to convert '$script:DistroName' to WSL2."
    }
}


function Configure-Systemd {
    Write-WeaveStep "Configuring systemd inside '$script:DistroName'."

    $systemdConfiguration = @'
set -eu

cat > /etc/wsl.conf <<'EOF'
[boot]
systemd=true

[user]
default=root
EOF
'@

    Invoke-WeaveWslScript -Script $systemdConfiguration -FailureMessage "Failed to configure systemd inside '$script:DistroName'."

    & $script:WslExecutable --terminate $script:DistroName

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to restart the '$script:DistroName' WSL distribution."
    }

    $systemdReady = $false

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        $pidOne = & $script:WslExecutable --distribution $script:DistroName --user root -- /bin/sh -lc 'ps -p 1 -o comm=' 2>$null

        if ($LASTEXITCODE -eq 0) {
            $pidOne = (($pidOne -join "").Trim())

            if ($pidOne -eq "systemd") {
                $systemdReady = $true
                break
            }
        }

        Start-Sleep -Seconds 1
    }

    if (-not $systemdReady) {
        throw (
            "systemd did not start inside '$script:DistroName'. " +
            "Update WSL with 'wsl --update', restart Windows if requested, " +
            "and retry WEAVE CBT installation."
        )
    }
}


function Install-DockerEngine {
    Write-WeaveStep "Provisioning Docker Engine inside '$script:DistroName'."

    $dockerProvisioning = @'
set -eu

. /etc/os-release

if [ "$ID" != "ubuntu" ]; then
    echo "WEAVE CBT requires an Ubuntu WSL runtime." >&2
    exit 20
fi

if command -v docker >/dev/null 2>&1 \
    && command -v dockerd >/dev/null 2>&1 \
    && docker compose version >/dev/null 2>&1 \
    && systemctl cat docker.service >/dev/null 2>&1; then
    systemctl enable docker.service >/dev/null
    systemctl enable containerd.service >/dev/null 2>&1 || true
    systemctl start docker.service
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl

for package in \
    docker.io \
    docker-compose \
    docker-compose-v2 \
    docker-doc \
    podman-docker \
    containerd \
    runc
do
    apt-get remove -y "$package" >/dev/null 2>&1 || true
done

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
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

apt-get update
apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

systemctl enable docker.service
systemctl enable containerd.service
systemctl start docker.service
'@

    Invoke-WeaveWslScript -Script $dockerProvisioning -FailureMessage "Failed to provision Docker Engine inside '$script:DistroName'."
}


function Assert-DockerRuntimeHealthy {
    Write-WeaveStep "Verifying Docker Engine and Docker Compose."

    $dockerReady = $false

    for ($attempt = 1; $attempt -le 15; $attempt++) {
        & $script:WslExecutable --distribution $script:DistroName --user root -- docker info *> $null

        if ($LASTEXITCODE -eq 0) {
            $dockerReady = $true
            break
        }

        Start-Sleep -Seconds 1
    }

    if (-not $dockerReady) {
        throw "Docker Engine did not become reachable inside '$script:DistroName'."
    }

    & $script:WslExecutable --distribution $script:DistroName --user root -- docker compose version *> $null

    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose plugin is not available inside '$script:DistroName'."
    }
}


function Write-RuntimeMarker {
    $markerScript = @'
set -eu

cat > /etc/weave-cbt-runtime <<'EOF'
runtime_name=WeaveCBT
schema_version=1
EOF

chmod 0644 /etc/weave-cbt-runtime
'@

    Invoke-WeaveWslScript -Script $markerScript -FailureMessage "Failed to write WEAVE CBT runtime marker."
}


Assert-Administrator

$wslCommand = Get-Command "wsl.exe" -ErrorAction SilentlyContinue

if (-not $wslCommand) {
    throw (
        "wsl.exe is unavailable. WEAVE CBT requires a supported Windows " +
        "version with Windows Subsystem for Linux."
    )
}

$script:WslExecutable = $wslCommand.Source
$script:DistroName = $DistroName
$script:DistroInstallDirectory = $DistroInstallDirectory

Ensure-WslAvailable
Ensure-WeaveDistro
Ensure-WeaveDistroUsesWsl2
Configure-Systemd
Install-DockerEngine
Assert-DockerRuntimeHealthy
Write-RuntimeMarker

Write-WeaveStep (
    "Windows runtime provisioning complete. " +
    "Docker is running inside WSL distribution '$DistroName'."
)

exit 0
