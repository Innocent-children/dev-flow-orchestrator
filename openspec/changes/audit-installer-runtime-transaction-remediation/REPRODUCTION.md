# Current-head reproduction evidence

## Boundary

- Branch: `fix/audit-installer-runtime-phase-1`
- Tested HEAD: `ae92935f0427c0e67dbebfbaab1c624630c358f1`
- Phase 0 parent commit: the same tested HEAD
- Product files changed during reproduction: none
- Final `git status --short`: empty

Every dynamic driver created a new `TemporaryDirectory` and placed HOME,
USERPROFILE, LOCALAPPDATA, XDG data, CODEX_HOME, Dev Flow data, managed runtime,
source, marketplace, executable PATH, fake Codex state, and Git remote below that
root. Task-data and unrelated-marketplace sentinels were compared before and after.
Drivers were invoked through the project environment with `uv run python -B` and
scoped bytecode suppression. No real Codex profile, marketplace, runtime, task data,
or remote repository was read or modified.

Native Windows destructive lifecycle was not run. Its status is
`NOT RUN — native Windows host unavailable`.

## Finding matrix

| Finding | Current status | Current-head evidence |
|---|---|---|
| DFO-AUDIT-006 | `REPRODUCED` | Source drift at all 6 requested boundaries still ended rc=0 with active plugin and success output while receipt retained the old commit. |
| DFO-AUDIT-007 | `REPRODUCED` | A→B add failure re-added B while claiming A restored; late failure left mixed state; rollback failure lacked durable partial evidence. |
| DFO-AUDIT-008 | `REPRODUCED` | Missing/corrupt receipt still started; package, metadata, RECORD and dependency drift were reused. |
| DFO-AUDIT-009 | `PARTIALLY_CHANGED_BY_PHASE_0` | Fresh install and repair still wrote 3 ignored cache directories/27 pyc files, but Phase 0 default uninstall now retains source and returns rc=0. |
| DFO-AUDIT-010 | `REPRODUCED` | Default POSIX uninstall recursively removed unknown content throughout active/inactive runtime levels, including content created after preflight. |

These are reproduction dispositions, not remediation results.

## DFO-AUDIT-006 — mutable candidate after verification

One isolated driver reused the canonical installer fixture and ran six independent
installations. It appended a harmless tracked Python comment at each boundary:

1. runtime build;
2. runtime completion before marketplace write;
3. marketplace write before/during plugin add;
4. plugin activation before visibility/health;
5. health before CLI launcher generation;
6. launcher generation before success receipt output.

All 6 cases returned installer rc=0, left the plugin active, emitted the success
receipt, and left source as
` M src/dev_flow_orchestrator/mcp/results.py`. In all cases source HEAD and
`runtime-receipt.json.source_commit` remained the originally verified commit, the
marketplace still targeted the mutable source checkout, and the CLI launcher still
executed source. In the runtime-build case the injected marker entered installed
site-packages while the receipt continued to claim the old commit.

Current code performs its last HEAD/plain-porcelain verification before package
validation. It later reads `manage_runtime.py`, MCP launcher template, marketplace
source path, plugin package, health runner, and CLI launcher sources from the same
writable checkout. PowerShell has the same trust shape by static inspection.

Focused historical test:

```text
uv run python -m unittest -v \
  tests.test_install_script.InstallerBehaviorTests.test_existing_install_fast_forwards_to_fetched_main

Ran 1 test in 25.045s — OK
```

That pass checks ordinary porcelain but does not inject post-verification drift.

## DFO-AUDIT-007 — incomplete transaction and false rollback

Independent isolated A→B installations exercised every current injectable boundary.
Each row used a fresh temporary direct-ancestor A/B remote and authority set. The two
requested boundaries that do not exist on current HEAD are recorded explicitly
rather than represented as executed fault injections.

| Requested boundary | Dynamic injection and result | State after failure | Recovery evidence |
|---|---|---|---|
| candidate staging | Candidate build `mkdtemp` raised `OSError`; installer rc=1. | plugin A active; source B; runtime only A; launchers/marketplace A. | Installer did not health A; manual MCP launcher smoke rc=0; no transaction or partial record. |
| runtime build | fake `uv` returned 31; installer rc=1. | plugin A active; source B; runtime only A; launchers/marketplace A. | No re-health of A and no durable failure authority. |
| runtime promotion | staging-to-target `os.replace` raised `OSError`; installer rc=1. | plugin A active; source B; staging cleaned; runtime only A; launchers/marketplace A. | Manual MCP launcher smoke rc=0; no transaction or partial record. |
| launcher write | MCP launcher writer exited 71; installer rc=1. | plugin A active; source B; runtimes A+B; exit trap restored A launcher; marketplace/CLI A. | Candidate health not reached; manual A MCP smoke rc=0; no partial record. |
| marketplace write | Exact marketplace heredoc writer exited 72; installer rc=72 without a bounded diagnostic. | plugin A active; source B; runtimes A+B; MCP launcher restored A; marketplace A. | Candidate health not reached; manual A MCP smoke rc=0; no partial record. |
| plugin remove | Fake Codex applied removal, then its outer command returned 79; installer rc=1. | plugin absent; source B; runtimes A+B; launchers/marketplace A. | Installer inferred no side effect from rc, did not observe actual plugin state, and emitted no partial record. |
| plugin add | Candidate add returned 17 and the recovery add returned 0; installer rc=1. | fixture observed plugin B active; source B; runtimes A+B; launchers/marketplace A. | Output falsely claimed previous activation restored; no post-recovery plugin/MCP/health validation. |
| health | Candidate activation succeeded, then the MCP launcher was damaged so candidate health failed; installer rc=1. | recovery re-added from current B source; plugin B active; source B; runtimes A+B; launchers/marketplace A. | Output falsely claimed restored; installer ran no recovery health. A later manual launcher smoke rc=0 did not prove plugin A active. |
| active receipt replace | `ABSENT-NOT-INJECTABLE`. Current product has only the per-release runtime receipt and a process-local POSIX `INSTALL_COMMITTED` flag. | No dynamic scenario produced a durable active receipt. | Nearest current boundary is runtime promotion; PowerShell has no equivalent commit flag. |
| final CLI smoke | `ABSENT-NOT-INJECTABLE`. Current product generates the POSIX CLI after candidate MCP health but never smokes it. | The equivalent late CLI-generation injection returned rc=1 with plugin B active, dirty source B, runtimes A+B, other local assets A, and CLI probe rc=66. | No activation rollback or durable mixed-state record. |

