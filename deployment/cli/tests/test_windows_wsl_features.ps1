$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot '..\..\bootstrap\windows\bootstrap.ps1'
$content = Get-Content -LiteralPath $scriptPath -Raw
foreach ($name in @('Ensure-WslWindowsFeatures', 'Get-WeaveWslStatusExitCode', 'Ensure-WslAvailable')) {
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
    if ($command -eq '--status') {
        $script:WslStatusCount++
        if ($script:WslStatusCount -eq 1) {
            Write-Output "The Windows Subsystem for Linux is not installed."
            return [PSCustomObject]@{ExitCode = 1}
        }
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

Write-Output "Windows feature enable/reboot/resume simulation passed."
