# Greenfield Architecture Contract

## Initial module graph

```text
dev_flow_orchestrator.cli
  → dev_flow_orchestrator.controller
      → dev_flow_orchestrator.engine
          → dev_flow_orchestrator.model
          → dev_flow_orchestrator.product
          → direct node-family callable catalog
          → dev_flow_orchestrator.repository_kernel
      → dev_flow_orchestrator.authority
      → dev_flow_orchestrator.store
          → dev_flow_orchestrator.filesystem
          → dev_flow_orchestrator.model
      → dev_flow_orchestrator.journal
          → dev_flow_orchestrator.filesystem
      → dev_flow_orchestrator.git_client
```

The skeleton has no other application layer, registry layer, facade layer or adapter layer.
New modules are added only when a completed vertical slice has a responsibility that cannot be
named accurately inside this graph.

## Module ownership

| Module | Sole responsibility | Forbidden responsibility |
|---|---|---|
| `product.py` | immutable product/profile/capability matrix | filesystem, task state, CLI |
| `model.py` | current V4 values and validation | filesystem, subprocess, environment |
| `store.py` | private task paths, lock, revision, atomic bytes | workflow eligibility, Git |
| `filesystem.py` | shared private directory, file lock and atomic-byte primitive | task schema, workflow, Git |
| `journal.py` | durable effect claim, receipt, quarantine and terminal outcome | workflow eligibility, effect execution |
| `authority.py` | durable conversation requests, exact task/revision/action/grant/account/role/context/scope/session binding, `UserPromptSubmit` decision ledger and one-time claim/consume | caller assertion, workflow mutation, authenticated-human claims |
| `repository_kernel.py` | pure repository DAG, lease, result, retry, cancellation and barrier state | filesystem, process, workflow-specific gates |
| `engine.py` | pure eligibility and mutation plan | I/O, time, UUID, environment |
| `git_client.py` | bounded Git subprocess evidence/effect | task state write, workflow policy |
| `controller.py` | plan/effect/commit coordination and only state write | wire protocol |
| `cli.py` | argv/JSON wire protocol | workflow policy, direct store/Git mutation |

## Node contract

Every node declares:

```text
id
input_fields
output_fields
required_authority
allowed_state_writes
effect_kind
effect_port
handler_id
effect_port
idempotency_fields
failure_code
recovery_action
```

Node evaluation returns `NodeDecision` or `MutationPlan`. The immutable contract contains
stable handler/effect IDs; one static engine catalog binds each stable node family to a direct
pure callable and the same effect port. Reducers are not selected through `output_kind`,
globals or late-bound strings.

## Mutation phases

1. `validate`: controller rejects invalid payload, confirmation input, write set or effect binding
   before journal claim or dispatch.
2. `confirmation`: controller creates or reloads one durable exact-bound request and returns
   without a guarded mutation when it is not confirmed. A later exact `UserPromptSubmit` event
   records only a decision. On a subsequent exact retry, the controller revalidates and claims
   the request; CLI/MCP accept no caller approval, actor, raw prompt or serialized record.
3. `plan`: load under task lock and expected revision; pure engine returns bounded plan.
4. `effect`: execute the one declared port and return bounded receipt.
5. `commit`: reacquire lock, reload, revalidate revision/plan/receipt, atomic replace and consume
   or reconcile the exact confirmation request.

Effect-free actions perform plan and commit under one lock. A failed or uncertain effect never
becomes a success mutation. The confirmation lock serializes requests and prompt decisions
across tasks in one data directory and is never nested with task, effect-journal or workspace
locks. Conversation session/turn evidence is correlation and audit data, not operating-system or
authenticated-human identity.

## Greenfield independence

Files below `src/dev_flow_orchestrator/` must not:

- import or read `scripts/dev_flow_parts`;
- call `exec` or `eval`;
- resolve operation names from `globals`, `locals`, module dictionaries or strings;
- use a service locator, runtime registry or dependency injection container;
- import old `scripts.dev_flow`, `scripts.dev_flow_mcp` or Hook implementation;
- expose a fallback to the old runtime.

The current implementation may remain in the worktree as read-only reference until Atomic
Greenfield Cutover, but no greenfield test or runtime call may execute it.

## Cutover contract

Cutover happens once, after every required vertical slice passes:

1. switch CLI, MCP, Hook and Skill launch paths together;
2. delete the old runtime and old-only assets/tests;
3. validate there is one product matrix and one executable runtime;
4. freeze candidate bytes only after deletion.

There is no command-by-command cutover and no environment-controlled rollback.
