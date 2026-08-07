"""Focused current exact repository-set domain contracts."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
from types import MappingProxyType
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator import workflows
from dev_flow_orchestrator.delivery import minimal_contract
from dev_flow_orchestrator.model import (
    DevFlowError,
    RepositoryRecord,
    TaskState,
    canonical_json_bytes,
    canonical_repositories,
    initial_state,
    repository_by_id,
    repository_set_id,
    validate_repositories,
)
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    MAX_REPOSITORY_COUNT,
    MIN_REPOSITORY_COUNT,
    PRODUCT_IDENTITY,
    MODEL_VERSION,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    REPOSITORY_TOPOLOGY_CAPABILITIES,
    WORKSPACE_SNAPSHOT_SCHEMA,
    product_domain,
    product_document,
)
from dev_flow_orchestrator.snapshot import (
    iter_repository_snapshots,
    make_repository_set_snapshot,
    repository_set_snapshot_digest,
    repository_snapshot,
    snapshot_digest,
    validate_repository_set_snapshot,
    validate_snapshot,
    validate_task_snapshot,
)


def _workspace_snapshot(root: str, common_dir: str, head_char: str) -> dict:
    base = {
        "schema": WORKSPACE_SNAPSHOT_SCHEMA,
        "repository_root": root,
        "git_worktree_dir": common_dir,
        "git_common_dir": common_dir,
        "object_format": "sha1",
        "head": head_char * 40,
        "branch": "main",
        "clean": True,
        "status_sha256": hashlib.sha256(b"").hexdigest(),
        "status_bytes": 0,
        "index_entry_count": 0,
        "index_output_bytes": 0,
        "has_unmerged_entries": False,
        "entries": [],
        "resources": [],
    }
    return validate_snapshot({**base, "digest": snapshot_digest(base)})


class RepositoryTopologyProductTests(unittest.TestCase):
    def test_topology_and_current_schemas_define_product_identity(self) -> None:
        self.assertEqual(MIN_REPOSITORY_COUNT, 1)
        self.assertEqual(MAX_REPOSITORY_COUNT, 8)
        self.assertEqual(MODEL_VERSION, "0.4.0")
        self.assertEqual(AGENT_PROTOCOL_SCHEMA, "dev-flow-agent/0.4.0")
        self.assertEqual(REPOSITORY_SET_SNAPSHOT_SCHEMA, "dev-flow-repository-set-snapshot/0.4.0")
        self.assertIsInstance(REPOSITORY_TOPOLOGY_CAPABILITIES, MappingProxyType)
        with self.assertRaises(TypeError):
            REPOSITORY_TOPOLOGY_CAPABILITIES["maximum_repositories"] = 9
        document = product_document()
        self.assertEqual(document["version"], MODEL_VERSION)
        self.assertEqual(
            document["repository_topology"],
            dict(REPOSITORY_TOPOLOGY_CAPABILITIES),
        )
        self.assertEqual(document["schemas"]["agent_projection"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(
            document["schemas"]["repository_set_snapshot"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(
            PRODUCT_IDENTITY,
            hashlib.sha256(
                product_domain("product-identity") + canonical_json_bytes(document)
            ).hexdigest(),
        )


class RepositoryMembershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.first = RepositoryRecord("alpha", "/tmp/dev-flow-core-alpha", "/tmp/dev-flow-core-alpha/.git", "/tmp/dev-flow-core-alpha/.git")
        self.second = RepositoryRecord("beta", "/tmp/dev-flow-core-beta", "/tmp/dev-flow-core-beta/.git", "/tmp/dev-flow-core-beta/.git")

    def test_members_are_unique_bounded_and_canonically_ordered(self) -> None:
        canonical = canonical_repositories((self.second, self.first))
        self.assertEqual(canonical, (self.first, self.second))
        self.assertEqual(validate_repositories(canonical), canonical)

        for invalid in (
            (),
            (self.first, RepositoryRecord("alpha", "/tmp/dev-flow-core-other", "/tmp/dev-flow-core-other/.git", "/tmp/dev-flow-core-other/.git")),
            (self.first, RepositoryRecord("other", self.first.path, "/tmp/dev-flow-other/.git", "/tmp/dev-flow-other/.git")),
            tuple(
                RepositoryRecord("repo-{}".format(index), "/tmp/repo-{}".format(index), "/tmp/repo-{}/.git".format(index), "/tmp/repo-{}/.git".format(index))
                for index in range(MAX_REPOSITORY_COUNT + 1)
            ),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(DevFlowError) as context:
                    canonical_repositories(invalid)
                self.assertEqual(context.exception.code, "STATE_INVALID")

        with self.assertRaises(DevFlowError):
            validate_repositories((self.second, self.first))

    def test_repository_records_require_safe_ids_and_canonical_paths(self) -> None:
        self.assertEqual(
            RepositoryRecord(".hidden-repository", "/tmp/repository", "/tmp/repository/.git", "/tmp/repository/.git").repository_id,
            ".hidden-repository",
        )
        for repository_id, path in (
            ("", "/tmp/repository"),
            ("bad\x00identity", "/tmp/repository"),
            ("repo", "relative/path"),
            ("repo", "/tmp/parent/../repository"),
            ("repo", "/tmp/repository\x00suffix"),
        ):
            with self.subTest(repository_id=repository_id, path=path):
                with self.assertRaises(DevFlowError) as context:
                    RepositoryRecord(repository_id, path, "/tmp/repository/.git", "/tmp/repository/.git")
                self.assertEqual(context.exception.code, "STATE_INVALID")

    def test_set_identity_uses_the_ordered_id_path_records(self) -> None:
        members = canonical_repositories((self.second, self.first))
        expected = hashlib.sha256(
            product_domain("repository-set-identity")
            + canonical_json_bytes([member.as_dict() for member in members])
        ).hexdigest()
        self.assertEqual(repository_set_id(members), expected)
        self.assertEqual(
            repository_set_id(canonical_repositories((self.first, self.second))),
            expected,
        )
        self.assertEqual(repository_by_id(members, "beta"), self.second)
        with self.assertRaises(DevFlowError) as context:
            repository_by_id(members, "missing")
        self.assertEqual(context.exception.code, "REPOSITORY_UNKNOWN")

    def test_task_state_persists_only_the_canonical_membership_tuple(self) -> None:
        definition = workflows.load_definition("lite")
        state = initial_state(
            task_id="task-multi-core",
            requirement="Deliver API and client together",
            contract=minimal_contract("Deliver API and client together"),
            definition=definition,
            repositories=(self.second, self.first),
            timestamp="2026-08-03T00:00:00Z",
        )
        self.assertEqual(state.repositories, (self.first, self.second))
        self.assertEqual(state.repository_set_id, repository_set_id(state.repositories))
        persisted = state.as_dict()
        self.assertNotIn("repository_set_id", persisted)
        self.assertEqual(
            TaskState.from_dict(persisted, definition=definition),
            state,
        )

        reordered = copy.deepcopy(persisted)
        reordered["repositories"].reverse()
        with self.assertRaises(DevFlowError) as context:
            TaskState.from_dict(reordered, definition=definition)
        self.assertEqual(context.exception.code, "STATE_INVALID")


class RepositorySetSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repositories = canonical_repositories(
            (
                RepositoryRecord("beta", "/tmp/dev-flow-core-beta", "/tmp/dev-flow-core-beta/.git", "/tmp/dev-flow-core-beta/.git"),
                RepositoryRecord("alpha", "/tmp/dev-flow-core-alpha", "/tmp/dev-flow-core-alpha/.git", "/tmp/dev-flow-core-alpha/.git"),
            )
        )
        self.snapshots = {
            "alpha": _workspace_snapshot(
                "/tmp/dev-flow-core-alpha",
                "/tmp/dev-flow-core-alpha/.git",
                "a",
            ),
            "beta": _workspace_snapshot(
                "/tmp/dev-flow-core-beta",
                "/tmp/dev-flow-core-beta/.git",
                "b",
            ),
        }

    def test_wrapper_seals_complete_membership_and_supports_member_lookup(self) -> None:
        wrapper = make_repository_set_snapshot(self.repositories, self.snapshots)
        self.assertEqual(wrapper["schema"], REPOSITORY_SET_SNAPSHOT_SCHEMA)
        self.assertEqual(
            wrapper["repository_set_id"],
            repository_set_id(self.repositories),
        )
        self.assertEqual(
            [item["repository_id"] for item in wrapper["repositories"]],
            [item.repository_id for item in self.repositories],
        )
        self.assertEqual(
            validate_repository_set_snapshot(wrapper, self.repositories),
            wrapper,
        )
        self.assertEqual(validate_task_snapshot(wrapper, self.repositories), wrapper)
        self.assertEqual(
            tuple(item.repository_id for item, _ in iter_repository_snapshots(
                wrapper, self.repositories
            )),
            ("alpha", "beta"),
        )
        self.assertEqual(
            repository_snapshot(wrapper, self.repositories, "beta"),
            self.snapshots["beta"],
        )
        changed = dict(self.snapshots)
        changed["beta"] = _workspace_snapshot(
            "/tmp/dev-flow-core-beta",
            "/tmp/dev-flow-core-beta/.git",
            "c",
        )
        self.assertNotEqual(
            make_repository_set_snapshot(self.repositories, changed)["digest"],
            wrapper["digest"],
        )

    def test_wrapper_rejects_missing_reordered_wrong_root_and_tampered_members(self) -> None:
        with self.assertRaises(DevFlowError):
            make_repository_set_snapshot(
                self.repositories,
                {"alpha": self.snapshots["alpha"]},
            )

        wrapper = make_repository_set_snapshot(self.repositories, self.snapshots)
        reordered = copy.deepcopy(wrapper)
        reordered["repositories"].reverse()
        reordered_base = {key: value for key, value in reordered.items() if key != "digest"}
        reordered["digest"] = repository_set_snapshot_digest(reordered_base)
        with self.assertRaises(DevFlowError):
            validate_repository_set_snapshot(reordered, self.repositories)

        wrong_root = copy.deepcopy(wrapper)
        wrong_root["repositories"][0]["snapshot"] = _workspace_snapshot(
            "/tmp/dev-flow-core-wrong",
            "/tmp/dev-flow-core-wrong/.git",
            "c",
        )
        wrong_root_base = {
            key: value for key, value in wrong_root.items() if key != "digest"
        }
        wrong_root["digest"] = repository_set_snapshot_digest(wrong_root_base)
        with self.assertRaises(DevFlowError):
            validate_repository_set_snapshot(wrong_root, self.repositories)

        tampered = copy.deepcopy(wrapper)
        tampered["repositories"][1]["snapshot"]["branch"] = "tampered"
        with self.assertRaises(DevFlowError):
            validate_repository_set_snapshot(tampered, self.repositories)

    def test_members_must_have_distinct_git_common_directories(self) -> None:
        duplicate_common_dir = dict(self.snapshots)
        duplicate_common_dir["beta"] = _workspace_snapshot(
            "/tmp/dev-flow-core-beta",
            "/tmp/dev-flow-core-alpha/.git",
            "b",
        )
        with self.assertRaises(DevFlowError) as context:
            make_repository_set_snapshot(self.repositories, duplicate_common_dir)
        self.assertEqual(context.exception.code, "SNAPSHOT_INVALID")

    def test_one_member_uses_the_repository_set_snapshot_model(self) -> None:
        one_member = (self.repositories[0],)
        workspace = self.snapshots["alpha"]
        wrapper = make_repository_set_snapshot(one_member, {"alpha": workspace})
        self.assertEqual(wrapper["schema"], REPOSITORY_SET_SNAPSHOT_SCHEMA)
        self.assertEqual(wrapper["repository_set_id"], repository_set_id(one_member))
        self.assertEqual(
            wrapper["repositories"],
            [{"repository_id": "alpha", "snapshot": workspace}],
        )
        self.assertEqual(validate_task_snapshot(wrapper, one_member), wrapper)
        self.assertEqual(
            repository_snapshot(wrapper, one_member, "alpha"),
            workspace,
        )
        self.assertEqual(
            iter_repository_snapshots(wrapper, one_member),
            ((one_member[0], workspace),),
        )
        with self.assertRaises(DevFlowError):
            validate_task_snapshot(workspace, one_member)

        multi_wrapper = make_repository_set_snapshot(
            self.repositories,
            self.snapshots,
        )
        with self.assertRaises(DevFlowError):
            validate_task_snapshot(multi_wrapper, one_member)
        with self.assertRaises(DevFlowError) as context:
            repository_snapshot(multi_wrapper, self.repositories, "unknown")
        self.assertEqual(context.exception.code, "REPOSITORY_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
