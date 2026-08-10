## 1. Preserve the regressions

- [x] 1.1 Add failing MCP tests proving impact and ownership fields are absent from
  current-action schemas.
- [x] 1.2 Add failing tests proving generated task IDs are lost after successful
  task creation followed by application or server post-processing failure.

## 2. Close the payload contract

- [x] 2.1 Implement the shared effective payload contract and complete nested JSON
  Schemas without changing workflow declarations.
- [x] 2.2 Route strict Controller validation, MCP current-action projection,
  guidance, and package validation through the shared contract.
- [x] 2.3 Add explicit replay-only compatibility for historical `0.4.x` records,
  including byte-preserving conservative confidence normalization.
- [x] 2.4 Cover all official workflow nodes dynamically, live-strict and
  replay-compatible impact assurance behavior, exact Lite ownership journeys, and
  fail-closed historical structure damage.

## 3. Retain mutation identity

- [x] 3.1 Add request-scoped mutation execution context and capture the generated ID
  immediately after Controller return.
- [x] 3.2 Use the captured ID for cancellation, result limits, nested validation,
  envelope errors, unexpected failures, and the server output guard.
- [x] 3.3 Prove every uncertain recovery contains the real ID, forbids blind retry,
  and can execute the named read tool.

## 4. Verify the bounded change

- [x] 4.1 Run payload, impact/ownership, uncertain recovery, and directly related
  Controller/workflow/assurance/MCP focused tests.
- [x] 4.2 Run complete unittest discovery once after implementation freezes.
- [x] 4.3 Run package validation, strict validation for every active OpenSpec change,
  `git diff --check`, and one final independent read-only review.
