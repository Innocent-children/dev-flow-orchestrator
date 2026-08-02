## ADDED Requirements

### Requirement: Candidate validation uses candidate content
The package validator SHALL evaluate the source, workflow definitions, product catalog, and public assets belonging to the candidate root supplied by the caller.

#### Scenario: Candidate workflow is invalid
- **WHEN** a copied candidate contains an invalid workflow while the invoking checkout remains valid
- **THEN** validation of that candidate fails

#### Scenario: Candidate is valid
- **WHEN** a complete candidate is validated from a different filesystem path
- **THEN** validation succeeds without using already imported modules from the invoking checkout

### Requirement: Public skill guidance matches V5
The packaged `follow-dev-flow` agent metadata SHALL describe the V5 single-repository workflow and SHALL invoke `$follow-dev-flow` in its default prompt.

#### Scenario: Packaged agent metadata is inspected
- **WHEN** package validation reads the main skill agent metadata
- **THEN** stale V4 or multi-repository guidance causes validation to fail

### Requirement: Verification evidence reflects an executed command
The installation smoke procedure SHALL record passing test evidence only after the documented verification command has executed successfully.

#### Scenario: Verification succeeds
- **WHEN** the documented verification command exits successfully
- **THEN** the smoke procedure records `passed: true` with that command

#### Scenario: Verification fails
- **WHEN** the documented verification command exits unsuccessfully
- **THEN** the smoke procedure does not record passing evidence
