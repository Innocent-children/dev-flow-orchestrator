[CmdletBinding()]
param()

# Source template for the version-matched GitHub Release bootstrap.
# scripts/build_release.py replaces every @DEV_FLOW_*@ token before promotion.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$BootstrapSchema = '@DEV_FLOW_BOOTSTRAP_SCHEMA@'
$Repository = '@DEV_FLOW_REPOSITORY@'
$ReleaseVersion = '@DEV_FLOW_RELEASE_VERSION@'
$ArchiveName = '@DEV_FLOW_ARCHIVE_NAME@'
$IndexSha256 = '@DEV_FLOW_INDEX_SHA256@'
$PhaseABase64 = '@DEV_FLOW_PHASE_A_B64@'

if ($IndexSha256.StartsWith('@DEV_FLOW_')) {
    [Console]::Error.WriteLine('This file is a release template; run the version-specific install.ps1 asset from an official GitHub Release.')
    exit 2
}
if (Test-Path Env:DEV_FLOW_SOURCE_ROOT) {
    [Console]::Error.WriteLine('DEV_FLOW_SOURCE_ROOT is not supported by artifact installation.')
    exit 1
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

$PhaseADir = Join-Path ([System.IO.Path]::GetTempPath()) ('dev-flow-bootstrap-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($PhaseADir) | Out-Null
$PhaseAPath = Join-Path $PhaseADir 'release_artifact.py'
try {
    [System.IO.File]::WriteAllBytes($PhaseAPath, [System.Convert]::FromBase64String($PhaseABase64))
    & $PythonCommand @PythonPrefix -I -S $PhaseAPath bootstrap `
        --repository $Repository `
        --version $ReleaseVersion `
        --archive-name $ArchiveName `
        --index-sha256 $IndexSha256 `
        -- @args
    exit $LASTEXITCODE
} finally {
    if ([System.IO.File]::Exists($PhaseAPath)) { [System.IO.File]::Delete($PhaseAPath) }
    if ([System.IO.Directory]::Exists($PhaseADir)) { [System.IO.Directory]::Delete($PhaseADir, $false) }
}
