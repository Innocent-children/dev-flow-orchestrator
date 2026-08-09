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
    Write-Output 'The source checkout is always retained; -KeepSource remains accepted for compatibility.'
    exit 0
}

$SourceRoot = [IO.Path]::GetFullPath($(if ($env:DEV_FLOW_SOURCE_ROOT) { $env:DEV_FLOW_SOURCE_ROOT } else { Join-Path $env:USERPROFILE 'plugins\dev-flow-orchestrator' }))
$MarketplaceFile = [IO.Path]::GetFullPath($(if ($env:DEV_FLOW_MARKETPLACE_FILE) { $env:DEV_FLOW_MARKETPLACE_FILE } else { Join-Path $env:USERPROFILE '.agents\plugins\marketplace.json' }))
$CodexRoot = [IO.Path]::GetFullPath($(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }))
$RuntimeRoot = [IO.Path]::GetFullPath($(if ($env:DEV_FLOW_RUNTIME_HOME) { $env:DEV_FLOW_RUNTIME_HOME } else { Join-Path $env:LOCALAPPDATA 'dev-flow-orchestrator\runtime' }))
$PluginId = 'dev-flow-orchestrator@personal'
$McpLauncherMarker = 'rem dev-flow-orchestrator managed MCP launcher'
$CliLauncherMarker = 'rem dev-flow-orchestrator managed CLI launcher'
$RuntimeIntegrityHelper = Join-Path $PSScriptRoot 'runtime_integrity.py'

