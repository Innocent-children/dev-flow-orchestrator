## Why

The MCP current-action projection exposes only workflow-declared payload fields,
while Controller validation privately adds `impact_manifest` and
`ownership_claims`. A caller following the public schema therefore cannot always
construct the payload that the Controller requires. Separately, an automatically
generated task ID is not retained when task creation succeeds but MCP response
post-processing becomes completion-uncertain, leaving read-after-write recovery
without the identity it needs.

## What Changes

- Derive one effective payload contract for Controller validation, MCP projection,
  guidance, package validation, and tests.
- Publish closed, complete nested JSON Schemas for impact manifests and ownership
  claims, and require them on their applicable live actions.
- Retain explicit legacy replay compatibility without changing persisted task
  records or workflow identity.
- Carry the authoritative task ID in a request-scoped mutation execution context
  from Controller return through every completion-uncertain response guard.

## Capabilities

### New Capabilities

- `mcp-effective-payload-contract`: one self-contained payload authority shared by
  the Controller and MCP surfaces.
- `mcp-mutation-recovery`: executable completion-uncertain recovery for mutations
  whose authoritative task identity becomes known during the call.

## Impact

The change is limited to payload contract derivation and validation, MCP
current-action/guidance projection, mutation response context, package validation,
and directly corresponding tests. It does not change workflow files, the persisted
task shape, model or release versions, namespace, Web lifecycle, file locking,
Store read bounds, or Windows behavior.
