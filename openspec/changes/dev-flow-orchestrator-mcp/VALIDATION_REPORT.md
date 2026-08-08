# Validation Report

## Candidate

- Change ID: `dev-flow-orchestrator-mcp`
- Repository baseline: `Innocent-children/dev-flow-orchestrator`
- Baseline commit: `38685bf09e934ba5c97ea61112110beedb7083ca`
- Target release: `0.5.0`
- Preserved persisted model and task-data namespace: `0.4.0`
- Current evidence host: macOS arm64

## Baseline evidence

The exact pre-change archive was run in an ephemeral Git checkout with macOS arm64
Python 3.9.6. The complete baseline discovery ran 364 tests in 693.301 seconds and
returned `OK (skipped=25)`. Native Windows baseline execution was unavailable on
this host, so task 0.2 remains open rather than treating macOS or static PowerShell
evidence as Windows evidence.

## Current verified results

| Check | Result |
|---|---|
| Capability delta files | PASS: 10 |
| OpenSpec inventory | PASS: 54 Requirements, 169 Scenarios |
| `openspec validate dev-flow-orchestrator-mcp --strict` | PASS |
| Requirement/Scenario traceability | PASS: 223 entries |
| Traceability canonical SHA-256 | `adccec38fe75728342d79551b4c85e28d54451e5a8bfccb024980e156c6c3948` |
| Current and copied-candidate package validation | PASS: `ok=true`, `errors=[]` |
| Codex plugin structure validator | PASS |
| Exact-lock validation | PASS: `uv lock --check` |
| Official MCP client over real STDIO | PASS |
| Exact eleven-tool catalog, closed schemas, bounded guidance/results | PASS |
| Source and managed PATH launcher installed journeys | PASS |
| Current packaged Skills/Hooks | NONE |

The final complete source-discovery matrix used the frozen working tree and an
isolated locked `uv` environment for each locally available supported interpreter:

| Interpreter | Result | Duration |
|---|---|---|
| Python 3.12 | 413 tests, `OK (skipped=22)` | 851.899 s |
| Python 3.13 | 413 tests, `OK (skipped=22)` | 851.903 s |
| Python 3.14 | 413 tests, `OK (skipped=22)` | 773.381 s |

The command shape was:

```bash
uv run --isolated --locked --python 3.X \
  python -m unittest discover -s tests -p 'test_*.py'
```

All 22 skips in each run are platform-gated tests; 16 are native Windows lifecycle
tests. They are reported as skips and are not counted as Windows evidence. Python
3.12 and 3.13 also emitted the standard-library future extraction-filter warning
while the test fixture unpacked the trusted local 0.4.2 Git archive; the tests and
runtime completed successfully.

Focused lifecycle evidence is also current:

- macOS installer: 34/34 tests passed;
- macOS uninstaller: 21/21 tests passed;
- Windows product plus lifecycle collection on macOS: 11 host-neutral tests passed
  and 16 native-Windows tests skipped;
- traceability package checks: 3/3 passed;
- managed-runtime and installed-journey coverage is also included in every 413-test
  discovery above.

## Isolated real Codex lifecycle evidence

An isolated temporary `HOME`, `CODEX_HOME`, marketplace, source checkout, managed
runtime, PATH directory, repositories, and task-data root were exercised with the
real local Codex CLI 0.146.0. The user's normal Codex profile was not read or
modified.

The isolated lifecycle proved:

1. fresh activation and subsequent idempotent repair both completed;
2. `codex plugin list --marketplace personal --json` reported exactly one installed
   and enabled `dev-flow-orchestrator@personal` at release `0.5.0`;
3. `codex mcp list --json` reported exactly one enabled `dev-flow` STDIO server using
   `dev-flow-mcp --stdio`;
4. the official MCP client initialized release `0.5.0`, listed the exact eleven-tool
   catalog, and discovered the pre-existing `retained-current` model-`0.4.0` task
   through the default installed data path;
5. the activated managed PATH launcher completed all six official workflows in
   focused and closed-trigger routes, plus legacy 0.4.2 resume, multi-member restart,
   OpenSpec/codebase-memory guidance paths, review/rework/waiver/disposition,
   contract revision, corrupt-inventory rejection, linked-worktree admission, lost
   response recovery, and terminal Dossiers;
6. marker-scoped `--keep-source` uninstall removed the plugin, MCP registration,
   both PATH launchers, and managed runtime while preserving source and task data;
7. current `0.4.0` and retained `0.3.0` namespace tree digests were byte-identical
   immediately before and after uninstall:
   `bfc71ece61283c6dc65b357f34992b9c4c38681757f69ede516ee55bcab66c11`
   and `96c0e0a853c2676fd294a84167be532f85bb20653a39cf279929012ff13079fc`.

## Verification defects found and closed

Final verification exposed defects that narrower tests had not covered. They were
fixed before the results above were recorded:

- three public guidance assertions required exact retry/review/current-baseline
  semantics;
- default installed data resolution appended namespace `0.4.0` twice before the
  Store; the Store is now the sole namespace appender and read-only discovery tests
  verify byte stability;
- the disconnect proxy left daemon threads holding buffered I/O at interpreter
  shutdown; raw file-descriptor forwarding now exits without a fatal Python error;
- repair initially classified its own bundled MCP registration as standalone;
- uninstall initially made the same conservative classification and failed before
  any deletion. Installer and uninstaller now require exact active plugin identity,
  one canonical bundled registration, and no explicit/extra standalone registration.

The final real repair and uninstall were rerun after these fixes and passed. The two
initial classification failures were fail-closed and did not modify task data.

## Explicit remaining external gates

Four task-level gates remain open because this macOS host cannot supply their
required evidence:

- **0.2:** focused native Windows pre-change baseline evidence;
- **16.2:** the complete supported interpreter/host matrix. Python 3.10 and 3.11 are
  not installed locally, and the native Windows host matrix is absent;
- **16.5:** native Windows 10 22H2 x64 and Windows 11 x64 install/repair/rollback/
  uninstall execution, including native path and reparse behavior;
- **16.10:** the final Delivery Dossier, which may be published only after those
  platform gates are current.

Static PowerShell checks, macOS results, skipped tests, WSL/Wine, and Windows Server
automation are not represented as native Windows client evidence. The isolated
Codex profile proves this local candidate's activation path; it does not prove that
an unrelated external Codex installation has enabled the server.
