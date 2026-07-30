# Contributing: adding a workflow node or executable contract

Dev Flow workflow definitions are package-owned, declarative, immutable
bundles. Target repositories, the plugin data directory, environment paths,
Python entry points, and MCP servers cannot register in-process workflow
behavior.

Use an existing registered contract whenever possible. Adding a declarative
node then requires only a new bundle version, a playbook section, graph edges,
and tests; it does not require a Python branch in the controller.

## Add a node with an existing contract

1. Copy the workflow bundle to a new versioned directory. Never modify a
   bundle version that an existing task may have pinned.
2. Add the node to `workflow.json`, including all required fields:
   `id`, `kind`, `contract_version`, localized labels, phase, input/output
   schema IDs, evidence contracts, context projection, playbook locator,
   actions, approval/effect/retry/recovery policies, executor reference, and
   exact allowed state writes.
3. Add explicit incoming and outgoing edges. Cycles must be declared rework
   edges; terminal edges can never be automatic.
4. Add the node ID to `ordered_nodes`, and update entry or terminal sets only
   when the workflow semantics require it.
5. Add a bounded `## <anchor>` section to the bundle playbook. The selected
   section must fit the 4 KiB UTF-8 playbook budget.
6. Inventory every graph, schema, and playbook file in `workflows/catalog.json`.
   A candidate may remain absent from `workflows/activation.json`; add an
   activation entry only in a separately authorized activation step.
7. Compute the expected graph and bundle identities through
   `expected_workflow_catalog_identities(...)`, update the catalog and
   activation manifest with those exact values, and reload the strict catalog.
8. Keep the new activation profile disabled until every reachable handler,
   edge, recovery path, compatibility test, and rollback rehearsal is green.

A minimal node still uses explicit policies. This sketch deliberately omits
workflow-specific values, but shows the shape:

```json
{
  "id": "QUALITY_BARRIER",
  "kind": "generic",
  "contract_version": "v1",
  "labels": {
    "en": "Quality barrier",
    "zh-CN": "质量屏障"
  },
  "phase": "quality-barrier",
  "terminal": false,
  "waiting": false,
  "input_schema": "dev-flow-node-input/v1",
  "output_schema": "dev-flow-node-result/v1",
  "required_evidence": [],
  "produced_evidence": [],
  "context_projection": {
    "profile": "node-v1",
    "state_paths": ["/status"],
    "max_bytes": 1024
  },
  "playbook": {
    "path": "playbooks/workflow.md",
    "anchor": "QUALITY_BARRIER"
  },
  "actions": [],
  "required_sections": [],
  "approval_policy": {
    "mode": "edge-policy",
    "gate": null
  },
  "effect_policy": {
    "classification": "controller",
    "effects": ["controller-transition"]
  },
  "retry_policy": {
    "mode": "never",
    "max_attempts": 1,
    "backoff": "none",
    "retry_on": []
  },
  "recovery_policy": {
    "mode": "reconcile",
    "on_uncertain": "block",
    "requires_receipt": true,
    "resume_same_attempt": false
  },
  "executor": {
    "registry": "executors",
    "id": "executor.deterministic/v1",
    "version": "v1"
  },
  "allowed_state_writes": []
}
```

`WorkflowCatalogTests.test_generic_node_composes_existing_contracts_without_python_branch`
is the executable example: it inserts a node using existing registered
contracts, recomputes the bundle identity, seals the catalog, and verifies
that projections and routing recognize the new node without adding a
node-specific controller branch.

## Add a versioned executable handler

Only package-trusted behavior may execute in process.

1. Put pure deterministic logic in a package-owned runtime file. A guard may
   read only its immutable projection through declared capabilities; a reducer
   may return only a bounded state delta. Neither may perform filesystem, Git,
   process, network, registration, or commit operations.
2. Add one entry to the appropriate static manifest under
   `workflows/runtime/`. Give it a new stable ID and `vN` contract version,
   exact authority and capabilities, input/output schema references, binding
   symbols, audit profile, and a named exact implementation-file set.
3. List every implementation file explicitly. Globs and runtime discovery are
   forbidden. Changing identity-covered implementation bytes changes every
   referring bundle digest; a semantic contract change also requires a new
   handler ID or version.
4. Reference the registered `(registry, id, version)` tuple from the new
   bundle. Workflow JSON must never contain a module path, callable name,
   shell command, or import string.
5. Route untrusted, optional-SDK, hosted, or open-world behavior through an
   external executor contract. Its output is a candidate only; the controller
   validates evidence and the authoritative `dev-flow-node-result/v1` before
   any state change.

The runtime supports these executor surfaces without importing optional SDKs:

- deterministic controller action;
- native Codex subagent;
- structured `codex exec`;
- resumable Codex thread;
- external tool;
- barrier;
- human gate.

Agents SDK Runtime is an optional external orchestrator for genuinely dynamic
handoffs. It does not own task state, approvals, revisions, leases, or
transitions.

## Validation checklist

Run these checks before enabling a bundle:

```text
python3 -m unittest <direct-test-method-or-class> -v
python3 scripts/audit_runtime_imports.py
python3 scripts/validate_package.py
python3 scripts/run_bundled_validators.py --require-available
openspec validate <change-id> --strict
git diff --check
```

Run only the smallest listed test targets directly affected by the change.
Test discovery, a full suite, and broad unrelated aggregation are prohibited.

Activation is a release gate, not a development shortcut. If any catalog,
identity, compatibility, shadow-equivalence, recovery, package, or
required macOS check is incomplete, leave the new profile inactive. Disabling
creation must never prevent an already-pinned task from completing.
