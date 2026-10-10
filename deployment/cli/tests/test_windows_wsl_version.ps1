$ErrorActionPreference = 'Stop'
$bootstrap = Join-Path $PSScriptRoot '..\..\bootstrap\windows\bootstrap.ps1'
$content = Get-Content -LiteralPath $bootstrap -Raw
foreach ($name in @('Get-WeaveWslCommandResult', 'Ensure-WslSystemdSupport')) {
    $match = [regex]::Match($content, '(?ms)^function ' + [regex]::Escape($name) + ' \{.*?^\}')
    if (-not $match.Success) { throw "Unable to extract WSL function $name." }
    Invoke-Expression $match.Value
}

function Write-WeaveCheck { param([string]$Message) }
function Write-WeaveAction { param([string]$Message) }
function Write-WeaveSuccess { param([string]$Message) }
function Write-WeaveWarning { param([string]$Message) }
$script:LatestVersion = [Version]'2.4.5.0'
$script:LatestWslMsiAsset = $null
function Get-LatestMicrosoftWslMsiAsset {
    $script:LatestWslMsiAsset = [PSCustomObject]@{Version = $script:LatestVersion}
    return $script:LatestWslMsiAsset
}
function Install-LatestMicrosoftWslMsi {
    throw 'MSI should not be necessary for this mocked successful WSL update'
}
function Exit-RebootRequired { param([string]$Message) throw "UNEXPECTED_RESTART" }
$script:RebootRequiredExitCode = 3010
$script:WslCalls = New-Object 'System.Collections.Generic.List[string]'
$script:Mode = 'inbox'
function Invoke-WeaveWslCommand {
    param([string[]]$Arguments, [switch]$CaptureOutput, [int]$TimeoutSeconds)
    if ($TimeoutSeconds -le 0) { throw "WSL command lacks timeout: $($Arguments -join ' ')" }
    $command = $Arguments -join ' '
    $script:WslCalls.Add($command)
    if ($command -eq '--version') {
        Write-Output 'Additional WSL version probe diagnostics'
        if ($script:Mode -eq 'missing-record') {
            return
        }
        if ($script:Mode -eq 'inbox') {
            return [PSCustomObject]@{ExitCode = 1; Output = @()}
        }
        $reportedVersion = if ($script:Mode -eq 'latest') { '3.0.1.0' } else { '2.4.5.0' }
        $nullSeparated = ("WSL version: " + $reportedVersion).ToCharArray() -join [char]0
        return [PSCustomObject]@{ExitCode = 0; Output = @($nullSeparated)}
    }
    if ($command -eq '--update --web-download') {
        $script:Mode = 'modern'
        Write-Output 'Updating official WSL runtime.'
        return [PSCustomObject]@{ExitCode = 0; Output = @()}
    }
    throw "Unexpected WSL command '$command'"
}
Ensure-WslSystemdSupport
if ($script:WslCalls -notcontains '--update --web-download') { throw 'Official WSL update was not invoked.' }
$count = $script:WslCalls.Count
Ensure-WslSystemdSupport
if ($script:WslCalls.Count -ne $count + 1) { throw 'Healthy modern WSL was updated unnecessarily.' }
$script:WslCalls.Clear()
$script:Mode = 'missing-record'
Ensure-WslSystemdSupport
if ($script:WslCalls -notcontains '--update --web-download') {
    throw 'Expected official WSL update if the version probe returns no ExitCode.'
}
$script:WslCalls.Clear()
Ensure-WslSystemdSupport
if ($script:WslCalls.Count -ne 1) {
    throw 'Expected a healthy installed WSL to skip updates despite extra version diagnostic output.'
}
# An already-working but outdated WSL must be upgraded automatically.
$script:WslCalls.Clear()
$script:Mode = 'modern'
$script:LatestVersion = [Version]'3.0.1.0'
$script:UsedMsiFallback = $false
Remove-Item Function:\Install-LatestMicrosoftWslMsi
function Install-LatestMicrosoftWslMsi {
    $script:UsedMsiFallback = $true
    $script:Mode = 'latest'
}
Ensure-WslSystemdSupport
if (-not $script:UsedMsiFallback) {
    throw 'Expected automatic MSI upgrade if WSL was left below the latest stable version.'
}
Write-Output 'Windows PowerShell WSL systemd version/update simulation passed.'
