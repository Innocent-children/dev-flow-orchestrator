from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts import runtime_integrity


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "legacy_migration", ROOT / "scripts" / "legacy_migration.py"
)
assert SPEC is not None and SPEC.loader is not None
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)


class LegacyMigrationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, object]:
        runtime = root / "runtime"
        release = runtime / "releases" / "r-0.5.0-known"
        plugin = release / "plugin"
        plugin.mkdir(parents=True)
        ownership = {
            "schema": "dev-flow-runtime-ownership/1.0.0",
            "release_id": release.name,
            "entries": [
                {
                    "path": ".",
                    "type": "directory",
                    "mode": 0o755,
                    "release_id": release.name,
                }
            ],
        }
        ownership_path = release / "ownership-manifest.json"
        ownership_path.write_text(json.dumps(ownership), encoding="utf-8")
        receipt = {
            "schema": "dev-flow-runtime-receipt/2.0.0",
            "release_id": release.name,
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "wheel_sha256": "3" * 64,
            "runtime_path": str(release),
            "plugin_path": str(plugin),
            "plugin_release_manifest_sha256": "4" * 64,
            "dev_flow": {
                "name": "dev-flow-orchestrator",
                "version": "0.5.0",
                "metadata_sha256": "5" * 64,
                "record_sha256": "6" * 64,
                "files": [],
            },
            "dependencies": [],
            "python": {
                "path": str(
                    release
                    / "venv"
                    / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                ),
                "executable_sha256": "7" * 64,
                "version": "3.14.0",
                "architecture": "arm64",
                "bits": 64,
            },
            "launcher_sha256": "8" * 64,
            "cli_launcher_sha256": "9" * 64,
            "ownership_manifest_sha256": hashlib.sha256(ownership_path.read_bytes()).hexdigest(),
            "dependency_lock_sha256": "a" * 64,
            "created_at": "2026-08-12T00:00:00Z",
        }
        (release / "runtime-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        transactions = runtime / "transactions"
        transactions.mkdir()
        (transactions / "tx-known.json").write_text(
            json.dumps(
                {
                    "schema": "dev-flow-install-transaction/0.4.0",
                    "transaction_id": "tx-known",
                    "operation": "install",
                    "previous_release": None,
                    "candidate_release": release.name,
                    "current_step": "committed",
                    "components": {
                        "plugin": "candidate",
                        "marketplace": "candidate",
                        "mcp_launcher": "candidate",
                        "cli_launcher": "candidate",
                        "runtime": "candidate-active",
                    },
                    "outcome": "committed",
                    "blind_retry_safe": True,
                    "retained_paths": [str(release)],
                }
            ),
            encoding="utf-8",
        )
        marketplace = root / ".agents" / "plugins" / "marketplace.json"
        marketplace.parent.mkdir(parents=True)
        relative = plugin.relative_to(root)
        marketplace.write_text(
            json.dumps(
                {
                    "name": "personal",
                    "interface": {"displayName": "Personal"},
                    "plugins": [
                        {
                            "name": "dev-flow-orchestrator",
                            "source": {"source": "local", "path": "./" + relative.as_posix()},
                            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                            "category": "Productivity",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "dev-flow").write_text(
            "# dev-flow-orchestrator managed launcher\n" + str(release), encoding="utf-8"
        )
        (bin_dir / "dev-flow-mcp").write_text(
            "# dev-flow-orchestrator managed MCP launcher\n" + str(release), encoding="utf-8"
        )
        return {
            "runtime_root": runtime,
            "bin_dir": bin_dir,
            "marketplace_file": marketplace,
            "plugin_observation": {
                "plugin_id": "dev-flow-orchestrator@personal",
                "installed": True,
                "enabled": True,
                "version": "0.5.0",
            },
            "windows": False,
        }

    def test_known_predecessor_is_proven_without_checkout_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "legacy checkout"
            checkout.mkdir()
            sentinel = checkout / "user.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            result = legacy.classify_predecessor(**self._fixture(root))
            self.assertEqual(result["version"], "0.5.0")
            self.assertFalse(result["legacy_checkout_owned"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_ambiguous_transaction_stops_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self._fixture(root)
            transactions = Path(inputs["runtime_root"]) / "transactions"
            (transactions / "tx-copy.json").write_bytes(
                (transactions / "tx-known.json").read_bytes()
            )
            before = (Path(inputs["marketplace_file"])).read_bytes()
            with self.assertRaisesRegex(legacy.MigrationClassificationError, "ambiguous"):
                legacy.classify_predecessor(**inputs)
            self.assertEqual(Path(inputs["marketplace_file"]).read_bytes(), before)

    def test_future_receipt_and_linked_plugin_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self._fixture(root)
            receipt = next(Path(inputs["runtime_root"]).glob("releases/*/runtime-receipt.json"))
            value = json.loads(receipt.read_text(encoding="utf-8"))
            value["schema"] = "dev-flow-runtime-receipt/99.0.0"
            receipt.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(legacy.MigrationClassificationError, "frozen"):
                legacy.classify_predecessor(**inputs)

    def test_receipt_ownership_and_transaction_are_closed_frozen_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self._fixture(root)
            receipt = next(Path(inputs["runtime_root"]).glob("releases/*/runtime-receipt.json"))
            value = json.loads(receipt.read_text(encoding="utf-8"))
            value["future"] = True
            receipt.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(legacy.MigrationClassificationError, "closed frozen"):
                legacy.classify_predecessor(**inputs)

            inputs = self._fixture(root / "second")
            transaction = next((Path(inputs["runtime_root"]) / "transactions").glob("*.json"))
            value = json.loads(transaction.read_text(encoding="utf-8"))
            value["future"] = True
            transaction.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(legacy.MigrationClassificationError, "absent or ambiguous"):
                legacy.classify_predecessor(**inputs)


if __name__ == "__main__":
    unittest.main()
