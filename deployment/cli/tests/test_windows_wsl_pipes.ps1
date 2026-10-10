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
# Windows hosts without WSL return an error on stderr for wsl --status.
# The quiet native probe must still yield one structured exit-code object.
$missingWslArgs = @(
    '-NoProfile', '-NonInteractive', '-Command',
    '[Console]::Error.WriteLine("The Windows Subsystem for Linux is not installed."); exit 1'
)
try {
    $missingWsl = @(Invoke-WeaveWslCommand -Arguments $missingWslArgs -Quiet -TimeoutSeconds 30)
}
catch {
    Write-Output "NATIVE FAILURE DEBUG: $($_.Exception.GetType().FullName) / $($_.Exception.Message)"
    Write-Output "NATIVE FAILURE STACK: $($_.ScriptStackTrace)"
    throw
}
if ($missingWsl.Count -ne 1) {
    throw "Quiet native probe returned $($missingWsl.Count) success records."
}
if ($null -eq $missingWsl[0].PSObject.Properties['ExitCode']) {
    throw 'Quiet native probe returned no ExitCode property.'
}
if ($missingWsl[0].ExitCode -ne 1) {
    throw "Expected missing-WSL exit code 1, received $($missingWsl[0].ExitCode)."
}
if (($missingWsl[0].ErrorOutput -join ' ') -notlike '*not installed*') {
    throw 'Missing-WSL stderr diagnostic was not captured.'
}

$script:StreamLines = 0
function Write-Host { param([string]$Object) $script:StreamLines++ }
$streamResult = Invoke-WeaveWslCommand -Arguments $arguments -InputText $payload -TimeoutSeconds 30
if ($streamResult.ExitCode -ne 0) { throw "Streaming child failed: $($streamResult.ErrorOutput)" }
if ($script:StreamLines -lt 600) { throw "Expected 600 live streamed lines; got $script:StreamLines" }
Write-Output 'Windows PowerShell 5.1 captured and streamed native pipe tests passed.'
