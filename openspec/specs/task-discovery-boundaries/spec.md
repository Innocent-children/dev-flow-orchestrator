# task-discovery-boundaries Specification

## Purpose
TBD - created by archiving change fix-v5-confirmed-defects. Update Purpose after archive.
## Requirements
### Requirement: Invalid task entries are isolated during discovery
Task inventory discovery SHALL continue loading healthy tasks when another candidate task directory has missing or invalid state. A direct operation on the invalid task SHALL remain a strict error.

#### Scenario: Healthy task and orphan directory coexist
- **WHEN** inventory contains one healthy task and one task directory without state
- **THEN** discovery returns the healthy task without failing the entire inventory

#### Scenario: Invalid task is addressed directly
- **WHEN** a caller explicitly loads the task whose state is missing or invalid
- **THEN** the existing task-specific error is returned

### Requirement: Repository and data directory are disjoint
Starting a task SHALL reject equality or containment in either direction between the target repository and controller data directory.

#### Scenario: Data directory is inside repository
- **WHEN** the controller data directory equals or is contained by the target repository
- **THEN** task creation fails before state is written

#### Scenario: Repository is inside data directory
- **WHEN** the target repository is contained by the controller data directory
- **THEN** task creation fails before state is written
