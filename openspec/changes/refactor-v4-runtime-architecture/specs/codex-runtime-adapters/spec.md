## ADDED Requirements

### Requirement: Every public entrypoint is a thin greenfield adapter
CLI, MCP, Hook and Skill SHALL call the same greenfield controller application
API. They MAY parse or serialize their own wire protocol but MUST NOT select a
workflow, evaluate a node, write task state, execute a workflow effect or
recover an action independently.

#### Scenario: Call through CLI and MCP
- **WHEN** CLI and MCP submit the same current action and revision
- **THEN** both reach the same controller operation and receive equivalent committed semantics

#### Scenario: Hook observes a command
- **WHEN** a Hook evaluates an in-scope tool request
- **THEN** it returns bounded advisory context or denial without performing a workflow transition

### Requirement: The current JSON CLI is independently usable
The greenfield JSON CLI SHALL run with Python's standard library and explicit
`--data-dir` without requiring MCP, Hook, SDK, Node.js or the old runtime. Its
command grammar and response envelope SHALL be defined by current V4 specs,
not by compatibility with schema-v1/v2/v3 responses or internal Python
symbols.

#### Scenario: Run the minimal CLI
- **WHEN** MCP and Hooks are disabled
- **THEN** an operator can run the implemented greenfield `start`, `show` and `preflight` commands and receive one JSON stdout object

#### Scenario: Request an old-only command before cutover
- **WHEN** a focused greenfield test requests a capability not yet implemented
- **THEN** the new CLI returns a stable unsupported-action response and does not call the old CLI

### Requirement: Plugin packaging launches only the greenfield runtime
After Atomic Greenfield Cutover, every packaged CLI, MCP and Hook command SHALL
resolve to `src/dev_flow_orchestrator/` through a fixed package-owned bootstrap.
The package MUST contain no command, wrapper, fallback, environment selector
or optional profile that can execute `scripts/dev_flow_parts/`.

#### Scenario: Validate package commands
- **WHEN** package validation resolves every plugin manifest, MCP and Hook command
- **THEN** each command starts the greenfield package and none references an old runtime path

## REMOVED Requirements

### Requirement: The JSON CLI remains a complete compatibility and recovery surface
**Reason**: greenfield V4 intentionally does not preserve schema-v1/v2/v3
grammar, response or recovery compatibility.

**Migration**: 无 historical caller 或 data；使用 current V4 CLI。

### Requirement: MCP failures degrade to explicit CLI fallback
**Reason**: CLI 与 MCP 是调用同一 controller 的独立 adapter；MCP failure 不应创建
隐式 fallback dispatch path。

**Migration**: MCP unavailable 时用户可显式调用 documented CLI command，系统不会
自动重放或切换 transport。

### Requirement: Plugin packaging declares runtime adapters without adding hidden dependencies
**Reason**: 旧 requirement 包含 facade compatibility、V3/V4 evidence 和 platform
profile obligation，已由 greenfield package launch requirement 取代。

**Migration**: package validator 只验证 current macOS greenfield entrypoint。
