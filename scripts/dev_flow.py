#!/usr/bin/env python3
"""Fixed public bootstrap for the Dev Flow 0.2.0 CLI."""

from pathlib import Path
import sys


_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SOURCE_ROOT))

from dev_flow_orchestrator.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
