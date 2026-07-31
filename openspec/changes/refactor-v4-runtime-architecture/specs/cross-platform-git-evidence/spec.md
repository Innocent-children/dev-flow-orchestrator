## ADDED Requirements

### Requirement: Current macOS Git evidence is explicit
The greenfield Git client SHALL capture byte-accurate current repository
identity, HEAD, branch, status and required worktree evidence on the current
macOS host through argument-vector subprocess calls. Every evidence record
MUST bind the exact Git capability observations used by its node. This change
MUST NOT claim Windows/Linux validation or parity.

#### Scenario: Preflight a current macOS repository
- **WHEN** the greenfield preflight node reads a Git repository on the current macOS host
- **THEN** it returns deterministic bounded evidence tied to that repository and performs no Git mutation

#### Scenario: Git evidence is unavailable
- **WHEN** required Git output is missing, undecodable or contradictory
- **THEN** preflight returns a structured blocker and task state does not advance

### Requirement: Git mutations require a declared effect port
Every Git-changing operation SHALL be represented by a node contract and
executed only through the greenfield Git effect port after controller
authorization. No adapter or domain node may execute Git mutation directly.

#### Scenario: Attempt Git mutation from a node
- **WHEN** domain or adapter code tries to call a mutating Git command
- **THEN** architecture validation rejects the dependency

## REMOVED Requirements

### Requirement: Capability-aware Git evidence profile
**Reason**: 该 requirement 要求跨 Windows/POSIX profile；当前 release 只验证
macOS。

**Migration**: 保留 byte-accurate evidence invariant，不迁移 platform parity。

### Requirement: Portable repository path selectors
**Reason**: Windows drive/UNC selector 不属于当前 macOS-only product contract。

**Migration**: current macOS path 使用 canonical absolute path 和 stable repository
identity。
