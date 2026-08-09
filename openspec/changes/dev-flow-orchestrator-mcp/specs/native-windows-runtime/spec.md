## Purpose

Update the native Windows core runtime boundary for the MCP-first installed product:
raise the supported Python floor to 3.10, keep the Controller/Git/storage core
standard-library-only, and isolate the official MCP SDK in the adapter runtime.

## MODIFIED Requirements

### Requirement: The core runtime operates natively on common Windows x64 clients

The core Controller, CLI, Web UI, and shared repository runtime SHALL operate without
WSL, Git Bash, or Cygwin on Windows 10 22H2 x64 and Windows 11 x64 client systems
using supported 64-bit CPython 3.10–3.14 and Git for Windows. Core production modules
outside `src/dev_flow_orchestrator/mcp/` SHALL remain Python-standard-library-only.
The installed MCP adapter MAY depend on the official Python MCP SDK stable v2 line and
its locked transitive dependencies, but those dependencies SHALL remain isolated from
the core import and persisted-model boundary.

The documented support boundary SHALL exclude Windows Server, Windows ARM64, 32-bit
Python, CPython 3.9, WSL execution, UNC/SMB/NAS repositories, `\\wsl$`, mapped
network storage, and remote MCP serving. The runtime is not required to detect every
unsupported Windows edition or storage technology merely to enforce that support
statement.

#### Scenario: Supported Windows core lifecycle executes

- **WHEN** a user runs the core CLI or an MCP tool against an ordinary local Git worktree on a documented Windows x64 client
- **THEN** start, capture, current-action projection, action application, stored inspection, path discovery, governance, and cancellation execute without a POSIX compatibility layer

#### Scenario: Core package imports without MCP dependencies

- **WHEN** Controller, Store, GitClient, CLI, and Web modules are imported on Windows in a core-only environment
- **THEN** no unavailable POSIX module or MCP SDK package is imported as a side effect

#### Scenario: The MCP adapter imports in its managed runtime

- **WHEN** the installed Windows launcher uses its validated managed runtime
- **THEN** the MCP adapter imports the locked official SDK and initializes STDIO while using the same core modules and current data namespace

#### Scenario: Only Python 3.9 is available

- **WHEN** a Windows operator attempts to install release `0.5.0` with no supported Python 3.10–3.14 runtime
- **THEN** installation fails before MCP activation, preserves existing task data, and reports the new runtime floor

#### Scenario: Unsupported environment is used

- **WHEN** the runtime is used outside the documented Windows client boundary
- **THEN** the product makes no compatibility claim and does not require a broad SKU, filesystem, or remote-transport detection subsystem
