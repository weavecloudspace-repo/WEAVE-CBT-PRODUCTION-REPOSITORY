# PowerShell 5.1 process-pipe regression test; no WSL installation required.
$ErrorActionPreference = 'Stop'
$source = Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\..\bootstrap\windows\bootstrap.ps1') -Raw
foreach ($name in @('ConvertTo-NativeArgument', 'Invoke-WeaveWslCommand')) {
    $pattern = '(?ms)^function ' + [Regex]::Escape($name) + ' \{.*?^\}'
    $found = [regex]::Match($source, $pattern)
    if (-not $found.Success) { throw "Unable to find bootstrap helper $name." }
    Invoke-Expression $found.Value
}
function Write-WeaveWait { param([string]$Message) }
function Write-WeaveWarning { param([string]$Message) }
$script:RootSessionWarningShown = $false
$script:WslExecutable = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

# Larger than anonymous Windows pipe buffers. Synchronous stdin writing
# before reading child stdout would risk a deadlock here.
$line = ('X' * 256) + [Environment]::NewLine
$payload = $line * 600
$arguments = @('-NoProfile', '-NonInteractive', '-Command', '$input | ForEach-Object { Write-Output $_ }')
$result = Invoke-WeaveWslCommand -Arguments $arguments -InputText $payload -CaptureOutput -TimeoutSeconds 30
if ($result.ExitCode -ne 0) { throw "Native process failed: $($result.ErrorOutput -join ' ')" }
if (@($result.Output).Count -lt 600) { throw "Expected 600 echoed lines; got $(@($result.Output).Count)." }
$script:StreamLines = 0
function Write-Host { param([string]$Object) $script:StreamLines++ }
$streamResult = Invoke-WeaveWslCommand -Arguments $arguments -InputText $payload -TimeoutSeconds 30
if ($streamResult.ExitCode -ne 0) { throw "Streaming child failed: $($streamResult.ErrorOutput)" }
if ($script:StreamLines -lt 600) { throw "Expected 600 live streamed lines; got $script:StreamLines" }
Write-Output 'Windows PowerShell 5.1 captured and streamed native pipe tests passed.'
