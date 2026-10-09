$ErrorActionPreference = 'Stop'
$bootstrap = Join-Path $PSScriptRoot '..\..\bootstrap\windows\bootstrap.ps1'
$content = Get-Content -LiteralPath $bootstrap -Raw
$match = [regex]::Match($content, '(?ms)^function Ensure-WslSystemdSupport \{.*?^\}')
if (-not $match.Success) { throw 'Unable to extract WSL systemd support function.' }
Invoke-Expression $match.Value

function Write-WeaveCheck { param([string]$Message) }
function Write-WeaveAction { param([string]$Message) }
function Write-WeaveSuccess { param([string]$Message) }
function Write-WeaveWarning { param([string]$Message) }
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
        if ($script:Mode -eq 'inbox') {
            return [PSCustomObject]@{ExitCode = 1; Output = @()}
        }
        $nullSeparated = "WSL version: 2.4.5.0".ToCharArray() -join [char]0
        return [PSCustomObject]@{ExitCode = 0; Output = @($nullSeparated)}
    }
    if ($command -eq '--update --web-download') {
        $script:Mode = 'modern'
        return [PSCustomObject]@{ExitCode = 0; Output = @()}
    }
    throw "Unexpected WSL command '$command'"
}
Ensure-WslSystemdSupport
if ($script:WslCalls -notcontains '--update --web-download') { throw 'Official WSL update was not invoked.' }
$count = $script:WslCalls.Count
Ensure-WslSystemdSupport
if ($script:WslCalls.Count -ne $count + 1) { throw 'Healthy modern WSL was updated unnecessarily.' }
Write-Output 'Windows PowerShell WSL systemd version/update simulation passed.'
