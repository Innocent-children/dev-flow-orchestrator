## Why

Source-producing actions intentionally bind the repository state before the executor
creates files. The current MCP guidance nevertheless tells the executor to discard
that binding whenever repository evidence changes. If a planning payload is then
rejected for an incorrectly shaped `resources` field, refreshing the action observes
the newly created OpenSpec files as ambient drift and withholds a replacement
binding. The Controller remains safe, but the public execution guidance leads the
client away from the valid atomic retry path.

## What Changes

- Describe the exact nested `resources.items` payload shape for actions that accept
  repository resources.
- Give source-producing actions recovery guidance that preserves their issued
  binding across task-owned edits and correctable pre-commit payload validation
  failures while the task authority is otherwise unchanged.
- Classify `NODE_OUTPUT_INVALID` from `dev_flow_apply_action` as a correct-request
  recovery and direct the caller to resubmit the corrected payload with the same
  binding when it is still current.
- Keep ambient-drift blocking, ownership claims, revision checks, and the prohibition
  on silently adopting unknown workspace changes unchanged.

## Capabilities

### New Capabilities

- `source-action-payload-recovery`: Exact payload construction and safe retry rules
  for source-producing MCP actions.

### Modified Capabilities

None.

## Impact

- `src/dev_flow_orchestrator/mcp/guidance.py`
- `src/dev_flow_orchestrator/mcp/results.py`
- `src/dev_flow_orchestrator/delivery.py`
- Focused MCP guidance, result-envelope, and source-action regression tests

