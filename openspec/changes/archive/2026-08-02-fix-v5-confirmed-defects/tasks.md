## 1. Package Delivery

- [x] 1.1 Validate foreign candidate roots with the candidate's own validator and add focused regression tests.
- [x] 1.2 Align `follow-dev-flow` agent metadata with V5 and make package validation reject stale metadata.
- [x] 1.3 Update the installation smoke flow to execute verification before recording passing evidence.

## 2. Runtime Correctness

- [x] 2.1 Accept mapping-backed object payloads and add persistence/replay coverage.
- [x] 2.2 Isolate task-local load failures during inventory discovery while preserving strict direct loads.
- [x] 2.3 Reject repository/data-directory overlap in both directions before task creation.

## 3. Focused Verification

- [x] 3.1 Run only the directly related package, payload, store, Hook, controller, and golden-path test modules.
- [x] 3.2 Validate the OpenSpec change, package, all skills, plugin manifest, and diff formatting.
