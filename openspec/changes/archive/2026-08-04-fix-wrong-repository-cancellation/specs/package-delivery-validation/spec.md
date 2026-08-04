## MODIFIED Requirements

### Requirement: Public skill guidance matches the current product
The packaged `follow-dev-flow` Skill and agent metadata SHALL describe candidate version `0.2.0` and its repository topology as one exact set of one to eight user-prepared local Git worktrees. They SHALL invoke `$follow-dev-flow` in the default prompt and SHALL explain official workflow selection, repeatable repository selection, one-task/one-current-action/one-Codex execution, structured contracts, explicit repository-scoped resources, repository-set snapshot bindings, bounded assurance, optional-driver fallback, scope decisions, and aggregate Delivery Dossier completion without claiming later roadmap capabilities. Guidance SHALL specifically keep branch/worktree creation, Git publication, multi-Agent execution, and external CI/PR/release effects outside the controller's supported authority.

The guidance SHALL define a semantic repository-mismatch cancellation handshake. After the executor confirms from the task contract and source that the immutable repository set cannot satisfy the accepted requirement, it SHALL stop the projected action, identify the exact task and mismatch, state that the task remains active, and obtain explicit user authorization for that exact cancellation unless the current user request already supplies it. Before authorization the executor SHALL NOT cancel, apply the blocked action, mutate a member, or claim that the task ended. After authorization at a stage that declares cancellation, it SHALL use the injected controller to cancel the exact task and SHALL verify `done: true`, `status: CANCELLED`, and `current_node: cancelled` before reporting completion. If cancellation is unavailable or fails, the guidance SHALL preserve and report the active state and required workflow or operator action without substituting another repository or starting an implicit replacement task.

#### Scenario: Packaged agent metadata is inspected
- **WHEN** package validation reads the main Skill and agent metadata
- **THEN** stale or component-specific version, workflow-catalog, controller-namespace, single-repository-only, managed-workspace, or parallel-executor guidance causes validation to fail

#### Scenario: Multi-repository start guidance is inspected
- **WHEN** package validation reads the documented start path
- **THEN** it requires repeatable `--repo` usage, canonical exact-set semantics, user-prepared worktrees, and one Codex executor, with one `--repo` producing a one-member set under the same model

#### Scenario: Repository mismatch lacks cancellation authority
- **WHEN** the executor confirms that the accepted requirement cannot be satisfied by the task's immutable repository set and the user has not authorized cancellation of that exact task
- **THEN** it stops the projected action, reports that the task remains active, and requests the exact cancellation decision without mutating controller or repository state

#### Scenario: Repository mismatch cancellation is authorized
- **WHEN** the user authorizes cancellation of the exact mismatched task at a stage that declares cancellation
- **THEN** the executor invokes the injected controller and reports completion only after the returned projection is `done: true`, `status: CANCELLED`, and `current_node: cancelled`

#### Scenario: Repository mismatch cannot be cancelled
- **WHEN** the current workflow stage does not declare cancellation or the controller cannot capture the complete repository set
- **THEN** the executor reports that the task remains active and identifies the required finalizer, restoration, or operator action without substituting repositories or claiming a terminal result

#### Scenario: Packaged mismatch guidance is inspected
- **WHEN** package validation reads the main Skill
- **THEN** omission of the repository-mismatch stop, explicit authority, active-state, controller-cancellation, or terminal-verification guidance causes validation to fail