function Fail([string]$Message) { [Console]::Error.WriteLine("Dev Flow uninstallation failed: $Message"); exit 1 }
function Capture-Checked([string]$Program, [string[]]$Arguments, [string]$Failure) {
    $Output = & $Program @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { Fail $Failure }
    return (($Output | Out-String).Trim())
}
function Find-OwnershipPython {
    $Candidates = @(
        [pscustomobject]@{ Program = 'py.exe'; Prefix = @('-3') },
        [pscustomobject]@{ Program = 'python.exe'; Prefix = @() },
        [pscustomobject]@{ Program = 'python3.exe'; Prefix = @() }
    )
    foreach ($Candidate in $Candidates) {
        if (-not (Get-Command $Candidate.Program -ErrorAction SilentlyContinue)) { continue }
        & $Candidate.Program @($Candidate.Prefix) -B -I -S -c 'import struct,sys;raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,15) and struct.calcsize("P") == 8 else 1)' *> $null
        if ($LASTEXITCODE -eq 0) { return $Candidate }
    }
    return $null
}
function Find-BinDirectory {
    if ($env:DEV_FLOW_BIN_DIR) { $Candidates = @($env:DEV_FLOW_BIN_DIR) }
    else { $Candidates = @($env:PATH -split ';' | Where-Object { $_ }) }
    foreach ($Candidate in $Candidates) {
        try { $Full = [IO.Path]::GetFullPath($Candidate) } catch { continue }
        if (Test-Path -LiteralPath $Full -PathType Container) { return $Full }
    }
    Fail 'PATH has no absolute directory; set DEV_FLOW_BIN_DIR explicitly.'
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
    return $null -ne $EnabledProperty -and $EnabledProperty.Value -is [bool] -and $EnabledProperty.Value
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
        if ($null -ne $CommandProperty -and $CommandProperty.Value -is [string]) { $Commands += [string]$CommandProperty.Value }
    }
    foreach ($Command in $Commands) {
        if (Test-OwnedMcpCommand $Command $OwnedLauncher) { return $true }
    }
    return $false
}
function Test-BundledMcpRegistration([object]$Registration) {
    $NameProperty = $Registration.PSObject.Properties['name']
    if ($null -eq $NameProperty -or -not ($NameProperty.Value -is [string]) -or $NameProperty.Value -cne 'dev-flow' -or -not (Test-McpRegistrationEnabled $Registration)) { return $false }
    $TransportProperty = $Registration.PSObject.Properties['transport']
    if ($null -eq $TransportProperty -or $null -eq $TransportProperty.Value) { return $false }
    $Transport = $TransportProperty.Value
    $TypeProperty = $Transport.PSObject.Properties['type']
    $CommandProperty = $Transport.PSObject.Properties['command']
    $ArgsProperty = $Transport.PSObject.Properties['args']
    if ($null -eq $TypeProperty -or -not ($TypeProperty.Value -is [string]) -or $TypeProperty.Value -cne 'stdio') { return $false }
    if ($null -eq $CommandProperty -or -not ($CommandProperty.Value -is [string]) -or $CommandProperty.Value -cne 'dev-flow-mcp') { return $false }
    if ($null -eq $ArgsProperty -or -not ($ArgsProperty.Value -is [Array])) { return $false }
    $Arguments = @($ArgsProperty.Value)
    return $Arguments.Count -eq 1 -and $Arguments[0] -is [string] -and $Arguments[0] -ceq '--stdio'
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

if ($env:OS -ne 'Windows_NT') { Fail 'This uninstaller requires a supported Windows x64 client.' }
if (-not [Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { Fail 'This uninstaller requires an x64 process on Windows x64.' }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { Fail 'Codex with plugin support is required.' }
$BinDirectory = Find-BinDirectory
$McpLauncherPath = Join-Path $BinDirectory 'dev-flow-mcp.cmd'
$CliLauncherPath = Join-Path $BinDirectory 'dev-flow.cmd'
$McpLauncherPresent = Test-Path -LiteralPath $McpLauncherPath
if ($McpLauncherPresent) {
    if (-not (Test-Path -LiteralPath $McpLauncherPath -PathType Leaf)) { Fail "$McpLauncherPath is not a regular file." }
    if (@(Get-Content -LiteralPath $McpLauncherPath -TotalCount 3 -Encoding UTF8) -notcontains $McpLauncherMarker) {
        Fail "$McpLauncherPath exists but is not owned by Dev Flow."
    }
}
$CliLauncherPresent = Test-Path -LiteralPath $CliLauncherPath
if ($CliLauncherPresent) {
    if (-not (Test-Path -LiteralPath $CliLauncherPath -PathType Leaf)) { Fail "$CliLauncherPath is not a regular file." }
    if (@(Get-Content -LiteralPath $CliLauncherPath -TotalCount 3 -Encoding UTF8) -notcontains $CliLauncherMarker) {
        Fail "$CliLauncherPath exists but is not owned by Dev Flow."
    }
}
$RuntimePresent = Test-Path -LiteralPath $RuntimeRoot

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

$PluginJson = Capture-Checked 'codex' @('plugin', 'list', '--marketplace', 'personal', '--json') 'Cannot inspect installed plugins.'
try { $PluginState = $PluginJson | ConvertFrom-Json } catch { Fail 'Codex returned invalid plugin JSON.' }
$PluginEntries = @($PluginState.installed | Where-Object {
    $PluginIdProperty = $_.PSObject.Properties['pluginId']
    $null -ne $PluginIdProperty -and $PluginIdProperty.Value -is [string] -and $PluginIdProperty.Value -ceq $PluginId
})
if ($PluginEntries.Count -gt 1) { Fail 'Codex returned duplicate Dev Flow plugin entries.' }
$Installed = @($PluginEntries | Where-Object {
    $InstalledProperty = $_.PSObject.Properties['installed']
    $null -ne $InstalledProperty -and $InstalledProperty.Value -is [bool] -and $InstalledProperty.Value
})
$PluginBundledActive = $false
if ($Installed.Count -eq 1) {
    $EnabledProperty = $Installed[0].PSObject.Properties['enabled']
    $PluginBundledActive = $null -ne $EnabledProperty -and $EnabledProperty.Value -is [bool] -and $EnabledProperty.Value
}

$McpListJson = Capture-Checked 'codex' @('mcp', 'list', '--json') 'Cannot inspect standalone MCP registrations before uninstalling.'
if (-not $McpListJson.TrimStart().StartsWith('[')) { Fail 'Codex MCP registration JSON must be an array.' }
try { $McpRegistrations = @($McpListJson | ConvertFrom-Json) } catch { Fail 'Codex returned invalid MCP registration JSON.' }
$ConfigPath = Join-Path $CodexRoot 'config.toml'
$ExplicitMcpConflicts = @(Get-ExplicitOwnedMcpRegistrationNames $ConfigPath $McpLauncherPath)
if ($ExplicitMcpConflicts.Count -gt 0) {
    Fail "Explicit standalone Dev Flow MCP registration(s) $($ExplicitMcpConflicts -join ', ') are present in $ConfigPath; remove them explicitly before uninstalling bundled mode."
}
$CanonicalBundled = @($McpRegistrations | Where-Object { Test-BundledMcpRegistration $_ })
$OwnedRegistrations = @($McpRegistrations | Where-Object { Test-OwnedMcpRegistration $_ $McpLauncherPath })
if ($PluginBundledActive) {
    if ($CanonicalBundled.Count -ne 1 -or $OwnedRegistrations.Count -ne 1) {
        Fail 'Active bundled plugin must expose exactly one enabled canonical dev-flow STDIO registration and no additional owned-launcher registrations before uninstalling.'
    }
} elseif ($OwnedRegistrations.Count -gt 0) {
    $Names = (($OwnedRegistrations | ForEach-Object {
        $NameProperty = $_.PSObject.Properties['name']
        if ($null -ne $NameProperty -and $NameProperty.Value) { $NameProperty.Value } else { '<unnamed>' }
    }) -join ', ')
    Fail "Standalone Dev Flow MCP registration(s) $Names still target the launcher/runtime selected for removal; remove them explicitly with codex mcp first."
}

$PluginAction = 'already absent'
if ($Installed.Count -eq 1) {
    & codex plugin remove $PluginId
    if ($LASTEXITCODE -ne 0) { Fail "Cannot remove $PluginId." }
    $PluginAction = 'removed'
}

$McpLauncherAction = 'already absent'
if ($McpLauncherPresent) {
    Remove-Item -LiteralPath $McpLauncherPath -Force
    $McpLauncherAction = 'removed'
}
$CliLauncherAction = 'already absent'
if ($CliLauncherPresent) {
    Remove-Item -LiteralPath $CliLauncherPath -Force
    $CliLauncherAction = 'removed'
}
$RuntimeAction = 'already absent'
$RuntimeRetainedPaths = @()
if ($RuntimePresent) {
    $OwnershipPython = Find-OwnershipPython
    if (
        $null -eq $OwnershipPython -or
        -not (Test-Path -LiteralPath $RuntimeIntegrityHelper -PathType Leaf) -or
        ((Get-Item -LiteralPath $RuntimeIntegrityHelper -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)
    ) {
        $RuntimeAction = 'retained (exact ownership helper unavailable)'
        $RuntimeRetainedPaths = @($RuntimeRoot)
    } else {
        $PreviousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
        try {
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $RuntimeRemovalOutput = & $OwnershipPython.Program @($OwnershipPython.Prefix) -B -I -S $RuntimeIntegrityHelper remove-owned --runtime-root $RuntimeRoot
            $RuntimeRemovalExitCode = $LASTEXITCODE
        } finally {
            if ($null -eq $PreviousNoBytecode) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
            else { $env:PYTHONDONTWRITEBYTECODE = $PreviousNoBytecode }
        }
        try { $RuntimeRemoval = (($RuntimeRemovalOutput | Out-String).Trim()) | ConvertFrom-Json } catch { $RuntimeRemoval = $null }
        if ($RuntimeRemovalExitCode -eq 0 -and $null -ne $RuntimeRemoval -and $RuntimeRemoval.action -eq 'removed') {
            $RuntimeAction = 'removed (exact ownership manifest)'
        } elseif ($RuntimeRemovalExitCode -eq 0 -and $null -ne $RuntimeRemoval -and $RuntimeRemoval.action -eq 'partial') {
            $RuntimeAction = 'partial (unknown or changed content retained)'
            $RuntimeRetainedPaths = @($RuntimeRemoval.retained_paths | Where-Object { $_ -is [string] })
        } else {
            $RuntimeAction = 'retained (legacy, missing, or mismatched exact ownership)'
            if ($null -ne $RuntimeRemoval) {
                $RuntimeRetainedPaths = @($RuntimeRemoval.retained_paths | Where-Object { $_ -is [string] })
            }
            if ($RuntimeRetainedPaths.Count -eq 0) { $RuntimeRetainedPaths = @($RuntimeRoot) }
        }
    }
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

$SourceAction = 'already absent (no deletion attempted)'
if (Test-Path -LiteralPath $SourceRoot) {
    $SourceAction = 'retained (destructive removal disabled)'
}

Write-Output ''
Write-Output 'DEV FLOW ORCHESTRATOR // UNINSTALL RECEIPT'
Write-Output 'OUTCOME        partial'
Write-Output "PLUGIN         $PluginAction"
Write-Output "MARKETPLACE    $MarketplaceAction"
Write-Output "SOURCE         $SourceAction"
Write-Output "SOURCE PATH    $SourceRoot"
Write-Output 'SOURCE REASON  destructive removal disabled: no verifiable exact-ownership manifest'
Write-Output "MCP COMMAND    $McpLauncherAction"
Write-Output "CLI COMMAND    $CliLauncherAction"
Write-Output "MCP RUNTIME    $RuntimeAction"
if ($RuntimeRetainedPaths.Count -gt 0) {
    Write-Output "RUNTIME RETAINED $($RuntimeRetainedPaths -join '; ')"
}
Write-Output 'STANDALONE     preserved / no owned registration removed'
Write-Output 'TASK DATA      preserved (external Controller data was not changed)'
if ($RuntimeRetainedPaths.Count -gt 0) {
    Write-Output "RUNTIME ACTION Inspect retained runtime paths before any manual deletion: $($RuntimeRetainedPaths -join '; ')"
}
Write-Output 'MANUAL ACTION  Inspect and back up the retained source checkout, then independently confirm ownership before any manual action.'
