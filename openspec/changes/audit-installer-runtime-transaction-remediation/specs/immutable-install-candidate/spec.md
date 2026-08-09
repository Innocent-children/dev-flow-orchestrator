## ADDED Requirements

### Requirement: Installation uses one sealed Git-tree release

After resolving the expected origin, branch, verified commit, tree, and eligible
checkout state, the installer SHALL export that commit from Git object storage into
installer-owned temporary staging. Extraction SHALL reject absolute paths, path
traversal, duplicate destinations, and unsupported entry types and SHALL preserve
and verify regular-file bytes, executable mode, and symlink target text against the
Git tree without following links.

Package validation, wheel and runtime build, plugin release generation, launcher
generation, health, and final smoke SHALL consume the staged or promoted sealed
release. The final plugin release SHALL live in an installer-owned,
release-specific directory. Marketplace registration and `codex plugin add` SHALL
target that directory rather than the authoritative checkout.

One `release_id` SHALL identify the plugin payload, wheel, runtime, launchers,
health evidence, release manifest, ownership manifest, and receipt. Receipt v2 SHALL
record the verified commit/tree, release path, release-manifest digest, and wheel
digest. No activation or candidate identity is required.

#### Scenario: Verified checkout changes after release sealing

- **WHEN** the checkout changes before or after runtime build, marketplace write,
  plugin add, health, launcher generation, or success receipt publication
- **THEN** the change cannot enter the sealed plugin, runtime, or launcher, and the
  installer either completes solely from that release or fails closed if a later
  step still depends on changed source

#### Scenario: Git archive content is unsafe or inconsistent

- **WHEN** an exported member is absolute, traverses staging, duplicates another
  destination, has an unsupported type, or differs from the verified Git tree
- **THEN** installation fails before runtime promotion, marketplace write, launcher
  write, or plugin mutation

#### Scenario: Git executable and symlink semantics are present

- **WHEN** the verified tree contains an executable file or symbolic link
- **THEN** the sealed release preserves the executable mode and link target text,
  and extraction never follows the link outside staging

#### Scenario: A release consumer points elsewhere

- **WHEN** runtime, marketplace, plugin target, launcher, health, ownership, or
  receipt refers to a different release path or `release_id`
- **THEN** success is refused and any provisional effect follows bounded rollback
  or truthful partial reporting

### Requirement: Installation preserves authoritative source state

After clone or an allowed fast-forward selects the authoritative revision, install,
repair, and upgrade SHALL capture HEAD and complete tracked, untracked, and ignored
Git inventories. They SHALL compare the same authorities after success and after
failure handling. Git inspection SHALL include ignored entries.

Every Python command executed from authoritative source SHALL use `-B` and
command-scoped `PYTHONDONTWRITEBYTECODE=1`. Build, package validation, health, and
launcher generation SHOULD run from sealed staging. The lifecycle SHALL NOT create
`__pycache__`, `.pyc`, build, dist, egg-info, or other generated content in source
and SHALL NOT delete source content to manufacture a passing final check.

Pre-existing ignored content allowed by the authoritative-installation contract
SHALL remain unchanged. Runtime ownership SHALL NOT authorize source deletion, and
DFO-AUDIT-002 source retention SHALL remain effective after every outcome.

#### Scenario: Fresh install completes

- **WHEN** a fresh clean checkout is installed successfully
- **THEN** HEAD and tracked, untracked, and ignored inventories are unchanged from
  the selected baseline and no installer-generated cache or build entry exists

#### Scenario: Repair completes

- **WHEN** repair reuses or rebuilds a managed runtime
- **THEN** authoritative source remains unchanged and no new ignored bytecode or
  build residue appears

#### Scenario: Installation fails

- **WHEN** staging, build, activation, health, smoke, or rollback fails
- **THEN** the installer neither cleans nor resets source, creates no source cache,
  and reports any externally caused difference from the selected baseline

#### Scenario: Existing ignored user content is present

- **WHEN** an eligible checkout contains allowed ignored content before installation
- **THEN** that content remains present and byte-identical, is excluded from the Git
  release export, and is not deleted during success or failure handling

#### Scenario: Paths contain spaces Unicode and apostrophes

- **WHEN** source, staging, runtime, marketplace, or launcher paths contain spaces,
  Unicode, or an apostrophe
- **THEN** no-bytecode execution, Git inventory, sealing, and source-preservation
  checks retain the same behavior