A separate compensation-failure run made both candidate add and recovery add return
17. Installer rc=1, no plugin was active, both runtimes remained, and output supplied
only a generic remove/add command. It did not record current active identity,
component restoration states, a sealed previous path, or blind-retry safety.

Restored launcher or marketplace bytes did not establish restored A because both
still resolved the mutable source, which was B. A manual launcher smoke proved only
that one launcher/runtime pair could run; it did not substitute for installer-owned
re-observation of plugin identity, MCP registration, and complete restored health.

Focused historical test:

```text
uv run python -B -m unittest \
  tests.test_install_script.InstallerBehaviorTests.test_failed_upgrade_activation_restores_previous_launcher_and_plugin \
  -v

Ran 1 test in 23.458s — OK
```

The test checks saved bytes and a version stub, not which artifact the restore add
used or whether the restored installation passed health. Every injectable boundary
returned non-success, but none persisted a durable transaction, active receipt, or
truthful partial outcome. PowerShell static inspection likewise finds no durable
active receipt, final CLI smoke, or post-restoration health check; native Windows
remains `NOT RUN — native Windows host unavailable`.

## DFO-AUDIT-008 — runtime receipt is not startup attestation

A real locked runtime was built from an isolated clone. Initial build returned rc=0,
`reused=false`, receipt schema `dev-flow-runtime-receipt/1.0.0`.

Startup experiments used the installed runtime and full STDIO installed-stage smoke:

- deleted receipt: rc=0, read and mutation smoke true, terminal `CANCELLED`;
- malformed receipt: same successful result;
- incompatible receipt schema: same successful result;
- launcher pointed at a copied receipt-less release outside the managed root: same
  successful result.

Repair experiments then changed one authority at a time:

- package Python bytes;
- the product distribution `RECORD`;
- the product distribution `METADATA`;
- one dependency's dist-info directory removed;
- one dependency version changed;
- an extra module and distribution added.

Every repair returned rc=0 and `reused=true`; each change survived. Replacing the
runtime Python executable did fail current validation, so that one sub-boundary is
already detected. Repair did not validate or restore a changed launcher. Task and
marketplace sentinel hashes remained byte-identical.

Current startup calls behavioral/version self-checks but does not read a runtime
receipt. Reuse checks receipt inputs, runtime location, Python executable hash, and
smoke, but not wheel/package bytes, distribution metadata, RECORD inventory, exact
dependencies, launcher content, or active release.

## DFO-AUDIT-009 — source bytecode pollution

Fresh installation and repair both returned rc=0. Ordinary porcelain and
tracked/untracked counts were empty, while ignored inspection found:

```text
src/dev_flow_orchestrator/__pycache__/
src/dev_flow_orchestrator/_platform/__pycache__/
src/dev_flow_orchestrator/mcp/__pycache__/
```

Together they contained 27 `.pyc` files; no build/dist residue was observed in this
run. Repair retained the same pollution. The source-side manage-runtime invocation
lacks both `-B` and scoped `PYTHONDONTWRITEBYTECODE`; PowerShell restores its
temporary bytecode setting before that invocation.

Phase 0 changed only the downstream uninstall behavior. Production default
uninstall now returned rc=0, removed plugin activation, retained source and caches,
and reported destructive source removal disabled. The installer/repair source
immutability defect therefore remains, while the old “default uninstall rc=1”
effect no longer describes current HEAD.

Focused path test:

```text
uv run python -m unittest -v \
  tests.test_managed_runtime.ManagedRuntimeTests.test_real_locked_runtime_create_receipt_smoke_and_reuse

Ran 1 test in 15.679s — OK
```

It covers spaces, Unicode, and an apostrophe in runtime paths but does not inspect
source ignored state.

## DFO-AUDIT-010 — shallow receipt followed by recursive root removal

The isolated runtime contained valid marker and receipt structure for active and
inactive/previous releases. Unknown content was placed at:

- runtime root file, directory, and nested directory;
- active and inactive release roots;
- venv root;
- site-packages;
- scripts/bin;
- distribution metadata;
- symlink to an external sentinel;
- FIFO and Unix-domain socket.

The fake Codex fixture also created a late runtime file after runtime preflight,
during plugin removal. The exact production command was default
`/bin/sh scripts/uninstall.sh`, without keep-source or another option.

Uninstall returned rc=0 and reported overall partial because source was retained,
but reported MCP runtime removed. The complete runtime root disappeared, including
every unknown path and the late file. The external symlink target, source, task
data, and unrelated marketplace bytes remained unchanged. Thus Phase 0 source
containment worked, while runtime whole-tree deletion did not change.

Host-neutral PowerShell evidence:

```text
PYTHONDONTWRITEBYTECODE=1 uv run python -B -m unittest \
  tests.test_windows_product_support

Ran 10 tests in 0.001s — OK
```

Static inspection still finds shallow receipt iteration followed by recursive
`Remove-Item` of the runtime root. This is not native lifecycle evidence.
