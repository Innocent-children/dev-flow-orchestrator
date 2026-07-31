## ADDED Requirements

### Requirement: Workflow depth, repository topology and workspace strategy are orthogonal
The product SHALL model workflow depth (`full@4` or `lite@4`), repository
topology (`single-repository` or `multi-repository`) and workspace strategy
(`in-place`, `branch` or `worktree`) as separate values. Repository count MUST
NOT select workflow depth, and workspace strategy MUST NOT silently select
workflow depth.

#### Scenario: Create a lite multi-repository task
- **WHEN** a caller selects `lite@4`, supplies more than one repository and selects an allowed workspace strategy
- **THEN** creation selects `lite@4`/`multi-repository` without returning `LITE_REQUIRES_FULL`

#### Scenario: Create a full single-repository task
- **WHEN** a caller selects `full@4` with one repository
- **THEN** creation selects `full@4`/`single-repository` independently of repository topology

#### Scenario: Omit workflow depth
- **WHEN** a creation request does not explicitly select a workflow and no documented product default applies
- **THEN** creation fails before state commit with the exact supported choices instead of inferring from repository count or workspace strategy

### Requirement: The V4 product exposes exactly four activation profiles
The package SHALL expose exactly
`full@4`/`single-repository`, `full@4`/`multi-repository`,
`lite@4`/`single-repository` and `lite@4`/`multi-repository`. Each profile MUST
bind one exact bundle identity and the minimum named suite set required for its
workflow nodes and topology.

#### Scenario: Validate the product matrix
- **WHEN** package validation loads the V4 product definition
- **THEN** it finds all four profiles exactly once and no implicit fifth or predecessor profile

#### Scenario: Activate lite multi-repository
- **WHEN** the lite bundle and shared multi-repository kernel pass their declared focused suites
- **THEN** `lite@4`/`multi-repository` is independently activatable

### Requirement: One package-owned matrix is authoritative
One immutable package-owned product definition SHALL own workflow identities,
profile combinations, workspace compatibility, required suites and capability
identities. Workflow graphs, activation assets, runtime selection, validators
and documentation MUST derive from it or prove exact equality; they MUST NOT
define independent hard-coded profile maps.

#### Scenario: Product definition changes
- **WHEN** one profile or suite binding changes in the authoritative product definition
- **THEN** generated or validated activation, runtime, tests and documentation must change consistently before package validation passes

#### Scenario: A second profile map appears
- **WHEN** runtime code introduces another independently maintained profile-to-suite mapping
- **THEN** architecture validation rejects the candidate as having multiple sources of truth

### Requirement: Product restrictions are explicit combinations
Any unsupported workflow, topology and workspace combination SHALL be declared
in the authoritative product definition with a stable reason. Generic risk
classification MUST NOT be used as a hidden substitute for product
compatibility.

#### Scenario: Reject an unsupported workspace combination
- **WHEN** a caller selects a combination explicitly marked unsupported
- **THEN** creation returns the declared combination error before writing task state

#### Scenario: Evaluate change risk
- **WHEN** a lite task has a declared high-risk change category
- **THEN** risk policy may require an explicit gate or reject that change category, but repository count alone does not rewrite the selected workflow
