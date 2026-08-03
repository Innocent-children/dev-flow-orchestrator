## Context

Dev Flow already has a controller-owned `task.cancel` mutation. It validates the selected workflow stage, captures the exact repository set, appends one replay record, and returns a terminal projection. The Hook only discovers non-terminal tasks whose canonical member roots contain the current path and injects the current projection. Neither component can determine whether a natural-language requirement is semantically satisfiable by the selected repositories.

The executor Skill currently says that cancellation requires explicit user instruction, but it does not define what the executor must do after confirming that the immutable repository set is wrong. An executor can therefore report the mismatch and end its turn without asking for the decision that would close the task.

## Goals / Non-Goals

**Goals:**

- Make a confirmed requirement-to-repository mismatch an explicit operator-decision boundary.
- Preserve user authority by requiring authorization for the exact cancellation action.
- Ensure authorized cancellation is verified as a controller terminal state before it is reported as complete.
- Make package validation fail if the shipped Skill loses this behavior.

**Non-Goals:**

- Detect semantic mismatch inside the Hook or controller.
- Automatically cancel without user authority.
- Replace immutable repository membership or start a replacement task.
- Add migration or compatibility handling for historical task data.

## Decisions

### Keep semantic diagnosis in the executor Skill

The Skill will own the response to a source-confirmed semantic mismatch. The Hook remains a small, fail-open path-discovery guardrail, and the controller remains the sole task-state writer. Adding requirement interpretation to either runtime component would introduce heuristic policy into deterministic infrastructure and would not be reliable for custom repositories or workflows.

### Use an explicit cancellation handshake

After confirming the mismatch, the executor will stop the projected workflow action and avoid repository changes. It will identify the exact task and mismatching repository set, state that the task remains active, check that the current node declares cancellation, and ask for explicit authorization unless the current user request already authorizes cancellation of that exact task.

After authorization, the executor will obtain a fresh projection, invoke the exact controller `cancel` command, and require `done: true`, `status: CANCELLED`, and `current_node: cancelled` before telling the user that the task ended. A failed or unavailable cancellation leaves the task active and must be reported with the required restoration, finalizer, or operator action.

### Enforce the journey in candidate validation

The package validator will require the main Skill to retain the mismatch, active-state, explicit-authority, controller-cancellation, and terminal-verification concepts. A focused mutation test will remove the guidance from a copied candidate and prove that validation rejects it. This matches the existing package-validation pattern and tests the shipped artifact rather than a parallel runtime policy.

### Leave controller and Hook implementation unchanged

Existing controller tests already prove cancellation terminal state, stage gating, replay, atomic exact-set capture, and no Git-changing effect. Existing Hook tests prove read-only path-based discovery. The regression belongs in Skill/package validation, with current tests retained as evidence for the unchanged runtime boundary.

## Risks / Trade-offs

- **A weak textual validator could accept incomplete prose** → Require a cohesive set of stable behavioral tokens and a focused candidate-mutation test.
- **The executor could over-classify an uncertain repository fit as confirmed** → Require source-backed confirmation; uncertainty remains diagnosis work rather than a cancellation trigger.
- **A current node may not expose cancellation** → Preserve the workflow declaration as authority and report the task as active until its required finalizer or operator path completes.
- **Installed snapshots do not change when source changes** → Validate the candidate and document installation/replacement as a separate operator-owned handoff.

## Migration Plan

No task-state migration is required. Ship the updated Skill, validator, tests, OpenSpec artifacts, and operator documentation in the next plugin candidate. Existing active tasks become subject to the corrected behavior when resumed under the updated installed Skill.

## Open Questions

None.
