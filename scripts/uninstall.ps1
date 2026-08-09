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

function Fail([string]$Message) { [Console]::Error.WriteLine("Dev Flow uninstallation failed: $Message"); exit 1 }
function Capture-Checked([string]$Program, [string[]]$Arguments, [string]$Failure) {
    $Output = & $Program @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { Fail $Failure }
    return (($Output | Out-String).Trim())
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
$McpLauncherPresent = Test-Path -LiteralPath $McpLauncherPath
if ($McpLauncherPresent) {
    if (-not (Test-Path -LiteralPath $McpLauncherPath -PathType Leaf)) { Fail "$McpLauncherPath is not a regular file." }
    if (@(Get-Content -LiteralPath $McpLauncherPath -TotalCount 3 -Encoding UTF8) -notcontains $McpLauncherMarker) {
        Fail "$McpLauncherPath exists but is not owned by Dev Flow."
    }
}
$RuntimePresent = Test-Path -LiteralPath $RuntimeRoot
if ($RuntimePresent) {
    if (-not (Test-Path -LiteralPath $RuntimeRoot -PathType Container)) { Fail "$RuntimeRoot is not a directory." }
    if ((Get-Item -LiteralPath $RuntimeRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "$RuntimeRoot is a reparse point." }
    $Marker = Join-Path $RuntimeRoot '.dev-flow-managed-runtime'
    if (-not (Test-Path -LiteralPath $Marker -PathType Leaf) -or (Get-Content -LiteralPath $Marker -Raw -Encoding UTF8) -ne "dev-flow-managed-runtime/1`n") {
        Fail "$RuntimeRoot does not have the Dev Flow managed-runtime marker."
    }
    $Releases = Join-Path $RuntimeRoot 'releases'
    if (-not (Test-Path -LiteralPath $Releases -PathType Container) -or ((Get-Item -LiteralPath $Releases -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Fail "$RuntimeRoot has no receipt-validated releases directory."
    }
    $ReleaseDirectories = @(Get-ChildItem -LiteralPath $Releases -Directory -Force)
    if ($ReleaseDirectories.Count -eq 0) { Fail "$RuntimeRoot has no receipt-validated release." }
    foreach ($Release in $ReleaseDirectories) {
        if ($Release.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "$($Release.FullName) is a reparse point." }
        $ReceiptPath = Join-Path $Release.FullName 'runtime-receipt.json'
        try { $Receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Fail "$ReceiptPath cannot be read." }
        $ExpectedFields = @('activation_action', 'activated_at', 'dependency_lock_sha256', 'launcher_identity', 'python', 'release_version', 'runtime_identity', 'schema', 'source_commit')
        $ActualFields = @($Receipt.PSObject.Properties.Name | Sort-Object)
        if (($ActualFields -join ',') -ne ($ExpectedFields -join ',')) { Fail "$ReceiptPath fields are invalid." }
        $Commit = [string]$Receipt.source_commit
        $Lock = [string]$Receipt.dependency_lock_sha256
        if ($Receipt.schema -ne 'dev-flow-runtime-receipt/1.0.0' -or $Receipt.release_version -ne '0.5.0' -or $Receipt.launcher_identity -ne 'dev-flow-mcp --stdio' -or $Commit -notmatch '^[0-9a-f]{40}$' -or $Lock -notmatch '^[0-9a-f]{64}$') {
            Fail "$ReceiptPath identity is invalid."
        }
        $PythonFields = @($Receipt.python.PSObject.Properties.Name | Sort-Object)
        if (($PythonFields -join ',') -ne 'architecture,bits,executable_sha256,version' -or $Receipt.python.bits -ne 64) { Fail "$ReceiptPath Python identity is invalid." }
        $ExpectedName = "0.5.0-$($Commit.Substring(0,12))-$($Lock.Substring(0,12))"
        if ($Release.Name -ne $ExpectedName) { Fail "$ReceiptPath does not match its release directory." }
        $CanonicalReleaseLocation = [IO.Path]::GetFullPath($Release.FullName).ToLowerInvariant()
        $IdentityBytes = [Text.Encoding]::UTF8.GetBytes($CanonicalReleaseLocation)
        $Hasher = [Security.Cryptography.SHA256]::Create()
        try { $ExpectedRuntimeIdentity = ([BitConverter]::ToString($Hasher.ComputeHash($IdentityBytes))).Replace('-', '').ToLowerInvariant() } finally { $Hasher.Dispose() }
        if ($Receipt.runtime_identity -ne $ExpectedRuntimeIdentity -or $Receipt.activation_action -notin @('create', 'update')) { Fail "$ReceiptPath managed location identity is invalid." }
        $RuntimePython = Join-Path $Release.FullName 'venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $RuntimePython -PathType Leaf)) { Fail "$RuntimePython is missing." }
        if ((Get-FileHash -LiteralPath $RuntimePython -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$Receipt.python.executable_sha256) { Fail "$RuntimePython does not match its receipt." }
        $ActivationTime = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string]$Receipt.activated_at, [ref]$ActivationTime)) { Fail "$ReceiptPath activation timestamp is invalid." }
    }
}

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
$RuntimeAction = 'already absent'
if ($RuntimePresent) {
    Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force
    $RuntimeAction = 'removed'
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
Write-Output "MCP RUNTIME    $RuntimeAction"
Write-Output 'STANDALONE     preserved / no owned registration removed'
Write-Output 'TASK DATA      preserved (external Controller data was not changed)'
Write-Output 'MANUAL ACTION  Inspect and back up the retained source checkout, then independently confirm ownership before any manual action.'
