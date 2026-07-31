## ADDED Requirements

### Requirement: Agent projections expose bounded confirmation lifecycle
For the current task revision and action, `agent-v1` SHALL report bounded
confirmation state sufficient to distinguish no request, pending, confirmed
and denied for the current binding. The Hook context MAY additionally report a
bounded ambiguous result for the current prompt event. A projected request
SHALL include its request ID, action, grant, status, session binding, bounded
scope and context digest, and exact reply forms. It MUST NOT expose raw
prompts, private authority records, unrelated requests, consumed/stale records
as current authority, or popup implementation data. The confirmation addition
SHALL be deterministically ordered, contain at most eight request locators and
serialize to at most 4,096 UTF-8 bytes.

#### Scenario: Project a pending request
- **WHEN** the current action has one pending exact confirmation request
- **THEN** `agent-v1` identifies that request and instructs the agent to stop and ask the user

#### Scenario: Project confirmed authority
- **WHEN** the later user prompt confirmed a request that still matches the current action and revision
- **THEN** `agent-v1` reports it ready for exact application without applying it automatically

#### Scenario: Hide stale requests
- **WHEN** stored requests are consumed, stale or belong to another task revision, action or session
- **THEN** they do not appear as usable authority in the current actionable frontier

#### Scenario: Return successful consumption
- **WHEN** an exact apply or recovery operation consumes its confirmed request
- **THEN** that operation's result carries the bounded consumed request locator while the next current `agent-v1` projection does not expose it as authority

#### Scenario: Retry after a lost success response
- **WHEN** a caller retries after task or journal evidence proves the prior operation succeeded
- **THEN** the controller returns the existing idempotency or placement diagnostic and does not revive a consumed or stale request

#### Scenario: Bound projection size
- **WHEN** multiple current requests exist
- **THEN** the projection deterministically bounds and orders their public locators and reports stable overflow counts without returning partial private record bodies
