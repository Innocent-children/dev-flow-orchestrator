[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryUrl = if ($env:DEV_FLOW_REPOSITORY_URL) { $env:DEV_FLOW_REPOSITORY_URL } else { 'https://github.com/Innocent-children/dev-flow-orchestrator.git' }
$RepositoryRef = 'main'
$SourceRoot = if ($env:DEV_FLOW_SOURCE_ROOT) { $env:DEV_FLOW_SOURCE_ROOT } else { Join-Path $env:USERPROFILE 'plugins\dev-flow-orchestrator' }
$MarketplaceFile = if ($env:DEV_FLOW_MARKETPLACE_FILE) { $env:DEV_FLOW_MARKETPLACE_FILE } else { Join-Path $env:USERPROFILE '.agents\plugins\marketplace.json' }
$CodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$PluginId = 'dev-flow-orchestrator@personal'

function Fail([string]$Message) {
    [Console]::Error.WriteLine("Dev Flow installation failed: $Message")
    exit 1
}

function Invoke-Checked([string]$Program, [string[]]$Arguments, [string]$Failure) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { Fail $Failure }
}

function Capture-Checked([string]$Program, [string[]]$Arguments, [string]$Failure) {
    $Output = & $Program @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { Fail $Failure }
    return (($Output | Out-String).Trim())
}

function Find-Python {
    $Candidates = @()
    if ($env:DEV_FLOW_PYTHON) { $Candidates += ,@($env:DEV_FLOW_PYTHON) }
    $Candidates += ,@('py.exe', '-3')
    $Candidates += ,@('python.exe')
    $Candidates += ,@('python3.exe')
    foreach ($Candidate in $Candidates) {
        $Program = $Candidate[0]
        if ($Program -match '[\\/]' -and -not (Test-Path -LiteralPath $Program -PathType Leaf)) { continue }
        if ($Program -notmatch '[\\/]' -and -not (Get-Command $Program -ErrorAction SilentlyContinue)) { continue }
        $Prefix = @()
        if ($Candidate.Count -gt 1) { $Prefix = $Candidate[1..($Candidate.Count - 1)] }
        & $Program @Prefix -c "import struct,sys;sys.exit(0 if (3,9) <= sys.version_info[:2] < (3,15) and struct.calcsize('P') == 8 else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return @{ Program = $Program; Prefix = [string[]]$Prefix } }
    }
    Fail 'Supported 64-bit Python 3.9-3.14 is required.'
}

if ($env:OS -ne 'Windows_NT') { Fail 'This installer requires a supported Windows x64 client.' }
if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { Fail 'This installer requires an x64 process on Windows x64.' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { Fail 'Git for Windows is required.' }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { Fail 'Codex with plugin support is required.' }
$Python = Find-Python

$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$MarketplaceFile = [IO.Path]::GetFullPath($MarketplaceFile)
$MarketplaceDirectory = Split-Path -Parent $MarketplaceFile
$MarketplaceRoot = [IO.Path]::GetFullPath((Join-Path $MarketplaceDirectory '..\..'))
$MarketplacePrefix = $MarketplaceRoot.TrimEnd('\') + '\'
if (-not $SourceRoot.StartsWith($MarketplacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    Fail "$SourceRoot must be inside marketplace root $MarketplaceRoot."
}
$RelativeSource = $SourceRoot.Substring($MarketplacePrefix.Length)
if (-not $RelativeSource) { Fail 'The marketplace root cannot be used as plugin source.' }
if ((Split-Path -Leaf $MarketplaceFile) -ne 'marketplace.json' -or (Split-Path -Leaf $MarketplaceDirectory) -ne 'plugins' -or (Split-Path -Leaf (Split-Path -Parent $MarketplaceDirectory)) -ne '.agents') {
    Fail "$MarketplaceFile must be located at <marketplace-root>\.agents\plugins\marketplace.json."
}

if (-not (Test-Path -LiteralPath $SourceRoot)) {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $SourceRoot)) | Out-Null
    Invoke-Checked 'git.exe' @('clone', '--depth', '1', '--branch', $RepositoryRef, '--single-branch', $RepositoryUrl, $SourceRoot) "Cannot clone authoritative branch '$RepositoryRef'."
} elseif (-not (Test-Path -LiteralPath (Join-Path $SourceRoot '.git') -PathType Container)) {
    Fail "$SourceRoot already exists and is not a Git checkout."
}

$Origin = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'remote', 'get-url', 'origin') "Cannot inspect origin at $SourceRoot."
if ($Origin -ne $RepositoryUrl) { Fail "$SourceRoot origin is '$Origin', expected '$RepositoryUrl'." }
$Branch = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'symbolic-ref', '--quiet', '--short', 'HEAD') "$SourceRoot must have an attached branch."
if ($Branch -ne $RepositoryRef) { Fail "$SourceRoot is on '$Branch', expected branch '$RepositoryRef'." }
$Status = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'status', '--porcelain') "Cannot inspect $SourceRoot."
if ($Status) { Fail "$SourceRoot has local changes; preserve or commit them before reinstalling." }

