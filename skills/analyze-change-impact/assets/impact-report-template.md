# Change impact report: <short requirement name>

## Analysis context

- Requirement: <normalized requirement>
- Acceptance signals: <observable outcomes>
- Repositories and baselines: <repository, source path, analysis-workspace path, baseline commit>
- Baseline index coverage: <exact returned project identifier, requested name, mode, persistence=false, result for each repository>
- Overall coverage: <complete or degraded, with reason>
- Funnel budget profile: <seed-v1 or expanded-v1>
- Expansion reason: <required for expanded-v1; otherwise not applicable>

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

### Funnel completeness

| Check | Status | Reason or evidence |
|---|---|---|
| orientation | <complete/not_applicable/degraded> | <location/boundary evidence or reason> |
| candidates | <complete/not_applicable/degraded> | <affected file/symbol evidence or reason> |
| paths | <complete/not_applicable/degraded> | <call/data/cross-service evidence or reason> |
| contracts | <complete/not_applicable/degraded> | <contract evidence or reason> |
| tests | <complete/not_applicable/degraded> | <test evidence or reason> |
| source_confirmation | <complete/not_applicable/degraded> | <pinned-source evidence or reason> |

Query counts: `architecture=<n>`, `search_graph=<n>`, `trace=<n>`, `search_code=<n>`, `snippet=<n>`.

- Unresolved truncations: <none, or precise query/result still truncated>
- Material unknowns: <none, or question and consequence>

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

- Cross-repository status: <complete/not_applicable/degraded, with reason>
- Shared contracts: <contract and owners>
- Implementation order: <safe sequence>
- Deployment/rollback order: <safe sequence>
- Cross-repository graph evidence: <paths found, no match, or degraded reason>

## Route recommendation

- Recommended route: <direct or OpenSpec>
- Reasons: <scope, ambiguity, contracts, migration, security, coordination>
- Direct-route contract requirements: <goal, scope, non-goals, acceptance, tests, risks>
- Remaining user decision: <route choice or material unresolved choice>

## Controller metadata

Pass this object, with one unique repository entry for every task repository, to `record-artifact --kind impact --metadata-json`:

```json
{
  "schema": "dev-flow-impact-analysis/v1",
  "strategy": "funnel",
  "coverage": "<complete|degraded>",
  "budget_profile": "<seed-v1|expanded-v1>",
  "repositories": [
    {
      "repository_id": "<task repository id>",
      "index_id": "<exact baseline project id or null>",
      "index_mode": "<fast|moderate|full>",
      "checks": {
        "orientation": {"status": "<complete|not_applicable|degraded>", "reason": "<required unless complete>"},
        "candidates": {"status": "<complete|not_applicable|degraded>", "reason": "<required unless complete>"},
        "paths": {"status": "<complete|not_applicable|degraded>", "reason": "<required unless complete>"},
        "contracts": {"status": "<complete|not_applicable|degraded>", "reason": "<required unless complete>"},
        "tests": {"status": "<complete|not_applicable|degraded>", "reason": "<required unless complete>"},
        "source_confirmation": {"status": "<complete|not_applicable|degraded>", "reason": "<required unless complete>"}
      },
      "queries": {
        "architecture": 0,
        "search_graph": 0,
        "trace": 0,
        "search_code": 0,
        "snippet": 0
      },
      "unresolved_truncations": [],
      "material_unknowns": []
    }
  ],
  "cross_repository": {
    "status": "<complete|not_applicable|degraded>",
    "reason": "<required unless complete>"
  }
}
```

For `expanded-v1`, also add a non-empty top-level `expansion_reason`. Remove optional `reason` keys from `complete` checks if they add no value; never leave placeholder strings in recorded metadata.
