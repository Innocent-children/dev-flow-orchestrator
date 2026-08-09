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
$CliLauncherMarker = 'rem dev-flow-orchestrator managed CLI launcher'

function Fail([string]$Message) {
    if ($null -ne (Get-Command Test-SelectedSourceInventory -CommandType Function -ErrorAction SilentlyContinue)) {
        if (-not (Test-SelectedSourceInventory)) {
            [Console]::Error.WriteLine('Authoritative source changed after candidate sealing; no post-seal activation input was read from that checkout.')
        }
    }
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

function Invoke-NoBytecodePython([object[]]$Arguments, [string]$Failure) {
    $PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONDONTWRITEBYTECODE = '1'
        $Output = & $Python.Program @($Python.Prefix) -B @Arguments
        $ExitCode = $LASTEXITCODE
    } finally {
        if ($null -eq $PreviousNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
        else { $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode }
    }
    if ($ExitCode -ne 0) { Fail $Failure }
    return $Output
}

function Seal-Commit([string]$Commit, [string]$Tree, [string]$Name) {
    $Archive = Join-Path $TransactionRoot ($Name + '.tar')
    $Destination = Join-Path $TransactionRoot ('sealed-' + $Name)
    Invoke-Checked 'git.exe' @('-C', $SourceRoot, 'archive', '--format=tar', "--output=$Archive", $Commit) "Cannot export Git commit $Commit."
    $Output = Invoke-NoBytecodePython @(
        '-I', '-S', $SealHelper, 'seal',
        '--archive', $Archive,
        '--destination', $Destination,
        '--source-commit', $Commit,
        '--source-tree', $Tree
    ) "Cannot seal Git commit $Commit."
    try { $Result = (($Output | Out-String).Trim()) | ConvertFrom-Json } catch { Fail 'Sealed release helper returned invalid JSON.' }
    if ($Result.ok -ne $true -or -not ($Result.release_id -is [string]) -or -not ($Result.plugin_root -is [string])) {
        Fail 'Sealed release helper returned an invalid identity.'
    }
    return $Result
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
        $PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
        try {
            $env:PYTHONDONTWRITEBYTECODE = '1'
            & $Program @Prefix -B -c "import struct,sys;sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,15) and struct.calcsize('P') == 8 else 1)" 2>$null
            $ProbeExitCode = $LASTEXITCODE
        } finally {
            if ($null -eq $PreviousNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
            else { $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode }
        }
        if ($ProbeExitCode -eq 0) { return @{ Program = $Program; Prefix = [string[]]$Prefix } }
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
$CliLauncherPath = Join-Path $BinDirectory 'dev-flow.cmd'
if (Test-Path -LiteralPath $McpLauncherPath) {
    if (-not (Test-Path -LiteralPath $McpLauncherPath -PathType Leaf)) { Fail "$McpLauncherPath is not a regular file." }
    $FirstLines = @(Get-Content -LiteralPath $McpLauncherPath -TotalCount 3 -Encoding UTF8)
    if ($FirstLines -notcontains $McpLauncherMarker) { Fail "$McpLauncherPath exists and is not owned by Dev Flow." }
}
if (Test-Path -LiteralPath $CliLauncherPath) {
    if (-not (Test-Path -LiteralPath $CliLauncherPath -PathType Leaf)) { Fail "$CliLauncherPath is not a regular file." }
    if (@(Get-Content -LiteralPath $CliLauncherPath -TotalCount 3 -Encoding UTF8) -notcontains $CliLauncherMarker) {
        Fail "$CliLauncherPath exists and is not owned by Dev Flow."
    }
}

$EarlyMcpListJson = Capture-Checked 'codex' @('mcp', 'list', '--json') 'Cannot inspect standalone MCP registrations before installation.'
if (-not $EarlyMcpListJson.TrimStart().StartsWith('[')) { Fail 'Codex MCP registration JSON must be an array.' }
try { $EarlyMcpRegistrations = @($EarlyMcpListJson | ConvertFrom-Json) } catch { Fail 'Codex returned invalid MCP registration JSON.' }
$EarlyStandalone = @($EarlyMcpRegistrations | Where-Object {
    -not (Test-BundledMcpRegistration $_) -and (
        $_.name -eq 'dev-flow' -or (Test-OwnedMcpRegistration $_ $McpLauncherPath)
    )
})
if ($EarlyStandalone.Count -gt 0) {
    Fail 'Unsupported standalone Dev Flow MCP registration is present; preserve it and inspect it manually before bundled installation.'
}
$EarlyConfigPath = Join-Path $CodexRoot 'config.toml'
$EarlyExplicit = @(Get-ExplicitOwnedMcpRegistrationNames $EarlyConfigPath $McpLauncherPath)
if ($EarlyExplicit.Count -gt 0) {
    Fail "Unsupported standalone Dev Flow MCP registration(s) $($EarlyExplicit -join ', ') are present; preserve them before bundled installation."
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

$TransactionRoot = Join-Path $env:TEMP ('dev-flow-install-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($TransactionRoot) | Out-Null
Invoke-Checked 'git.exe' @('-C', $SourceRoot, 'fetch', '--no-tags', 'origin', "refs/heads/$RepositoryRef") "Cannot fetch authoritative main."
$ApprovedHead = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', 'FETCH_HEAD^{commit}') 'Fetched main is not a commit.'
$CurrentHead = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', 'HEAD^{commit}') 'HEAD is not a commit.'
$SealHelper = Join-Path $TransactionRoot 'runtime_integrity.py'
$HelperText = (& git.exe -C $SourceRoot show "${ApprovedHead}:scripts/runtime_integrity.py" | Out-String)
if ($LASTEXITCODE -ne 0 -or -not $HelperText) { Fail 'The selected release is missing its runtime integrity helper.' }
[IO.File]::WriteAllText($SealHelper, $HelperText, (New-Object Text.UTF8Encoding($false)))
$PreviousSealResult = $null
$PreviousSourceTree = ''
if ($CurrentHead -ne $ApprovedHead) {
    & git.exe -C $SourceRoot merge-base --is-ancestor $CurrentHead $ApprovedHead
    if ($LASTEXITCODE -eq 0) {
        $PreviousSourceTree = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', "$CurrentHead^{tree}") 'Previous HEAD has no readable tree.'
        $PreviousSealResult = Seal-Commit $CurrentHead $PreviousSourceTree 'previous'
        Invoke-Checked 'git.exe' @('-C', $SourceRoot, 'merge', '--ff-only', '--no-overwrite-ignore', $ApprovedHead) 'Could not fast-forward without overwriting local work.'
    } else {
        & git.exe -C $SourceRoot merge-base --is-ancestor $ApprovedHead $CurrentHead
        if ($LASTEXITCODE -eq 0) { Fail "$SourceRoot has local commits beyond authoritative origin/main." }
        Fail "$SourceRoot has diverged from authoritative origin/main."
    }
}
$VerifiedHead = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', 'HEAD^{commit}') 'Cannot verify final HEAD.'
$VerifiedTree = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'rev-parse', '--verify', 'HEAD^{tree}') 'Cannot verify final tree.'
$FinalStatus = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'status', '--porcelain') 'Cannot verify final status.'
if ($VerifiedHead -ne $ApprovedHead -or $FinalStatus) { Fail 'Source is not the clean fetched authoritative commit.' }
$SourceBaselineTracked = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'status', '--porcelain', '--untracked-files=all') 'Cannot capture the selected source inventory.'
$SourceBaselineIgnored = Capture-Checked 'git.exe' @('-C', $SourceRoot, 'ls-files', '--others', '--ignored', '--exclude-standard') 'Cannot capture ignored source paths.'

function Test-SelectedSourceInventory {
    $FinalHead = & git.exe -C $SourceRoot rev-parse --verify 'HEAD^{commit}' 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $FinalTree = & git.exe -C $SourceRoot rev-parse --verify 'HEAD^{tree}' 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $FinalTracked = & git.exe -C $SourceRoot status --porcelain --untracked-files=all 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    $FinalIgnored = & git.exe -C $SourceRoot ls-files --others --ignored --exclude-standard 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    return (
        (($FinalHead | Out-String).Trim()) -ceq $VerifiedHead -and
        (($FinalTree | Out-String).Trim()) -ceq $VerifiedTree -and
        (($FinalTracked | Out-String).Trim()) -ceq $SourceBaselineTracked -and
        (($FinalIgnored | Out-String).Trim()) -ceq $SourceBaselineIgnored
    )
}

$SealResult = Seal-Commit $VerifiedHead $VerifiedTree 'candidate'
$CandidateReleaseId = [string]$SealResult.release_id
$SealedSourceRoot = [string]$SealResult.plugin_root

$PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $Python.Program @($Python.Prefix) -B -I -S (Join-Path $SealedSourceRoot 'scripts\validate_package.py')
    $ValidationExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $PreviousNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
    else { $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode }
}
if ($ValidationExitCode -ne 0) { Fail 'Candidate package validation failed.' }
$Manifest = Get-Content -LiteralPath (Join-Path $SealedSourceRoot '.codex-plugin\plugin.json') -Raw -Encoding UTF8 | ConvertFrom-Json
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

function Build-SealedRuntime([string]$PluginRoot, [string]$Commit, [string]$Tree, [string]$ReleaseId) {
    $Output = Invoke-NoBytecodePython @(
        (Join-Path $SealedSourceRoot 'scripts\manage_runtime.py'),
        '--source-root', $PluginRoot,
        '--runtime-root', $RuntimeRoot,
        '--source-commit', $Commit,
        '--source-tree', $Tree,
        '--release-id', $ReleaseId,
        '--data-root', $DataRoot
    ) 'Cannot build and validate the managed MCP runtime.'
    try { $Result = (($Output | Out-String).Trim()) | ConvertFrom-Json } catch { Fail 'Managed MCP runtime returned invalid JSON.' }
    if ($Result.ok -ne $true) { Fail 'Managed MCP runtime validation failed.' }
    return $Result
}

$RuntimeResult = Build-SealedRuntime $SealedSourceRoot $VerifiedHead $VerifiedTree $CandidateReleaseId
$RuntimePython = Join-Path ([string]$RuntimeResult.runtime_dir) 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) { Fail 'Managed MCP runtime Python is unavailable.' }
$PersistentPluginRoot = [IO.Path]::GetFullPath([string]$RuntimeResult.plugin_root)
$ManagedLauncherPayload = [IO.Path]::GetFullPath([string]$RuntimeResult.launcher_path)
$ManagedCliLauncherPayload = [IO.Path]::GetFullPath([string]$RuntimeResult.cli_launcher_path)
if (-not (Test-Path -LiteralPath $PersistentPluginRoot -PathType Container)) { Fail 'Managed sealed plugin release is unavailable.' }
if (-not (Test-Path -LiteralPath $ManagedLauncherPayload -PathType Leaf)) { Fail 'Managed MCP launcher payload is unavailable.' }
if (-not (Test-Path -LiteralPath $ManagedCliLauncherPayload -PathType Leaf)) { Fail 'Managed CLI launcher payload is unavailable.' }

