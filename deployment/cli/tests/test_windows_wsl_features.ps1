$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot '..\..\bootstrap\windows\bootstrap.ps1'
$content = Get-Content -LiteralPath $scriptPath -Raw
foreach ($name in @('Ensure-WslWindowsFeatures', 'Get-WeaveWslCommandResult', 'Get-WeaveWslStatusExitCode', 'Ensure-WslAvailable', 'Get-InstalledWslDistributions', 'Ensure-WeaveDistro')) {
    $pattern = '(?ms)^function ' + [regex]::Escape($name) + ' \{.*?^\}'
    $match = [regex]::Match($content, $pattern)
    if (-not $match.Success) {
        throw "Could not find Windows bootstrap function $name."
    }
    Invoke-Expression $match.Value
}

function Write-WeaveCheck { param($Message) }
function Write-WeaveAction { param($Message) }
function Write-WeaveSkip { param($Message) }
function Write-WeaveWait { param($Message) }
function Write-WeaveSuccess { param($Message) }
function Write-WeaveStep { param($Message) }
function Write-WeaveWarning { param($Message) }

$script:FeatureStates = @{
    'Microsoft-Windows-Subsystem-Linux' = 'Disabled'
    'VirtualMachinePlatform' = 'Disabled'
}
$script:EnabledFeatures = New-Object 'System.Collections.Generic.List[string]'
$script:RebootRequests = 0
$script:PendingWindowsServicingReboot = $false
function Test-WindowsServicingRebootPending {
    return $script:PendingWindowsServicingReboot
}

function Get-WindowsOptionalFeature {
    param([switch]$Online, [string]$FeatureName, $ErrorAction)
    return [PSCustomObject]@{ State = $script:FeatureStates[$FeatureName] }
}

function Enable-WindowsOptionalFeature {
    param([switch]$Online, [string]$FeatureName, [switch]$All, [switch]$NoRestart, $ErrorAction)
    $script:EnabledFeatures.Add($FeatureName)
    $script:FeatureStates[$FeatureName] = 'EnablePending'
}

function Exit-RebootRequired {
    param([string]$Message)
    $script:RebootRequests++
    throw "WEAVE_TEST_REBOOT_REQUIRED"
}

try {
    Ensure-WslWindowsFeatures
    throw "Expected WSL feature setup to request reboot."
}
catch {
    if ($_.Exception.Message -ne "WEAVE_TEST_REBOOT_REQUIRED") {
        throw
    }
}

if ($script:EnabledFeatures.Count -ne 2) {
    throw "Expected both WSL feature installations, got $($script:EnabledFeatures.Count)."
}
if ($script:RebootRequests -ne 1) {
    throw "Expected exactly one reboot request."
}

$script:FeatureStates['Microsoft-Windows-Subsystem-Linux'] = 'Enabled'
$script:FeatureStates['VirtualMachinePlatform'] = 'Enabled'

# Feature state may report Enabled even though servicing needs a reboot.
$script:PendingWindowsServicingReboot = $true
try {
    Ensure-WslWindowsFeatures
    throw "Expected pending servicing reboot to block WSL initialization."
}
catch {
    if ($_.Exception.Message -ne "WEAVE_TEST_REBOOT_REQUIRED") {
        throw
    }
}
if ($script:RebootRequests -ne 2) {
    throw "Expected a second reboot request for pending Windows servicing."
}

$script:PendingWindowsServicingReboot = $false
Ensure-WslWindowsFeatures

$script:SavedState = [PSCustomObject]@{
    stage = 'wsl_reboot_required'
    boot_marker = 'old-boot'
}
$script:RemovedState = $false
$script:WslCalls = New-Object 'System.Collections.Generic.List[string]'
$script:WslStatusCount = 0
$script:InstallMode = 'normal'
$script:RebootRequiredExitCode = 3010

function Read-BootstrapState { return $script:SavedState }
function Get-SystemBootMarker { return 'new-boot' }
function Remove-BootstrapState {
    $script:RemovedState = $true
    $script:SavedState = $null
}
function Write-BootstrapState {
    param($Stage, $RebootRequired, $Message)
}
function Invoke-WeaveWslCommand {
    param([string[]]$Arguments, [switch]$Quiet)
    $command = $Arguments -join ' '
    $script:WslCalls.Add($command)
    if ($command -eq '--list --quiet') {
        Write-Output 'diagnostic line not carrying an exit code'
        if ($script:ListHasNoResult) { return }
        return [PSCustomObject]@{ ExitCode = 0; Output = @('Ubuntu', 'WeaveCBT') }
    }
    if ($command -eq '--status') {
        $script:WslStatusCount++
        if ($script:WslStatusCount -eq 1) {
            Write-Output "The Windows Subsystem for Linux is not installed."
            return [PSCustomObject]@{ExitCode = 1}
        }
    }
    if ($command -eq '--install --no-distribution') {
        Write-Output 'WSL installer emitted additional native output.'
        if ($script:InstallMode -eq 'native-fails') {
            return [PSCustomObject]@{ExitCode = 1}
        }
        if ($script:InstallMode -eq 'missing-record') {
            # The exact failure seen on Windows: no usable ExitCode record.
            return
        }
        return [PSCustomObject]@{ExitCode = 0}
    }
    if ($command -eq '--install --no-distribution --web-download') {
        Write-Output 'Official WSL web-download is finishing.'
        if ($script:InstallMode -eq 'native-fails') {
            return [PSCustomObject]@{ExitCode = 1}
        }
        return [PSCustomObject]@{ExitCode = 0}
    }
    return [PSCustomObject]@{ExitCode = 0}
}

