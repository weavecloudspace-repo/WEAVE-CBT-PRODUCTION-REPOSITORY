$ErrorActionPreference = 'Stop'
$bootstrapPath = Join-Path $PSScriptRoot '..\..\bootstrap\windows\bootstrap.ps1'
$content = Get-Content -LiteralPath $bootstrapPath -Raw

foreach ($name in @('Write-BootstrapState', 'Read-BootstrapState', 'Remove-BootstrapState')) {
    $pattern = '(?ms)^function ' + [regex]::Escape($name) + ' \{.*?^\}'
    $match = [regex]::Match($content, $pattern)
    if (-not $match.Success) {
        throw "Could not extract bootstrap function '$name'."
    }
    Invoke-Expression $match.Value
}

function Get-SystemBootMarker {
    return 'test-boot-one'
}

$testDirectory = Join-Path ([IO.Path]::GetTempPath()) ('weave-cbt-state-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testDirectory -Force | Out-Null

$script:WeaveDataDirectory = $testDirectory
$script:BootstrapStatePath = Join-Path $testDirectory 'bootstrap-state.json'
$script:BootstrapStateSchemaVersion = 1

try {
    # First write creates the file without a destination to replace.
    Write-BootstrapState -Stage 'wsl_prerequisites_installing' -RebootRequired $false -Message 'start'
    $first = Read-BootstrapState
    if ($first.stage -ne 'wsl_prerequisites_installing') {
        throw 'First state write did not persist.'
    }

    # A real fresh Windows Server executes this second write before reboot:
    # the existing state file must be replaced atomically.
    Write-BootstrapState -Stage 'wsl_reboot_required' -RebootRequired $true -Message 'restart required'
    $second = Read-BootstrapState

    if ($second.stage -ne 'wsl_reboot_required' -or -not $second.reboot_required) {
        throw 'Reboot-required state replacement did not persist.'
    }
    if ($second.boot_marker -ne 'test-boot-one') {
        throw 'Reboot state boot marker is incorrect.'
    }

    # Verify that a third replacement also works on Windows PowerShell 5.1.
    Write-BootstrapState -Stage 'wsl_prerequisites_installing' -RebootRequired $false -Message 'resuming'
    $third = Read-BootstrapState
    if ($third.message -ne 'resuming') {
        throw 'Subsequent state replacement did not persist.'
    }

    $leftovers = @(Get-ChildItem -LiteralPath $testDirectory -Force |
        Where-Object { $_.Name -like '.bootstrap-state.*' })
    if ($leftovers.Count -ne 0) {
        throw "Temporary state/backup files remain after a successful write: $($leftovers.Name -join ', ')"
    }

    Remove-BootstrapState
    if (Test-Path -LiteralPath $script:BootstrapStatePath) {
        throw 'State removal did not remove the state file.'
    }

    Write-Output 'Windows state creation/replacement/reboot persistence tests passed.'
}
finally {
    Remove-Item -LiteralPath $testDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
