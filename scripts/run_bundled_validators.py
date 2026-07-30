#!/usr/bin/env python3
"""Run every bounded V4 release validator; never aggregate unit tests here."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL_DIRECTORIES = (
    Path("skills/analyze-change-impact"),
    Path("skills/follow-dev-flow"),
    Path("skills/review-dev-flow-change"),
)
VALIDATOR_SNAPSHOTS = {
    "quick_validate.py": (
        "6cc9dc3199c935916cf6f73fcbbbb0e3bb1b58c8f5109fefa499978908164f51",
        "H4sIAAAAAAACA61XYW/bNhD9rl9x0QZE2mwlaYsBC5IMGZp2xZxsw1JgQ9sJjETbXCRKI6k0muH/3jtKlijZToGt+RBL9N27d3fvSPqrg6NKq6M7IY+4fICyNstCPvd83/d+q0RyDw8sEykzopCgEyVKA/NCgb4XWaZhCrmQImcZPHCl0cY6eiIvC2VA8c2TrrU3V0UOJTPLTNxBu/4rvnbmNcszz7u+/CP+/ec3s1l8c3l9Fc+ubl7f/gTn8N0Lz/NSPt8Q4rHlENj/MeGGpx7gHzL4kWmRuMyLObCGM/Ejq94NsYmGC+Q5JnmKBo71EfiWXpSnDZKYgyxMZx3xR6GNDlo29Ke4qZSEVyzTfNK7W7d5UUkEsrZJIQ2XpouHYIqzNDb80QShG6y1jLRhyuiPAun70+nU3x/0poA/L69ngF2QJmfGcDWIjUsJlULxyD4Gyv8LEd/LIPrmh/C9JPTJJu6EzF7+cns5mw1oWc+9FN5I25ERBYVPLQfnC5sz0rGI0UIVVRmctH0xqu5juGDnVkKRZnMeZwVLgzFg2Lm1hIUWEmsoE+7aTiAViXFquSOZV07cvNIG7jhKzJaYnFF0TNWNQPhjwstG3hEZXCmFE8Q08H2lmne1soBCummewoqv24qxLCs+8jQuVVFyZQTXWISVL1nOsVt+ypuRRTb0momES22/aR2npigyTQs5NwyHhfnrBrmS/LHkiUHwe14TrObGLVJEy0EY4h6wzWIjihFKn2/rgrAUPPq7EDLQuAnwNNhGC/u+9YC7XEfhHL+2vsGgpU21B0tz/20fATECHVL5u5Ed9qGPt47gsk3J6QVTHK3ahNZ+H6pVMlao6VUjxmGb943RtdCo2gUckufhyKvbkga9/0/wDsB2FOtNBLANrigWKJJOfv5gc3BmjQwmoI0K90/ADYH3k4XGyGoCC0RambpsQMIojukzjte+S4k+InIpnX0T107HG4C73b1j03+Pp99PP3z7NbK38Du3gKGI9gipEZNN4nBFWOtD0MuiylLKZ1mXSy6nCdMcAlKHso8ZpyJq2n8WwuAnk2lrq6GQWR36wyjDDa1J2jkR/BBwp7HrXKbDVTwvfGrrsCxfIs2ESXsgEhO8VKRAcds0KDIdIgwj46fmSWXEw6Yg+qn0Mi6bnsMF7LwkfJEshAbcEyErcASCVRdzDcmSKZZQe8II/B3u1+xR5FVOCKud/FyMaCtT++rM3K7BGu3ne+fLsfvcmL10Ij41bQ7k1tANWTtv4xF0vhpMon9mpejikEIvxqtPnshuJq0EN0pjcpFxuMPa33OjITgj+IvQH8vLTRJVdnL87MX/FZXLaltbbsCRxBw5EY/Pa6fldqsqe8mkGyQ523vEAe7YHia5aRyc4+kZxzkWJ479U8+pAV7VI6YWDyEcnMOzPv0SFYESfKvZAg+15ncC/EM/EeLNjTwqazhrrq6pUHguFqq+8PshJmi8HZvuJmcdJ5BzTaionfHdvuXy7uRDg9KQaO2bpQ70mDJobk0cmwEY5BNKqqcZ3QwAAA==",
    ),
    "validate_plugin.py": (
        "ebda00d55d7518b127f675f062fb5c6e7a1ffdc0a99df1a55ac594400d7d3228",
        "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",
    ),
}


def _write_validator_snapshot(directory: Path, name: str) -> Path:
    expected, encoded = VALIDATOR_SNAPSHOTS[name]
    payload = gzip.decompress(base64.b64decode(encoded))
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected:
        raise ValueError(f"bundled validator snapshot digest mismatch: {name}")
    path = directory / name
    path.write_bytes(payload)
    return path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="dev-flow-v4-validators-") as temporary:
        validator_root = Path(temporary)
        skill_validator = _write_validator_snapshot(
            validator_root, "quick_validate.py"
        )
        plugin_validator = _write_validator_snapshot(
            validator_root, "validate_plugin.py"
        )
        commands = [
        *(
            [sys.executable, str(skill_validator), str(root / relative)]
            for relative in SKILL_DIRECTORIES
        ),
        [sys.executable, str(plugin_validator), str(root)],
        [sys.executable, "scripts/audit_runtime_imports.py", "--root", str(root)],
        [sys.executable, "scripts/validate_package.py", "--root", str(root)],
        [
            sys.executable,
            "scripts/candidate_identity.py",
            "--root",
            str(root),
            "verify",
            "--l0-allowlist",
            "workflows/provenance/l0-allowlist.json",
            "--l2-allowlist",
            "workflows/provenance/l2-allowlist.json",
            "--genesis",
            "workflows/provenance/v4-genesis.json",
        ],
        [
            sys.executable,
            "scripts/candidate_identity.py",
            "--root",
            str(root),
            "vector",
        ],
        [
            "openspec",
            "validate",
            "establish-v4-only-runtime",
            "--strict",
            "--json",
        ],
        ]
        results: list[dict[str, object]] = []
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
            except OSError as exc:
                results.append(
                    {
                        "command": command,
                        "returncode": 127,
                        "stdout": "",
                        "stderr": str(exc),
                        "ok": False,
                    }
                )
                continue
            results.append(
                {
                    "command": command,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr.strip(),
                    "ok": completed.returncode == 0,
                }
            )
    ok = all(result.get("ok") is True for result in results)
    identity = next(
        (
            json.loads(str(result["stdout"]))
            for result in results
            if any(
                str(part).endswith("candidate_identity.py")
                for part in result["command"]
            )
            and "verify" in result["command"]
            and result.get("returncode") == 0
        ),
        {},
    )
    print(
        json.dumps(
            {
                "schema": "dev-flow-v4-bundled-validation/v1",
                "ok": ok,
                "canonical_candidate_sha256": identity.get(
                    "canonical_candidate_sha256"
                ),
                "results": results,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
