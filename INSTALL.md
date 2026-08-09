# Install Dev Flow Orchestrator

[Simplified Chinese](INSTALL_CN.md)

This guide installs release `0.5.0` with its local MCP-first interface. The
persisted model and task-data namespace remain `0.4.0`.

## 1. Supported registration mode

Bundled Codex plugin/MCP installation is the only supported mode. The manifest
references the root `.mcp.json`; the installer does not provision standalone
registrations. If an independently managed standalone registration already
exists, installation stops before source, runtime, marketplace, plugin, or
launcher mutation and tells the operator to inspect it manually. Uninstallation
preserves registrations it cannot prove belong to the bundled installation.

## 2. Requirements

Bundled macOS installation requires:

- macOS;
- Git;
- `uv`;
- Codex with plugin and MCP server support;
- a writable absolute directory already on `PATH`;
- 64-bit CPython 3.10, 3.11, 3.12, 3.13, or 3.14.

Windows preview installation requires Windows 10 22H2 x64 or Windows 11 x64,
Git for Windows, `uv`, Codex, 64-bit CPython 3.10–3.14, and Windows PowerShell
5.1 or PowerShell 7. Native Windows evidence is required before treating a
release candidate as verified on Windows. Windows Server and POSIX compatibility
layers are outside the supported client claim.

## 3. Bundled installation on macOS

One-line install:

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

Reviewed local install:

```sh
git clone --branch main --single-branch \
  https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
sh "$HOME/plugins/dev-flow-orchestrator/scripts/install.sh"
```

Useful explicit locations:

```sh
DEV_FLOW_SOURCE_ROOT="$HOME/plugins/dev-flow-orchestrator" \
DEV_FLOW_RUNTIME_HOME="$HOME/.local/share/dev-flow-orchestrator/runtime" \
DEV_FLOW_BIN_DIR="$HOME/.local/bin" \
sh scripts/install.sh
```

`DEV_FLOW_BIN_DIR` must already be on `PATH`. The installer will not change
shell profiles or unrelated configuration.

## 4. What the installer does

In order, the installer:

1. verifies the expected origin, attached `main`, clean checkout, ignored-path
   safety, and fast-forward-only update;
2. validates candidate content before executing candidate runtime code;
3. checks for a duplicate enabled standalone `dev-flow` registration;
4. locates supported 64-bit Python and requires `uv`;
5. exports and installs the exact `uv.lock` runtime into a temporary virtual
   environment outside source and task data;
6. builds and installs the project wheel, then checks import, initialization,
   instructions, the exact eleven-tool catalog, and a read call;
7. writes a runtime receipt with release, source commit, Python identity,
   architecture, lock digest, launcher identity, and activation timestamp;
8. atomically publishes the versioned runtime and `dev-flow-mcp` launcher;
9. preserves unrelated marketplace entries and activates the plugin.

A failed runtime build never replaces the previous versioned runtime or
launcher. A runtime version is reused only when its receipt still matches the
verified source commit, dependency lock, launcher, and interpreter digest.

The default managed runtime is:

- macOS: `~/.local/share/dev-flow-orchestrator/runtime`
- Windows: `%LOCALAPPDATA%\dev-flow-orchestrator\runtime`

Task data remains under the Codex plugin data root in the `0.4.0` namespace and
is disjoint from the runtime.

## 5. Verify bundled activation

Confirm that the command is on `PATH`:

```sh
command -v dev-flow-mcp
dev-flow-mcp --http
```

The second command must fail with `MCP_RUNTIME_UNAVAILABLE` and must not open
a listening socket. In Codex, inspect the enabled plugin and confirm one
`dev-flow` server. Ask Codex to call `dev_flow_server_info`; it should report
release `0.5.0`, model `0.4.0`, STDIO transport, six workflows, and catalog
digests. Then list tools and confirm exactly eleven `dev_flow_*` tools.

The server is a long-lived STDIO protocol process, so do not run
`dev-flow-mcp --stdio` directly in an interactive terminal unless using an MCP
client or inspector.

## 6. Registration boundary

Standalone provisioning is not supported in this release. Existing standalone
registrations remain operator-owned and are never silently adopted or removed.

