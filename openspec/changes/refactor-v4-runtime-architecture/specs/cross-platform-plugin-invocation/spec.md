## ADDED Requirements

### Requirement: Packaged macOS commands launch the greenfield project
The plugin SHALL register one package-owned macOS launch path for each bundled
CLI, Hook and optional MCP entrypoint. Each command MUST safely resolve the
plugin root, add only its fixed `src` directory to the isolated interpreter
path and import the greenfield entrypoint. It MUST NOT execute source fragments
or select another runtime by environment, platform fallback or task content.

#### Scenario: Launch from a path containing spaces
- **WHEN** Codex starts a packaged command from a non-trivial macOS plugin path
- **THEN** the command imports the intended greenfield entrypoint and exchanges the declared JSON wire format

#### Scenario: Inspect all packaged commands
- **WHEN** validation resolves plugin, Hook, Skill and MCP commands
- **THEN** every runtime command points to the same greenfield product and no Windows/Linux or predecessor command is required

## REMOVED Requirements

### Requirement: Platform-specific bundled hook launch
**Reason**: 当前 release 不提供 Windows launch contract。

**Migration**: 只保留 packaged macOS Hook command。

### Requirement: Platform-specific MCP profiles use their native packaged launch commands
**Reason**: 当前 release 只有一个 optional macOS MCP profile，不维护跨平台 profile
矩阵。

**Migration**: 使用 current macOS profile。

### Requirement: Wrapped Git commands receive equivalent guardrails
**Reason**: Windows Command Prompt/PowerShell wrapper parsing不属于当前 validation
范围；greenfield controller authority 不依赖 wrapper compatibility。

**Migration**: macOS supported Git command 继续经过 current Hook 和 controller
effect boundary。
