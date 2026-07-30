# Installation

Dev Flow Orchestrator requires macOS, Git, and Python 3.9 or newer.

## Install the candidate

Keep the existing plugin identity `dev-flow-orchestrator`. Copy the reviewed
candidate to the local marketplace path used by Codex and enable that single
entry. Do not create a second plugin whose name includes V4.

The package manifest points to:

- `skills/` for the three bundled Skills;
- `.mcp.json` for the disabled macOS MCP profile;
- `hooks/hooks.json` for packaged Hook discovery.

Codex supplies `PLUGIN_ROOT` and `PLUGIN_DATA` to packaged launch
configurations. Runtime state belongs under `PLUGIN_DATA`, never inside a
target repository.

## Real Codex acceptance

After receiving the reviewed handoff, the user performs these checks:

1. replace the installed candidate and confirm exactly one enabled Dev Flow
   Orchestrator instance;
2. start a new Codex task and confirm packaged Hook pickup plus MCP
   initialize/tool discovery;
3. in a real project, create a new V4 task and complete one representative
   action end to end.

These are real-host acceptance checks. Repository-local tests do not stand in
for them.
