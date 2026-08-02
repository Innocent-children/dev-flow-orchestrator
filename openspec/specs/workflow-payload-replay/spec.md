# workflow-payload-replay Specification

## Purpose
TBD - created by archiving change fix-v5-confirmed-defects. Update Purpose after archive.
## Requirements
### Requirement: Object payloads survive replay
An action field declared as `object` SHALL accept JSON mappings and SHALL retain the same value after state persistence and reload.

#### Scenario: Object payload is applied and reloaded
- **WHEN** a workflow action submits a nested object payload and a new controller reloads the task
- **THEN** persisted-state validation succeeds and the recorded payload equals the submitted JSON value

#### Scenario: Non-object value is submitted
- **WHEN** an action field declared as `object` receives a non-mapping value
- **THEN** the action fails with `NODE_OUTPUT_INVALID` without advancing the task
