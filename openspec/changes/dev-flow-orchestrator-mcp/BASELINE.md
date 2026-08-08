# Implementation Baseline

- Recorded on: 2026-08-08 (Asia/Shanghai)
- Authoritative `main`: `38685bf09e934ba5c97ea61112110beedb7083ca`
- `origin/main`: `38685bf09e934ba5c97ea61112110beedb7083ca`
- Implementation branch started at the same commit with no committed divergence.
- Release authority: `0.4.2`
- Model authority and task-data namespace: `0.4.0`
- Python metadata: `>=3.9,<3.15`
- Package manifest: `.codex-plugin/plugin.json`, version `0.4.2`, packaged Skills at `./skills/`
- Official workflows: `bugfix`, `feature`, `full`, `investigation`, `lite`, `refactor`
- Installed lifecycle assets: three packaged Skills, `hooks/hooks.json`, POSIX and Windows Hook launchers, installer/uninstaller scripts, CLI, and read-only Web UI
- Tracked-file manifest before implementation: 210 paths, SHA-256 `3596c3a0b84ae6c8dc00d7b205dd38c2cc3c84f30fd237d009566931fb548960`

## Baseline validation

OpenSpec structure was validated before the production implementation was
continued:

```text
openspec validate dev-flow-orchestrator-mcp --strict
Change 'dev-flow-orchestrator-mcp' is valid
```

The change package originally contained an extra `openspec/changes/introduce-mcp-first-runtime/`
directory layer. The implementation setup moved the authoritative proposal, design, tasks, and
delta specs to the standard `openspec/changes/dev-flow-orchestrator-mcp/`
layout before validation.

The complete pre-change source suite was run from a `git archive` of the exact
authoritative commit, not from the modified working tree. The archive initially
had no `.git` directory; that first attempt executed 343 tests but ended with one
`setUpClass` error when the legacy installer test called `git ls-files`. It is
retained as an invalid test-environment attempt and is not counted as either a
product pass or failure.

The same untouched archive content was then given an ephemeral local `main` Git
repository so Git-aware baseline tests could enumerate it. No current working-tree
content was copied into that archive. Environment and command:

```text
host: Darwin 27.0.0 arm64
interpreter: /usr/bin/python3, Python 3.9.6
source content: 38685bf09e934ba5c97ea61112110beedb7083ca
command: /usr/bin/python3 -I -S -m unittest discover -s tests -p 'test_*.py'
Ran 364 tests in 693.301s
OK (skipped=25)
```

This is the complete macOS pre-change baseline. The skips are the baseline's
platform-conditional tests; they are not counted as Windows evidence.

Native Windows baseline execution is not available on this macOS host and remains
an external release gate. No macOS result is treated as native Windows evidence,
so task 0.2 remains open as a combined cross-host gate even though its macOS half
is now current and complete.

## Concurrent-change check

No other active OpenSpec change exists under `openspec/changes/`; only the archive and this change
are present. Therefore no concurrent active change currently overlaps the plugin manifest,
installer authority, Hook removal, Python floor, or release authority.