Invoke-Checked 'git.exe' @('-C', $SourceRoot, 'fetch', '--no-tags', 'origin', "refs/heads/$RepositoryRef") "Cannot fetch authoritative main."
$ApprovedHead = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}') 'Fetched main is not a commit.'
$CurrentHead = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', 'HEAD^{commit}') 'HEAD is not a commit.'
if ($CurrentHead -ne $ApprovedHead) {
    & git.exe -C $SourceRoot merge-base --is-ancestor $CurrentHead $ApprovedHead
    if ($LASTEXITCODE -eq 0) {
        Invoke-Checked 'git.exe' @('-C', $SourceRoot, 'merge', '--ff-only', '--no-overwrite-ignore', $ApprovedHead) 'Could not fast-forward without overwriting local work.'
    } else {
        & git.exe -C $SourceRoot merge-base --is-ancestor $ApprovedHead $CurrentHead
        if ($LASTEXITCODE -eq 0) { Fail "$SourceRoot has local commits beyond authoritative origin/main." }
        Fail "$SourceRoot has diverged from authoritative origin/main."
    }
}
$VerifiedHead = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', 'HEAD^{commit}') 'Cannot verify final HEAD.'
$FinalStatus = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'status', '--porcelain') 'Cannot verify final status.'
if ($VerifiedHead -ne $ApprovedHead -or $FinalStatus) { Fail 'Source is not the clean fetched authoritative commit.' }

$PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $Python.Program @($Python.Prefix) -B -I -S (Join-Path $SourceRoot 'scripts\validate_package.py')
    $ValidationExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $PreviousNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
    else { $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode }
}
if ($ValidationExitCode -ne 0) { Fail 'Candidate package validation failed.' }
$Manifest = Get-Content -LiteralPath (Join-Path $SourceRoot '.codex-plugin\plugin.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not ($Manifest.version -is [string]) -or -not $Manifest.version) { Fail 'Validated manifest has no version.' }
$PluginVersion = $Manifest.version

[IO.Directory]::CreateDirectory($MarketplaceDirectory) | Out-Null
if (Test-Path -LiteralPath $MarketplaceFile) {
    try { $Marketplace = Get-Content -LiteralPath $MarketplaceFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Fail "Cannot read $MarketplaceFile as JSON." }
    if ($null -eq $Marketplace.plugins -or -not ($Marketplace.plugins -is [Array])) { Fail "$MarketplaceFile must contain a plugins array." }
} else {
    $Marketplace = [pscustomobject]@{ name = 'personal'; interface = [pscustomobject]@{ displayName = 'Personal' }; plugins = @() }
}
$Kept = @($Marketplace.plugins | Where-Object { $_.name -ne 'dev-flow-orchestrator' })
$Entry = [pscustomobject]@{
    name = 'dev-flow-orchestrator'
    source = [pscustomobject]@{ source = 'local'; path = './' + ($RelativeSource -replace '\\', '/') }
    policy = [pscustomobject]@{ installation = 'AVAILABLE'; authentication = 'ON_INSTALL' }
    category = 'Productivity'
}
$Marketplace.plugins = @($Kept) + @($Entry)
$Temporary = "$MarketplaceFile.tmp.$PID"
[IO.File]::WriteAllText($Temporary, (($Marketplace | ConvertTo-Json -Depth 10) + "`n"), (New-Object Text.UTF8Encoding($false)))
if (Test-Path -LiteralPath $MarketplaceFile) {
    $Backup = "$MarketplaceFile.bak.$PID"
    [IO.File]::Replace($Temporary, $MarketplaceFile, $Backup)
    Remove-Item -LiteralPath $Backup -Force
} else { [IO.File]::Move($Temporary, $MarketplaceFile) }

$PluginJson = Capture-Checked 'codex' @('plugin', 'list', '--marketplace', 'personal', '--json') 'Cannot inspect installed plugins.'
try { $PluginState = $PluginJson | ConvertFrom-Json } catch { Fail 'Codex returned invalid plugin JSON.' }
$Matches = @($PluginState.installed | Where-Object { $_.pluginId -eq $PluginId -and $_.installed -eq $true })
if ($Matches.Count -gt 1) { Fail 'Codex returned duplicate installed entries.' }
$Action = 'installed'
$PreviousVersion = ''
if ($Matches.Count -eq 1) {
    $PreviousVersion = [string]$Matches[0].version
    $Action = if ($PreviousVersion -eq $PluginVersion) { 'repaired' } else { 'upgraded' }
    Invoke-Checked 'codex' @('plugin', 'remove', $PluginId) "Cannot remove $PluginId before repair or upgrade."
}
& codex plugin add $PluginId
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("Plugin activation failed. Run: codex plugin add $PluginId")
    exit 1
}

Write-Output ''
Write-Output 'DEV FLOW ORCHESTRATOR // INSTALL RECEIPT'
Write-Output "ACTION         $Action"
if ($PreviousVersion) { Write-Output "PREVIOUS       $PreviousVersion" }
Write-Output "VERSION        $PluginVersion"
Write-Output "SOURCE         $SourceRoot"
Write-Output "MARKETPLACE    $MarketplaceFile"
Write-Output "CODEX HOME     $CodexRoot"
Write-Output 'FIRST PROMPT   Invoke $follow-dev-flow'
Write-Output 'HOOK REVIEW    Required: start a new Codex session, open /hooks, review the exact installed definition, then trust it.'
Write-Output 'Plugin installation does not establish Hook trust.'
