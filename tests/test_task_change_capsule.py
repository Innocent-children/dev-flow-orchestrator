"""Focused task-owned capsule, exact claims, and ambient-drift tests."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.capsule import (
    ambient_drift,
    derive_manifest,
    make_preflight_baseline,
    validate_ownership_claims,
)
from dev_flow_orchestrator.model import DevFlowError, RepositoryRecord
from dev_flow_orchestrator.product import TASK_CHANGE_CLAIMS_SCHEMA, WORKSPACE_SNAPSHOT_SCHEMA
from dev_flow_orchestrator.snapshot import make_repository_set_snapshot, snapshot_digest, validate_snapshot


REPOSITORY = RepositoryRecord("repo", "/tmp/capsule-repo", "/tmp/capsule-repo/.git", "/tmp/capsule-repo/.git")
REPOSITORIES = (REPOSITORY,)
CONTRACT = {"acceptance_criteria": [{"id": "criterion-1", "statement": "works"}]}
CONTRACT_DIGEST = "c" * 64


def entry(path: str, content: str, oid_char: str = "a") -> dict:
    raw = content.encode("utf-8")
    return {
        "path": path,
        "kind": "regular",
        "mode": "100644",
        "size": len(raw),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "index_entries": [{"mode": "100644", "oid": oid_char * 40, "stage": 0}],
        "submodule_head": None,
    }


def snapshot(entries, *, head="a" * 40, status=b""):
    ordered = sorted(copy.deepcopy(entries), key=lambda item: item["path"].encode("utf-8"))
    base = {
        "schema": WORKSPACE_SNAPSHOT_SCHEMA,
        "repository_root": REPOSITORY.path,
        "git_worktree_dir": REPOSITORY.git_worktree_dir,
        "git_common_dir": REPOSITORY.git_common_dir,
        "object_format": "sha1",
        "head": head,
        "branch": "main",
        "clean": not status,
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "status_bytes": len(status),
        "index_entry_count": sum(len(item["index_entries"]) for item in ordered),
        "index_output_bytes": 0,
        "has_unmerged_entries": False,
        "entries": ordered,
        "resources": [],
    }
    member = validate_snapshot({**base, "digest": snapshot_digest(base)})
    return make_repository_set_snapshot(REPOSITORIES, {"repo": member})


def claims(*paths):
    return {
        "schema": TASK_CHANGE_CLAIMS_SCHEMA,
        "claims": [{
            "repository_id": "repo",
            "path": path,
            "classification": "implementation",
            "criterion_ids": ["criterion-1"],
            "purpose": "Implement the accepted criterion",
        } for path in paths],
    }


def producer(revision):
    return {
        "action_id": "implementation.record",
        "task_revision": revision,
        "contract_revision": 1,
        "binding_digest": str(revision) * 64,
    }


class TaskChangeCapsuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = snapshot([entry("src/a.py", "old")])
        self.preflight = make_preflight_baseline(
            task_id="task-capsule",
            contract_digest=CONTRACT_DIGEST,
            snapshot=self.before,
            repositories=REPOSITORIES,
        )

    def test_claims_must_exactly_cover_observed_changes(self) -> None:
        changes = ({"repository_id": "repo", "path": "src/a.py"},)
        with self.assertRaises(DevFlowError) as context:
            validate_ownership_claims(claims(), changes=changes, contract=CONTRACT)
        self.assertEqual(context.exception.code, "OWNERSHIP_CLAIMS_INVALID")
        with self.assertRaises(DevFlowError):
            validate_ownership_claims(claims("src/a.py", "src/b.py"), changes=changes, contract=CONTRACT)

    def test_manifest_rolls_forward_and_net_reversion_drops_entry(self) -> None:
        after_one = snapshot([entry("src/a.py", "new", "b")], status=b" M src/a.py\0")
        first = derive_manifest(
            task_id="task-capsule",
            contract=CONTRACT,
            contract_digest=CONTRACT_DIGEST,
            repositories=REPOSITORIES,
            preflight=self.preflight,
            predecessor=None,
            before_snapshot=self.before,
            after_snapshot=after_one,
            claims=claims("src/a.py"),
            producer=producer(1),
        )
        self.assertEqual([(item["path"], item["original_before"]["worktree"]["content_sha256"]) for item in first["entries"]], [("src/a.py", entry("src/a.py", "old")["content_sha256"])])

        after_two = snapshot([entry("src/a.py", "new", "b"), entry("src/b.py", "added", "c")], status=b" M src/a.py\0?? src/b.py\0")
        second = derive_manifest(
            task_id="task-capsule",
            contract=CONTRACT,
            contract_digest=CONTRACT_DIGEST,
            repositories=REPOSITORIES,
            preflight=self.preflight,
            predecessor=first,
            before_snapshot=after_one,
            after_snapshot=after_two,
            claims=claims("src/b.py"),
            producer=producer(2),
        )
        self.assertEqual([item["path"] for item in second["entries"]], ["src/a.py", "src/b.py"])

        after_three = snapshot([entry("src/a.py", "old"), entry("src/b.py", "added", "c")], status=b"?? src/b.py\0")
        third = derive_manifest(
            task_id="task-capsule",
            contract=CONTRACT,
            contract_digest=CONTRACT_DIGEST,
            repositories=REPOSITORIES,
            preflight=self.preflight,
            predecessor=second,
            before_snapshot=after_two,
            after_snapshot=after_three,
            claims=claims("src/a.py"),
            producer=producer(3),
        )
        self.assertEqual([item["path"] for item in third["entries"]], ["src/b.py"])
        self.assertEqual(third["preflight_digest"], first["preflight_digest"])

    def test_ambient_drift_is_separate_from_accepted_source(self) -> None:
        drifted = snapshot([entry("src/a.py", "ambient", "d")], status=b" M src/a.py\0")
        report = ambient_drift(self.before, drifted, REPOSITORIES)
        self.assertTrue(report["present"])
        self.assertEqual([(item["repository_id"], item["path"]) for item in report["paths"]], [("repo", "src/a.py")])


if __name__ == "__main__":
    unittest.main()
