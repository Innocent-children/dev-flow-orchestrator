## ADDED Requirements

### Requirement: Every live action has one closed effective payload contract

The product SHALL derive one effective payload contract from the immutable workflow
node plus current repository and delivery-contract identities. Controller live
validation, MCP current-action `payload_schema`, guidance, package validation, and
tests SHALL use that contract. Its properties SHALL be exactly the fields accepted
by Controller validation, all effective fields SHALL be required, unknown fields
SHALL fail closed, and no guidance SHALL name a field absent from the schema.

#### Scenario: Any official workflow node is inspected

- **WHEN** a test derives the effective contract for any executable node in any of the six official workflows
- **THEN** Controller accepted fields, schema properties and required fields are identical and an extra field is rejected

#### Scenario: A necessary field is omitted

- **WHEN** a live Controller or MCP action payload omits an effective field
- **THEN** it receives a stable correct-request domain failure rather than a successful action with an inferred hidden value

### Requirement: Impact input is complete and self-contained

An action producing `impact-report` SHALL publish a required `impact_manifest` with
closed nested constraints for confidence, entries, edges, risk triggers, public and
documentation behavior, manual and executable evidence, overflow, and limitations.
The constraints SHALL use existing domain values and bounds. A legal
`source-confirmed` value SHALL reach the existing assurance policy unchanged;
explicit uncertainty or a real risk trigger SHALL continue to select conservative
assurance according to that policy.

#### Scenario: Source-confirmed impact is submitted from current action

- **WHEN** a caller builds a legal source-confirmed impact payload solely from the current-action schema
- **THEN** MCP schema and Controller validation accept the same value without transport-induced conservative fallback

#### Scenario: Impact is explicitly uncertain

- **WHEN** a legal manifest reports unknown confidence or another existing conservative trigger
- **THEN** the existing assurance policy remains conservative

### Requirement: Source ownership input is complete and exact

Every non-preflight action whose workspace role is `produces-source` SHALL publish a
required closed `ownership_claims` envelope containing the current schema constant
and bounded claims with repository ID, path, classification, criterion IDs, and
purpose. Empty claims SHALL be valid only when no source path changed. Existing
exact coverage validation for missing, extra, and duplicate paths SHALL remain in
force.

#### Scenario: A Lite implementation changes one path

- **WHEN** a caller uses only the current-action schema to claim the one changed path exactly
- **THEN** the action advances without adding a schema-external field

#### Scenario: Ownership does not match the change set

- **WHEN** claims omit, add, or duplicate a changed path
- **THEN** existing ownership validation rejects the action without weakening path authority

### Requirement: Historical task replay remains byte-stable

Historical `0.4.x` action records SHALL replay using an explicit compatibility path
that requires the immutable node-declared fields while recognizing derived fields
when present. Normal live application SHALL NOT use this compatibility path.
Current live impact submission SHALL reject confidence outside the current enum.
Historical replay SHALL preserve the `0.4.x` baseline behavior that conservatively
normalizes any other persisted confidence value to `unknown`, without modifying the
record or artifact bytes. This exception SHALL apply only to confidence
normalization; missing fields, invalid impact structure, foreign repository
identities, unknown fields, and product-bound overflow SHALL remain fail closed.
Loading or replaying an existing task SHALL NOT migrate or rewrite its persisted
bytes, and workflow identity, `MODEL_VERSION`, namespace, and release SHALL remain
unchanged.

#### Scenario: An old record omitted a formerly hidden field

- **WHEN** a current-format persisted task containing that historical record is loaded and replayed
- **THEN** replay succeeds under compatibility without changing the task file bytes or relaxing a new live action

#### Scenario: A historical confidence is outside the current enum

- **WHEN** a sealed `0.4.x` record contains a confidence value that the baseline conservatively treated as non-confirmed
- **THEN** internal replay derives `unknown`, preserves the original record and bytes, and retains conservative assurance

#### Scenario: A live confidence is outside the current enum

- **WHEN** a Controller or MCP live action submits a confidence value outside the current enum
- **THEN** the action fails without changing revision, node, records, or artifacts

#### Scenario: Historical impact structure is damaged

- **WHEN** a persisted impact omits a required field, contains an unknown field, exceeds a bound, or identifies a foreign repository
- **THEN** replay fails closed because confidence compatibility does not relax any other validation