Ensure-WslAvailable

if (-not $script:RemovedState) {
    throw "Expected stale reboot state to be cleared on the second boot."
}
if ($script:WslCalls -notcontains '--install --no-distribution') {
    throw "Expected WSL runtime installation without a default distribution."
}
if ($script:WslStatusCount -ne 2) {
    throw "Expected WSL status to be checked twice."
}


# Fresh host: initial installer command returns only a diagnostic and no
# structured result. Bootstrap must fall back to Microsoft's web-download
# method rather than throwing PropertyNotFoundStrict on ExitCode.
$script:WslCalls.Clear()
$script:WslStatusCount = 0
$script:SavedState = $null
$script:RemovedState = $false
$script:InstallMode = 'missing-record'
Ensure-WslAvailable
if ($script:WslCalls -notcontains '--install --no-distribution --web-download') {
    throw 'Expected official WSL web-download fallback after missing install ExitCode.'
}
if ($script:WslStatusCount -ne 2) {
    throw 'Expected WSL status to be verified after web-download fallback.'
}

# If the native WSL installer refuses both normal methods, the official
# Microsoft MSI must be installed without requiring user intervention.
$script:WslCalls.Clear()
$script:WslStatusCount = 0
$script:SavedState = $null
$script:InstallMode = 'native-fails'
$script:MsiInstallCount = 0
function Install-LatestMicrosoftWslMsi { $script:MsiInstallCount++ }
Ensure-WslAvailable
if ($script:MsiInstallCount -ne 1) {
    throw 'Expected automatic Microsoft WSL MSI fallback when native commands fail.'
}
if ($script:WslCalls -notcontains '--install --no-distribution --web-download') {
    throw 'Expected both built-in WSL commands before MSI fallback.'
}

$script:ListHasNoResult = $false
$distributions = @(Get-InstalledWslDistributions)
if ($distributions.Count -ne 2 -or $distributions -notcontains 'WeaveCBT') {
    throw "WSL distribution enumeration ignored a valid structured result."
}
$script:ListHasNoResult = $true
try {
    Get-InstalledWslDistributions | Out-Null
    throw 'Expected missing structured WSL distribution list to fail.'
}
catch {
    if ($_.Exception.Message -notlike '*Failed to list installed WSL distributions*') {
        throw
    }
}
# Exercise the actual production Ensure-WeaveDistro code with empty,
# single-entry, and multi-entry lists. PowerShell 5.1 with StrictMode
# must not attempt to access Count on a scalar or null.
Set-StrictMode -Version Latest
$script:DistroName = 'WeaveCBT'
$script:MockInstalledNames = @()
$script:RootfsRequests = 0
$script:UbuntuChecks = 0

function Get-InstalledWslDistributions {
    return $script:MockInstalledNames
}
function Ensure-UbuntuRootfs {
    $script:RootfsRequests++
    throw 'WEAVE_TEST_ROOTFS_REQUESTED'
}
function Assert-WeaveDistroIsUbuntu {
    $script:UbuntuChecks++
}

foreach ($names in @(
    [PSCustomObject]@{Names = @(); Rootfs = $true},
    [PSCustomObject]@{Names = @('Ubuntu'); Rootfs = $true},
    [PSCustomObject]@{Names = @('Ubuntu', 'Debian'); Rootfs = $true},
    [PSCustomObject]@{Names = @('WeaveCBT'); Rootfs = $false}
)) {
    $script:MockInstalledNames = @($names.Names)
    if ($names.Rootfs) {
        try {
            Ensure-WeaveDistro
            throw 'Expected Ubuntu download request.'
        }
        catch {
            if ($_.Exception.Message -ne 'WEAVE_TEST_ROOTFS_REQUESTED') {
                throw
            }
        }
    }
    else {
        Ensure-WeaveDistro
    }
}
if ($script:RootfsRequests -ne 3) {
    throw "Expected 3 Ubuntu download attempts, got $($script:RootfsRequests)."
}
if ($script:UbuntuChecks -ne 1) {
    throw "Expected to verify existing WeaveCBT distro once, got $($script:UbuntuChecks)."
}

Write-Output "Windows feature enable/reboot/resume simulation passed."
