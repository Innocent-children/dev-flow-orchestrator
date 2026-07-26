#!/usr/bin/env python3
"""A deterministic, local control plane for Codex development work.

The module intentionally depends only on Python's standard library.  Every
normal CLI response (including errors) is one JSON object on stdout so hooks
and skills do not need to scrape prose.
"""

from __future__ import annotations

from pathlib import Path as _DevFlowBootstrapPath

# Runtime layout version 1 intentionally executes trusted, ordered source
# fragments in this module's globals. This preserves direct-script,
# spec_from_file_location, isolated -I/-S startup, cache, ContextVar,
# and monkeypatch behavior while keeping dev_flow.py as the sole facade.
_DEV_FLOW_PART_NAMES = (
    "core.py",
    "mutation.py",
    "scope.py",
    "process.py",
    "git.py",
    "commands.py",
    "baseline.py",
    "workspace.py",
    "review.py",
    "cli.py",
)
_DEV_FLOW_PART_DIRECTORY = (
    _DevFlowBootstrapPath(__file__).resolve().with_name("dev_flow_parts")
)
for _DevFlowPartName in _DEV_FLOW_PART_NAMES:
    _DevFlowPartPath = _DEV_FLOW_PART_DIRECTORY / _DevFlowPartName
    if not _DevFlowPartPath.is_file():
        raise RuntimeError(
            "incomplete dev-flow installation: missing runtime part "
            + _DevFlowPartName
        )
    _DevFlowPartSource = _DevFlowPartPath.read_bytes()
    exec(
        compile(_DevFlowPartSource, str(_DevFlowPartPath), "exec"),
        globals(),
        globals(),
    )
del (
    _DevFlowPartSource,
    _DevFlowPartPath,
    _DevFlowPartName,
    _DEV_FLOW_PART_DIRECTORY,
    _DEV_FLOW_PART_NAMES,
    _DevFlowBootstrapPath,
)


if __name__ == "__main__":
    raise SystemExit(main())
