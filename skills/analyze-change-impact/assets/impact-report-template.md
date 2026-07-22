# Change impact report: <short requirement name>

## Analysis context

- Requirement: <normalized requirement>
- Acceptance signals: <observable outcomes>
- Repositories and baselines: <repository, source path, analysis-workspace path, baseline commit>
- Index coverage: <project identifier, mode, result for each repository>
- Overall coverage: <complete or degraded, with reason>

## Requirement interpretation

### Intended behavior

<What must change from the user's perspective.>

### Assumptions

- <Assumption and how it affects the analysis>

### Non-goals

- <Explicitly excluded behavior or repository>

## Project: <project identifier>

### Role in the change

<Why this project participates.>

### Affected files and symbols

| Confidence | File | Symbol or region | Expected impact | Evidence |
|---|---|---|---|---|
| confirmed | `<path>` | `<qualified symbol>` | <change or dependency> | <source/graph/test evidence> |

### Call and data paths

- Inbound: `<caller>` -> `<changed symbol>`
- Outbound: `<changed symbol>` -> `<dependency>`
- Data flow: `<input>` -> `<validation/transform>` -> `<sink/output>`
- Cross-service: `<producer/client>` -> `<contract>` -> `<consumer/handler>`

### Public contracts and compatibility

- <API, event, schema, configuration, migration, version, or rollout concern>

### Test impact

- Existing coverage: `<test path or command>` — <what it proves>
- Required coverage: <unit/integration/contract/migration/failure case>

### Risks and unknowns

- [confirmed|inferred|unknown] <finding, consequence, and next evidence needed>

## Cross-project coordination

- Shared contracts: <contract and owners>
- Implementation order: <safe sequence>
- Deployment/rollback order: <safe sequence>
- Cross-repository graph evidence: <paths found, no match, or degraded reason>

## Route recommendation

- Recommended route: <direct or OpenSpec>
- Reasons: <scope, ambiguity, contracts, migration, security, coordination>
- Direct-route contract requirements: <goal, scope, non-goals, acceptance, tests, risks>
- Remaining user decision: <route choice or material unresolved choice>
