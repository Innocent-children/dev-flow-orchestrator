[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryUrl = if ($env:DEV_FLOW_REPOSITORY_URL) { $env:DEV_FLOW_REPOSITORY_URL } else { 'https://github.com/Innocent-children/dev-flow-orchestrator.git' }
$RepositoryRef = 'main'
$SourceRoot = if ($env:DEV_FLOW_SOURCE_ROOT) { $env:DEV_FLOW_SOURCE_ROOT } else { Join-Path $env:USERPROFILE 'plugins\dev-flow-orchestrator' }
$MarketplaceFile = if ($env:DEV_FLOW_MARKETPLACE_FILE) { $env:DEV_FLOW_MARKETPLACE_FILE } else { Join-Path $env:USERPROFILE '.agents\plugins\marketplace.json' }
$CodexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$RuntimeRoot = if ($env:DEV_FLOW_RUNTIME_HOME) { $env:DEV_FLOW_RUNTIME_HOME } else { Join-Path $env:LOCALAPPDATA 'dev-flow-orchestrator\runtime' }
$DataRoot = Join-Path $CodexRoot 'plugins\data\dev-flow-orchestrator-personal\0.4.0'
$PluginId = 'dev-flow-orchestrator@personal'
$McpLauncherMarker = 'rem dev-flow-orchestrator managed MCP launcher'

function Fail([string]$Message) {
    [Console]::Error.WriteLine("Dev Flow installation failed: $Message")
    exit 1
}

function Quote-PowerShellLiteral([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
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
        & $Program @Prefix -c "import struct,sys;sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,15) and struct.calcsize('P') == 8 else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return @{ Program = $Program; Prefix = [string[]]$Prefix } }
    }
    Fail 'Supported 64-bit Python 3.10-3.14 is required.'
}

function Find-BinDirectory {
    if ($env:DEV_FLOW_BIN_DIR) { $Candidates = @($env:DEV_FLOW_BIN_DIR) }
    else { $Candidates = @($env:PATH -split ';' | Where-Object { $_ }) }
    foreach ($Candidate in $Candidates) {
        try { $Full = [IO.Path]::GetFullPath($Candidate) } catch { continue }
        if (-not [IO.Path]::IsPathRooted($Full)) { continue }
        if (-not (Test-Path -LiteralPath $Full -PathType Container)) { continue }
        try {
            $Probe = Join-Path $Full ('.dev-flow-write-probe.' + $PID)
            [IO.File]::WriteAllText($Probe, '')
            Remove-Item -LiteralPath $Probe -Force
            return $Full
        } catch { continue }
    }
    Fail 'PATH has no writable absolute directory; set DEV_FLOW_BIN_DIR explicitly.'
}

function Test-OwnedMcpCommand([string]$Command, [string]$OwnedLauncher) {
    $Leaf = [IO.Path]::GetFileName($Command).ToLowerInvariant()
    if ($Leaf -in @('dev-flow-mcp', 'dev-flow-mcp.cmd')) { return $true }
    try {
        return [IO.Path]::GetFullPath($Command).Equals(
            [IO.Path]::GetFullPath($OwnedLauncher),
            [StringComparison]::OrdinalIgnoreCase
        )
    } catch { return $false }
}

function Test-McpRegistrationEnabled([object]$Registration) {
    $EnabledProperty = $Registration.PSObject.Properties['enabled']
    return $null -ne $EnabledProperty -and $EnabledProperty.Value -eq $true
}

function Test-OwnedMcpRegistration([object]$Registration, [string]$OwnedLauncher) {
    $Commands = @()
    $Containers = @($Registration)
    foreach ($Name in @('transport', 'config', 'server')) {
        $Property = $Registration.PSObject.Properties[$Name]
        if ($null -ne $Property -and $null -ne $Property.Value) { $Containers += $Property.Value }
    }
    foreach ($Container in $Containers) {
        $CommandProperty = $Container.PSObject.Properties['command']
        if ($null -ne $CommandProperty -and $CommandProperty.Value -is [string]) {
            $Commands += [string]$CommandProperty.Value
        }
    }
    foreach ($Command in $Commands) {
        if (Test-OwnedMcpCommand $Command $OwnedLauncher) { return $true }
    }
    return $false
}

function Test-BundledMcpRegistration([object]$Registration) {
    $NameProperty = $Registration.PSObject.Properties['name']
    if ($null -eq $NameProperty -or $NameProperty.Value -ne 'dev-flow' -or -not (Test-McpRegistrationEnabled $Registration)) { return $false }
    $TransportProperty = $Registration.PSObject.Properties['transport']
    if ($null -eq $TransportProperty -or $null -eq $TransportProperty.Value) { return $false }
    $Transport = $TransportProperty.Value
    $TypeProperty = $Transport.PSObject.Properties['type']
    $CommandProperty = $Transport.PSObject.Properties['command']
    $ArgsProperty = $Transport.PSObject.Properties['args']
    if ($null -eq $TypeProperty -or $TypeProperty.Value -ne 'stdio') { return $false }
    if ($null -eq $CommandProperty -or $CommandProperty.Value -ne 'dev-flow-mcp') { return $false }
    if ($null -eq $ArgsProperty) { return $false }
    $Arguments = @($ArgsProperty.Value)
    return $Arguments.Count -eq 1 -and $Arguments[0] -eq '--stdio'
}

function Get-ExplicitOwnedMcpRegistrationNames([string]$ConfigPath, [string]$OwnedLauncher) {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return @() }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { Fail "$ConfigPath must be a regular config.toml file." }
    $Names = @()
    $CurrentName = $null
    $HeaderPattern = '^\s*\[\s*mcp_servers\s*\.\s*(?:"([^"]+)"|''([^'']+)''|([A-Za-z0-9_-]+))\s*\]\s*(?:#.*)?$'
    $CommandPattern = '^\s*command\s*=\s*(?:"([^"]+)"|''([^'']+)'')'
    $DottedPattern = '^\s*mcp_servers\s*\.\s*(?:"([^"]+)"|''([^'']+)''|([A-Za-z0-9_-]+))\s*\.\s*command\s*=\s*(?:"([^"]+)"|''([^'']+)'')'
    foreach ($Line in Get-Content -LiteralPath $ConfigPath -Encoding UTF8) {
        $Header = [regex]::Match($Line, $HeaderPattern)
        if ($Header.Success) {
            $CurrentName = @($Header.Groups[1..3] | Where-Object { $_.Success })[0].Value
            continue
        }
        if ($Line.TrimStart().StartsWith('[')) {
            $CurrentName = $null
            continue
        }
        $Dotted = [regex]::Match($Line, $DottedPattern)
        if ($Dotted.Success) {
            $Name = @($Dotted.Groups[1..3] | Where-Object { $_.Success })[0].Value
            $Command = @($Dotted.Groups[4..5] | Where-Object { $_.Success })[0].Value
            if (Test-OwnedMcpCommand $Command $OwnedLauncher) { $Names += $Name }
            continue
        }
        if ($null -ne $CurrentName) {
            $CommandMatch = [regex]::Match($Line, $CommandPattern)
            if ($CommandMatch.Success) {
                $Command = @($CommandMatch.Groups[1..2] | Where-Object { $_.Success })[0].Value
                if (Test-OwnedMcpCommand $Command $OwnedLauncher) { $Names += $CurrentName }
            }
        }
    }
    return $Names
}

