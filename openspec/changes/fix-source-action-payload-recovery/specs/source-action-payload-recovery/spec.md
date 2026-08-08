## ADDED Requirements

### Requirement: Source-producing payload correction preserves issued authority

For a current action whose workspace role is `produces-source`, MCP guidance SHALL
distinguish expected task-owned repository edits from changes to task authority.
Creating the files authorized by the action SHALL NOT instruct the executor to
discard the issued binding. If `dev_flow_apply_action` rejects the payload before a
task mutation with `NODE_OUTPUT_INVALID`, guidance and error recovery SHALL direct
the executor to correct the payload and resubmit the exact issued binding when the
task revision, action, contract, inputs, and repository membership remain unchanged.

The Controller SHALL continue to require current exact ownership claims and SHALL
NOT reissue authority over ambient drift, infer that an unknown changed path is
task-owned, or accept a binding after its task authority changes.

#### Scenario: Resource payload is malformed after OpenSpec files are created

- **WHEN** a planning executor creates its authorized OpenSpec files and the action
  submission is rejected because `resources` has the wrong shape
- **THEN** task state remains unchanged and the executor can correct the payload and
  resubmit the original binding without refreshing solely because those files now
  exist

#### Scenario: Task authority changes before correction

- **WHEN** task revision, action, contract, inputs, or repository membership changes
  after the binding was issued
- **THEN** the old binding remains stale and the caller must obtain current authority

#### Scenario: Caller no longer has the issued binding

- **WHEN** ambient drift exists and the caller has discarded the source-producing
  binding
- **THEN** Dev Flow does not infer ownership or mint replacement authority over that
  drift and exposes only the existing safe recovery choices

### Requirement: Resource-bearing actions expose an exact correction contract

When an action payload declares `resources`, current-action guidance SHALL identify
the exact object envelope `resources.items` and the required item fields
`repository_id`, `path`, `role`, and `normalizer`. It SHALL identify the allowed roles
and normalizers and require repository IDs from the projected immutable repository
set.

When `dev_flow_apply_action` rejects an invalid node output, the MCP result SHALL use
`correct-request` recovery, SHALL keep blind retry disabled, and SHALL identify
`dev_flow_apply_action` as the corrected operation. Resource validation details SHALL
identify the expected envelope or fields without exposing secrets or Controller
state.

#### Scenario: Resources are submitted as an array

- **WHEN** the caller submits an array directly instead of an object containing
  exactly `items`
- **THEN** the request fails atomically with expected-envelope details and a
  non-blind correct-request recovery

#### Scenario: A resource item omits repository scope

- **WHEN** an item does not contain exactly the required repository-scoped fields
- **THEN** the request fails atomically with the required field names and does not
  capture, record, or adopt the referenced workspace changes

