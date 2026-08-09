## ADDED Requirements

### Requirement: Default uninstall preserves source while exact ownership is unavailable

Until the exact ownership and quarantine protocol is implemented and validated,
POSIX and PowerShell uninstall entry points SHALL preserve the complete source
checkout for default invocation, the documented keep-source option, and any explicit
source-removal option. An explicit removal request SHALL fail closed to source
retention and SHALL NOT bypass containment. No path SHALL execute recursive
source-root deletion or classify path, Git origin, branch, clean status, or commit
ancestry as sufficient deletion authority.

The human output and machine-observable result SHALL identify the exact retained
source path, state that destructive source removal is disabled because no verifiable
exact-ownership manifest exists, and report an explicit partial outcome plus factual
per-component results for plugin, launcher, runtime, and marketplace operations
without creating a new ownership or safety claim for those components. They SHALL
preserve Controller task data and unrelated marketplace entries. Recovery
guidance SHALL direct the operator to inspect and back up the checkout and confirm
ownership manually; it SHALL NOT recommend unconditional recursive deletion. The
result SHALL NOT print or return a complete source-removal success claim.

#### Scenario: Default uninstall is requested

- **WHEN** an operator invokes uninstall without a keep-source option
- **THEN** source is retained under safety containment and the receipt explicitly
  distinguishes that partial lifecycle outcome from source removal

#### Scenario: A file appears during plugin removal

- **WHEN** an external plugin-removal command creates a file in source after
  uninstall begins
- **THEN** the file and source remain present and the receipt does not claim complete
  source removal

#### Scenario: Keep source is requested

- **WHEN** the documented keep-source option is supplied
- **THEN** source and task data remain unchanged while other component operations
  may proceed and are reported separately without new ownership or safety claims

#### Scenario: Explicit source removal is requested

- **WHEN** an operator selects an existing or future remove-source option without a
  conforming exact-ownership manifest
- **THEN** the option remains safety-contained, source is retained, and the partial
  result explains that the removal request could not establish exact ownership

#### Scenario: Unrelated marketplace content exists

- **WHEN** a valid personal marketplace contains unrelated entries
- **THEN** source containment does not change those entries and only the validated
  Dev Flow entry may be updated or removed

#### Scenario: Recovery guidance is emitted

- **WHEN** source is retained by containment
- **THEN** output names the retained path and tells the operator to inspect, back up,
  and independently confirm ownership before any manual action without suggesting an
  unconditional recursive deletion command