$PreviousReleaseId = ''
$PreviousPersistentPluginRoot = ''
$PreviousRuntimePython = ''
$PreviousManagedLauncherPayload = ''
$PreviousManagedCliLauncherPayload = ''
if ($InstalledMatches.Count -eq 1) {
    if ($null -eq $PreviousSealResult) {
        $PreviousSealResult = $SealResult
        $PreviousSourceTree = $VerifiedTree
        $PreviousHead = $VerifiedHead
    } else {
        $PreviousHead = $CurrentHead
    }
    $PreviousReleaseId = [string]$PreviousSealResult.release_id
    $PreviousStagedRoot = [string]$PreviousSealResult.plugin_root
    if ($PreviousReleaseId -eq $CandidateReleaseId) {
        $PreviousRuntimeResult = $RuntimeResult
    } else {
        $PreviousRuntimeResult = Build-SealedRuntime $PreviousStagedRoot $PreviousHead $PreviousSourceTree $PreviousReleaseId
    }
    $PreviousPersistentPluginRoot = [IO.Path]::GetFullPath([string]$PreviousRuntimeResult.plugin_root)
    $PreviousRuntimePython = Join-Path ([string]$PreviousRuntimeResult.runtime_dir) 'venv\Scripts\python.exe'
    $PreviousManagedLauncherPayload = [IO.Path]::GetFullPath([string]$PreviousRuntimeResult.launcher_path)
    $PreviousManagedCliLauncherPayload = [IO.Path]::GetFullPath([string]$PreviousRuntimeResult.cli_launcher_path)
    if (
        -not (Test-Path -LiteralPath $PreviousPersistentPluginRoot -PathType Container) -or
        -not (Test-Path -LiteralPath $PreviousRuntimePython -PathType Leaf) -or
        -not (Test-Path -LiteralPath $PreviousManagedLauncherPayload -PathType Leaf) -or
        -not (Test-Path -LiteralPath $PreviousManagedCliLauncherPayload -PathType Leaf)
    ) { Fail 'The previous release cannot be staged for bounded rollback.' }
}

