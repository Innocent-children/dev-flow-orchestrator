#!/usr/bin/env python3
"""Fixed public bootstrap for the current Dev Flow Hook."""

from pathlib import Path
import os
import sys


_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from dev_flow_orchestrator.hook import main  # noqa: E402


if __name__ == "__main__":
    launcher_name = (
        "dev_flow_python_launcher.cmd"
        if os.name == "nt"
        else "dev_flow_python_launcher"
    )
    raise SystemExit(
        main(
            controller_argv=(
                str(_PLUGIN_ROOT / "scripts" / launcher_name),
                str(_PLUGIN_ROOT / "scripts" / "dev_flow.py"),
            )
        )
    )