if ($env:OS -ne 'Windows_NT') { Fail 'This installer requires a supported Windows x64 client.' }
if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { Fail 'This installer requires an x64 process on Windows x64.' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { Fail 'Git for Windows is required.' }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { Fail 'Codex with plugin support is required.' }
if (-not (Get-Command uv.exe -ErrorAction SilentlyContinue)) { Fail 'uv is required to build the exact locked MCP runtime.' }
$Python = Find-Python
$BinDirectory = Find-BinDirectory
$McpLauncherPath = Join-Path $BinDirectory 'dev-flow-mcp.cmd'
if (Test-Path -LiteralPath $McpLauncherPath) {
    if (-not (Test-Path -LiteralPath $McpLauncherPath -PathType Leaf)) { Fail "$McpLauncherPath is not a regular file." }
    $FirstLines = @(Get-Content -LiteralPath $McpLauncherPath -TotalCount 3 -Encoding UTF8)
    if ($FirstLines -notcontains $McpLauncherMarker) { Fail "$McpLauncherPath exists and is not owned by Dev Flow." }
}

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
$IgnoredStatus = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'status', '--ignored', '--porcelain') 'Cannot inspect ignored source paths.'
if ($IgnoredStatus) {
    $QuotedSource = Quote-PowerShellLiteral $SourceRoot
    $QuotedInstaller = Quote-PowerShellLiteral $PSCommandPath
    [Console]::Error.WriteLine('Candidate source contains ignored paths. Preserve and inspect them before removing only confirmed disposable caches:')
    [Console]::Error.WriteLine("  git.exe -C $QuotedSource status --ignored --porcelain")
    [Console]::Error.WriteLine('After resolving every ignored source path, retry:')
    [Console]::Error.WriteLine("  powershell.exe -NoProfile -ExecutionPolicy Bypass -File $QuotedInstaller")
    Fail 'Candidate source contains ignored paths and cannot be activated.'
}

$PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $Python.Program @($Python.Prefix) -B -I -S (Join-Path $SourceRoot 'scripts\validate_package.py')
    $ValidationExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $PreviousNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
    else { $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode }
}
if ($ValidationExitCode -ne 0) {
    $IgnoredStatus = (& git.exe -C $SourceRoot status --ignored --porcelain 2>$null | Out-String).Trim()
    if ($IgnoredStatus) {
        $QuotedSource = Quote-PowerShellLiteral $SourceRoot
        $QuotedInstaller = Quote-PowerShellLiteral $PSCommandPath
        [Console]::Error.WriteLine('Candidate source contains ignored paths. Preserve and inspect them before removing only confirmed disposable caches:')
        [Console]::Error.WriteLine("  git.exe -C $QuotedSource status --ignored --porcelain")
        [Console]::Error.WriteLine('After resolving the candidate validation error, retry:')
        [Console]::Error.WriteLine("  powershell.exe -NoProfile -ExecutionPolicy Bypass -File $QuotedInstaller")
    }
    Fail 'Candidate package validation failed.'
}
$Manifest = Get-Content -LiteralPath (Join-Path $SourceRoot '.codex-plugin\plugin.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not ($Manifest.version -is [string]) -or -not $Manifest.version) { Fail 'Validated manifest has no version.' }
$PluginVersion = $Manifest.version

$PluginJson = Capture-Checked 'codex' @('plugin', 'list', '--marketplace', 'personal', '--json') 'Cannot inspect installed plugins.'
try { $PluginState = $PluginJson | ConvertFrom-Json } catch { Fail 'Codex returned invalid plugin JSON.' }
$PluginEntries = @($PluginState.installed | Where-Object { $_.pluginId -eq $PluginId })
if ($PluginEntries.Count -gt 1) { Fail 'Codex returned duplicate installed entries.' }
$InstalledMatches = @($PluginEntries | Where-Object { $_.installed -eq $true })
$Action = 'installed'
$PreviousVersion = ''
$PluginBundledActive = $false
if ($InstalledMatches.Count -eq 1) {
    $PreviousVersion = [string]$InstalledMatches[0].version
    if (-not $PreviousVersion) { Fail 'Installed plugin entry has no version.' }
    $EnabledProperty = $InstalledMatches[0].PSObject.Properties['enabled']
    $PluginBundledActive = $null -ne $EnabledProperty -and $EnabledProperty.Value -eq $true
    $Action = if ($PreviousVersion -eq $PluginVersion) { 'repaired' } else { 'upgraded' }
}

$McpListJson = Capture-Checked 'codex' @('mcp', 'list', '--json') 'Cannot inspect standalone MCP registrations.'
if (-not $McpListJson.TrimStart().StartsWith('[')) { Fail 'Codex MCP registration JSON must be an array.' }
try { $McpRegistrations = @($McpListJson | ConvertFrom-Json) } catch { Fail 'Codex returned invalid MCP registration JSON.' }
$ConfigPath = Join-Path $CodexRoot 'config.toml'
$ExplicitMcpConflicts = @(Get-ExplicitOwnedMcpRegistrationNames $ConfigPath $McpLauncherPath)
if ($ExplicitMcpConflicts.Count -gt 0) {
    Fail "Explicit standalone Dev Flow MCP registration(s) $($ExplicitMcpConflicts -join ', ') are present in $ConfigPath; remove them before enabling bundled mode."
}
$CanonicalBundled = @($McpRegistrations | Where-Object { Test-BundledMcpRegistration $_ })
$OwnedRegistrations = @($McpRegistrations | Where-Object { Test-OwnedMcpRegistration $_ $McpLauncherPath })
if ($PluginBundledActive -and $CanonicalBundled.Count -eq 1) {
    $McpConflicts = @($OwnedRegistrations | Where-Object { (Test-McpRegistrationEnabled $_) -and -not (Test-BundledMcpRegistration $_) })
} else {
    $McpConflicts = $OwnedRegistrations
}
if ($McpConflicts.Count -gt 0) {
    $Names = (($McpConflicts | ForEach-Object { if ($_.name) { $_.name } else { '<unnamed>' } }) -join ', ')
    Fail "Standalone Dev Flow MCP registration(s) $Names target the owned launcher; disable or remove them with codex mcp before enabling bundled mode."
}

$RuntimeOutput = & $Python.Program @($Python.Prefix) (Join-Path $SourceRoot 'scripts\manage_runtime.py') --source-root $SourceRoot --runtime-root $RuntimeRoot --source-commit $VerifiedHead --data-root $DataRoot
if ($LASTEXITCODE -ne 0) { Fail 'Cannot build and validate the managed MCP runtime.' }
try { $RuntimeResult = (($RuntimeOutput | Out-String).Trim()) | ConvertFrom-Json } catch { Fail 'Managed MCP runtime returned invalid JSON.' }
if ($RuntimeResult.ok -ne $true) { Fail 'Managed MCP runtime validation failed.' }
$RuntimePython = Join-Path ([string]$RuntimeResult.runtime_dir) 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) { Fail 'Managed MCP runtime Python is unavailable.' }
$PreviousLauncherBytes = if (Test-Path -LiteralPath $McpLauncherPath -PathType Leaf) { [IO.File]::ReadAllBytes($McpLauncherPath) } else { $null }
$PreviousMarketplaceBytes = if (Test-Path -LiteralPath $MarketplaceFile -PathType Leaf) { [IO.File]::ReadAllBytes($MarketplaceFile) } else { $null }
$LauncherTemplatePath = Join-Path $SourceRoot 'scripts\dev_flow_mcp_launcher.cmd'
if (-not (Test-Path -LiteralPath $LauncherTemplatePath -PathType Leaf)) { Fail 'Validated Windows MCP launcher template is unavailable.' }
$LauncherPayload = [IO.File]::ReadAllText($LauncherTemplatePath, [Text.Encoding]::UTF8)
$LauncherPlaceholder = '__DEV_FLOW_RUNTIME_PYTHON__'
if ([regex]::Matches($LauncherPayload, [regex]::Escape($LauncherPlaceholder)).Count -ne 1 -or -not $LauncherPayload.Contains($McpLauncherMarker)) {
    Fail 'Validated Windows MCP launcher template is invalid.'
}
# Percent is legal in a Windows path but is cmd.exe expansion syntax.  Doubling
# it in the generated batch file preserves the literal runtime path.
$EscapedRuntimePython = $RuntimePython.Replace('%', '%%')
$LauncherPayload = $LauncherPayload.Replace($LauncherPlaceholder, $EscapedRuntimePython)
$LauncherTemporary = "$McpLauncherPath.tmp.$PID"
[IO.File]::WriteAllText($LauncherTemporary, $LauncherPayload, (New-Object Text.UTF8Encoding($false)))
if (Test-Path -LiteralPath $McpLauncherPath) {
    $LauncherBackup = "$McpLauncherPath.bak.$PID"
    [IO.File]::Replace($LauncherTemporary, $McpLauncherPath, $LauncherBackup)
    Remove-Item -LiteralPath $LauncherBackup -Force
} else { [IO.File]::Move($LauncherTemporary, $McpLauncherPath) }

