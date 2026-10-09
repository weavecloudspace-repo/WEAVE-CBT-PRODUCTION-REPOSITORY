# Run this explicitly in Windows PowerShell 5.1 (powershell.exe), not pwsh.
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw 'WEAVE Windows setup requires Windows PowerShell 5.1 or newer.'
}

$nativeCommands = @(
    'powershell.exe', 'wsl.exe', 'curl.exe',
    'Get-Command', 'Get-CimInstance', 'Get-FileHash',
    'Get-WindowsOptionalFeature', 'Enable-WindowsOptionalFeature',
    'Get-ScheduledTask', 'Register-ScheduledTask', 'New-ScheduledTaskTrigger',
    'icacls.exe', 'netsh.exe'
)
foreach ($name in $nativeCommands) {
    if (-not (Get-Command -Name $name -ErrorAction SilentlyContinue)) {
        throw "Native Windows command/cmdlet '$name' is unavailable on CI host."
    }
}

$payload = @'
function Test-PowerShell-Compat {
    [Text.UTF8Encoding]::new($false) | Out-Null
    [Version]::new(0,67,6) | Out-Null
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.RedirectStandardError = $true
    $startInfo.RedirectStandardInput = $true
}
'@
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseInput(
    $payload, [ref]$tokens, [ref]$parseErrors
) | Out-Null
if ($parseErrors.Count -gt 0) {
    throw 'Bootstrap Windows PowerShell 5.1 syntax is not valid.'
}

# Confirm supported overloads and .NET types in actual Windows PowerShell.
Invoke-Expression $payload
Test-PowerShell-Compat
Write-Output "Windows PowerShell $($PSVersionTable.PSVersion): required Windows-native commands/types are available."
