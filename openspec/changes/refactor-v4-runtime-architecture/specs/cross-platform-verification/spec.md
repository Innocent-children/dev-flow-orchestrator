## ADDED Requirements

### Requirement: Greenfield verification follows skeleton-first gates
Verification SHALL first exercise the minimal greenfield `start`, `show` and
`preflight` vertical slice, then add only the focused tests for each newly
implemented node contract. A later node MUST NOT be used to compensate for an
unverified skeleton boundary.

#### Scenario: Verify the skeleton
- **WHEN** product, store, engine, controller, Git reader and CLI skeleton are implemented
- **THEN** focused tests cover four profile creations, schema-v4 persistence, revision conflict, preflight read and one JSON response

#### Scenario: Add one node
- **WHEN** a later workflow node is implemented
- **THEN** verification adds the minimum representative success, authority failure and effect/recovery case for that node

### Requirement: Architecture validation rejects hidden complexity
Before cutover, validation SHALL reject greenfield imports of the old runtime,
`exec`/`eval` source loading, string-based operation lookup, duplicate product
matrices, adapter state writes, domain infrastructure imports, old-runtime
wrapper/fallback and public dual-dispatch.

#### Scenario: Validate source independence
- **WHEN** the greenfield source and public entrypoints are audited
- **THEN** every dependency follows the documented direction and no forbidden old-runtime edge exists

### Requirement: Release verification is current macOS and focused
Release evidence SHALL be produced only on the current macOS host for the
frozen greenfield candidate. It MUST include exact focused node suites, Skill
validation, plugin manifest validation, package inventory validation, OpenSpec
strict validation and `git diff --check`. It MUST NOT run the full suite,
legacy-data tests or native Windows/Linux validation, and MUST NOT extrapolate
support from macOS evidence.

#### Scenario: Verify the frozen candidate
- **WHEN** all greenfield slices and Atomic Greenfield Cutover are complete
- **THEN** the exact focused suites and required package validators pass against the same frozen candidate identity

#### Scenario: Request full-suite evidence
- **WHEN** a milestone or reviewer asks for `python3 -m unittest discover -s tests -v`
- **THEN** the run is skipped and reported unverified rather than executed

## REMOVED Requirements

### Requirement: Native operating-system and supported-Python CI matrix
**Reason**: 本 release 不验证 Windows/Linux matrix。

**Migration**: 只记录当前 macOS host 和实际 Python version。

### Requirement: Project-local Windows native validation is safe and evidence-producing
**Reason**: Windows validation 不在当前范围。

**Migration**: 无。

### Requirement: Windows support includes a real Codex-host pickup smoke
**Reason**: 当前 product 不宣称 Windows support。

**Migration**: 真实 macOS Codex acceptance 仍由用户执行。

### Requirement: Cross-platform tests use portable and isolated fixtures
**Reason**: cross-platform suite 被当前 macOS focused fixture contract 取代。

**Migration**: focused tests 仍使用显式临时 `--data-dir` 和隔离 Git repository。
