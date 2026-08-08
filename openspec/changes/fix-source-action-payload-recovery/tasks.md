## 1. Guidance and errors

- [x] 1.1 Publish the exact `resources.items` envelope and item fields in bounded
  current-action guidance.
- [x] 1.2 Override source-producing stale recovery so expected task-owned edits and
  correctable pre-commit payload failures retain the issued binding.
- [x] 1.3 Add structured expected-shape details to resource validation failures.
- [x] 1.4 Map `NODE_OUTPUT_INVALID` from action application to a non-blind
  `correct-request` recovery using `dev_flow_apply_action`.

## 2. Verification

- [x] 2.1 Add guidance tests for exact resource shape, source-producing retry rules,
  unchanged authority refresh rules, digest stability, and size bounds.
- [x] 2.2 Add MCP result tests for `NODE_OUTPUT_INVALID` recovery metadata.
- [x] 2.3 Add a source-action regression proving that malformed resources do not
  mutate task state and that the corrected payload succeeds with the original
  binding after the task-owned file was created.
- [x] 2.4 Run focused tests and strict OpenSpec validation.
