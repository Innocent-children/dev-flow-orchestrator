#!/usr/bin/env python3
"""Compute the acyclic identity of the greenfield V4 plugin candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator.product import (  # noqa: E402
    PRODUCT_IDENTITY,
    product_document,
)
from dev_flow_orchestrator.workflow import (  # noqa: E402
    FULL_GRAPH,
    LITE_GRAPH,
    PREFLIGHT_CONTRACT,
    REPOSITORY_CANCEL_CONTRACT,
    REPOSITORY_GRAPH,
    workflow_identity,
)


RUNTIME_FILES = (
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "hooks/dev_flow_hook.py",
    "hooks/hooks.json",
    "scripts/dev_flow.py",
    "scripts/dev_flow_mcp.py",
    "scripts/dev_flow_python_launcher",
)
RUNTIME_ROOTS = ("src/dev_flow_orchestrator", "skills", "templates")
DOCUMENT_FILES = (
    "ARCHITECTURE.md",
    "README.md",
    "README.zh-CN.md",
    "INSTALL.md",
    "CONTRIBUTING.md",
    "LICENSE",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _files(root: Path) -> tuple[str, ...]:
    result = set(RUNTIME_FILES)
    result.update(DOCUMENT_FILES)
    for relative in RUNTIME_ROOTS:
        base = root / relative
        for path in base.rglob("*"):
            if path.is_symlink():
                raise ValueError("candidate contains symlink: " + str(path))
            if path.is_file() and path.suffix != ".pyc":
                result.add(path.relative_to(root).as_posix())
    missing = [relative for relative in result if not (root / relative).is_file()]
    if missing:
        raise ValueError("candidate file is missing: " + ", ".join(sorted(missing)))
    return tuple(sorted(result, key=lambda item: item.encode("utf-8")))


def _framed_digest(domain: bytes, root: Path, paths: tuple[str, ...]) -> str:
    preimage = bytearray(domain)
    preimage.extend(struct.pack(">Q", len(paths)))
    for relative in paths:
        name = relative.encode("utf-8")
        payload = (root / relative).read_bytes()
        preimage.extend(struct.pack(">Q", len(name)))
        preimage.extend(name)
        preimage.extend(struct.pack(">Q", len(payload)))
        preimage.extend(payload)
    return hashlib.sha256(preimage).hexdigest()


def _graph_document() -> dict:
    return {
        "entry@4": PREFLIGHT_CONTRACT.as_dict(),
        "full@4": {
            node_id: contract.as_dict()
            for node_id, contract in sorted(FULL_GRAPH.items())
        },
        "lite@4": {
            node_id: contract.as_dict()
            for node_id, contract in sorted(LITE_GRAPH.items())
        },
        "repository-kernel@4": {
            node_id: contract.as_dict()
            for node_id, contract in sorted(REPOSITORY_GRAPH.items())
        },
        "repository-shared@4": {
            "repository.cancel": REPOSITORY_CANCEL_CONTRACT.as_dict(),
        },
        "activated-profile-identities": {
            "{}/{}".format(workflow_id, topology): workflow_identity(
                workflow_id,
                topology,
            )
            for workflow_id in ("full", "lite")
            for topology in ("single-repository", "multi-repository")
        },
    }


def identity(root: Path = ROOT) -> dict:
    candidate_paths = _files(root)
    document_set = set(DOCUMENT_FILES)
    runtime_paths = tuple(
        path for path in candidate_paths if path not in document_set
    )
    l0 = _framed_digest(
        b"dev-flow-greenfield-runtime-inventory/v1\x00",
        root,
        runtime_paths,
    )
    handlers = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in (
            "src/dev_flow_orchestrator/authority.py",
            "src/dev_flow_orchestrator/controller.py",
            "src/dev_flow_orchestrator/engine.py",
            "src/dev_flow_orchestrator/repository_kernel.py",
            "src/dev_flow_orchestrator/workflow.py",
        )
    }
    l1_document = {
        "schema": "dev-flow-v4-product-provenance/v1",
        "runtime_inventory_sha256": l0,
        "product_identity": PRODUCT_IDENTITY,
        "product": product_document(),
        "graphs": _graph_document(),
        "handler_sha256": handlers,
    }
    l1 = hashlib.sha256(
        b"dev-flow-greenfield-product-provenance/v1\x00"
        + _canonical(l1_document)
    ).hexdigest()
    l2_files = _framed_digest(
        b"dev-flow-greenfield-candidate-files/v1\x00",
        root,
        candidate_paths,
    )
    l2 = hashlib.sha256(
        b"dev-flow-greenfield-candidate/v1\x00"
        + _canonical(
            {
                "l1_product_provenance_sha256": l1,
                "candidate_files_sha256": l2_files,
            }
        )
    ).hexdigest()
    return {
        "schema": "dev-flow-v4-candidate-identity/v1",
        "l0_runtime_inventory_sha256": l0,
        "l1_product_provenance_sha256": l1,
        "l2_candidate_sha256": l2,
        "candidate_files_sha256": l2_files,
        "candidate_file_count": len(candidate_paths),
        "runtime_file_count": len(runtime_paths),
        "handler_sha256": handlers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args(argv)
    try:
        result = identity(arguments.root.resolve())
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1
    print(
        json.dumps(
            {"ok": True, "identity": result},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