$MarketplacePrefix = $MarketplaceRoot.TrimEnd('\') + '\'
if (-not $PersistentPluginRoot.StartsWith($MarketplacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    Fail "$PersistentPluginRoot must be inside marketplace root $MarketplaceRoot."
}
$RelativePlugin = $PersistentPluginRoot.Substring($MarketplacePrefix.Length)
$RelativePreviousPlugin = ''
if ($PreviousPersistentPluginRoot) {
    if (-not $PreviousPersistentPluginRoot.StartsWith($MarketplacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Fail "$PreviousPersistentPluginRoot must be inside marketplace root $MarketplaceRoot."
    }
    $RelativePreviousPlugin = $PreviousPersistentPluginRoot.Substring($MarketplacePrefix.Length)
}

$PreviousLauncherBytes = if (Test-Path -LiteralPath $McpLauncherPath -PathType Leaf) { [IO.File]::ReadAllBytes($McpLauncherPath) } else { $null }
$CandidateLauncherBytes = [IO.File]::ReadAllBytes($ManagedLauncherPayload)
$PreviousCliLauncherBytes = if (Test-Path -LiteralPath $CliLauncherPath -PathType Leaf) { [IO.File]::ReadAllBytes($CliLauncherPath) } else { $null }
$CandidateCliLauncherBytes = [IO.File]::ReadAllBytes($ManagedCliLauncherPayload)
[IO.Directory]::CreateDirectory($MarketplaceDirectory) | Out-Null
$MarketplaceOriginallyPresent = Test-Path -LiteralPath $MarketplaceFile
if (Test-Path -LiteralPath $MarketplaceFile) {
    try { $Marketplace = Get-Content -LiteralPath $MarketplaceFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Fail "Cannot read $MarketplaceFile as JSON." }
    if ($null -eq $Marketplace.plugins -or -not ($Marketplace.plugins -is [Array])) { Fail "$MarketplaceFile must contain a plugins array." }
} else {
    $Marketplace = [pscustomobject]@{ name = 'personal'; interface = [pscustomobject]@{ displayName = 'Personal' }; plugins = @() }
}
$ExistingEntries = @($Marketplace.plugins | Where-Object { $_.name -eq 'dev-flow-orchestrator' })
if ($ExistingEntries.Count -gt 1) { Fail "$MarketplaceFile contains duplicate Dev Flow entries." }
$OriginalMarketplaceEntry = if ($ExistingEntries.Count -eq 1) { $ExistingEntries[0] } else { $null }
$CandidateMarketplaceEntry = [pscustomobject]@{
    name = 'dev-flow-orchestrator'
    source = [pscustomobject]@{ source = 'local'; path = './' + ($RelativePlugin -replace '\\', '/') }
    policy = [pscustomobject]@{ installation = 'AVAILABLE'; authentication = 'ON_INSTALL' }
    category = 'Productivity'
}
$RollbackMarketplaceEntry = $OriginalMarketplaceEntry
if ($InstalledMatches.Count -eq 1) {
    $RollbackMarketplaceEntry = [pscustomobject]@{
        name = 'dev-flow-orchestrator'
        source = [pscustomobject]@{ source = 'local'; path = './' + ($RelativePreviousPlugin -replace '\\', '/') }
        policy = [pscustomobject]@{ installation = 'AVAILABLE'; authentication = 'ON_INSTALL' }
        category = 'Productivity'
    }
}

function Convert-MarketplaceEntry([object]$Value) {
    if ($null -eq $Value) { return '<absent>' }
    return ($Value | ConvertTo-Json -Depth 10 -Compress)
}

function Set-MarketplaceEntry([object]$Expected, [object]$Replacement) {
    try {
        if (Test-Path -LiteralPath $MarketplaceFile) {
            $CurrentMarketplace = Get-Content -LiteralPath $MarketplaceFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($null -eq $CurrentMarketplace.plugins -or -not ($CurrentMarketplace.plugins -is [Array])) { return $false }
        } else {
            $CurrentMarketplace = [pscustomobject]@{ name = 'personal'; interface = [pscustomobject]@{ displayName = 'Personal' }; plugins = @() }
        }
        $Matches = @($CurrentMarketplace.plugins | Where-Object { $_.name -eq 'dev-flow-orchestrator' })
        if ($Matches.Count -gt 1) { return $false }
        $Current = if ($Matches.Count -eq 1) { $Matches[0] } else { $null }
        if ((Convert-MarketplaceEntry $Current) -cne (Convert-MarketplaceEntry $Expected)) { return $false }
        $Kept = @($CurrentMarketplace.plugins | Where-Object { $_.name -ne 'dev-flow-orchestrator' })
        $CurrentMarketplace.plugins = if ($null -eq $Replacement) { $Kept } else { @($Kept) + @($Replacement) }
        if (-not $MarketplaceOriginallyPresent -and $null -eq $Replacement -and $Kept.Count -eq 0) {
            Remove-Item -LiteralPath $MarketplaceFile -Force -ErrorAction SilentlyContinue
            return $true
        }
        $Temporary = "$MarketplaceFile.tmp.$PID"
        [IO.File]::WriteAllText($Temporary, (($CurrentMarketplace | ConvertTo-Json -Depth 10) + "`n"), (New-Object Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $MarketplaceFile) {
            $Backup = "$MarketplaceFile.bak.$PID"
            [IO.File]::Replace($Temporary, $MarketplaceFile, $Backup)
            Remove-Item -LiteralPath $Backup -Force
        } else { [IO.File]::Move($Temporary, $MarketplaceFile) }
        return $true
    } catch { return $false }
}

function Test-BytesEqual([object]$Left, [object]$Right) {
    if ($null -eq $Left -or $null -eq $Right) { return $null -eq $Left -and $null -eq $Right }
    return [Convert]::ToBase64String([byte[]]$Left) -ceq [Convert]::ToBase64String([byte[]]$Right)
}

function Set-McpLauncher([object]$Expected, [object]$Replacement) {
    try {
        $Current = if (Test-Path -LiteralPath $McpLauncherPath -PathType Leaf) { [IO.File]::ReadAllBytes($McpLauncherPath) } else { $null }
        if (-not (Test-BytesEqual $Current $Expected)) { return $false }
        if ($null -eq $Replacement) {
            Remove-Item -LiteralPath $McpLauncherPath -Force -ErrorAction Stop
            return $true
        }
        $Temporary = "$McpLauncherPath.tmp.$PID"
        [IO.File]::WriteAllBytes($Temporary, [byte[]]$Replacement)
        if (Test-Path -LiteralPath $McpLauncherPath) {
            $Backup = "$McpLauncherPath.bak.$PID"
            [IO.File]::Replace($Temporary, $McpLauncherPath, $Backup)
            Remove-Item -LiteralPath $Backup -Force
        } else { [IO.File]::Move($Temporary, $McpLauncherPath) }
        return $true
    } catch { return $false }
}

function Set-CliLauncher([object]$Expected, [object]$Replacement) {
    try {
        $Current = if (Test-Path -LiteralPath $CliLauncherPath -PathType Leaf) { [IO.File]::ReadAllBytes($CliLauncherPath) } else { $null }
        if (-not (Test-BytesEqual $Current $Expected)) { return $false }
        if ($null -eq $Replacement) {
            Remove-Item -LiteralPath $CliLauncherPath -Force -ErrorAction Stop
            return $true
        }
        $Temporary = "$CliLauncherPath.tmp.$PID"
        [IO.File]::WriteAllBytes($Temporary, [byte[]]$Replacement)
        if (Test-Path -LiteralPath $CliLauncherPath) {
            $Backup = "$CliLauncherPath.bak.$PID"
            [IO.File]::Replace($Temporary, $CliLauncherPath, $Backup)
            Remove-Item -LiteralPath $Backup -Force
        } else { [IO.File]::Move($Temporary, $CliLauncherPath) }
        return $true
    } catch { return $false }
}

function Get-PluginObservation {
    $Json = & codex plugin list --marketplace personal --json 2>$null
    if ($LASTEXITCODE -ne 0) { return 'unknown' }
    try { $State = (($Json | Out-String).Trim()) | ConvertFrom-Json } catch { return 'unknown' }
    $Matches = @($State.installed | Where-Object { $_.pluginId -eq $PluginId -and $_.installed -eq $true })
    if ($Matches.Count -eq 0) { return 'absent' }
    if ($Matches.Count -ne 1 -or -not ($Matches[0].version -is [string])) { return 'unknown' }
    $Enabled = $Matches[0].PSObject.Properties['enabled']
    $Prefix = if ($null -ne $Enabled -and $Enabled.Value -eq $true) { 'active:' } else { 'inactive:' }
    return $Prefix + [string]$Matches[0].version
}

function Test-BundledMcpVisibility {
    $Json = & codex mcp list --json 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    try { $Rows = @((($Json | Out-String).Trim()) | ConvertFrom-Json) } catch { return $false }
    $Canonical = @($Rows | Where-Object { Test-BundledMcpRegistration $_ })
    $Owned = @($Rows | Where-Object { Test-OwnedMcpRegistration $_ $McpLauncherPath })
    return $Canonical.Count -eq 1 -and $Owned.Count -eq 1
}

function Test-ReleaseHealth([string]$HealthPython, [string]$HealthPluginRoot) {
    $PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONDONTWRITEBYTECODE = '1'
        $Output = & $HealthPython -B -I (Join-Path $HealthPluginRoot 'scripts\validate_installed_stage1.py') --plugin-root $HealthPluginRoot --launcher $McpLauncherPath --smoke-only 2>$null
        $ExitCode = $LASTEXITCODE
    } finally {
        if ($null -eq $PreviousNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
        else { $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode }
    }
    if ($ExitCode -ne 0) { return $false }
    try { $Evidence = (($Output | Out-String).Trim()) | ConvertFrom-Json } catch { return $false }
    return $Evidence.ok -eq $true -and $Evidence.journey.read_smoke -eq $true -and $Evidence.journey.mutation_smoke -eq $true
}

$TransactionId = 'tx-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + $PID
$TransactionOperation = switch ($Action) {
    'installed' { 'install' }
    'upgraded' { 'upgrade' }
    'repaired' { 'repair' }
}
$TransactionDirectory = Join-Path $RuntimeRoot 'transactions'
if (Test-Path -LiteralPath $TransactionDirectory) {
    if (-not (Test-Path -LiteralPath $TransactionDirectory -PathType Container) -or ((Get-Item -LiteralPath $TransactionDirectory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Fail "$TransactionDirectory must be a regular directory."
    }
} else { [IO.Directory]::CreateDirectory($TransactionDirectory) | Out-Null }
$TransactionPath = Join-Path $TransactionDirectory ($TransactionId + '.json')
$script:TxStep = 'staged'
$script:TxOutcome = 'in_progress'
$script:TxPlugin = if ($InstalledMatches.Count -eq 1) { 'previous' } else { 'absent' }
$script:TxMarketplace = 'original'
$script:TxLauncher = 'original'
$script:TxRuntime = 'candidate-staged'
$script:TxBlindRetrySafe = $true

function Write-InstallTransaction {
    try {
        $Record = [ordered]@{
            schema = 'dev-flow-install-transaction/0.4.0'
            transaction_id = $TransactionId
            operation = $TransactionOperation
            previous_release = $(if ($PreviousReleaseId) { $PreviousReleaseId } else { $null })
            candidate_release = $CandidateReleaseId
            current_step = $script:TxStep
            components = [ordered]@{
                plugin = $script:TxPlugin
                marketplace = $script:TxMarketplace
                mcp_launcher = $script:TxLauncher
                runtime = $script:TxRuntime
            }
            outcome = $script:TxOutcome
            blind_retry_safe = $script:TxBlindRetrySafe
            retained_paths = @([string]$RuntimeResult.runtime_dir) + $(if ($PreviousReleaseId -and $PreviousReleaseId -ne $CandidateReleaseId) { @([string]$PreviousRuntimeResult.runtime_dir) } else { @() })
        }
        $Temporary = "$TransactionPath.tmp.$PID"
        [IO.File]::WriteAllText($Temporary, (($Record | ConvertTo-Json -Depth 10) + "`n"), (New-Object Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $TransactionPath) {
            $Backup = "$TransactionPath.bak.$PID"
            [IO.File]::Replace($Temporary, $TransactionPath, $Backup)
            Remove-Item -LiteralPath $Backup -Force
        } else { [IO.File]::Move($Temporary, $TransactionPath) }
        return $true
    } catch { return $false }
}

function Restore-CandidateActivation([string]$Reason) {
    $RollbackOk = $true
    $script:TxStep = 'rolling-back'
    $script:TxOutcome = 'in_progress'
    [void](Write-InstallTransaction)

    & codex plugin remove $PluginId *> $null
    if ((Get-PluginObservation) -eq 'absent') { $script:TxPlugin = 'absent' } else { $script:TxPlugin = 'unknown'; $RollbackOk = $false }

    if ($script:TxMarketplace -eq 'candidate') {
        if (Set-MarketplaceEntry $CandidateMarketplaceEntry $RollbackMarketplaceEntry) { $script:TxMarketplace = 'original' }
        else { $script:TxMarketplace = 'unknown'; $RollbackOk = $false }
    }

    if ($script:TxLauncher -eq 'candidate') {
        $RollbackLauncherBytes = if ($PreviousReleaseId) { [IO.File]::ReadAllBytes($PreviousManagedLauncherPayload) } else { $PreviousLauncherBytes }
        $RollbackCliLauncherBytes = if ($PreviousReleaseId) { [IO.File]::ReadAllBytes($PreviousManagedCliLauncherPayload) } else { $PreviousCliLauncherBytes }
        $McpLauncherRestored = Set-McpLauncher $CandidateLauncherBytes $RollbackLauncherBytes
        $CliLauncherRestored = Set-CliLauncher $CandidateCliLauncherBytes $RollbackCliLauncherBytes
        if ($McpLauncherRestored -and $CliLauncherRestored) { $script:TxLauncher = 'original' }
        else { $script:TxLauncher = 'unknown'; $RollbackOk = $false }
    }

    if ($PreviousReleaseId) {
        & codex plugin add $PluginId *> $null
        $PreviousObserved = Get-PluginObservation
        if (
            $PreviousObserved -eq ('active:' + $PreviousVersion) -and
            (Test-BundledMcpVisibility) -and
            (Test-ReleaseHealth $PreviousRuntimePython $PreviousPersistentPluginRoot)
        ) { $script:TxPlugin = 'previous' }
        else { $script:TxPlugin = 'unknown'; $RollbackOk = $false }
    } elseif ((Get-PluginObservation) -ne 'absent') {
        $script:TxPlugin = 'unknown'
        $RollbackOk = $false
    }

    if ($RollbackOk) {
        $script:TxStep = 'rolled-back'
        $script:TxOutcome = 'rolled_back'
        $script:TxRuntime = 'candidate-retained'
        $script:TxBlindRetrySafe = $true
        if (-not (Write-InstallTransaction)) { $RollbackOk = $false }
    }
    if (-not $RollbackOk) {
        $script:TxStep = 'rollback-incomplete'
        $script:TxOutcome = 'partial'
        $script:TxRuntime = 'candidate-retained'
        $script:TxBlindRetrySafe = $false
        [void](Write-InstallTransaction)
        [Console]::Error.WriteLine('Installation rollback is partial; blind_retry_safe=false.')
    } elseif ($PreviousReleaseId) {
        [Console]::Error.WriteLine('Previous plugin activation was restored and verified after the failed candidate.')
    }
    [Console]::Error.WriteLine("Plugin activation failed: $Reason")
    [Console]::Error.WriteLine("Inspect transaction state at: $TransactionPath")
    Remove-Item -LiteralPath $TransactionRoot -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

if (-not (Write-InstallTransaction)) { Fail 'Cannot create the bounded installation transaction record.' }
if (-not (Set-McpLauncher $PreviousLauncherBytes $CandidateLauncherBytes)) { Fail 'Cannot install the exact managed MCP launcher.' }
if (-not (Set-CliLauncher $PreviousCliLauncherBytes $CandidateCliLauncherBytes)) {
    [void](Set-McpLauncher $CandidateLauncherBytes $PreviousLauncherBytes)
    Fail 'Cannot install the exact managed CLI launcher.'
}
$script:TxLauncher = 'candidate'
$script:TxStep = 'mcp-launcher'
if (-not (Write-InstallTransaction)) { Restore-CandidateActivation 'Cannot record the managed MCP launcher update.' }
if ((Get-FileHash -LiteralPath $McpLauncherPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$RuntimeResult.launcher_sha256) {
    Restore-CandidateActivation 'Installed MCP launcher bytes do not match the verified runtime receipt.'
}
if ((Get-FileHash -LiteralPath $CliLauncherPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$RuntimeResult.cli_launcher_sha256) {
    Restore-CandidateActivation 'Installed CLI launcher bytes do not match the verified runtime receipt.'
}

if (-not (Set-MarketplaceEntry $OriginalMarketplaceEntry $CandidateMarketplaceEntry)) {
    Restore-CandidateActivation 'The Dev Flow marketplace member changed concurrently.'
}
$script:TxMarketplace = 'candidate'
$script:TxStep = 'marketplace'
if (-not (Write-InstallTransaction)) { Restore-CandidateActivation 'Cannot record the marketplace member update.' }

if ($InstalledMatches.Count -eq 1) {
    & codex plugin remove $PluginId
    if ((Get-PluginObservation) -ne 'absent') {
        $script:TxPlugin = 'unknown'
        Restore-CandidateActivation "Cannot remove $PluginId or prove it absent."
    }
    $script:TxPlugin = 'absent'
    $script:TxStep = 'plugin-removed'
    if (-not (Write-InstallTransaction)) { Restore-CandidateActivation 'Cannot record the observed plugin removal.' }
}

& codex plugin add $PluginId
$CandidateObserved = Get-PluginObservation
if ($CandidateObserved -ne ('active:' + $PluginVersion)) {
    $script:TxPlugin = if ($CandidateObserved -eq 'absent') { 'absent' } else { 'unknown' }
    Restore-CandidateActivation 'Codex did not expose the candidate plugin after activation.'
}
$script:TxPlugin = 'candidate'
$script:TxStep = 'plugin-active'
if (-not (Write-InstallTransaction)) { Restore-CandidateActivation 'Cannot record the observed plugin activation.' }

if (-not (Test-BundledMcpVisibility)) {
    Restore-CandidateActivation 'The activated bundled MCP registration is missing, disabled, duplicated, or shadowed.'
}
if (-not (Test-ReleaseHealth $RuntimePython $PersistentPluginRoot)) {
    Restore-CandidateActivation 'The real installed launcher failed initialize, catalog, read, or mutation smoke.'
}

try { Remove-Item -LiteralPath $TransactionRoot -Recurse -Force -ErrorAction Stop }
catch { Restore-CandidateActivation 'Cannot clean the bounded transaction staging directory.' }

$script:TxStep = 'committed'
$script:TxOutcome = 'committed'
$script:TxRuntime = 'candidate-active'
$script:TxBlindRetrySafe = $true
if (-not (Write-InstallTransaction)) { Restore-CandidateActivation 'Cannot publish the committed installation transaction.' }

if (-not (Test-SelectedSourceInventory)) {
    [Console]::Error.WriteLine('Authoritative source changed after sealing; no post-seal activation input was read from that checkout.')
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
Write-Output "CLI COMMAND    $CliLauncherPath"
Write-Output 'FIRST PROMPT   Ask Codex to discover or start a Dev Flow task through the dev-flow MCP server.'