[IO.Directory]::CreateDirectory($MarketplaceDirectory) | Out-Null
if (Test-Path -LiteralPath $MarketplaceFile) {
    try { $Marketplace = Get-Content -LiteralPath $MarketplaceFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Fail "Cannot read $MarketplaceFile as JSON." }
    if ($null -eq $Marketplace.plugins -or -not ($Marketplace.plugins -is [Array])) { Fail "$MarketplaceFile must contain a plugins array." }
} else {
    $Marketplace = [pscustomobject]@{ name = 'personal'; interface = [pscustomobject]@{ displayName = 'Personal' }; plugins = @() }
}
$ExistingEntries = @($Marketplace.plugins | Where-Object { $_.name -eq 'dev-flow-orchestrator' })
if ($ExistingEntries.Count -gt 1) { Fail "$MarketplaceFile contains duplicate Dev Flow entries." }
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

$PreviousPluginRemoved = $false
$NewPluginActive = $false
function Restore-CandidateActivation([string]$Reason) {
    if ($NewPluginActive) { & codex plugin remove $PluginId *> $null }
    if ($null -eq $PreviousMarketplaceBytes) {
        Remove-Item -LiteralPath $MarketplaceFile -Force -ErrorAction SilentlyContinue
    } else {
        [IO.File]::WriteAllBytes($MarketplaceFile, $PreviousMarketplaceBytes)
    }
    if ($null -eq $PreviousLauncherBytes) {
        Remove-Item -LiteralPath $McpLauncherPath -Force -ErrorAction SilentlyContinue
    } else {
        [IO.File]::WriteAllBytes($McpLauncherPath, $PreviousLauncherBytes)
    }
    if ($PreviousPluginRemoved) {
        & codex plugin add $PluginId *> $null
        if ($LASTEXITCODE -eq 0) { [Console]::Error.WriteLine('Previous plugin activation was restored after the failed candidate.') }
        else { [Console]::Error.WriteLine("Previous plugin reactivation failed; after resolving Codex, run: codex plugin add $PluginId") }
    }
    [Console]::Error.WriteLine("Plugin activation failed: $Reason")
    [Console]::Error.WriteLine("Recovery: codex plugin remove $PluginId; codex plugin add $PluginId")
    [Console]::Error.WriteLine('Inspect MCP state with: codex mcp list --json')
    exit 1
}
if ($InstalledMatches.Count -eq 1) {
    Invoke-Checked 'codex' @('plugin', 'remove', $PluginId) "Cannot remove $PluginId before repair or upgrade."
    $PreviousPluginRemoved = $true
}
& codex plugin add $PluginId
if ($LASTEXITCODE -ne 0) {
    Restore-CandidateActivation 'Codex rejected the candidate plugin.'
}
$NewPluginActive = $true

