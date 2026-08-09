## ADDED Requirements

### Requirement: Subprocess tests own every mutable authority

Every CLI, installer, uninstaller, managed-runtime, installed-journey, Web runtime,
MCP runtime, Windows runtime, and lifecycle subprocess fixture SHALL use a hermetic environment
that removes inherited `DEV_FLOW_DATA_DIR`, `PLUGIN_DATA`, `CODEX_HOME`, and every
supported authority capable of selecting data, runtime, source, marketplace,
profile, home, temporary, or executable paths before setting explicit test-local
values. The scrub list SHALL include `XDG_DATA_HOME`, `GIT_DIR`, `GIT_WORK_TREE`, and
`GIT_INDEX_FILE`; Git fixture setup and production-script invocations SHALL not be
redirectable outside the fixture by inherited Git state. At minimum, lifecycle tests
SHALL set temporary `HOME`, `CODEX_HOME`,
`DEV_FLOW_DATA_DIR` where explicit selection is intended,
`DEV_FLOW_RUNTIME_HOME`, `LOCALAPPDATA`, and `USERPROFILE`, plus temporary source,
marketplace, temporary directories, fake Codex, and `PATH` values appropriate to the
host.

Every fixture SHALL validate the final child environment after all per-test
overrides are merged. A child-side probe SHALL invoke the actual data and managed
runtime resolvers, return their resolved roots, and allow the parent test to prove
both roots are descendants of the current `TemporaryDirectory`; parent-side mapping
resolution alone is insufficient.

The product's normal data-root precedence SHALL remain unchanged. Each test SHALL
assert that the resolved data and runtime roots are descendants of its own temporary
directory before invoking production lifecycle behavior. Native Windows lifecycle
tests SHALL not run destructive production paths until the same containment is
established.

#### Scenario: Parent sets DEV_FLOW_DATA_DIR

- **WHEN** the parent process points `DEV_FLOW_DATA_DIR` at an external directory
  containing recognizable Web state and a sentinel
- **THEN** the child under test resolves only its declared temporary data root and
  the external directory remains byte-for-byte unchanged

#### Scenario: Parent sets PLUGIN_DATA

- **WHEN** the parent process points `PLUGIN_DATA` at an external directory
- **THEN** the child ignores that inherited authority, remains within its temporary
  profile, and leaves the external sentinel unchanged

#### Scenario: Parent sets CODEX_HOME

- **WHEN** the parent points `CODEX_HOME` at an external profile containing running
  Web state, task data, PID/status data, and a recognizable sentinel
- **THEN** a child test with its own declared profile resolves below its
  `TemporaryDirectory`, observes no external running state, and leaves every
  external byte unchanged

#### Scenario: Parent sets authority combinations

- **WHEN** the hostile parent sets `DEV_FLOW_DATA_DIR + PLUGIN_DATA`,
  `DEV_FLOW_DATA_DIR + CODEX_HOME`, `PLUGIN_DATA + CODEX_HOME`, or all three
- **THEN** the child environment removes the inherited combination before declaring
  its own authority, the production precedence remains unchanged, and the resolved
  root remains below the child's `TemporaryDirectory`

#### Scenario: Parent redirects runtime and Git authorities

- **WHEN** the parent sets external `XDG_DATA_HOME`, `GIT_DIR`, `GIT_WORK_TREE`, or
  `GIT_INDEX_FILE` values
- **THEN** final override validation, child-side resolver probes, fixture Git setup,
  and production commands remain within the current `TemporaryDirectory` and leave
  every external sentinel unchanged

#### Scenario: Temporary CODEX_HOME fallback is tested

- **WHEN** a test intentionally verifies the `CODEX_HOME` fallback
- **THEN** it starts from a scrubbed environment with no higher-priority data-root
  override and asserts the resolver result is below that temporary `CODEX_HOME`

#### Scenario: Native Windows fixture is prepared

- **WHEN** the PowerShell lifecycle suite is eligible to run on a supported Windows
  client
- **THEN** `DEV_FLOW_RUNTIME_HOME`, `LOCALAPPDATA`, `USERPROFILE`, data, source,
  marketplace, and executable paths are all temporary before a production script is
  invoked

### Requirement: External authority evidence remains untouched

Hostile-parent tests SHALL place recognizable sentinel bytes, running Web state,
PID/status data, and task data under external temporary authority roots. The child's
own temporary data root SHALL contain no running state before invocation. Tests SHALL
assert the resolved child data root is contained by the current `TemporaryDirectory`
and that external sentinel, runtime state, PID/status, and task bytes are identical
before and after execution. A test SHALL NOT manufacture isolation by clearing the
invoking shell.

#### Scenario: External Web state is live

- **WHEN** the hostile external root contains a reachable running Web runtime
- **THEN** the isolated child still reports only its own stopped/absent state and
  does not read, overwrite, stop, or delete the external runtime

#### Scenario: External task data exists

- **WHEN** a hostile authority root contains recognizable task data
- **THEN** child CLI and lifecycle fixtures leave it byte-for-byte unchanged and do
  not expose it in their result

### Requirement: Windows verification distinguishes static and native evidence

Host-neutral/static tests SHALL inspect PowerShell containment and lock invariants on
any supported development host. Native Windows dynamic tests SHALL separately cover
lock order, canonical multi-repository ordering, concurrent mutation, freshness
true/false/unknown, retained source output, exact-ownership reason, partial outcome,
manual recovery, temporary mutation targets, and external sentinel stability.

#### Scenario: Native Windows host is unavailable

- **WHEN** verification runs on a non-Windows host
- **THEN** static checks may report their actual result while every native Windows
  dynamic item is recorded as `NOT RUN — native Windows host unavailable`, never as
  passed evidence
