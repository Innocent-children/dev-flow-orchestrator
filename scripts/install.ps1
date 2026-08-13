[CmdletBinding()]
param()

# Source template for the canonical GitHub Release first-install entry.
# scripts/build_release.py replaces every @DEV_FLOW_*@ token before promotion.
# This entry accepts <MAJOR.MINOR.PATCH|latest>, resolves and downloads the
# matching versioned bootstrap, and executes it; Phase A and Phase B then run
# exactly as in the versioned asset.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$BootstrapSchema = '@DEV_FLOW_BOOTSTRAP_SCHEMA@'
$Repository = '@DEV_FLOW_REPOSITORY@'
$ResolverBase64 = '@DEV_FLOW_RESOLVER_B64@'

if ($BootstrapSchema.StartsWith('@DEV_FLOW_')) {
    [Console]::Error.WriteLine('This file is a release template; run the version-specific install asset from an official GitHub Release.')
    exit 2
}
if (Test-Path Env:DEV_FLOW_SOURCE_ROOT) {
    [Console]::Error.WriteLine('DEV_FLOW_SOURCE_ROOT is not supported by artifact installation.')
    exit 1
}
if ($args.Count -lt 1) {
    [Console]::Error.WriteLine('Usage: install.ps1 <MAJOR.MINOR.PATCH|latest> [Phase B options]')
    exit 2
}
$Requested = [string]$args[0]
$Remaining = @()
if ($args.Count -gt 1) {
    $Remaining = @($args | Select-Object -Skip 1)
}

$PythonCommand = $null
$PythonPrefix = @()
foreach ($Candidate in @(
    @{ Name = 'python'; Prefix = @() },
    @{ Name = 'python3'; Prefix = @() },
    @{ Name = 'py'; Prefix = @('-3') }
)) {
    $Resolved = Get-Command $Candidate.Name -ErrorAction SilentlyContinue
    if ($null -eq $Resolved) { continue }
    & $Resolved.Source @($Candidate.Prefix) -I -S -c 'import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (3, 15)))'
    if ($LASTEXITCODE -eq 0) {
        $PythonCommand = $Resolved.Source
        $PythonPrefix = @($Candidate.Prefix)
        break
    }
}
if ($null -eq $PythonCommand) {
    [Console]::Error.WriteLine('Python >=3.10,<3.15 is required.')
    exit 1
}

$ResolverDir = Join-Path ([System.IO.Path]::GetTempPath()) ('dev-flow-install-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($ResolverDir) | Out-Null
$ResolverPath = Join-Path $ResolverDir 'release_resolver.py'
try {
    [System.IO.File]::WriteAllBytes($ResolverPath, [System.Convert]::FromBase64String($ResolverBase64))
    & $PythonCommand @PythonPrefix -I -S $ResolverPath install `
        --repository $Repository `
        --requested $Requested `
        -- @Remaining
    exit $LASTEXITCODE
} finally {
    if ([System.IO.File]::Exists($ResolverPath)) { [System.IO.File]::Delete($ResolverPath) }
    if ([System.IO.Directory]::Exists($ResolverDir)) { [System.IO.Directory]::Delete($ResolverDir, $false) }
}