## 7. Windows preview

Run from a normal native PowerShell session:

```powershell
git clone --branch main --single-branch `
  https://github.com/Innocent-children/dev-flow-orchestrator.git `
  "$HOME\plugins\dev-flow-orchestrator"
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$HOME\plugins\dev-flow-orchestrator\scripts\install.ps1"
```

The installer uses literal paths, validates an x64 process and interpreter,
builds `venv\Scripts\python.exe`, and creates owned `dev-flow-mcp.cmd` and
`dev-flow.cmd` launchers in a writable absolute PATH directory. The latter
reuses the existing CLI and supports `--help` and `web start|status|stop`. It
does not use POSIX tooling.

## 8. Approvals and residual boundary

MCP annotations are descriptive, not enforcement. Keep user authority over
every approval. When supported by the host, approve read tools separately and
scope mutation approval to the `dev-flow` server, the exact tool, and the
current task. Do not grant generic shell or blanket mutation approval.

Release `0.5.0` removes the legacy fail-open Hook and its pre-tool data-directory
guard. The remaining protection comes from Controller validation, Store locks,
revision CAS, exact bindings, repository permissions, host approvals, and user
review. Do not describe tool annotations as a replacement security boundary.

## 9. Repair and upgrade

Rerun the same installer. It accepts only a clean authoritative checkout,
fetches `refs/heads/main`, and performs a fast-forward-only update. It never
stashes, resets, cleans, rebases, switches branches, or overwrites ignored
collisions. Local changes, local-only commits, a detached/unexpected branch,
unexpected origin, or divergence stop before activation.

The managed runtime is content-addressed by release, source commit, and lock
digest. Previous validated runtime directories are retained so a failed build
does not destroy the last usable runtime. Plugin activation errors are reported
with explicit rerun recovery and are never presented as success.

## 10. Uninstall

macOS:

```sh
sh "$HOME/plugins/dev-flow-orchestrator/scripts/uninstall.sh"
```

The source checkout is preserved by both forms. `--keep-source` remains accepted
for compatibility and makes that intent explicit:

```sh
sh "$HOME/plugins/dev-flow-orchestrator/scripts/uninstall.sh" --keep-source
```

Windows:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$HOME\plugins\dev-flow-orchestrator\scripts\uninstall.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$HOME\plugins\dev-flow-orchestrator\scripts\uninstall.ps1" -KeepSource
```

The uninstallers may remove the Dev Flow plugin entry, owned launchers, personal
marketplace entry, and the managed runtime under their existing component checks.
They report each component separately and return an explicit `partial` outcome
because the source checkout is retained. This does not establish exact ownership
or independent safety for runtime removal; DFO-AUDIT-010 remains open.

Destructive source removal is disabled because installations do not yet have a
verifiable, receipt-bound exact-ownership manifest. The receipt names the lexical
absolute retained source path and preserves Controller task data and unrelated
marketplace/MCP/plugin configuration. Before any manual action, inspect and back up
the checkout and independently confirm ownership. `--keep-source` and
`-KeepSource` have the same source-retention behavior as the default invocation.

## 11. Troubleshooting

- `Python ... required`: set `DEV_FLOW_PYTHON` to a verified 64-bit CPython
  3.10–3.14 executable.
- `uv is required`: install `uv` and rerun; dependencies are never installed
  into system or user Python.
- `PATH has no writable absolute directory`: set `DEV_FLOW_BIN_DIR` to a safe
  directory already on `PATH`.
- `standalone ... conflicts`: the bundled installer does not manage standalone
  registrations; inspect and preserve the existing registration, then resolve
  the conflict manually before retrying.
- `MCP_RUNTIME_UNAVAILABLE` for a transport option: use local `--stdio`; remote transports are not
  implemented.
- uncertain mutation completion: call `dev_flow_get_task` and
  `dev_flow_get_next_action`; never blindly replay the mutation.
- stored task is visible but next action fails: restore every immutable member
  worktree at its canonical path and retry the read.

The read-only Web UI remains available at `127.0.0.1` through
`dev-flow web start`; inspect it with `dev-flow web status` and stop it with
`dev-flow web stop`. It is not an MCP health substitute and has no mutation authority.
