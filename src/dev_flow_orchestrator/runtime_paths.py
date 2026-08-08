"""Neutral runtime path authorities shared by CLI, MCP, and installers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional, Sequence

from ._platform.paths import canonical_data_root, paths_overlap
from .model import DevFlowError


PLUGIN_DATA_ENV = "PLUGIN_DATA"
CODEX_HOME_ENV = "CODEX_HOME"
RUNTIME_HOME_ENV = "DEV_FLOW_RUNTIME_HOME"
DATA_DIR_ENV = "DEV_FLOW_DATA_DIR"


def resolve_data_dir(
    explicit: Optional[str] = None,
    *,
    environment: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve the product data base root without creating it.

    Resolution follows explicit, data-override, plugin, then Codex-home
    precedence.  The task store remains the sole authority that appends the
    current model namespace.
    """
    values = os.environ if environment is None else environment
    if explicit is not None:
        if not explicit:
            raise DevFlowError("DATA_DIR_REQUIRED", "data directory must not be empty")
        return str(canonical_data_root(explicit))
    data_override = values.get(DATA_DIR_ENV)
    if data_override:
        return str(canonical_data_root(data_override))
    plugin_data = values.get(PLUGIN_DATA_ENV)
    if plugin_data:
        root = canonical_data_root(plugin_data)
    else:
        codex_root = canonical_data_root(
            values.get(CODEX_HOME_ENV, str(Path.home() / ".codex"))
        )
        root = codex_root / "plugins" / "data" / "dev-flow-orchestrator-personal"
    return str(canonical_data_root(root))


def resolve_managed_runtime_root(
    explicit: Optional[str] = None,
    *,
    environment: Optional[Mapping[str, str]] = None,
    source_root: Optional[str | Path] = None,
    data_root: Optional[str | Path] = None,
    repository_roots: Sequence[str | Path] = (),
) -> str:
    """Resolve a non-created runtime root and prove it is disjoint.

    Existing symlinks/reparse points are resolved by the shared host path
    canonicalizer before comparison. Different Windows drives are disjoint by
    the shared platform comparison rules.
    """
    values = os.environ if environment is None else environment
    if explicit is not None and not explicit:
        raise DevFlowError("RUNTIME_PATH_UNSAFE", "managed runtime path must not be empty")
    selected = explicit if explicit is not None else values.get(RUNTIME_HOME_ENV)
    if selected:
        root = canonical_data_root(selected)
    else:
        if os.name == "nt":
            base = values.get("LOCALAPPDATA")
            platform_root = Path(base) if base else Path.home() / "AppData" / "Local"
        else:
            base = values.get("XDG_DATA_HOME")
            platform_root = Path(base) if base else Path.home() / ".local" / "share"
        root = canonical_data_root(platform_root / "dev-flow-orchestrator" / "runtime")

    protected = []
    if source_root is not None:
        protected.append(("verified source", canonical_data_root(source_root)))
    if data_root is not None:
        protected.append(("Controller data", canonical_data_root(data_root)))
    protected.extend(
        ("repository", canonical_data_root(item))
        for item in repository_roots
    )
    for label, candidate in protected:
        if paths_overlap(root, candidate):
            raise DevFlowError(
                "RUNTIME_PATH_UNSAFE",
                "managed runtime must be disjoint from {}".format(label),
            )
    return str(root)
