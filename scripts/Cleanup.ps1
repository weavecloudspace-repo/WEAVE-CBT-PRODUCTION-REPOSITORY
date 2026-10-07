param([switch]$Preview)

$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$targets = @(
    '.ruff_cache', '.uv-cache',
    'backend/.pytest_cache', 'backend/.ruff_cache',
    'frontend/dist', 'frontend/.vite', 'frontend/node_modules/.vite',
    'frontend/node_modules/.vite-temp'
)
# Vite verification builds can be created below either app root.
foreach ($buildRoot in @('frontend', 'frontend/apps/staff', 'frontend/apps/student')) {
    $buildPath = Join-Path $repositoryRoot $buildRoot
    if (Test-Path -LiteralPath $buildPath) {
        $targets += Get-ChildItem -LiteralPath $buildPath -Directory -Filter 'dist-*' |
            ForEach-Object { $_.FullName }
    }
}
$sourceRoots = @('backend/app', 'backend/tests')
foreach ($sourceRoot in $sourceRoots) {
    $sourcePath = Join-Path $repositoryRoot $sourceRoot
    if (Test-Path -LiteralPath $sourcePath) {
        $targets += Get-ChildItem -LiteralPath $sourcePath -Directory -Recurse -Filter '__pycache__' |
            ForEach-Object { $_.FullName }
    }
}
foreach ($target in $targets) {
    $targetPath = if ([IO.Path]::IsPathRooted($target)) { $target } else { Join-Path $repositoryRoot $target }
    $resolvedTarget = [IO.Path]::GetFullPath($targetPath)
    if (-not $resolvedTarget.StartsWith($repositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup target is outside the repository: $resolvedTarget"
    }
    if (Test-Path -LiteralPath $resolvedTarget) {
        if ((Get-Item -LiteralPath $resolvedTarget).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to clean a linked directory: $resolvedTarget"
        }
        if ($Preview) {
            Write-Output "Would remove $resolvedTarget"
        } else {
            Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
            Write-Output "Removed $resolvedTarget"
        }
    }
}
