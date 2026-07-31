## ADDED Requirements

### Requirement: Greenfield runtime uses explicit macOS infrastructure boundaries
The greenfield store, lock, filesystem, Git and process implementations SHALL
be ordinary macOS infrastructure modules behind the controller boundary. State
directories and files MUST remain private, state replacement MUST be atomic,
writer locks MUST fail closed, subprocesses MUST use argument vectors and
Hook internal failures MUST remain fail open. Domain modules MUST NOT import
these infrastructure modules.

#### Scenario: Commit private task state
- **WHEN** the controller creates or replaces schema-v4 task state on macOS
- **THEN** directory and file permissions remain private and another stale writer cannot commit

#### Scenario: Infrastructure operation fails
- **WHEN** lock, atomic replacement or required process observation fails
- **THEN** mutation stops with a structured error and no success state is inferred

#### Scenario: Hook infrastructure fails
- **WHEN** a Hook encounters an internal parsing or process error
- **THEN** it reports bounded advisory failure and does not claim controller authorization

### Requirement: Runtime code uses only standard library and package modules
Every greenfield runtime import SHALL resolve to Python standard library or
`dev_flow_orchestrator`. Startup validation MUST reject a third-party runtime
import before a public entrypoint accepts work.

#### Scenario: Import in isolated Python
- **WHEN** the greenfield CLI starts with `-I -S`
- **THEN** it initializes using only packaged source and Python standard library

## REMOVED Requirements

### Requirement: Platform-native state directory and actor defaults
**Reason**: Windows and Linux native default contracts are outside the current
macOS-only release.

**Migration**: 使用 current macOS data directory 或显式 `--data-dir`。

### Requirement: Atomic portable state writes
**Reason**: portable Windows replacement behavior不在本次验证范围。

**Migration**: atomicity invariant 由新的 macOS infrastructure requirement 保留。

### Requirement: Portable subprocess and interruption handling
**Reason**: cross-platform process parity 不属于当前 contract。

**Migration**: argument-vector execution 和 bounded interruption safety 在 macOS
infrastructure 中重新实现。

### Requirement: Fail-closed cross-platform locking
**Reason**: Windows lock backend 不属于当前 contract。

**Migration**: current macOS writer lock 继续 fail closed。

### Requirement: Standard-library-only runtime parity
**Reason**: standard-library-only 保留，但不宣称跨平台 parity。

**Migration**: 使用新的 standard-library-only requirement。
