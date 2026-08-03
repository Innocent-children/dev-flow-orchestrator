## Why

When Codex determines that a Dev Flow task was started against a repository set that cannot satisfy the accepted requirement, the current Skill can stop after reporting the mismatch. The controller task then remains active indefinitely even though its immutable repository membership makes the intended delivery impossible.

## What Changes

- Define a repository-mismatch cancellation handshake for the `follow-dev-flow` executor: stop the projected action, identify the exact active task and mismatch, and request explicit cancellation authority.
- Require an authorized cancellation to use the controller and verify the returned `CANCELLED` terminal projection before reporting the task as ended.
- Keep an unauthorized task active and make that state and the required operator decision explicit; never cancel silently or substitute another repository.
- Add package validation and focused regression coverage so the shipped Skill cannot omit this closure behavior.
- Document the operator journey while preserving controller, Hook, Git, and immutable-membership boundaries.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `package-delivery-validation`: Packaged executor guidance must close a confirmed semantic repository mismatch through an explicit-authority cancellation handshake and terminal-state verification.

## Impact

The change affects `skills/follow-dev-flow/SKILL.md`, package validation and its focused tests, the current OpenSpec capability, and operator-facing documentation. The controller cancellation implementation and Hook path discovery remain unchanged because they already enforce the correct state and authority boundaries and cannot determine semantic requirement-to-repository fit.
