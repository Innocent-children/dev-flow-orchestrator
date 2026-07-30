#!/usr/bin/env python3
"""Compute and validate the acyclic V4 provenance layers."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
import struct
import sys
import unicodedata
from pathlib import Path, PurePosixPath


L0_DOMAIN = b"dev-flow-v4-runtime-inventory/v1\x00"
L2_DOMAIN = b"dev-flow-canonical-v1\x00"
ENTRY_KIND = b"\x46"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
L0_ROOTS = (
    ".codex-plugin",
    "hooks",
    "scripts",
    "skills",
    "templates",
    "workflows",
)
L0_SINGLE_FILES = (".mcp.json", "AGENTS.md")
L0_EXCLUDED = {
    "scripts/__init__.py",
    "scripts/audit_runtime_imports.py",
    "scripts/candidate_identity.py",
    "scripts/run_bundled_validators.py",
    "scripts/validate_package.py",
    "workflows/provenance/l0-allowlist.json",
    "workflows/provenance/l2-allowlist.json",
    "workflows/provenance/v4-genesis.json",
}
L2_EXTRA_ROOTS = (".github", "tests")
L2_EXTRA_FILES = {
    ".gitattributes",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "pyproject.toml",
    "scripts/__init__.py",
    "scripts/audit_runtime_imports.py",
    "scripts/candidate_identity.py",
    "scripts/run_bundled_validators.py",
    "scripts/validate_package.py",
    "uv.lock",
    "workflows/provenance/l0-allowlist.json",
    "workflows/provenance/l2-allowlist.json",
    "workflows/provenance/v4-genesis.json",
}


class IdentityError(ValueError):
    pass


def _u64(value: int) -> bytes:
    return struct.pack(">Q", value)


def _validated_paths(root: Path, allowlist: Path, layer: str) -> list[str]:
    data = json.loads(allowlist.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema") != "dev-flow-v4-identity-allowlist/v1"
        or data.get("layer") != layer
        or not isinstance(data.get("files"), list)
    ):
        raise IdentityError(f"invalid {layer} allowlist")
    result: list[str] = []
    normalized: set[str] = set()
    for item in data["files"]:
        if not isinstance(item, str) or not item:
            raise IdentityError("allowlist paths must be non-empty strings")
        pure = PurePosixPath(item)
        parts = pure.parts
        if (
            pure.is_absolute()
            or "\\" in item
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
            or unicodedata.normalize("NFC", item) != item
        ):
            raise IdentityError(f"unsafe allowlist path: {item!r}")
        collision = unicodedata.normalize("NFC", item).casefold()
        if collision in normalized:
            raise IdentityError(f"duplicate or colliding path: {item}")
        normalized.add(collision)
        path = root / item
        if not path.is_file() or path.is_symlink():
            raise IdentityError(f"allowlisted entry is not a regular file: {item}")
        result.append(item)
    if result != sorted(result, key=lambda value: value.encode("utf-8")):
        raise IdentityError("allowlist files are not in UTF-8 byte order")
    return result


def _digest(root: Path, allowlist: Path, layer: str) -> tuple[str, list[str]]:
    domain = L0_DOMAIN if layer == "l0" else L2_DOMAIN
    paths = _validated_paths(root, allowlist, layer)
    preimage = bytearray(domain)
    preimage.extend(_u64(len(paths)))
    for relative in paths:
        path_bytes = relative.encode("utf-8")
        payload = (root / relative).read_bytes()
        preimage.extend(_u64(len(path_bytes)))
        preimage.extend(path_bytes)
        preimage.extend(ENTRY_KIND)
        preimage.extend(_u64(len(payload)))
        preimage.extend(payload)
    return hashlib.sha256(preimage).hexdigest(), paths


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files_under(root: Path, relative: str) -> set[str]:
    base = root / relative
    if not base.is_dir():
        raise IdentityError(f"candidate directory is missing: {relative}")
    result: set[str] = set()
    for path in base.rglob("*"):
        if path.is_symlink():
            raise IdentityError(
                f"candidate directory contains a symlink: "
                f"{path.relative_to(root).as_posix()}"
            )
        if path.is_file() and path.suffix != ".pyc":
            result.add(path.relative_to(root).as_posix())
    return result


def _expected_inventory(root: Path, layer: str) -> set[str]:
    l0 = set(L0_SINGLE_FILES)
    for relative in L0_ROOTS:
        l0.update(_files_under(root, relative))
    l0.difference_update(L0_EXCLUDED)
    if layer == "l0":
        return l0
    result = set(l0)
    result.update(L2_EXTRA_FILES)
    for relative in L2_EXTRA_ROOTS:
        result.update(_files_under(root, relative))
    return result


def _verify_allowlist_coverage(
    root: Path,
    paths: list[str],
    layer: str,
) -> None:
    expected = _expected_inventory(root, layer)
    observed = set(paths)
    if observed == expected:
        return
    missing = sorted(expected - observed, key=lambda value: value.encode("utf-8"))
    extra = sorted(observed - expected, key=lambda value: value.encode("utf-8"))
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unexpected " + ", ".join(extra))
    raise IdentityError(f"{layer} allowlist coverage mismatch: {'; '.join(details)}")


def _genesis(root: Path, l0_digest: str) -> dict[str, object]:
    if not SHA256.fullmatch(l0_digest):
        raise IdentityError("L0 digest must be lowercase SHA-256")
    namespace = runpy.run_path(str(root / "scripts/dev_flow.py"), run_name="v4_genesis")
    services = namespace["_WORKFLOW_RUNTIME_SERVICES"]
    bundles = sorted(
        services.catalog.bundles.values(),
        key=lambda bundle: (bundle.workflow_id, bundle.workflow_version),
    )
    contract_keys = {
        (reference.registry, reference.identifier, reference.version)
        for bundle in bundles
        for reference in bundle.contracts
    }
    handler_entries = []
    for manifest in services.handler_manifests:
        for entry in manifest.entries:
            key = (
                entry.registry_kind,
                entry.identifier,
                entry.contract_version,
            )
            if key in contract_keys:
                handler_entries.append(
                    {
                        "registry": entry.registry_kind,
                        "id": entry.identifier,
                        "version": entry.contract_version,
                        "contract_id": entry.contract_id,
                        "implementation_sha256": entry.implementation_sha256,
                        "implementation_files": [
                            declaration.path
                            for declaration in entry.implementation_files
                        ],
                    }
                )
    handler_entries.sort(
        key=lambda entry: (
            str(entry["registry"]).encode("utf-8"),
            str(entry["id"]).encode("utf-8"),
            str(entry["version"]).encode("utf-8"),
        )
    )
    workflows = [
        {
            "id": bundle.workflow_id,
            "version": bundle.workflow_version,
            "graph_sha256": bundle.graph_sha256,
            "bundle_sha256": bundle.bundle_sha256,
        }
        for bundle in bundles
    ]
    return {
        "schema": "dev-flow-v4-genesis/v1",
        "product": "dev-flow-orchestrator",
        "runtime_inventory_sha256": l0_digest,
        "plugin_manifest_sha256": _file_sha256(
            root / ".codex-plugin/plugin.json"
        ),
        "catalog_sha256": _file_sha256(root / "workflows/catalog.json"),
        "activation_sha256": _file_sha256(root / "workflows/activation.json"),
        "workflows": workflows,
        "handlers": handler_entries,
    }


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _vector() -> dict[str, object]:
    entries = [
        ("README.md", b"hello\n"),
        ("scripts/\u6d4b\u8bd5.py", b'print("ok")\n'),
    ]
    results: dict[str, str] = {}
    for layer, domain in (("l0", L0_DOMAIN), ("l2", L2_DOMAIN)):
        preimage = bytearray(domain)
        preimage.extend(_u64(len(entries)))
        for path, payload in entries:
            encoded = path.encode("utf-8")
            preimage.extend(_u64(len(encoded)))
            preimage.extend(encoded)
            preimage.extend(ENTRY_KIND)
            preimage.extend(_u64(len(payload)))
            preimage.extend(payload)
        results[layer] = hashlib.sha256(preimage).hexdigest()
    expected = {
        "l0": "4b647f3ea4ae12f214fffb3e87944eb0202dcfe29e812c560342e324d3d0849f",
        "l2": "a5f265def6c95a23cf668937f83a6d06320d2e784f064627a6847aed11974674",
    }
    return {
        "schema": "dev-flow-v4-identity-vector/v1",
        "ok": results == expected,
        "observed": results,
        "expected": expected,
    }


def _verify(root: Path, l0_allowlist: Path, l2_allowlist: Path, genesis: Path) -> dict[str, object]:
    l0_digest, l0_paths = _digest(root, l0_allowlist, "l0")
    _verify_allowlist_coverage(root, l0_paths, "l0")
    expected = _canonical_json(_genesis(root, l0_digest))
    actual = genesis.read_bytes()
    if actual != expected:
        raise IdentityError("V4 genesis does not match current L0/runtime closure")
    l2_digest, l2_paths = _digest(root, l2_allowlist, "l2")
    _verify_allowlist_coverage(root, l2_paths, "l2")
    encoded = l2_digest.encode("ascii")
    containing = [
        relative for relative in l2_paths if encoded in (root / relative).read_bytes()
    ]
    if containing:
        raise IdentityError(
            "L2 digest occurs inside candidate files: " + ", ".join(containing)
        )
    vector = _vector()
    if not vector["ok"]:
        raise IdentityError("canonical identity vector mismatch")
    return {
        "schema": "dev-flow-v4-identity-verification/v1",
        "ok": True,
        "runtime_inventory_sha256": l0_digest,
        "canonical_candidate_sha256": l2_digest,
        "l0_entry_count": len(l0_paths),
        "l2_entry_count": len(l2_paths),
        "genesis_sha256": hashlib.sha256(actual).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    vector_parser = subparsers.add_parser("vector")
    vector_parser.set_defaults(action="vector")

    digest_parser = subparsers.add_parser("digest")
    digest_parser.add_argument("--layer", choices=("l0", "l2"), required=True)
    digest_parser.add_argument("--allowlist", type=Path, required=True)
    digest_parser.set_defaults(action="digest")

    genesis_parser = subparsers.add_parser("genesis")
    genesis_parser.add_argument("--runtime-inventory-sha256", required=True)
    genesis_parser.add_argument(
        "--output",
        type=Path,
        help="write the canonical genesis bytes to this exact path",
    )
    genesis_parser.set_defaults(action="genesis")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--l0-allowlist", type=Path, required=True)
    verify_parser.add_argument("--l2-allowlist", type=Path, required=True)
    verify_parser.add_argument("--genesis", type=Path, required=True)
    verify_parser.set_defaults(action="verify")

    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.action == "vector":
            result = _vector()
        elif args.action == "digest":
            digest, paths = _digest(root, args.allowlist.resolve(), args.layer)
            result = {
                "schema": "dev-flow-v4-identity-digest/v1",
                "ok": True,
                "layer": args.layer,
                "sha256": digest,
                "entry_count": len(paths),
            }
        elif args.action == "genesis":
            payload = _canonical_json(
                _genesis(root, args.runtime_inventory_sha256)
            )
            if args.output is None:
                sys.stdout.buffer.write(payload)
                return 0
            output = args.output.resolve()
            output.write_bytes(payload)
            result = {
                "schema": "dev-flow-v4-genesis-write/v1",
                "ok": True,
                "path": str(output),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        else:
            result = _verify(
                root,
                args.l0_allowlist.resolve(),
                args.l2_allowlist.resolve(),
                args.genesis.resolve(),
            )
    except (IdentityError, OSError, ValueError, KeyError) as exc:
        result = {
            "schema": "dev-flow-v4-identity-error/v1",
            "ok": False,
            "error": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
