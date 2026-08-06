[CmdletBinding()]
param(
    [switch]$KeepSource,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    Write-Output 'Usage: .\uninstall.ps1 [-KeepSource] [-Help]'
    Write-Output 'Removes the plugin and marketplace entry; external Controller task data is always preserved.'
    exit 0
}

$DefaultRepositoryUrl = 'https://github.com/Innocent-children/dev-flow-orchestrator.git'
$RepositoryUrl = if ($env:DEV_FLOW_REPOSITORY_URL) { $env:DEV_FLOW_REPOSITORY_URL } else { $DefaultRepositoryUrl }
$SourceRoot = [IO.Path]::GetFullPath($(if ($env:DEV_FLOW_SOURCE_ROOT) { $env:DEV_FLOW_SOURCE_ROOT } else { Join-Path $env:USERPROFILE 'plugins\dev-flow-orchestrator' }))
$MarketplaceFile = [IO.Path]::GetFullPath($(if ($env:DEV_FLOW_MARKETPLACE_FILE) { $env:DEV_FLOW_MARKETPLACE_FILE } else { Join-Path $env:USERPROFILE '.agents\plugins\marketplace.json' }))
$PluginId = 'dev-flow-orchestrator@personal'

function Fail([string]$Message) { [Console]::Error.WriteLine("Dev Flow uninstallation failed: $Message"); exit 1 }
function Capture-Checked([string]$Program, [string[]]$Arguments, [string]$Failure) {
    $Output = & $Program @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { Fail $Failure }
    return (($Output | Out-String).Trim())
}

if ($env:OS -ne 'Windows_NT') { Fail 'This uninstaller requires a supported Windows x64 client.' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { Fail 'Git for Windows is required.' }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { Fail 'Codex with plugin support is required.' }

$MarketplaceDirectory = Split-Path -Parent $MarketplaceFile
if ((Split-Path -Leaf $MarketplaceFile) -ne 'marketplace.json' -or (Split-Path -Leaf $MarketplaceDirectory) -ne 'plugins' -or (Split-Path -Leaf (Split-Path -Parent $MarketplaceDirectory)) -ne '.agents') {
    Fail "$MarketplaceFile must be located at <marketplace-root>\.agents\plugins\marketplace.json."
}
$Marketplace = $null
$MarketplaceHasEntry = $false
if (Test-Path -LiteralPath $MarketplaceFile) {
    try { $Marketplace = Get-Content -LiteralPath $MarketplaceFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Fail "Cannot read $MarketplaceFile as JSON." }
    if ($null -eq $Marketplace.plugins -or -not ($Marketplace.plugins -is [Array])) { Fail "$MarketplaceFile must contain a plugins array." }
    $Matches = @($Marketplace.plugins | Where-Object { $_.name -eq 'dev-flow-orchestrator' })
    if ($Matches.Count -gt 1) { Fail "$MarketplaceFile contains duplicate Dev Flow entries." }
    $MarketplaceHasEntry = $Matches.Count -eq 1
}

$RemoveSource = -not $KeepSource
if ($RemoveSource -and (Test-Path -LiteralPath $SourceRoot)) {
    if ((Get-Item -LiteralPath $SourceRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "$SourceRoot is a reparse point; preserve it for manual handling." }
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot '.git') -PathType Container)) { Fail "$SourceRoot is not the expected Git checkout." }
    $MarketplaceRoot = [IO.Path]::GetFullPath((Join-Path $MarketplaceDirectory '..\..'))
    if (-not $SourceRoot.StartsWith($MarketplaceRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { Fail "$SourceRoot is outside marketplace root $MarketplaceRoot." }
    try { $Manifest = Get-Content -LiteralPath (Join-Path $SourceRoot '.codex-plugin\plugin.json') -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Fail 'Cannot validate the source manifest.' }
    if ($Manifest.name -ne 'dev-flow-orchestrator') { Fail "$SourceRoot is not Dev Flow plugin source." }
    $Origin = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'remote', 'get-url', 'origin') 'Cannot inspect source origin.'
    $Allowed = if ($env:DEV_FLOW_REPOSITORY_URL) { $Origin -eq $RepositoryUrl } else { $Origin -in @($DefaultRepositoryUrl, 'git@github.com:Innocent-children/dev-flow-orchestrator.git') }
    if (-not $Allowed) { Fail "$SourceRoot has unexpected origin '$Origin'." }
    $Branch = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'symbolic-ref', '--quiet', '--short', 'HEAD') 'Source must have an attached branch.'
    if ($Branch -ne 'main') { Fail "$SourceRoot is on '$Branch', expected main." }
    if (Capture-Checked 'git.exe' @('-C', $SourceRoot, 'status', '--porcelain') 'Cannot inspect source changes.') { Fail "$SourceRoot has local changes." }
    if (Capture-Checked 'git.exe' @('-C', $SourceRoot, 'status', '--ignored', '--porcelain') 'Cannot inspect ignored source paths.') { Fail "$SourceRoot contains ignored paths." }
    if ((Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-list', '--count', '--all', '--not', '--remotes=origin') 'Cannot inspect local-only history.') -ne '0') { Fail "$SourceRoot contains local-only commits." }
}

$PluginJson = Capture-Checked 'codex' @('plugin', 'list', '--marketplace', 'personal', '--json') 'Cannot inspect installed plugins.'
try { $PluginState = $PluginJson | ConvertFrom-Json } catch { Fail 'Codex returned invalid plugin JSON.' }
$Installed = @($PluginState.installed | Where-Object { $_.pluginId -eq $PluginId -and $_.installed -eq $true })
if ($Installed.Count -gt 1) { Fail 'Codex returned duplicate installed entries.' }
$PluginAction = 'already absent'
if ($Installed.Count -eq 1) {
    & codex plugin remove $PluginId
    if ($LASTEXITCODE -ne 0) { Fail "Cannot remove $PluginId." }
    $PluginAction = 'removed'
}

$MarketplaceAction = 'already absent'
if ($MarketplaceHasEntry) {
    $Marketplace.plugins = @($Marketplace.plugins | Where-Object { $_.name -ne 'dev-flow-orchestrator' })
    $Temporary = "$MarketplaceFile.tmp.$PID"
    [IO.File]::WriteAllText($Temporary, (($Marketplace | ConvertTo-Json -Depth 10) + "`n"), (New-Object Text.UTF8Encoding($false)))
    $Backup = "$MarketplaceFile.bak.$PID"
    [IO.File]::Replace($Temporary, $MarketplaceFile, $Backup)
    Remove-Item -LiteralPath $Backup -Force
    $MarketplaceAction = 'entry removed'
}

$SourceAction = 'already absent'
if (Test-Path -LiteralPath $SourceRoot) {
    if ($KeepSource) { $SourceAction = 'preserved (-KeepSource)' }
    else { Remove-Item -LiteralPath $SourceRoot -Recurse -Force; $SourceAction = 'removed' }
}

Write-Output ''
Write-Output 'DEV FLOW ORCHESTRATOR // UNINSTALL RECEIPT'
Write-Output "PLUGIN         $PluginAction"
Write-Output "MARKETPLACE    $MarketplaceAction"
Write-Output "SOURCE         $SourceAction"
Write-Output 'TASK DATA      preserved (external Controller data was not changed)'
