## ADDED Requirements

### Requirement: Windows lifecycle fixtures contain every authority

Windows lifecycle fixtures SHALL use a minimal environment and prove HOME, USERPROFILE,
LOCALAPPDATA, CODEX_HOME, data, runtime, marketplace, source, PATH, launcher, fake Codex,
and temporary-file authorities are descendants of one temporary root before and after
production scripts, with external sentinels unchanged.

#### Scenario: A target resolves outside the fixture

- **WHEN** any resolved mutation target is outside the temporary root
- **THEN** the test SHALL stop before invoking the production lifecycle script

### Requirement: POSIX lifecycle honors DEV_FLOW_PYTHON

Install and uninstall SHALL prefer an explicitly configured regular executable supported
64-bit CPython and fail clearly if that override is invalid; without an override they
SHALL validate candidates in order and continue past invalid candidates.

#### Scenario: Override path contains special characters

- **WHEN** a valid override path contains spaces, Unicode, or apostrophes
- **THEN** both lifecycle scripts SHALL select it without shell reinterpretation

#### Scenario: The first fallback candidate is unsupported

- **WHEN** `python3` is invalid and a later candidate is supported
- **THEN** selection SHALL continue to the supported candidate

### Requirement: Windows installs the supported CLI and Web launcher

The bundled Windows lifecycle SHALL install an exact-owned `dev-flow.cmd` beside
`dev-flow-mcp.cmd`, backed by the verified managed release and existing CLI/Web code,
and include it in receipt, repair, rollback, and exact uninstall ownership.

#### Scenario: Windows launcher is inspected host-neutrally

- **WHEN** the generated launcher is inspected
- **THEN** it SHALL quote the managed runtime path, forward `%*`, contain no source path,
  and run the existing CLI including `web start|status|stop`

### Requirement: Bundled MCP is the only supported installation mode

Current English/Chinese documentation and specifications SHALL describe bundled MCP as
the supported mode and SHALL NOT instruct standalone provisioning. A detected foreign
standalone registration SHALL be preserved and reported before any lifecycle mutation.

#### Scenario: Existing standalone registration is detected

- **WHEN** install or uninstall observes registration not owned by the bundled install
- **THEN** install SHALL stop before mutation and uninstall SHALL preserve and report the
  registration, runtime, launchers, and task data

### Requirement: Windows evidence describes the MCP-first product

Windows lifecycle evidence SHALL cover bundled MCP registration/catalog/health, both
commands, approval boundary, and current receipt, without requiring removed Hook or
Skills assets.

#### Scenario: Host-neutral Windows checks run on a non-Windows host

- **WHEN** parser/static/contract tests run without native Windows
- **THEN** they SHALL validate current assets while native lifecycle remains explicitly
  `NOT RUN — native Windows host unavailable`
