## ADDED Requirements

### Requirement: Plugin packages the Dev Flow Skill and MCP together
The installed plugin SHALL expose one Skill named `dev-flow` from `./skills/` and the existing local STDIO MCP server named `dev-flow` from `./.mcp.json`.

#### Scenario: Installed package contains both capabilities
- **WHEN** a validated plugin candidate is installed into an isolated Codex plugin destination
- **THEN** the installed copy contains the `dev-flow` Skill metadata and the unchanged `dev-flow-mcp --stdio` server registration

#### Scenario: Skill dependency metadata cannot express bundled STDIO
- **WHEN** the supported `agents/openai.yaml` MCP dependency schema requires a streamable HTTP URL
- **THEN** the Skill omits that dependency block and the plugin manifest retains `mcpServers: "./.mcp.json"` as the local bundled server registration

### Requirement: Codex can activate the Skill explicitly and implicitly
The Skill SHALL support explicit `$dev-flow` invocation and SHALL permit implicit invocation from a concise description that states the applicable user goals and boundaries.

#### Scenario: Explicit invocation metadata
- **WHEN** Codex discovers the installed Skill and the user invokes `$dev-flow`
- **THEN** the Skill name, interface prompt, and policy identify `dev-flow` and allow the workflow to load

#### Scenario: Matching development task
- **WHEN** a user asks Codex to carry a repository development task through resumable planning, implementation, investigation, verification, recovery, or delivery
- **THEN** the Skill description provides sufficient goal and trigger language for implicit matching and implicit invocation remains enabled

### Requirement: Skill routes through Controller authority
The Skill SHALL use the existing `dev-flow` MCP to inspect server identity, discover active tasks, select or start exactly one task, obtain the authoritative current action, and submit only the exact Controller-issued action, binding, and closed payload.

#### Scenario: One matching active task
- **WHEN** discovery returns one active task for the user-prepared repository scope
- **THEN** the Skill resumes that task and requests its current action instead of creating a replacement task

#### Scenario: No matching active task
- **WHEN** discovery returns no active task and the user has supplied an exact repository set and requirement
- **THEN** the Skill selects a workflow identifier advertised by the server, starts one task, and requests its current action

#### Scenario: Ambiguous or unavailable discovery
- **WHEN** task discovery is ambiguous, unavailable, or inconsistent across repository members
- **THEN** the Skill stops mutation, reports the Controller result, and obtains the user choice or follows the MCP-provided recovery

#### Scenario: Current action execution
- **WHEN** the Controller returns a current action with a binding and guidance
- **THEN** the Skill performs only that action within its allowed effects and applies the exact action identifier, unchanged binding, and schema-conforming payload

#### Scenario: Mutation completion is uncertain
- **WHEN** a mutation response is lost or cancellation occurs after dispatch
- **THEN** the Skill reads the stored task and current action before deciding whether another mutation is required

### Requirement: Skill remains an orchestration layer
The Skill SHALL describe activation, routing, and use of Controller-issued guidance while leaving task state, transitions, action definitions, payload schemas, workflow semantics, repository authority, and authorization enforcement to the existing MCP Controller.

#### Scenario: Packaged guidance is inspected
- **WHEN** package validation reads the Skill and its reference material
- **THEN** it finds no duplicated state machine, closed action or payload schema catalog, generic shell MCP tool, lifecycle Hook, renamed MCP tool, fabricated remote endpoint, or alternate task-state writer

### Requirement: Delivery validates installed Skill discovery
Package and installed-stage validation SHALL verify the Skill structure, frontmatter, Codex interface and policy metadata, manifest linkage, installed file integrity, and coexistence with a successful MCP initialization and tool-catalog observation.

#### Scenario: Source candidate validation
- **WHEN** `scripts/validate_package.py` validates the repository candidate
- **THEN** it accepts only the expected `skills/dev-flow/` files and rejects missing, malformed, unlinked, unsupported, or authority-duplicating Skill content

#### Scenario: Installed-stage validation
- **WHEN** the managed runtime acceptance runs against the installed plugin copy
- **THEN** it proves the installed Skill is discoverable from its manifest and metadata while the same installation initializes the existing `dev-flow` MCP and observes its expected tool catalog

### Requirement: Public documentation describes the installed experience
The English source documentation and corresponding Simplified Chinese translations SHALL describe the Skill, `$dev-flow`, implicit activation, bundled STDIO registration, Controller authority, installation contents, and validation evidence with equivalent scope and constraints.

#### Scenario: Documentation consistency validation
- **WHEN** package validation checks public documentation
- **THEN** each required English and Simplified Chinese document contains aligned Skill and MCP claims, commands, paths, and safety boundaries
