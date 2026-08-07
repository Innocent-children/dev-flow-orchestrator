## ADDED Requirements

### Requirement: Focused validation covers the native Windows runtime without duplicating the full product matrix

The candidate SHALL include a focused Windows CI job that imports the runtime and executes the platform path, storage, process, snapshot, and core-controller tests required by `native-windows-runtime`. The job MAY use GitHub's maintained Windows runner as implementation test infrastructure without adding Windows Server to the public support claim.

The existing macOS focused job SHALL remain the complete product regression gate. Windows validation SHALL NOT duplicate every workflow, assurance profile, installed journey, documentation assertion, Python version, and boundary maximum solely for platform parity.

#### Scenario: Windows runtime candidate passes

- **WHEN** Windows import, path, lock, state replacement, bounded process, representative snapshot, and core-journey tests pass and the existing macOS focused job passes
- **THEN** the candidate satisfies this change's automated platform gate

#### Scenario: Windows imports POSIX-only storage

- **WHEN** importing the candidate on Windows attempts to import `fcntl` or execute another unavailable POSIX-only primitive
- **THEN** the Windows job fails before the candidate can be accepted

#### Scenario: Core platform change alters persisted authority

- **WHEN** the candidate changes current persisted field sets, Schema identifiers, product version, workflow definitions, or replay rules without a separately declared product change
- **THEN** candidate validation fails this change's scope gate

### Requirement: Client smoke evidence remains proportional to the delivered runtime slice

Before downstream Hook and installer work treats the runtime as available, validation SHALL record one native Windows 11 x64 client smoke covering the core controller lifecycle. A Windows 10 22H2 x64 smoke SHOULD be recorded when that host is available.

The evidence SHALL identify the OS build, Python version, Git version, repository path characteristics, commands or test entry point, and outcome. It is not required to certify Windows Server, ARM64, WSL, network storage, every supported Python version, or extreme filesystem behavior.

#### Scenario: Windows 11 client smoke succeeds

- **WHEN** the scoped core lifecycle completes on a native Windows 11 x64 client using an ordinary local repository
- **THEN** the evidence is sufficient for subsequent Hook and lifecycle changes to depend on this runtime

#### Scenario: A smoke defect is found

- **WHEN** the supported client smoke exposes a reproducible path, lock, process, or snapshot defect
- **THEN** the defect is fixed with one targeted regression test before the runtime is treated as ready
