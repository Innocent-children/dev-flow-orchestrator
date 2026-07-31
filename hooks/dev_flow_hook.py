#!/usr/bin/env python3
"""Fixed public bootstrap for the greenfield V4 Hook."""

from pathlib import Path
import sys


_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from dev_flow_orchestrator.hook import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        main(controller_path=str(_PLUGIN_ROOT / "scripts" / "dev_flow.py"))
    )