$PostPluginJson = & codex plugin list --marketplace personal --json
if ($LASTEXITCODE -ne 0) { Restore-CandidateActivation 'Codex could not report the installed plugin after activation.' }
try { $PostPluginState = (($PostPluginJson | Out-String).Trim()) | ConvertFrom-Json } catch { Restore-CandidateActivation 'Codex returned invalid installed-plugin JSON after activation.' }
$PostMatches = @($PostPluginState.installed | Where-Object {
    $EnabledProperty = $_.PSObject.Properties['enabled']
    $_.pluginId -eq $PluginId -and $_.installed -eq $true -and $null -ne $EnabledProperty -and $EnabledProperty.Value -eq $true -and $_.version -eq $PluginVersion
})
if ($PostMatches.Count -ne 1) { Restore-CandidateActivation 'The activated plugin identity or release is not visible.' }

$PostMcpJson = & codex mcp list --json
if ($LASTEXITCODE -ne 0) { Restore-CandidateActivation 'Codex could not report MCP registrations after activation.' }
$PostMcpText = ($PostMcpJson | Out-String).Trim()
if (-not $PostMcpText.TrimStart().StartsWith('[')) { Restore-CandidateActivation 'Codex MCP registration JSON after activation was not an array.' }
try { $PostMcpRegistrations = @($PostMcpText | ConvertFrom-Json) } catch { Restore-CandidateActivation 'Codex returned invalid MCP registration JSON after activation.' }
$PostCanonicalBundled = @($PostMcpRegistrations | Where-Object { Test-BundledMcpRegistration $_ })
$PostOwnedRegistrations = @($PostMcpRegistrations | Where-Object { Test-OwnedMcpRegistration $_ $McpLauncherPath })
if ($PostCanonicalBundled.Count -ne 1 -or $PostOwnedRegistrations.Count -ne 1) {
    Restore-CandidateActivation 'The activated bundled MCP registration is missing, disabled, duplicated, or shadowed.'
}

$HealthOutput = & $RuntimePython -I (Join-Path $SourceRoot 'scripts\validate_installed_stage1.py') --plugin-root $SourceRoot --launcher $McpLauncherPath --smoke-only
if ($LASTEXITCODE -ne 0) { Restore-CandidateActivation 'The real installed launcher failed initialize, catalog, read, or mutation smoke.' }
try { $Health = (($HealthOutput | Out-String).Trim()) | ConvertFrom-Json } catch { Restore-CandidateActivation 'The installed MCP health evidence is invalid JSON.' }
if ($Health.ok -ne $true -or $Health.journey.read_smoke -ne $true -or $Health.journey.mutation_smoke -ne $true) {
    Restore-CandidateActivation 'The installed MCP health evidence is incomplete.'
}

Write-Output ''
Write-Output 'DEV FLOW ORCHESTRATOR // INSTALL RECEIPT'
Write-Output "ACTION         $Action"
if ($PreviousVersion) { Write-Output "PREVIOUS       $PreviousVersion" }
Write-Output "VERSION        $PluginVersion"
Write-Output "SOURCE         $SourceRoot"
Write-Output "MARKETPLACE    $MarketplaceFile"
Write-Output "CODEX HOME     $CodexRoot"
Write-Output "MCP RUNTIME    $RuntimeRoot"
Write-Output "MCP COMMAND    $McpLauncherPath"
Write-Output 'FIRST PROMPT   Ask Codex to discover or start a Dev Flow task through the dev-flow MCP server.'
