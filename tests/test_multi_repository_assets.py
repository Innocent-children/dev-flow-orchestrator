"""Focused package-asset checks for the current exact repository-set product."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator import workflows
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    MAX_REPOSITORY_COUNT,
    MIN_REPOSITORY_COUNT,
    MODEL_VERSION,
    RELEASE_VERSION,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    REPOSITORY_TOPOLOGY_CAPABILITIES,
    VERIFICATION_COVERAGE_SCHEMA,
    WORKFLOW_IDS,
    WORKFLOW_SCHEMA,
    product_schema,
)


WORKFLOW_FILE_SHA256 = {
    "bugfix": "ba43c9ba8f7c0e6b3a41a9a3652e0719336f4add2edd179f863c46ba6c4cfd07",
    "feature": "a6aa3392339a2ab7ca00856007505f788e32156b4421cd1cfa4ae3f3247978a3",
    "full": "2a7c2fc0b1b5b5f16fb1278d5a5ea54344af2ffd50602beade0f3c4a8f71247d",
    "investigation": "c5ac8836b8a4f3b12388e13ebe97fef48597be85953facb800401e6aa40929c9",
    "lite": "4e660f93efcb55ff4160b6785736ea60d4093b5e493a08a2c1b892589e2ee710",
    "refactor": "592a13b18bdef3c86e83e4673902dd0ed3225d2e65e2490bfeefdb7cec3e12e9",
}

WORKFLOW_IDENTITIES = {
    "bugfix": "6f59684625ede85360b140466a40826f9259baf354e48e2664b87e0200986ebb",
    "feature": "14e79f4415e207821c5a792ee20a5088574b332643bde80e9650aaa3615ed5a3",
    "full": "0aaea7aa7e6143937bd8483d4d624c7f958e969f7adad908361bb178758bab72",
    "investigation": "fcf4daca20ca8497c1cd4435de70eac51ae89ae8642597cecd1a2e6e7ff36a07",
    "lite": "8fa8964df433e36b99585f819e47d303476beb8ff1fc1d2957a44a2e67820a3d",
    "refactor": "0acbed9ef928f505cf5c598d863f533ead30053d8b184da86c19b318bee4a6a4",
}

CURRENT_MODEL_ASSETS = (
    ".codex-plugin/plugin.json",
    "README.md",
    "README_CN.md",
    "ARCHITECTURE.md",
    "INSTALL.md",
    "CONTRIBUTING.md",
    "ROADMAP.md",
    "ROADMAP_CN.md",
    "skills/follow-dev-flow/SKILL.md",
    "skills/follow-dev-flow/agents/openai.yaml",
    "skills/analyze-change-impact/SKILL.md",
    "skills/analyze-change-impact/agents/openai.yaml",
    "skills/review-dev-flow-change/SKILL.md",
    "skills/review-dev-flow-change/agents/openai.yaml",
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class RepositorySetPublicAssetTests(unittest.TestCase):
    def assert_contains_all(self, document: str, fragments: tuple[str, ...]) -> None:
        normalized_document = " ".join(document.split())
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(" ".join(fragment.split()), normalized_document)

    def test_topology_authority_and_manifest_describe_the_same_product(self) -> None:
        self.assertEqual((MIN_REPOSITORY_COUNT, MAX_REPOSITORY_COUNT), (1, 8))
        self.assertEqual(MODEL_VERSION, "0.4.0")
        self.assertEqual(WORKFLOW_SCHEMA, product_schema("workflow"))
        self.assertEqual(AGENT_PROTOCOL_SCHEMA, product_schema("agent"))
        self.assertEqual(
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
            product_schema("repository-set-snapshot"),
        )
        self.assertEqual(
            VERIFICATION_COVERAGE_SCHEMA,
            product_schema("verification-coverage"),
        )
        self.assertEqual(
            DELIVERY_DOSSIER_SCHEMA,
            product_schema("delivery-dossier"),
        )
        self.assertEqual(
            REPOSITORY_TOPOLOGY_CAPABILITIES["minimum_repositories"],
            MIN_REPOSITORY_COUNT,
        )
        self.assertEqual(
            REPOSITORY_TOPOLOGY_CAPABILITIES["maximum_repositories"],
            MAX_REPOSITORY_COUNT,
        )
        self.assertEqual(
            REPOSITORY_TOPOLOGY_CAPABILITIES["membership"],
            "exact-canonical-set",
        )
        self.assertEqual(
            REPOSITORY_TOPOLOGY_CAPABILITIES["execution"],
            "single-codex-single-current-action",
        )
        self.assertFalse(REPOSITORY_TOPOLOGY_CAPABILITIES["managed_git_effects"])
        self.assertTrue(
            REPOSITORY_TOPOLOGY_CAPABILITIES["partial_assurance_reuse"]
        )
        self.assertFalse(
            REPOSITORY_TOPOLOGY_CAPABILITIES["external_delivery_effects"]
        )

        manifest = json.loads(_read(".codex-plugin/plugin.json"))
        public_text = " ".join(
            (
                manifest["description"],
                manifest["interface"]["shortDescription"],
                manifest["interface"]["longDescription"],
                *manifest["interface"]["defaultPrompt"],
            )
        )
        self.assert_contains_all(
            public_text,
            (
                "exact set of one to eight",
                "user-prepared",
                "one current action",
                "one Codex",
                WORKFLOW_SCHEMA,
                AGENT_PROTOCOL_SCHEMA,
                "index-exact repository-set snapshots",
                "adaptive assurance obligations",
                "causal review",
                DELIVERY_DOSSIER_SCHEMA,
                "never manages worktrees or branches",
                "parallel agents",
                "external CI, PR, or release automation",
            ),
        )

    def test_english_and_chinese_readmes_cover_the_exact_set_journey(self) -> None:
        english = _read("README.md")
        chinese = _read("README_CN.md")
        self.assertGreaterEqual(english.count("--repo"), 3)
        self.assertGreaterEqual(chinese.count("--repo"), 3)
        self.assert_contains_all(
            english,
            (
                "one to eight",
                "one immutable repository set",
                "one current action",
                "one Codex executor",
                "user-prepared repository roots",
                WORKFLOW_SCHEMA,
                AGENT_PROTOCOL_SCHEMA,
                REPOSITORY_SET_SNAPSHOT_SCHEMA,
                VERIFICATION_COVERAGE_SCHEMA,
                DELIVERY_DOSSIER_SCHEMA,
                "repository_id",
                "criteria",
                "repositories",
                "integration",
                "cancel.stages",
                "exclude every `delivery.finalize` stage",
                "restore that exact root",
            ),
        )
        self.assert_contains_all(
            chinese,
            (
                "一至八个",
                "一个不可变仓库集合",
                "一个当前动作",
                "一个 Codex",
                "用户提前准备",
                WORKFLOW_SCHEMA,
                AGENT_PROTOCOL_SCHEMA,
                REPOSITORY_SET_SNAPSHOT_SCHEMA,
                VERIFICATION_COVERAGE_SCHEMA,
                DELIVERY_DOSSIER_SCHEMA,
                "repository_id",
                "criteria",
                "repositories",
                "integration",
                "cancel.stages",
                "排除所有 `delivery.finalize` 阶段",
                "恢复同一精确根目录",
            ),
        )

    def test_public_manual_install_clones_pin_authoritative_main(self) -> None:
        repository_urls = (
            "git@github.com:Innocent-children/dev-flow-orchestrator.git",
            "https://github.com/Innocent-children/dev-flow-orchestrator.git",
        )
        for relative_path in ("README.md", "README_CN.md", "INSTALL.md"):
            document = _read(relative_path)
            shell_blocks = re.findall(r"```sh\n(.*?)```", document, re.DOTALL)
            clone_commands: list[str] = []
            for block in shell_blocks:
                continued_block = re.sub(r"\\\n\s*", " ", block)
                clone_commands.extend(
                    line.strip()
                    for line in continued_block.splitlines()
                    if line.strip().startswith("git clone ")
                    and any(url in line for url in repository_urls)
                )

            self.assertTrue(clone_commands, relative_path)
            for command in clone_commands:
                with self.subTest(relative_path=relative_path, command=command):
                    self.assertIn("--branch main", command)
                    self.assertIn("--single-branch", command)

    def test_packaged_skills_cover_member_scope_and_aggregate_assurance(self) -> None:
        follow = _read("skills/follow-dev-flow/SKILL.md")
        impact = _read("skills/analyze-change-impact/SKILL.md")
        review = _read("skills/review-dev-flow-change/SKILL.md")
        self.assertGreaterEqual(follow.count("--repo"), 3)
        self.assert_contains_all(
            follow,
            (
                "exact set of one to eight user-prepared",
                "one current action",
                "one Codex",
                WORKFLOW_SCHEMA,
                AGENT_PROTOCOL_SCHEMA,
                "repository_id",
                '"assurance_result"',
                '"obligation_id"',
                '"evidence"',
                "slice-aware",
                DELIVERY_DOSSIER_SCHEMA,
                "cancel.stages",
                "Delivery finalizers never expose cancellation",
            ),
        )
        self.assert_contains_all(
            impact,
            (
                "immutable declared members",
                "For every `repository_id`",
                "Never reuse one project ID across generations or repository members",
                "cross-repository",
                "details.repositories",
                "same envelope when the exact set has one member",
                "silently omitted",
            ),
        )
        self.assert_contains_all(
            review,
            (
                "complete canonical member inventory",
                "aggregate `workspace_snapshot_digest`",
                "Never share a graph project across members",
                "structured causal findings",
                "unchanged when the exact set has one member",
                "pre-existing",
                "out-of-scope",
            ),
        )

    def test_skill_agent_metadata_invokes_each_skill_and_retains_dependencies(self) -> None:
        for skill_name in (
            "follow-dev-flow",
            "analyze-change-impact",
            "review-dev-flow-change",
        ):
            with self.subTest(skill=skill_name):
                document = _read("skills/{}/agents/openai.yaml".format(skill_name))
                self.assertIn("${}".format(skill_name), document)
                self.assertIn('value: "codebase-memory-mcp"', document)
                self.assertIn("allow_implicit_invocation:", document)
                match = re.search(
                    r'^  short_description: "([^"]+)"$',
                    document,
                    flags=re.MULTILINE,
                )
                self.assertIsNotNone(match)
                description = match.group(1)
                self.assertGreaterEqual(len(description), 25)
                self.assertLessEqual(len(description), 64)

    def test_public_assets_contain_only_the_current_product_model(self) -> None:
        forbidden_fragments = (
            "adapter_identity",
            "rollback",
            "singleton",
        )
        forbidden_version_patterns = (
            re.compile(r"dev-flow-[a-z0-9_-]+(?:-v|/v)[0-9]+"),
            re.compile(r"\bv[1-9][0-9]*\b"),
        )
        for relative in CURRENT_MODEL_ASSETS:
            document = _read(relative).lower()
            for fragment in forbidden_fragments:
                with self.subTest(relative=relative, fragment=fragment):
                    self.assertNotIn(fragment, document)
            for pattern in forbidden_version_patterns:
                with self.subTest(relative=relative, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(document))

    def test_manifest_project_and_lock_versions_match(self) -> None:
        manifest_version = json.loads(
            _read(".codex-plugin/plugin.json")
        )["version"]
        self.assertEqual(manifest_version, RELEASE_VERSION)
        for relative in ("pyproject.toml", "uv.lock"):
            with self.subTest(relative=relative):
                path = ROOT / relative
                if not path.is_file():
                    continue
                version_match = re.search(
                    r'(?m)^version = "([^"]+)"$',
                    path.read_text(encoding="utf-8"),
                )
                self.assertIsNotNone(version_match)
                self.assertEqual(version_match.group(1), manifest_version)

    def test_official_workflow_files_identities_and_cancellation_are_pinned(
        self,
    ) -> None:
        self.assertEqual(tuple(sorted(WORKFLOW_FILE_SHA256)), WORKFLOW_IDS)
        self.assertEqual(tuple(sorted(WORKFLOW_IDENTITIES)), WORKFLOW_IDS)
        for workflow_id in WORKFLOW_IDS:
            with self.subTest(workflow=workflow_id):
                raw = (ROOT / "workflows" / "{}.yaml".format(workflow_id)).read_bytes()
                self.assertEqual(
                    hashlib.sha256(raw).hexdigest(),
                    WORKFLOW_FILE_SHA256[workflow_id],
                )
                self.assertEqual(
                    workflows.load_definition(workflow_id).identity,
                    WORKFLOW_IDENTITIES[workflow_id],
                )
                definition = workflows.load_definition(workflow_id)
                self.assertEqual(definition.schema, WORKFLOW_SCHEMA)
                normal_nonterminal = tuple(
                    node_id
                    for node_id, node in definition.nodes.items()
                    if node_id not in definition.terminal_nodes
                    and node.finalize_outcome is None
                )
                self.assertGreater(
                    len(definition.cancel_stages),
                    len(normal_nonterminal) / 2,
                )
                self.assertTrue(
                    set(definition.cancel_stages).issubset(normal_nonterminal)
                )
                self.assertEqual(
                    tuple(definition.document["cancel"]["stages"]),
                    definition.cancel_stages,
                )
                for node_id in definition.cancel_stages:
                    self.assertEqual(
                        definition.cancel_for(node_id).action_id,
                        "task.cancel",
                    )
                for node_id, node in definition.nodes.items():
                    if node.finalize_outcome is not None:
                        self.assertIsNone(definition.cancel_for(node_id))


if __name__ == "__main__":
    unittest.main()
