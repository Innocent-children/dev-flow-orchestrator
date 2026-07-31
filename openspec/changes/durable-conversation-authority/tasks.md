## 1. Workflow Contract

- [x] 1.1 Remove `lite-approval` and derive topology-aware Lite preflight target/status from one package-owned workflow source of truth.
- [x] 1.2 Update workflow identity, single-repository and multi-repository focused tests to prove Lite enters `implement` or `repository-plan` directly while Full retains plan approval.

## 2. Durable Confirmation Core

- [x] 2.1 Replace `MacOSApprovalPort` with a private-permission confirmation store covering pending, confirmed, denied, claimed, consumed and stale/tombstone lifecycle states plus corruption/limit diagnostics.
- [x] 2.2 Bind request identity and verification to task, workflow identity, revision, action, grant, actor role/local account, validated payload, repository context, scope and Codex session; serialize all task candidates and `(session_id, turn_id)` event decisions under one data-directory confirmation lock with CAS and replay/conflict enforcement.
- [x] 2.3 Integrate request-or-apply behavior into ordinary actions and actionable effect-recovery modes without changing existing effect settlement evidence rules; diagnose unsupported reattach/compensate modes before requesting confirmation.
- [x] 2.4 Make denial terminal for the exact binding, compact only safely terminal records, and bound private retention/public projection without expiring or evicting live replay protection.
- [x] 2.5 Persist confirmation request IDs in successful task evidence or effect claims and reconcile commit/receipt/consume crash windows without redispatch, duplicate commit or nested confirmation/task/journal locks.

## 3. Codex Adapters

- [x] 3.1 Forward feature-detected `UserPromptSubmit` session, turn, cwd and prompt fields through a narrow controller observer with exact agreement, denial and ambiguity parsing.
- [x] 3.2 Expose only current no-request/pending/confirmed/denied state in session-routed `agent-v1` and Hook context; return consumed locators in successful operation results and hide stale/consumed records as authority.
- [x] 3.3 Update CLI and MCP next/apply/recovery schemas and handlers for conversation-session routing while rejecting the per-field matrix of approval, request/authority, actor, issuer, prompt and serialized-record inputs.
- [x] 3.4 Update Follow Dev Flow instructions to create a pending request, explain it, end the turn, reload on a later turn, and never poll, invoke the Hook, reopen denial or auto-retry.
- [x] 3.5 Validate the packaged `UserPromptSubmit` launcher end to end from manifest/cache path to the same greenfield package and data directory as CLI/MCP.

## 4. Focused Verification

- [x] 4.1 Replace popup mocks with exact request/UserPromptSubmit helpers and cover pending persistence, arbitrary delay, exact/bare confirmation, ambiguity, terminal denial, mismatch, staleness, event replay/conflict and single consumption.
- [x] 4.2 Cover concurrent first requests, second-request/bare-reply ordering, same-turn cross-task replay/conflict, approve/deny CAS, duplicate confirmed retry, prune races and task/effect/receipt/consume fault-injection windows.
- [x] 4.3 Cover CLI/MCP parity and the forbidden-input matrix, Hook fail-open/store fail-closed behavior, private permissions/corruption/limits, bounded projection, consumed response visibility and no public confirmation issuer.
- [x] 4.4 Cover effect recovery confirmation without weakening receipt, absence, reattach, compensation or operator-intervention checks.
- [x] 4.5 Add semantic Skill pause/reload/no-retry checks and a complete shipped/current source-closure audit proving every plugin-owned popup symbol, timeout, prerequisite and executable path is gone outside explicit historical evidence.
- [x] 4.6 Run only directly affected macOS test methods/modules; record the prohibited full unittest suite and native Windows/Linux validation as unverified.

## 5. Product and Package Closure

- [x] 5.1 Update `README.md`, `README.zh-CN.md`, `INSTALL.md`, `ARCHITECTURE.md`, plugin metadata and troubleshooting for Hook discovery, exact diagnostics, old-popup upgrade, data-preserving uninstall/explicit cleanup, the honest conversation trust boundary and the separate Codex host-permission boundary.
- [x] 5.2 Update the stacked architecture change's directly superseded dialog/principal requirements, invalidate its old frozen candidate by content identity, and leave unrelated artifacts and archive history untouched.
- [x] 5.3 Extend package validation for one Hook/data-dir route, complete popup source closure and installed cache launch; run the bundled validator for every packaged Skill plus plugin manifest/package validators.
- [x] 5.4 Freeze plan and implementation review identities, perform independent reviews, resolve actionable findings, and record final evidence without archiving the stacked architecture change.
