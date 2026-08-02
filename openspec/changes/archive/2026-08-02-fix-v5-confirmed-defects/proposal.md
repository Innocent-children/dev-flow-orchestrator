## Why

The V5 candidate currently has six confirmed defects that break normal installation, guidance, workflow execution, or task discovery. These defects should be corrected without adding new security models, migration layers, parser hardening, or recovery protocols.

## What Changes

- Validate a candidate package against the candidate's own source, workflows, and product catalog.
- Align the `follow-dev-flow` UI metadata with the V5 single-repository workflow.
- Require the installation smoke flow to execute its verification command before recording passing evidence.
- Make declared `object` action payloads survive persistence and replay.
- Prevent one missing or invalid task state from blocking discovery of healthy tasks.
- Reject both directions of repository/data-directory overlap when starting a task.

## Capabilities

### New Capabilities

- `package-delivery-validation`: Candidate-root validation, V5 skill guidance, and truthful installation verification evidence.
- `workflow-payload-replay`: End-to-end persistence and replay of declared object payloads.
- `task-discovery-boundaries`: Healthy-task discovery in the presence of invalid task entries and bidirectional repository/data-directory exclusion.

### Modified Capabilities

None.

## Impact

The change affects the package validator and its focused tests, the main skill UI metadata, installation documentation, action payload validation, task inventory scanning, controller start validation, and their directly related focused tests. Runtime code remains Python-standard-library-only. Task schema, workflow schema, Hook authority, filesystem permission policy, and migration behavior are unchanged.
