## Purpose

Move the model-facing execution of the existing personal delivery workflows from
packaged Skills and Hook-injected CLI locators to the stable MCP current-action
interface without changing workflow definitions, task topology, assurance policy,
budgets, records, or terminal Dossiers.

## ADDED Requirements

### Requirement: Official workflow execution is MCP-first

The `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full` workflows
SHALL remain current `dev-flow-workflow/0.4.0` definitions governed by the existing
Controller and assurance policy. In the installed `0.5.0` product, a Codex executor
SHALL start or discover a task through the stable MCP tools, obtain one live current
action through `dev_flow_get_next_action`, perform only that action across the exact
immutable repository set, and submit the exact action ID, closed payload, and
unmodified binding through `dev_flow_apply_action` or the applicable governance tool.

Workflow execution SHALL NOT require `$follow-dev-flow`, a Hook-injected Controller
locator, shell construction of the CLI, or direct task-state access. The MCP adapter
SHALL NOT auto-run repository edits, tests, external drivers, or review; the Codex
executor continues to perform the projected work with its ordinary repository and
optional-tool capabilities. One task SHALL retain one current action and one executor
regardless of the number of MCP requests or repository members.

#### Scenario: A user starts each official workflow through MCP

- **WHEN** a caller invokes `dev_flow_start_task` with any official workflow and a valid exact repository set
- **THEN** the Controller pins the same workflow identity and projects the same preflight action and current-model contract as the CLI path

#### Scenario: A workflow resumes after the MCP process restarts

- **WHEN** the local MCP process exits and a later process opens the same current data namespace
- **THEN** `dev_flow_find_tasks_for_path` and `dev_flow_get_next_action` resume the persisted task from its authoritative revision without session memory or workflow reconstruction

#### Scenario: An executor tries to skip the current action

- **WHEN** a caller submits an action ID or payload not projected for the current node
- **THEN** existing action and binding validation rejects it and no later workflow phase is entered

#### Scenario: A task reaches terminal delivery

- **WHEN** all current obligations and finalization rules succeed or an absolute budget routes to incomplete delivery
- **THEN** the same current Delivery Dossier authority reports `DONE` or `INCOMPLETE`; MCP adds no separate terminal model

### Requirement: Current action guidance replaces procedural Skill authority

For every official action template, the package SHALL provide bounded
`dev-flow-mcp-guidance/1.0.0` selected from the live projection. The guidance SHALL
preserve all current execution rules previously carried by the packaged Skills,
including repository-set completeness, source ownership claims, workspace roles,
resource bindings, optional-driver provenance, focused assurance, review causality,
contract-revision behavior, cancellation authority, absolute attempts, and terminal
verification.

Tool schemas and guidance SHALL be the model-facing authority for invocation shape.
They SHALL not change domain semantics or become persisted workflow inputs except
where a current review contract explicitly binds the stable package guidance digest.
A change to workflow semantics SHALL still be made in the Controller/workflow
capabilities rather than hidden only in MCP prose.

#### Scenario: Action guidance and workflow disagree

- **WHEN** package validation finds guidance that permits an effect, payload, retry, or transition forbidden by the current workflow projection
- **THEN** the candidate fails rather than treating guidance as a second workflow authority

#### Scenario: Guidance omits a required current rule

- **WHEN** an installed journey must read legacy Skill or implementation source to complete a projected action correctly
- **THEN** the candidate fails and the missing rule must be expressed in the projection, schema, or bounded guidance

## MODIFIED Requirements

### Requirement: Optional drivers have an explicit degraded path

An official workflow action template that names an optional OpenSpec,
codebase-memory, or independent-review driver SHALL declare its tool, produced
artifact or evidence type, fallback instructions, and the assurance obligations that
can require it. The runtime SHALL project driver metadata only when the current
action is required by an outstanding obligation and SHALL NOT dynamically load or
execute driver code.

The current MCP action guidance SHALL direct the Codex executor to use the named tool
when available or follow the declared fallback and record the actual driver status.
`available` SHALL mean the named tool produced evidence for the bound inputs;
`degraded` SHALL mean the declared fallback or materially incomplete supporting
coverage was used; and `unavailable` SHALL mean the named assurance could not be
produced. Fallback evidence SHALL NOT be described as the named tool's result.

Degraded, partial, stale, unavailable, unconfirmed, internally inconsistent, or
otherwise incomplete impact evidence SHALL normalize to `unknown` and SHALL invoke
the current conservative assurance result. Review evidence SHALL distinguish
`independent` and `self` assurance, but the Controller SHALL derive satisfaction,
rework, causal triage, impact-gap reentry, disposition, waiver, or exhaustion from the
current review obligation, structured findings, causal status, and absolute budgets
rather than trusting an executor-supplied aggregate outcome.

#### Scenario: Optional tool is available

- **WHEN** Codex can invoke the current action's named optional tool
- **THEN** the submitted driver result records that tool, current phase, bound inputs, concrete evidence, and limitations

#### Scenario: Optional tool is unavailable

- **WHEN** a required optional tool cannot be invoked
- **THEN** current MCP guidance provides the declared fallback, the executor records degraded or unavailable status truthfully, and the obligation's completion requirements remain intact

#### Scenario: Independent tool approves

- **WHEN** an independent-review driver produces current evidence with no unresolved blocking finding, causal-triage state, or impact gap for the exact task-change slice
- **THEN** the Controller marks that review obligation satisfied and does not project duplicate review for the same current fingerprint

#### Scenario: Fallback self-review finds changes

- **WHEN** independent review is unavailable and truthful self-review reports a current blocking `introduced` or `affected` finding
- **THEN** the Controller records self assurance and projects only the finding-bound route permitted by current obligations and absolute budgets

#### Scenario: Fallback review cannot establish causality

- **WHEN** independent or fallback review reports a current blocking finding with `unknown` causal relation
- **THEN** the Controller derives `triage-required` and permits only projected bounded causal refresh or an authorized disposition before approval or source rework

#### Scenario: Fallback cannot provide independence

- **WHEN** self-review finds no unresolved blocker but the plan requires independent review and no exact current assurance waiver exists
- **THEN** the independent-review obligation remains outstanding and follows its recorded execution and exhaustion rules

#### Scenario: Operator waives unavailable independent review

- **WHEN** the named driver records unavailable independent assurance and an exact current authorized assurance waiver governs that obligation
- **THEN** the Controller may mark it waived while the Dossier reports the actor, rationale, and remaining risk and never labels self-review as independent approval

#### Scenario: Optional review is not required

- **WHEN** the current assurance plan marks independent review not required
- **THEN** no independent-review driver action or fallback self-review is projected merely because the driver exists
