## MODIFIED Requirements

### Requirement: One pre-release version seals the supported protocol
The product SHALL expose exact semantic version `0.3.0` from one `PRODUCT_VERSION` runtime authority. Plugin and package metadata, task state, workflow and assurance-policy documents, controller data namespace, every current persisted schema identifier and digest domain, projections, task-change manifests, assurance plans, obligations, structured findings, snapshots, action bindings, records, evidence, Delivery Dossier, receipt, Skills, local Web UI server and assets, local HTTP view envelopes, tests, installed evidence, and public guidance SHALL use that same value. The local Web UI SHALL expose no component-specific version, package, plugin, marketplace entry, state namespace, or release gate. The product SHALL derive one current `PRODUCT_IDENTITY` from the shared version, accepted persisted schema vocabulary, and one-to-eight repository topology authorities. Selected-workflow identity SHALL bind only the workflow selector, current schema, and canonical document. Presentation-only Web UI assets, HTTP view names, and content digests SHALL NOT change the accepted persisted schema vocabulary, `product_document()`, or `PRODUCT_IDENTITY`.

Every supplied workflow, policy, task, contract, record, snapshot, binding, manifest, plan, obligation, finding, projection, evidence, and Dossier value SHALL carry its exact supported 0.3.0 identity; a supplied non-0.3 value SHALL be rejected at the current input boundary without migration, translation, repair, recovery, fallback parsing, or partial recording. Runtime discovery SHALL be confined to the 0.3 data namespace. The 0.3 runtime SHALL never enumerate, discover, read, import, migrate, translate, repair, reinterpret, recover, or delete retained 0.2 namespace bytes. Retained 0.2 bytes SHALL remain byte-for-byte unchanged outside the 0.3 product boundary and SHALL have no effect on current installation, discovery, admission, replay, task operations, or local Web UI inventory.

#### Scenario: Current task loads
- **WHEN** a task and every persisted value match the installed current identities and schemas
- **THEN** deterministic replay derives the same task-change manifest, assurance plan, satisfied and outstanding obligations, budget consumption, state, and current action

#### Scenario: Product surfaces are inspected
- **WHEN** package validation inspects runtime constants, plugin and package metadata, workflow assets, Skills, local Web UI runtime and assets, HTTP view envelopes, tests, installed evidence, and public guidance
- **THEN** every current version equals `0.3.0` and any generation-coded or component-specific current version causes validation to fail

#### Scenario: Existing current task is inspected through the Web UI
- **WHEN** a valid current task created before the local Web UI assets were installed is opened after the same-version candidate is installed
- **THEN** the task keeps the same `PRODUCT_IDENTITY`, namespace, persisted bytes, workflow identity, replay result, and current action without migration or rewrite

#### Scenario: Workflow document changes
- **WHEN** the canonical selected workflow document differs from the pinned selected-workflow identity
- **THEN** the task fails with a workflow identity mismatch

#### Scenario: Unsupported schema is encountered
- **WHEN** a caller supplies any workflow, policy, task, record, snapshot, action binding, task-change manifest, assurance plan, obligation, finding, projection, verification, or Dossier value whose identity is not exactly supported by 0.3.0
- **THEN** the current input boundary rejects the value without invoking an alternate parser, compatibility path, conversion, repair, or partial mutation

#### Scenario: Repository topology authority changes
- **WHEN** the supported topology or current persisted schema vocabulary changes
- **THEN** the derived product identity changes and persisted tasks under the prior identity are not reinterpreted

#### Scenario: Prior-version files remain on disk
- **WHEN** persisted `0.2.0` bytes exist outside the `0.3.0` data namespace
- **THEN** the current runtime and local Web UI leave them byte-for-byte unchanged, never enumerate, discover, read, migrate, translate, repair, or delete them, and exclude them from current installation, inventory, and task operations

