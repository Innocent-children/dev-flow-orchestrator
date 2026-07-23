from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_flow.py"
SPEC = importlib.util.spec_from_file_location("dev_flow", SCRIPT)
assert SPEC and SPEC.loader
dev_flow = importlib.util.module_from_spec(SPEC)
sys.modules["dev_flow"] = dev_flow
SPEC.loader.exec_module(dev_flow)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


class DevFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "state"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_repo(self, name: str) -> tuple[Path, Path]:
        repo = self.root / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        git(repo, "config", "user.name", "Dev Flow Test")
        git(repo, "config", "user.email", "dev-flow@example.invalid")
        (repo / "tracked.txt").write_text(f"initial {name}\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-q", "-m", "initial")
        remote = self.root / f"{name}.git"
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(repo), str(remote)], check=True
        )
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "fetch", "-q", "origin")
        git(repo, "remote", "set-head", "origin", "main")
        return repo, remote

    def cli(self, *arguments: str, expected_code: int = 0) -> dict:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = dev_flow.main([*arguments, "--data-dir", str(self.data)])
        self.assertEqual(code, expected_code, stdout.getvalue())
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1, stdout.getvalue())
        return json.loads(lines[0])

    def canonical(self, *paths: Path) -> list[str]:
        """Scope directories are stored resolved; temp roots may be symlinked."""

        return sorted(str(path.resolve()) for path in paths)

    def start(self, *repos: Path, task_id: str = "task-1") -> dict:
        arguments = [
            "start",
            "--task-id",
            task_id,
            "--requirement",
            "Implement deterministic flow",
        ]
        for repo in repos:
            arguments.extend(["--repo", str(repo)])
        return self.cli(*arguments)

    def mutate(
        self, command: str, task: dict, *arguments: str, expected_code: int = 0
    ) -> dict:
        return self.cli(
            command,
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            *arguments,
            expected_code=expected_code,
        )

    def ready_workspace_task(
        self, *repos: Path, task_id: str = "workspace-task"
    ) -> dict:
        task = self.start(*repos, task_id=task_id)["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "local baseline and analysis worktree approved",
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task_id, self.data)
        for repository in task["repositories"]:
            self.mutate(
                "record-index",
                task,
                "--repo",
                repository["id"],
                "--index-id",
                dev_flow._recommended_index_name(
                    task, repository, "baseline"
                ),
            )
            task = dev_flow.load_state(task_id, self.data)
        impact = self.root / f"{task_id}-impact.md"
        impact.write_text("current impact\n", encoding="utf-8")
        impact_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "impact",
            "--path",
            str(impact),
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "set-route",
            task,
            "direct",
            "--reason",
            "bounded test change",
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "impact and direct route approved",
            "--artifact-sha256",
            impact_response["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task_id, self.data)
        workspace_plan = self.mutate("prepare-workspace", task)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "workspace plan approved",
            "--artifact-sha256",
            workspace_plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate("prepare-workspace", task, "--execute")
        return dev_flow.load_state(task_id, self.data)

    def record_workspace_indexes(
        self,
        task: dict,
        *,
        receipt: Path | None = None,
        metadata: dict | None = None,
    ) -> dict:
        for repository in task["repositories"]:
            arguments = [
                "--role",
                "workspace",
                "--repo",
                repository["id"],
                "--index-id",
                dev_flow._recommended_index_name(
                    task, repository, "workspace"
                ),
                "--metadata-json",
                json.dumps(
                    {"persistence": False}
                    if metadata is None
                    else metadata
                ),
            ]
            if receipt is not None:
                arguments.extend(["--receipt", str(receipt)])
            self.mutate("record-index", task, *arguments)
            task = dev_flow.load_state(task["task_id"], self.data)
        return task

    def route_indexed_task_to_workspace(self, task: dict) -> dict:
        self.assertEqual(task["status"], "INDEXED")
        impact = self.root / (
            f"{task['task_id']}-history-impact-"
            f"r{task.get('impact_generation', 0)}.md"
        )
        impact.write_text("history-aware impact\n", encoding="utf-8")
        impact_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "impact",
            "--path",
            str(impact),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "set-route",
            task,
            "direct",
            "--reason",
            "bounded history test",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "history-aware impact approved",
            "--artifact-sha256",
            impact_response["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        plan = self.mutate("prepare-workspace", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "history test workspace approved",
            "--artifact-sha256",
            plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("prepare-workspace", task, "--execute")
        return dev_flow.load_state(task["task_id"], self.data)

    def test_data_dir_precedence_and_helper_lookup(self) -> None:
        explicit = self.root / "explicit"
        with mock.patch.dict(
            os.environ,
            {"DEV_FLOW_DATA_DIR": str(self.root / "env"), "PLUGIN_DATA": str(self.root / "plugin")},
        ):
            self.assertEqual(dev_flow.resolve_data_dir(explicit), explicit.resolve())
            self.assertEqual(dev_flow.resolve_data_dir(), (self.root / "env").resolve())
        with mock.patch.dict(
            os.environ,
            {"PLUGIN_DATA": str(self.root / "plugin")},
            clear=True,
        ):
            self.assertEqual(dev_flow.resolve_data_dir(), (self.root / "plugin").resolve())

        repo, _ = self.make_repo("one")
        response = self.start(repo)
        task = response["task"]
        found = dev_flow.find_active_task_for_cwd(repo, self.data)
        self.assertIsNotNone(found)
        self.assertEqual(found["task_id"], task["task_id"])
        loaded = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(loaded["revision"], 1)

    def test_start_multi_repo_atomic_state_events_and_revision_conflict(self) -> None:
        first, _ = self.make_repo("first")
        second, _ = self.make_repo("second")
        response = self.start(first, second, task_id="multi")
        task = response["task"]
        self.assertEqual(task["status"], "INTAKE")
        self.assertEqual(task["revision"], 1)
        self.assertEqual(len(task["repositories"]), 2)
        task_dir = self.data / "tasks" / "multi"
        self.assertTrue((task_dir / "state.json").is_file())
        self.assertTrue((task_dir / "artifacts").is_dir())
        if os.name == "posix":
            self.assertEqual((task_dir / "artifacts").stat().st_mode & 0o777, 0o700)
        events = (task_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events[0])["type"], "task_started")

        conflict = self.cli(
            "preflight",
            "multi",
            "--expected-revision",
            "0",
            expected_code=3,
        )
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(dev_flow.load_state("multi", self.data)["revision"], 1)
        self.assertEqual(len((task_dir / "events.jsonl").read_text().splitlines()), 1)

    def test_start_rejects_two_worktrees_from_the_same_git_repository(self) -> None:
        repo, _ = self.make_repo("duplicate-common-dir")
        linked = self.root / "duplicate-common-linked"
        git(
            repo,
            "worktree",
            "add",
            "-q",
            "-b",
            "duplicate-common-linked",
            str(linked),
            "HEAD",
        )
        denied = self.cli(
            "start",
            "--task-id",
            "duplicate-common-dir",
            "--requirement",
            "must not double-count one Git repository",
            "--repo",
            str(repo),
            "--repo",
            str(linked),
            expected_code=2,
        )
        self.assertEqual(
            denied["error"]["code"], "DUPLICATE_GIT_REPOSITORY"
        )
        self.assertFalse(
            (self.data / "tasks" / "duplicate-common-dir" / "state.json").exists()
        )

    def test_preflight_records_dirty_state_and_blocks_git_operation(self) -> None:
        repo, _ = self.make_repo("dirty")
        task = self.start(repo)["task"]
        (repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        git(repo, "add", "staged.txt")
        (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        response = self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        preflight = task["repositories"][0]["preflight"]
        self.assertTrue(response["ready"])
        self.assertEqual(task["status"], "PREFLIGHTED")
        self.assertIn("staged.txt", preflight["staged"])
        self.assertIn("tracked.txt", preflight["unstaged"])
        self.assertIn("untracked.txt", preflight["untracked"])

        # A real sequencer directory is sufficient for Git to report an in-progress operation.
        git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
        (git_dir / "sequencer").mkdir()
        (git_dir / "sequencer" / "todo").write_text("pick deadbeef test\n")
        response = self.mutate("preflight", task)
        self.assertFalse(response["ready"])
        blocked = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn(
            "operation_in_progress:sequencer",
            blocked["repositories"][0]["preflight"]["blockers"],
        )

    def test_git_environment_redirects_cannot_change_repository_or_baseline(self) -> None:
        target, _ = self.make_repo("redirect-target")
        decoy, _ = self.make_repo("redirect-decoy")
        target_head = git(target, "rev-parse", "HEAD")
        decoy_head = git(decoy, "rev-parse", "HEAD")
        redirected_config = self.root / "redirected-git-config"
        redirected_config.write_text(
            '[branch "main"]\n\tremote = decoy\n', encoding="utf-8"
        )
        malicious_environment = {
            "GIT_DIR": str(decoy / ".git"),
            "GIT_WORK_TREE": str(decoy),
            "GIT_INDEX_FILE": str(decoy / ".git" / "index"),
            "GIT_OBJECT_DIRECTORY": str(decoy / ".git" / "objects"),
            "GIT_NAMESPACE": "redirected",
            "GIT_CONFIG": str(redirected_config),
            "GIT_GRAFT_FILE": str(self.root / "malicious-grafts"),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.bare",
            "GIT_CONFIG_VALUE_0": "false",
        }
        with mock.patch.dict(os.environ, malicious_environment):
            task = self.start(target, task_id="redirect-safe")["task"]
            self.assertEqual(
                Path(task["repositories"][0]["path"]).resolve(), target.resolve()
            )
            self.mutate("preflight", task)
            task = dev_flow.load_state(task["task_id"], self.data)
            preflight = task["repositories"][0]["preflight"]
            self.assertEqual(preflight["head_sha"], target_head)
            self.assertNotEqual(preflight["head_sha"], decoy_head)
            self.assertEqual(preflight["remote"], "origin")
            self.mutate(
                "approve",
                task,
                "--gate",
                "baseline-fetch",
                "--note",
                "the exact target repository is approved",
            )
            task = dev_flow.load_state(task["task_id"], self.data)
            self.mutate("baseline", task, "--materialize")

        state = dev_flow.load_state("redirect-safe", self.data)
        baseline = state["repositories"][0]["baseline"]
        analysis = state["repositories"][0]["analysis_workspace"]
        self.assertEqual(baseline["base_sha"], target_head)
        self.assertEqual(git(Path(analysis["path"]), "rev-parse", "HEAD"), target_head)
        self.assertEqual(git(decoy, "rev-parse", "HEAD"), decoy_head)

    def test_repository_grafts_cannot_forge_ancestry(self) -> None:
        repo, _ = self.make_repo("graft-ancestry")
        first = git(repo, "rev-parse", "HEAD")
        git(repo, "switch", "-q", "--orphan", "unrelated")
        (repo / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
        git(repo, "add", "unrelated.txt")
        git(repo, "commit", "-q", "-m", "unrelated root")
        second = git(repo, "rev-parse", "HEAD")
        common_dir = Path(git(repo, "rev-parse", "--git-common-dir"))
        if not common_dir.is_absolute():
            common_dir = (repo / common_dir).resolve()
        info = common_dir / "info"
        info.mkdir(exist_ok=True)
        (info / "grafts").write_text(f"{second} {first}\n", encoding="utf-8")
        result = dev_flow._run(
            [
                "git",
                "-C",
                str(repo),
                "merge-base",
                "--is-ancestor",
                first,
                second,
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_git_evidence_ignores_external_diff_textconv_and_submodule_hiding(self) -> None:
        parent, _ = self.make_repo("evidence-parent")
        child, _ = self.make_repo("evidence-child")
        git(
            parent,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(child),
            "vendor/child",
        )
        (parent / ".gitattributes").write_text(
            "tracked.txt diff=evil\n", encoding="utf-8"
        )
        git(parent, "add", ".gitattributes", ".gitmodules", "vendor/child")
        git(parent, "commit", "-q", "-m", "add adversarial diff fixtures")
        base_sha = git(parent, "rev-parse", "HEAD")

        true_command = shutil.which("true")
        self.assertIsNotNone(true_command)
        git(parent, "config", "diff.external", true_command)
        git(parent, "config", "diff.ignoreSubmodules", "all")
        git(parent, "config", "diff.evil.command", true_command)
        git(parent, "config", "diff.evil.textconv", true_command)
        adversarial_environment = {
            "GIT_EXTERNAL_DIFF": str(true_command),
            "GIT_DIFF_OPTS": "--unified=0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "diff.ignoreSubmodules",
            "GIT_CONFIG_VALUE_0": "all",
        }
        with mock.patch.dict(os.environ, adversarial_environment):
            clean = dev_flow._fingerprint_repo(parent)

        (parent / "tracked.txt").write_text("cached evidence\n", encoding="utf-8")
        git(parent, "add", "tracked.txt")
        (parent / "tracked.txt").write_text("unstaged evidence\n", encoding="utf-8")
        submodule = parent / "vendor" / "child"
        git(submodule, "config", "user.name", "Dev Flow Test")
        git(submodule, "config", "user.email", "dev-flow@example.invalid")
        (submodule / "tracked.txt").write_text(
            "committed submodule pointer change\n", encoding="utf-8"
        )
        git(submodule, "add", "tracked.txt")
        git(submodule, "commit", "-q", "-m", "move clean submodule head")
        repo_record = {
            "id": "evidence-parent",
            "path": str(parent),
            "protected_branches": ["main", "master", "trunk"],
            "baseline": {"base_branch": "main", "base_sha": base_sha},
            "workspace": None,
        }
        with mock.patch.dict(os.environ, adversarial_environment):
            dirty = dev_flow._fingerprint_repo(parent)
            preflight = dev_flow._preflight_repo(repo_record, None, None)
            review = dev_flow._write_review_repo(
                self.root / "adversarial-review", repo_record
            )

        self.assertNotEqual(clean["sha256"], dirty["sha256"])
        self.assertNotEqual(clean["cached_sha256"], dirty["cached_sha256"])
        self.assertNotEqual(clean["unstaged_sha256"], dirty["unstaged_sha256"])
        self.assertIn("tracked.txt", preflight["staged"])
        self.assertIn("tracked.txt", preflight["unstaged"])
        self.assertIn("vendor/child", preflight["unstaged"])
        sections = review["sections"]
        self.assertIn("tracked.txt", "\n".join(sections["cached"]["files"]))
        self.assertIn("tracked.txt", "\n".join(sections["unstaged"]["files"]))
        self.assertIn("vendor/child", "\n".join(sections["unstaged"]["files"]))
        self.assertIn(
            b"cached evidence",
            Path(sections["cached"]["path"]).read_bytes(),
        )
        self.assertIn(
            b"unstaged evidence",
            Path(sections["unstaged"]["path"]).read_bytes(),
        )

        for inner_content in ("dirty version a\n", "dirty version b\n"):
            with self.subTest(inner_content=inner_content.strip()):
                (submodule / "tracked.txt").write_text(
                    inner_content, encoding="utf-8"
                )
                with mock.patch.dict(os.environ, adversarial_environment):
                    with self.assertRaises(dev_flow.FlowError) as captured:
                        dev_flow._fingerprint_repo(parent)
                self.assertEqual(
                    captured.exception.code, "DIRTY_SUBMODULE_UNSUPPORTED"
                )
                self.assertEqual(
                    captured.exception.details["submodules"][0]["path"],
                    "vendor/child",
                )
        (submodule / "tracked.txt").write_text(
            "committed submodule pointer change\n", encoding="utf-8"
        )
        (submodule / "inner-untracked.txt").write_text(
            "untracked submodule content\n", encoding="utf-8"
        )
        with mock.patch.dict(os.environ, adversarial_environment):
            with self.assertRaises(dev_flow.FlowError) as untracked_error:
                dev_flow._fingerprint_repo(parent)
        self.assertEqual(
            untracked_error.exception.code, "DIRTY_SUBMODULE_UNSUPPORTED"
        )
        self.assertIn(
            "U",
            untracked_error.exception.details["submodules"][0][
                "submodule_status"
            ],
        )
        with mock.patch.dict(os.environ, adversarial_environment):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._write_review_repo(
                    self.root / "dirty-submodule-review", repo_record
                )
        self.assertEqual(captured.exception.code, "DIRTY_SUBMODULE_UNSUPPORTED")
        (submodule / "inner-untracked.txt").unlink()
        git(submodule, "update-index", "--assume-unchanged", "tracked.txt")
        for hidden_content in ("hidden submodule a\n", "hidden submodule b\n"):
            with self.subTest(hidden_content=hidden_content.strip()):
                (submodule / "tracked.txt").write_text(
                    hidden_content, encoding="utf-8"
                )
                with mock.patch.dict(os.environ, adversarial_environment):
                    with self.assertRaises(dev_flow.FlowError) as hidden_error:
                        dev_flow._fingerprint_repo(parent)
                self.assertEqual(hidden_error.exception.code, "HIDDEN_INDEX_FLAGS")
                self.assertEqual(
                    hidden_error.exception.details["entries"][0]["path"],
                    "vendor/child/tracked.txt",
                )
        git(submodule, "update-index", "--no-assume-unchanged", "tracked.txt")

    def test_content_filters_are_rejected_before_git_can_hide_bytes(self) -> None:
        repo, _ = self.make_repo("content-filter")
        (repo / ".gitattributes").write_text(
            "tracked.txt filter=hide\n", encoding="utf-8"
        )
        git(repo, "add", ".gitattributes")
        git(repo, "commit", "-q", "-m", "configure filtered path")
        git(repo, "config", "filter.hide.clean", "git show HEAD:tracked.txt")
        git(repo, "config", "filter.hide.smudge", "cat")
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._fingerprint_repo(repo)
        self.assertEqual(captured.exception.code, "CONTENT_FILTER_UNSUPPORTED")
        self.assertEqual(
            captured.exception.details["entries"][0],
            {"path": "tracked.txt", "filter": "hide"},
        )

        global_repo, _ = self.make_repo("global-content-filter")
        global_home = self.root / "filter-home"
        global_home.mkdir()
        attributes = global_home / "global-attributes"
        attributes.write_text("tracked.txt filter=hide\n", encoding="utf-8")
        (global_home / ".gitconfig").write_text(
            "[core]\n"
            f"\tattributesFile = {attributes}\n"
            "[filter \"hide\"]\n"
            "\tclean = git show HEAD:tracked.txt\n"
            "\tsmudge = cat\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"HOME": str(global_home)}):
            with self.assertRaises(dev_flow.FlowError) as global_error:
                dev_flow._fingerprint_repo(global_repo)
        self.assertEqual(
            global_error.exception.code, "CONTENT_FILTER_UNSUPPORTED"
        )

    def test_hidden_index_flags_are_rejected_before_fingerprinting(self) -> None:
        repo, _ = self.make_repo("hidden-index")
        original = (repo / "tracked.txt").read_text(encoding="utf-8")
        dev_flow._fingerprint_repo(repo)

        git(repo, "update-index", "--assume-unchanged", "tracked.txt")
        for content in ("assumed version a\n", "assumed version b\n"):
            with self.subTest(flag="assume-unchanged", content=content.strip()):
                (repo / "tracked.txt").write_text(content, encoding="utf-8")
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._fingerprint_repo(repo)
                self.assertEqual(captured.exception.code, "HIDDEN_INDEX_FLAGS")
                self.assertEqual(
                    captured.exception.details["entries"][0]["flags"],
                    "assume-unchanged",
                )
                with self.assertRaises(dev_flow.FlowError) as status_error:
                    dev_flow._status_porcelain(repo)
                self.assertEqual(status_error.exception.code, "HIDDEN_INDEX_FLAGS")
        git(repo, "update-index", "--no-assume-unchanged", "tracked.txt")
        (repo / "tracked.txt").write_text(original, encoding="utf-8")

        git(repo, "update-index", "--skip-worktree", "tracked.txt")
        for content in ("skipped version a\n", "skipped version b\n"):
            with self.subTest(flag="skip-worktree", content=content.strip()):
                (repo / "tracked.txt").write_text(content, encoding="utf-8")
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._fingerprint_repo(repo)
                self.assertEqual(captured.exception.code, "HIDDEN_INDEX_FLAGS")
                self.assertIn(
                    "skip-worktree",
                    captured.exception.details["entries"][0]["flags"],
                )
        git(repo, "update-index", "--no-skip-worktree", "tracked.txt")

    @unittest.skipUnless(os.name == "posix", "requires byte-preserving POSIX paths")
    def test_untracked_paths_are_nul_safe_and_archived_losslessly(self) -> None:
        repo, _ = self.make_repo("untracked-path-bytes")
        unicode_name = "未跟踪-文件.txt"
        newline_name = "line\nbreak.txt"
        (repo / unicode_name).write_bytes(b"unicode\n")
        (repo / newline_name).write_bytes(b"newline\n")
        undecodable_name: bytes | None = b"raw-\xff.bin"
        try:
            descriptor = os.open(
                os.path.join(os.fsencode(repo), undecodable_name),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except OSError:
            # Some sandboxed/macOS volumes reject non-UTF-8 directory entries.
            undecodable_name = None
        else:
            try:
                os.write(descriptor, b"raw bytes\n")
            finally:
                os.close(descriptor)

        expected_names = {
            os.fsencode(unicode_name),
            os.fsencode(newline_name),
        }
        if undecodable_name is not None:
            expected_names.add(undecodable_name)
        fingerprint = dev_flow._fingerprint_repo(repo)
        items = fingerprint["untracked"]
        self.assertEqual(
            [item["path_bytes_hex"] for item in items],
            [name.hex() for name in sorted(expected_names)],
        )
        by_hex = {item["path_bytes_hex"]: item for item in items}
        self.assertEqual(by_hex[os.fsencode(unicode_name).hex()]["path"], unicode_name)
        self.assertEqual(by_hex[os.fsencode(newline_name).hex()]["path"], newline_name)
        if undecodable_name is not None:
            self.assertIn("\ufffd", by_hex[undecodable_name.hex()]["path"])

        review = dev_flow._write_review_repo(
            self.root / "untracked-path-review",
            {
                "id": "untracked-path-bytes",
                "path": str(repo),
                "baseline": {"base_sha": git(repo, "rev-parse", "HEAD")},
                "workspace": None,
            },
        )
        untracked = review["sections"]["untracked"]
        manifest = json.loads(
            Path(untracked["manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            {bytes.fromhex(item["path_bytes_hex"]) for item in manifest},
            expected_names,
        )
        with tarfile.open(untracked["archive_path"], "r") as archive:
            archived_names = {os.fsencode(name) for name in archive.getnames()}
        self.assertEqual(archived_names, expected_names)

    @unittest.skipUnless(os.name == "posix", "requires POSIX mode and symlink semantics")
    def test_evidence_overrides_stat_mode_and_symlink_hiding_config(self) -> None:
        mode_repo, _ = self.make_repo("mode-evidence")
        git(mode_repo, "config", "core.fileMode", "false")
        clean_mode = dev_flow._fingerprint_repo(mode_repo)
        tracked = mode_repo / "tracked.txt"
        tracked.chmod(tracked.stat().st_mode | 0o111)
        executable_mode = dev_flow._fingerprint_repo(mode_repo)
        self.assertNotEqual(clean_mode["sha256"], executable_mode["sha256"])
        mode_patch = dev_flow._git_diff(
            mode_repo, "--binary", "--full-index", "--", text=False
        )
        self.assertIn(b"old mode 100644", mode_patch)
        self.assertIn(b"new mode 100755", mode_patch)

        stat_repo, _ = self.make_repo("stat-evidence")
        git(stat_repo, "config", "core.trustctime", "false")
        git(stat_repo, "config", "core.checkStat", "minimal")
        stat_path = stat_repo / "tracked.txt"
        before = dev_flow._fingerprint_repo(stat_repo)
        original_stat = stat_path.stat()
        original_bytes = stat_path.read_bytes()
        replacement = b"x" * (len(original_bytes) - 1) + b"\n"
        self.assertEqual(len(replacement), len(original_bytes))
        stat_path.write_bytes(replacement)
        os.utime(
            stat_path,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        after = dev_flow._fingerprint_repo(stat_repo)
        self.assertNotEqual(before["sha256"], after["sha256"])

        symlink_repo, _ = self.make_repo("symlink-evidence")
        link = symlink_repo / "tracked-link"
        link.symlink_to("tracked.txt")
        git(symlink_repo, "add", "tracked-link")
        git(symlink_repo, "commit", "-q", "-m", "add tracked symlink")
        git(symlink_repo, "config", "core.symlinks", "false")
        symlink_fingerprint = dev_flow._fingerprint_repo(symlink_repo)
        link.unlink()
        link.write_text("tracked.txt", encoding="utf-8")
        regular_fingerprint = dev_flow._fingerprint_repo(symlink_repo)
        self.assertNotEqual(
            symlink_fingerprint["sha256"], regular_fingerprint["sha256"]
        )
        type_patch = dev_flow._git_diff(
            symlink_repo, "--binary", "--full-index", "--", text=False
        )
        self.assertIn(b"120000", type_patch)
        self.assertIn(b"100644", type_patch)

        ident_repo, _ = self.make_repo("ident-evidence")
        (ident_repo / "tracked.txt").write_text("$Id$\n", encoding="utf-8")
        (ident_repo / ".gitattributes").write_text(
            "tracked.txt ident\n", encoding="utf-8"
        )
        git(ident_repo, "add", "tracked.txt", ".gitattributes")
        git(ident_repo, "commit", "-q", "-m", "enable ident conversion")
        ident_before = dev_flow._fingerprint_repo(ident_repo)
        (ident_repo / "tracked.txt").write_text(
            "$Id: arbitrary-worktree-bytes $\n", encoding="utf-8"
        )
        self.assertEqual(dev_flow._git_diff(ident_repo, "--name-only", "--"), "")
        ident_after = dev_flow._fingerprint_repo(ident_repo)
        self.assertNotEqual(ident_before["sha256"], ident_after["sha256"])

    def test_controller_generated_artifact_kinds_cannot_be_recorded_manually(self) -> None:
        repo, _ = self.make_repo("reserved-artifact")
        task = self.start(repo, task_id="reserved-artifact")["task"]
        artifact = self.root / "forged-controller-artifact.json"
        artifact.write_text("{}\n", encoding="utf-8")
        for kind in ("workspace-plan", "review-snapshot"):
            with self.subTest(kind=kind):
                denied = self.cli(
                    "record-artifact",
                    task["task_id"],
                    "--expected-revision",
                    str(task["revision"]),
                    "--kind",
                    kind,
                    "--path",
                    str(artifact),
                    expected_code=2,
                )
                self.assertEqual(
                    denied["error"]["code"], "RESERVED_ARTIFACT_KIND"
                )

    def test_full_flow_creates_worktree_and_complete_review_snapshot(self) -> None:
        repo, _ = self.make_repo("flow")
        task = self.start(repo)["task"]
        self.assertEqual(task["impact_generation"], 0)
        self.assertEqual(task["planning_generation"], 0)
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["repositories"][0]["preflight"]["remote"], "origin")

        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--fetch",
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "local remote and detached analysis worktree approved",
            "--allow-fetch",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--fetch", "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline = task["repositories"][0]["baseline"]
        self.assertEqual(baseline["base_sha"], git(repo, "rev-parse", "origin/main"))
        analysis = task["repositories"][0]["analysis_workspace"]
        self.assertTrue(analysis["detached"])
        self.assertEqual(analysis["head_sha"], baseline["base_sha"])
        self.assertEqual(git(Path(analysis["path"]), "branch", "--show-current"), "")
        self.assertEqual(
            dev_flow.find_active_task_for_cwd(analysis["path"], self.data)["task_id"],
            task["task_id"],
        )

        git(repo, "commit", "-q", "--allow-empty", "-m", "source moved after baseline")
        mismatched = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--commit",
            git(repo, "rev-parse", "HEAD"),
            "--index-id",
            "memory-index-mismatch",
            expected_code=2,
        )
        self.assertEqual(mismatched["error"]["code"], "INDEX_BASE_MISMATCH")
        index_response = self.mutate(
            "record-index", task, "--index-id", "memory-index-1"
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "INDEXED")
        self.assertEqual(index_response["repositories"][0]["repo_path"], analysis["path"])

        impact = self.root / "impact.md"
        impact.write_text("# Impact\n\nOne repository.\n", encoding="utf-8")
        no_impact = self.cli(
            "set-route",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "direct",
            "--reason",
            "must not route without impact",
            expected_code=2,
        )
        self.assertEqual(no_impact["error"]["code"], "ARTIFACT_REQUIRED")
        artifact_response = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            artifact_response["artifact"]["metadata"]["impact_generation"], 0
        )
        artifact_hash = artifact_response["artifact"]["sha256"]

        previous_index_record_id = task["repositories"][0]["index"]["index_record_id"]
        self.mutate("record-index", task, "--index-id", "memory-index-1")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotEqual(
            task["repositories"][0]["index"]["index_record_id"],
            previous_index_record_id,
        )
        stale_impact = self.cli(
            "set-route",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "direct",
            "--reason",
            "stale impact must not route",
            expected_code=2,
        )
        self.assertEqual(stale_impact["error"]["code"], "STALE_IMPACT")
        impact.write_text("# Impact\n\nRefreshed index coverage.\n", encoding="utf-8")
        artifact_response = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        artifact_hash = artifact_response["artifact"]["sha256"]

        self.mutate("set-route", task, "direct", "--reason", "localized change")
        task = dev_flow.load_state(task["task_id"], self.data)
        impact.write_text("# Impact\n\nUpdated, still one repository.\n", encoding="utf-8")
        latest_impact = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertIsNone(task["route"])
        missing_reselection = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "route",
            "--note",
            "route must be selected again",
            "--artifact-sha256",
            latest_impact["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(missing_reselection["error"]["code"], "ROUTE_REQUIRED")
        self.mutate("set-route", task, "direct", "--reason", "updated impact")
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_route = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "route",
            "--note",
            "stale impact",
            "--artifact-sha256",
            artifact_hash,
            expected_code=2,
        )
        self.assertEqual(stale_route["error"]["code"], "APPROVAL_ARTIFACT_MISMATCH")
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "impact reviewed",
            "--artifact-sha256",
            latest_impact["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)

        dry_run = self.mutate("prepare-workspace", task)
        self.assertTrue(dry_run["dry_run"])
        self.assertEqual(dry_run["revision"], task["revision"] + 1)
        self.assertFalse(Path(dry_run["plans"][0]["path"]).exists())
        workspace_plan_hash = dry_run["plan_artifact"]["sha256"]
        task = dev_flow.load_state(task["task_id"], self.data)
        repeated_plan = self.mutate("prepare-workspace", task)
        self.assertTrue(repeated_plan["unchanged"])
        self.assertEqual(repeated_plan["revision"], task["revision"])

        denied = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--execute",
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "worktree plan approved",
            "--artifact-sha256",
            workspace_plan_hash,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        plan_mismatch = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--execute",
            "--branch",
            "codex/not-approved",
            expected_code=2,
        )
        self.assertEqual(plan_mismatch["error"]["code"], "WORKSPACE_PLAN_MISMATCH")
        self.mutate("prepare-workspace", task, "--execute")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "WORKSPACE_READY")
        workspace = Path(task["repositories"][0]["workspace"]["path"])
        self.assertTrue(workspace.is_dir())
        self.assertEqual(git(workspace, "branch", "--show-current"), "codex/task-1")

        # A recorded workspace may move forward and is still reused idempotently.
        (workspace / "committed.txt").write_text("committed\n", encoding="utf-8")
        git(workspace, "add", "committed.txt")
        git(workspace, "commit", "-q", "-m", "early implementation")
        second = self.mutate("prepare-workspace", task, "--execute")
        self.assertFalse(second["workspaces"][0]["created"])
        self.assertEqual(second["workspaces"][0]["head_sha"], git(workspace, "rev-parse", "HEAD"))
        task = dev_flow.load_state(task["task_id"], self.data)
        replacement_path = self.root / "same-generation-replacement"
        replacement = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--path",
            str(replacement_path),
            "--branch",
            "codex/same-generation-replacement",
            expected_code=2,
        )
        self.assertEqual(
            replacement["error"]["code"], "WORKSPACE_REASSESSMENT_REQUIRED"
        )
        self.assertFalse(replacement_path.exists())

        task = self.record_workspace_indexes(task)
        workspace_index = task["repositories"][0]["workspace_index"]
        self.assertEqual(workspace_index["role"], "workspace")
        self.assertEqual(workspace_index["repo_path"], str(workspace))
        git(workspace, "switch", "-q", "-c", "workspace-hijack")
        hijacked = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(hijacked["error"]["code"], "STALE_WORKSPACE_INDEX")
        git(workspace, "switch", "-q", "codex/task-1")
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["planning_generation"], 1)
        contract = self.root / "direct-contract.md"
        contract.write_text("# Contract\n\nOnly flow repo changes.\n", encoding="utf-8")
        contract_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        first_planning_context = contract_response["artifact"]["metadata"][
            "planning_context"
        ]
        self.assertEqual(first_planning_context["planning_generation"], 1)
        self.assertEqual(
            first_planning_context["route"]["approval_id"],
            task["approvals"]["route"]["approval_id"],
        )
        self.assertEqual(
            first_planning_context["workspace"]["generation"], 0
        )
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "direct contract reviewed",
            "--artifact-sha256",
            contract_response["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        contract.write_text("# Contract\n\nUpdated contract.\n", encoding="utf-8")
        latest_contract = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_plan = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "IMPLEMENTING",
            expected_code=2,
        )
        self.assertEqual(stale_plan["error"]["code"], "STALE_APPROVAL")
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "updated direct contract reviewed",
            "--artifact-sha256",
            latest_contract["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)

        (workspace / "cached.txt").write_text("cached\n", encoding="utf-8")
        git(workspace, "add", "cached.txt")
        (workspace / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (workspace / "untracked.bin").write_bytes(b"\x00untracked\xff")
        task = self.record_workspace_indexes(task)

        # Editing approved evidence on disk is caught, then an explicit replan
        # clears the old approval and permits a new planning artifact.
        contract.write_text("# Contract\n\nChanged during implementation.\n", encoding="utf-8")
        stale_after_implementation = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "VERIFYING",
            expected_code=2,
        )
        self.assertEqual(stale_after_implementation["error"]["code"], "ARTIFACT_CHANGED")
        missing_note = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(missing_note["error"]["code"], "INVALID_ARGUMENT")
        self.mutate(
            "transition",
            task,
            "PLANNING",
            "--note",
            "implementation revealed a contract change",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("plan", task["approvals"])
        self.assertEqual(task["planning_generation"], 2)
        # Restore the previously recorded bytes so this rejection proves the
        # planning epoch binding rather than ordinary on-disk artifact drift.
        contract.write_text("# Contract\n\nUpdated contract.\n", encoding="utf-8")
        old_epoch_plan = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "plan",
            "--note",
            "old planning epoch must not be reapproved",
            "--artifact-sha256",
            latest_contract["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(old_epoch_plan["error"]["code"], "STALE_PLAN")
        contract.write_text(
            "# Contract\n\nChanged during implementation.\n", encoding="utf-8"
        )
        implementation_contract = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            implementation_contract["artifact"]["metadata"]["planning_context"][
                "planning_generation"
            ],
            2,
        )
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "implementation contract revision reviewed",
            "--artifact-sha256",
            implementation_contract["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)

        # A later impact reassessment returns to INDEXED, preserves the actual
        # worktree/history, and invalidates every downstream human gate.
        self.mutate(
            "record-test",
            task,
            "--name",
            "pre-reassessment",
            "--command",
            "python -m unittest",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        missing_reassessment_note = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "INDEXED",
            expected_code=2,
        )
        self.assertEqual(missing_reassessment_note["error"]["code"], "INVALID_ARGUMENT")
        self.mutate(
            "transition",
            task,
            "INDEXED",
            "--note",
            "implementation exposed broader impact",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertIsNone(task["route"])
        self.assertIsNone(task["repositories"][0]["workspace"])
        self.assertEqual(
            task["repositories"][0]["workspace_history"][-1]["path"], str(workspace)
        )
        self.assertEqual(
            task["repositories"][0]["workspace_history"][-1][
                "workspace_index"
            ]["index_id"],
            workspace_index["index_id"],
        )
        self.assertIsNone(task["repositories"][0]["workspace_index"])
        self.assertFalse(task["workspace"]["ready"])
        self.assertIsNone(task["workspace"]["plan"])
        self.assertEqual(task["workspace"]["generation"], 1)
        self.assertEqual(task["impact_generation"], 1)
        for cleared_gate in ("route", "workspace", "plan", "review"):
            self.assertNotIn(cleared_gate, task["approvals"])

        stale_impact_epoch = self.cli(
            "set-route",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "direct",
            "--reason",
            "old impact epoch must not be routed",
            expected_code=2,
        )
        self.assertEqual(stale_impact_epoch["error"]["code"], "STALE_IMPACT")
        impact.write_text("# Impact\n\nReassessed impact.\n", encoding="utf-8")
        reassessed_impact = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        self.assertEqual(
            reassessed_impact["artifact"]["metadata"]["impact_generation"], 1
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("set-route", task, "direct", "--reason", "reassessed localized change")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "reassessed impact approved",
            "--artifact-sha256",
            reassessed_impact["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        registry_path = self.data / "workspace-registry.json"
        registry_before_reuse = registry_path.read_bytes()
        revision_before_reuse = task["revision"]
        retired_reuse = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--path",
            str(workspace),
            "--branch",
            "codex/task-1",
            expected_code=2,
        )
        self.assertEqual(
            retired_reuse["error"]["code"], "RETIRED_WORKSPACE_REUSE"
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data)["revision"],
            revision_before_reuse,
        )
        self.assertEqual(registry_path.read_bytes(), registry_before_reuse)
        reassessed_workspace_plan = self.mutate("prepare-workspace", task)
        self.assertNotEqual(
            reassessed_workspace_plan["plan_artifact"]["sha256"],
            workspace_plan_hash,
        )
        self.assertEqual(
            reassessed_workspace_plan["plan_artifact"]["metadata"][
                "workspace_generation"
            ],
            1,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "reassessed workspace plan approved",
            "--artifact-sha256",
            reassessed_workspace_plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("prepare-workspace", task, "--execute")
        task = dev_flow.load_state(task["task_id"], self.data)
        reassessed_workspace = Path(task["repositories"][0]["workspace"]["path"])
        self.assertNotEqual(reassessed_workspace, workspace)
        self.assertEqual(
            task["repositories"][0]["workspace"]["branch"], "codex/task-1-r1"
        )
        workspace = reassessed_workspace
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["planning_generation"], 3)
        stale_after_impact_reassessment = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "plan",
            "--note",
            "pre-reassessment plan must not be reapproved",
            "--artifact-sha256",
            implementation_contract["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(
            stale_after_impact_reassessment["error"]["code"], "STALE_PLAN"
        )
        contract.write_text("# Contract\n\nContract after impact reassessment.\n", encoding="utf-8")
        reassessed_contract = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        reassessed_context = reassessed_contract["artifact"]["metadata"][
            "planning_context"
        ]
        self.assertEqual(reassessed_context["planning_generation"], 3)
        self.assertEqual(reassessed_context["impact_generation"], 1)
        self.assertEqual(reassessed_context["workspace"]["generation"], 1)
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "reassessed contract approved",
            "--artifact-sha256",
            reassessed_contract["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)
        (workspace / "committed.txt").write_text("committed\n", encoding="utf-8")
        git(workspace, "add", "committed.txt")
        git(workspace, "commit", "-q", "-m", "reassessed implementation")
        (workspace / "cached.txt").write_text("cached\n", encoding="utf-8")
        git(workspace, "add", "cached.txt")
        (workspace / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (workspace / "untracked.bin").write_bytes(b"\x00untracked\xff")
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "VERIFYING")
        task = dev_flow.load_state(task["task_id"], self.data)
        old_test_denied = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(old_test_denied["error"]["code"], "CURRENT_TEST_REQUIRED")
        test_output = self.root / "unit-test-output.txt"
        test_output.write_text("all tests passed\n", encoding="utf-8")
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "python -m unittest",
            "--exit-code",
            "0",
            "--output",
            str(test_output),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        test_output.write_text("tampered output\n", encoding="utf-8")
        tampered_test_output = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(
            tampered_test_output["error"]["code"], "CURRENT_TEST_REQUIRED"
        )
        test_output.unlink()
        missing_test_output = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(
            missing_test_output["error"]["code"], "CURRENT_TEST_REQUIRED"
        )
        test_output.write_text("all tests passed\n", encoding="utf-8")
        response = self.mutate("review-snapshot", task)
        snapshot = response["snapshot"]
        self.assertEqual(response["status"], "REVIEWING")
        sections = snapshot["repositories"][0]["sections"]
        self.assertIn("committed.txt", "\n".join(sections["committed"]["files"]))
        self.assertIn("cached.txt", "\n".join(sections["cached"]["files"]))
        self.assertIn("tracked.txt", "\n".join(sections["unstaged"]["files"]))
        self.assertIn("untracked.bin", [item["path"] for item in sections["untracked"]["files"]])
        with tarfile.open(sections["untracked"]["archive_path"], "r") as archive:
            self.assertIn("untracked.bin", archive.getnames())
        for name in ("committed", "cached", "unstaged"):
            self.assertTrue(Path(sections[name]["path"]).is_file())

        task = dev_flow.load_state(task["task_id"], self.data)
        review_report = self.root / "review-report.md"
        review_report.write_text(
            "# Review\n\nVerdict: CONDITIONAL\n\nNo findings.\n", encoding="utf-8"
        )
        misplaced_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "CONDITIONAL",
            expected_code=2,
        )
        self.assertEqual(misplaced_verdict["error"]["code"], "INVALID_REVIEW_REPORT")
        review_report.write_text(
            "Verdict: CONDITIONAL\n\n  Verdict: FAIL\n", encoding="utf-8"
        )
        duplicate_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "CONDITIONAL",
            expected_code=2,
        )
        self.assertEqual(duplicate_verdict["error"]["code"], "INVALID_REVIEW_REPORT")
        review_report.write_text(
            "Verdict: CONDITIONAL\n\n# Review\n\nNo findings.\n", encoding="utf-8"
        )
        missing_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            expected_code=2,
        )
        self.assertEqual(missing_verdict["error"]["code"], "INVALID_ARGUMENT")
        mismatched_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "PASS",
            expected_code=2,
        )
        self.assertEqual(
            mismatched_verdict["error"]["code"], "REVIEW_VERDICT_MISMATCH"
        )
        report_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "CONDITIONAL",
        )
        self.assertEqual(
            report_response["artifact"]["metadata"]["review_snapshot_sha256"],
            snapshot["sha256"],
        )
        self.assertEqual(report_response["artifact"]["metadata"]["verdict"], "CONDITIONAL")
        task = dev_flow.load_state(task["task_id"], self.data)
        conditional_denied = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "review",
            "--note",
            "review report approved",
            "--artifact-sha256",
            report_response["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(
            conditional_denied["error"]["code"], "CONDITIONAL_ACCEPTANCE_REQUIRED"
        )
        conditional_approval = self.mutate(
            "approve",
            task,
            "--gate",
            "review",
            "--note",
            "conditional review explicitly accepted",
            "--artifact-sha256",
            report_response["artifact"]["sha256"],
            "--accept-conditional",
        )
        self.assertTrue(conditional_approval["approval"]["conditional_accepted"])
        task = dev_flow.load_state(task["task_id"], self.data)
        verified_conditional, _ = dev_flow._require_review_gate(task)
        self.assertTrue(verified_conditional["conditional_accepted"])
        newer_snapshot = self.mutate("review-snapshot", task)["snapshot"]
        self.assertNotEqual(newer_snapshot["sha256"], snapshot["sha256"])
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_report = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(stale_report["error"]["code"], "STALE_REVIEW_REPORT")
        review_report.write_text(
            "Verdict: FAIL\n\n# Review\n\nBlocking finding.\n", encoding="utf-8"
        )
        failing_report = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "FAIL",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        failed_approval = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "review",
            "--note",
            "must not approve",
            "--artifact-sha256",
            failing_report["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(failed_approval["error"]["code"], "REVIEW_VERDICT_FAILED")
        failed_final = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(failed_final["error"]["code"], "REVIEW_VERDICT_FAILED")
        review_report.write_text(
            "Verdict: PASS\n\n# Review\n\nUpdated: no findings.\n", encoding="utf-8"
        )
        latest_report = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "PASS",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_review = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(stale_review["error"]["code"], "STALE_APPROVAL")
        self.mutate(
            "approve",
            task,
            "--gate",
            "review",
            "--note",
            "updated review report approved",
            "--artifact-sha256",
            latest_report["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        committed_patch = Path(
            newer_snapshot["repositories"][0]["sections"]["committed"]["path"]
        )
        original_patch = committed_patch.read_bytes()
        committed_patch.write_bytes(original_patch + b"tampered\n")
        tampered_snapshot = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(tampered_snapshot["error"]["code"], "CURRENT_REVIEW_REQUIRED")
        self.assertIn("committed", tampered_snapshot["error"]["message"])
        committed_patch.write_bytes(original_patch)
        self.mutate("transition", task, "FINALIZING")
        task = dev_flow.load_state(task["task_id"], self.data)
        done = self.mutate("transition", task, "DONE")
        self.assertEqual(done["status"], "DONE")
        self.assertIsNone(dev_flow.find_active_task_for_cwd(workspace, self.data))

    def test_cancel_is_terminal_and_audited(self) -> None:
        repo, _ = self.make_repo("cancel")
        task = self.start(repo)["task"]
        response = self.mutate("cancel", task, "--reason", "requirement withdrawn")
        self.assertEqual(response["status"], "CANCELLED")
        state = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(state["cancelled"]["reason"], "requirement withdrawn")
        events = (self.data / "tasks" / task["task_id"] / "events.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(events[-1])["type"], "task_cancelled")

    def test_nonstandard_feature_branch_needs_explicit_base(self) -> None:
        repo = self.root / "feature-only"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "feature", str(repo)], check=True)
        git(repo, "config", "user.name", "Dev Flow Test")
        git(repo, "config", "user.email", "dev-flow@example.invalid")
        (repo / "file.txt").write_text("one\n", encoding="utf-8")
        git(repo, "add", "file.txt")
        git(repo, "commit", "-q", "-m", "initial")
        task = self.start(repo, task_id="feature-base")["task"]
        response = self.mutate("preflight", task)
        self.assertFalse(response["ready"])
        self.assertEqual(response["status"], "BLOCKED")
        self.assertIn(
            "base_branch_unresolved",
            response["repositories"][0]["preflight"]["blockers"],
        )

    def test_baseline_approval_binds_exact_clean_or_explicit_dirty_snapshot(self) -> None:
        clean_repo, _ = self.make_repo("clean-preflight-drift")
        clean_task = self.start(clean_repo, task_id="clean-preflight-drift")["task"]
        self.mutate("preflight", clean_task)
        clean_task = dev_flow.load_state(clean_task["task_id"], self.data)
        self.mutate(
            "approve",
            clean_task,
            "--gate",
            "baseline-fetch",
            "--note",
            "clean snapshot approved",
        )
        clean_task = dev_flow.load_state(clean_task["task_id"], self.data)
        (clean_repo / "tracked.txt").write_text("changed after approval\n", encoding="utf-8")
        clean_drift = self.cli(
            "baseline",
            clean_task["task_id"],
            "--expected-revision",
            str(clean_task["revision"]),
            expected_code=2,
        )
        self.assertEqual(clean_drift["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED")

        dirty_repo, _ = self.make_repo("dirty-preflight-approval")
        (dirty_repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        git(dirty_repo, "add", "staged.txt")
        (dirty_repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (dirty_repo / "untracked.txt").write_text("original\n", encoding="utf-8")
        dirty_task = self.start(dirty_repo, task_id="dirty-preflight-approval")["task"]
        self.mutate("preflight", dirty_task)
        dirty_task = dev_flow.load_state(dirty_task["task_id"], self.data)
        denied = self.cli(
            "approve",
            dirty_task["task_id"],
            "--expected-revision",
            str(dirty_task["revision"]),
            "--gate",
            "baseline-fetch",
            "--note",
            "implicit dirty approval is forbidden",
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "DIRTY_APPROVAL_REQUIRED")
        invalid_scope = self.cli(
            "approve",
            dirty_task["task_id"],
            "--expected-revision",
            str(dirty_task["revision"]),
            "--gate",
            "route",
            "--note",
            "invalid dirty flag scope",
            "--allow-dirty",
            expected_code=2,
        )
        self.assertEqual(invalid_scope["error"]["code"], "INVALID_ARGUMENT")
        approval = self.mutate(
            "approve",
            dirty_task,
            "--gate",
            "baseline-fetch",
            "--note",
            "exact dirty snapshot approved",
            "--allow-dirty",
        )["approval"]
        self.assertTrue(approval["dirty_allowed"])
        dirty_task = dev_flow.load_state(dirty_task["task_id"], self.data)
        (dirty_repo / "untracked.txt").write_text("changed\n", encoding="utf-8")
        dirty_drift = self.cli(
            "baseline",
            dirty_task["task_id"],
            "--expected-revision",
            str(dirty_task["revision"]),
            expected_code=2,
        )
        self.assertEqual(dirty_drift["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED")
        (dirty_repo / "untracked.txt").write_text("original\n", encoding="utf-8")
        accepted = self.mutate("baseline", dirty_task, "--materialize")
        self.assertEqual(accepted["status"], "BASELINED")

    def test_materialize_can_resume_after_baseline_and_is_idempotent(self) -> None:
        repo, _ = self.make_repo("materialize-later")
        task = self.start(repo, task_id="materialize-later")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "materialization approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        fetch_denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--fetch",
            expected_code=2,
        )
        self.assertEqual(fetch_denied["error"]["code"], "FETCH_NOT_APPROVED")
        invalid_fetch_flag = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "route",
            "--note",
            "invalid flag scope",
            "--allow-fetch",
            expected_code=2,
        )
        self.assertEqual(invalid_fetch_flag["error"]["code"], "INVALID_ARGUMENT")
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("baseline-fetch", task["approvals"])
        denied_after_preflight = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied_after_preflight["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "refreshed preflight approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline_approval = task["approvals"]["baseline-fetch"]
        self.assertEqual(
            baseline_approval["preflight_remotes"][0]["remote"], "origin"
        )
        original_remote_url = git(repo, "remote", "get-url", "origin")
        replacement_remote = self.root / "replacement.git"
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(repo), str(replacement_remote)],
            check=True,
        )
        git(repo, "remote", "set-url", "origin", str(replacement_remote))
        changed_remote = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(changed_remote["error"]["code"], "REMOTE_URL_CHANGED")
        git(repo, "remote", "set-url", "origin", original_remote_url)
        self.mutate("baseline", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertIsNone(task["repositories"][0]["analysis_workspace"])
        response = self.mutate("baseline", task, "--materialize")
        workspace = response["repositories"][0]["analysis_workspace"]
        self.assertTrue(workspace["created"])
        task = dev_flow.load_state(task["task_id"], self.data)
        repeated = self.mutate("baseline", task, "--materialize")
        self.assertFalse(repeated["repositories"][0]["analysis_workspace"]["created"])
        self.assertGreater(repeated["revision"], task["revision"])

        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_path = Path(task["repositories"][0]["analysis_workspace"]["path"])
        (workspace_path / "unexpected.txt").write_text("dirty\n", encoding="utf-8")
        dirty = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--materialize",
            expected_code=2,
        )
        self.assertEqual(dirty["error"]["code"], "ANALYSIS_WORKSPACE_COLLISION")
        self.assertTrue(dirty["error"]["details"]["dirty"])
        (workspace_path / "unexpected.txt").unlink()

        git(workspace_path, "switch", "-q", "-c", "analysis-hijack")
        wrong_branch = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--materialize",
            expected_code=2,
        )
        self.assertEqual(
            wrong_branch["error"]["code"], "ANALYSIS_WORKSPACE_COLLISION"
        )
        self.assertEqual(
            wrong_branch["error"]["details"]["actual_branch"], "analysis-hijack"
        )
        base_sha = task["repositories"][0]["baseline"]["base_sha"]
        git(workspace_path, "switch", "-q", "--detach", base_sha)

        shutil.rmtree(workspace_path)
        rebuilt = self.mutate("baseline", task, "--materialize")
        self.assertTrue(rebuilt["repositories"][0]["analysis_workspace"]["created"])
        self.assertEqual(git(workspace_path, "rev-parse", "HEAD"), base_sha)

        task = dev_flow.load_state(task["task_id"], self.data)
        git(repo, "worktree", "remove", "--force", str(workspace_path))
        foreign, _ = self.make_repo("analysis-foreign")
        foreign.rename(workspace_path)
        foreign_collision = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--materialize",
            expected_code=2,
        )
        self.assertEqual(
            foreign_collision["error"]["code"], "ANALYSIS_WORKSPACE_COLLISION"
        )
        self.assertFalse(foreign_collision["error"]["details"]["same_common_dir"])

    def test_record_index_rejects_replaced_analysis_clone(self) -> None:
        repo, _ = self.make_repo("analysis-replacement")
        task = self.start(repo, task_id="analysis-replacement")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "analysis materialization approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        analysis = Path(task["repositories"][0]["analysis_workspace"]["path"])
        base_sha = task["repositories"][0]["baseline"]["base_sha"]
        git(repo, "worktree", "remove", "--force", str(analysis))
        subprocess.run(
            ["git", "clone", "-q", "--no-local", str(repo), str(analysis)],
            check=True,
        )
        git(analysis, "switch", "-q", "--detach", base_sha)
        denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--index-id",
            "replacement-index",
            expected_code=2,
        )
        self.assertEqual(
            denied["error"]["code"], "ANALYSIS_WORKSPACE_CHANGED"
        )

    def test_configured_remote_never_falls_back_to_local_base(self) -> None:
        repo = self.root / "missing-remote-ref"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        git(repo, "config", "user.name", "Dev Flow Test")
        git(repo, "config", "user.email", "dev-flow@example.invalid")
        (repo / "file.txt").write_text("local main\n", encoding="utf-8")
        git(repo, "add", "file.txt")
        git(repo, "commit", "-q", "-m", "local main")
        empty_remote = self.root / "empty.git"
        subprocess.run(["git", "init", "-q", "--bare", str(empty_remote)], check=True)
        git(repo, "remote", "add", "origin", str(empty_remote))

        task = self.start(repo, task_id="missing-remote-ref")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["repositories"][0]["preflight"]["remote"], "origin")
        self.assertEqual(task["repositories"][0]["preflight"]["base_branch"], "main")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "baseline resolution approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "BASE_REF_NOT_FOUND")
        self.assertEqual(
            denied["error"]["details"]["required_ref"], "refs/remotes/origin/main"
        )
        self.assertEqual(dev_flow.load_state(task["task_id"], self.data)["status"], "PREFLIGHTED")

    def test_baseline_fetch_uses_only_the_approved_base_refspec(self) -> None:
        repo, _ = self.make_repo("explicit-fetch")
        old_remote_sha = git(repo, "rev-parse", "refs/remotes/origin/main")
        (repo / "tracked.txt").write_text("remote base advanced\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-q", "-m", "advance remote base")
        new_remote_sha = git(repo, "rev-parse", "HEAD")
        git(repo, "push", "-q", "origin", "main")
        git(repo, "update-ref", "refs/remotes/origin/main", old_remote_sha)
        git(repo, "config", "--unset-all", "remote.origin.fetch")
        git(
            repo,
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/other:refs/remotes/origin/other",
        )

        task = self.start(repo, task_id="explicit-fetch")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            task["repositories"][0]["preflight"]["fetch_refspec"],
            "+refs/heads/main:refs/remotes/origin/main",
        )
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "explicit main refspec fetch approved",
            "--allow-fetch",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        response = self.mutate("baseline", task, "--fetch")
        baseline = response["repositories"][0]["baseline"]
        self.assertEqual(baseline["base_sha"], new_remote_sha)
        self.assertEqual(
            baseline["fetch_refspec"],
            "+refs/heads/main:refs/remotes/origin/main",
        )
        self.assertEqual(
            git(repo, "rev-parse", "refs/remotes/origin/main"), new_remote_sha
        )

    def test_baseline_without_fetch_rejects_approved_ref_drift(self) -> None:
        repo, _ = self.make_repo("base-ref-drift")
        task = self.start(repo, task_id="base-ref-drift")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        approved_candidate = task["repositories"][0]["preflight"][
            "base_candidate_sha"
        ]
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "exact no-fetch base candidate approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        tree = git(repo, "rev-parse", "HEAD^{tree}")
        changed_candidate = git(repo, "commit-tree", tree, "-m", "ref-only drift")
        self.assertNotEqual(changed_candidate, approved_candidate)
        git(repo, "update-ref", "refs/remotes/origin/main", changed_candidate)
        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "BASE_REF_CHANGED")

    def test_option_like_remote_name_is_rejected_before_fetch(self) -> None:
        repo, remote = self.make_repo("option-remote")
        git(repo, "config", "branch.main.remote", "--all")
        git(repo, "config", "remote.--all.url", str(remote))
        task = self.start(repo, task_id="option-remote")["task"]
        denied = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "INVALID_REMOTE")

    def test_degraded_index_requires_current_approval_and_structured_provenance(self) -> None:
        first, _ = self.make_repo("degraded-first")
        second, _ = self.make_repo("degraded-second")
        task = self.start(first, second, task_id="degraded-index")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "local baseline materialization approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        repository_ids = [repo["id"] for repo in task["repositories"]]

        unapproved = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            expected_code=2,
        )
        self.assertEqual(unapproved["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "impact-degraded",
            "--note",
            "memory index unavailable; fallback review approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        approval_id = task["approvals"]["impact-degraded"]["approval_id"]

        failed_with_index = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            "--index-id",
            "unexpected-index",
            "--metadata-json",
            json.dumps({"status": "failed"}),
            expected_code=2,
        )
        self.assertEqual(failed_with_index["error"]["code"], "INVALID_INDEX_METADATA")
        missing_metadata = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            expected_code=2,
        )
        self.assertEqual(
            missing_metadata["error"]["code"], "DEGRADED_INDEX_METADATA_REQUIRED"
        )
        wrong_binding = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            "--metadata-json",
            json.dumps(
                {
                    "status": "failed",
                    "impact_degraded_approval_id": "old-approval",
                    "error": "service unavailable",
                    "fallback_coverage": {"method": "manual rg review"},
                }
            ),
            expected_code=2,
        )
        self.assertEqual(wrong_binding["error"]["code"], "STALE_APPROVAL")

        degraded_metadata = json.dumps(
            {
                "status": "failed",
                "impact_degraded_approval_id": approval_id,
                "error": "service unavailable",
                "fallback_coverage": {"method": "manual rg review"},
            }
        )
        self.mutate(
            "record-index",
            task,
            "--repo",
            repository_ids[0],
            "--metadata-json",
            degraded_metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "BASELINED")
        self.mutate(
            "record-index",
            task,
            "--repo",
            repository_ids[1],
            "--metadata-json",
            degraded_metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "INDEXED")
        for repo_record in task["repositories"]:
            index = repo_record["index"]
            self.assertIsNone(index["index_id"])
            self.assertTrue(index["index_record_id"])
            self.assertEqual(index["impact_degraded_approval_id"], approval_id)
            self.assertEqual(
                index["metadata"]["impact_degraded_approval_id"], approval_id
            )

        digest = dev_flow._index_provenance_sha256(task)
        changed = dev_flow._copy_state(task)
        changed["repositories"][1]["index"]["index_record_id"] = "changed-token"
        self.assertNotEqual(dev_flow._index_provenance_sha256(changed), digest)
        impact = self.root / "degraded-impact.md"
        impact.write_text("degraded fallback impact\n", encoding="utf-8")
        recorded = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        self.assertEqual(
            recorded["artifact"]["metadata"]["index_provenance_sha256"], digest
        )

    def test_baseline_index_replacements_are_audited_and_history_ids_are_isolated(self) -> None:
        first, _ = self.make_repo("baseline-history-first")
        second, _ = self.make_repo("baseline-history-second")
        task = self.start(
            first, second, task_id="baseline-index-history"
        )["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "history test baselines approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        first_id = task["repositories"][0]["id"]
        second_id = task["repositories"][1]["id"]
        project_a = "baseline-history-project-a"
        project_b = "baseline-history-project-b"
        project_c = "baseline-history-project-c"

        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_a,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline_a = dev_flow._copy_state(task["repositories"][0]["index"])
        self.mutate(
            "record-index",
            task,
            "--repo",
            second_id,
            "--index-id",
            project_c,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_b,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline_b = dev_flow._copy_state(task["repositories"][0]["index"])
        history = task["repositories"][0]["index_history"]
        self.assertEqual(len(history), 1)
        first_history = history[0]
        for key, value in baseline_a.items():
            self.assertEqual(first_history[key], value)
        self.assertTrue(first_history["superseded_at"])
        self.assertEqual(first_history["replacement_role"], "baseline")
        self.assertEqual(first_history["replacement_project"], project_b)
        self.assertEqual(
            first_history["replacement_index_record_id"],
            baseline_b["index_record_id"],
        )
        self.assertEqual(
            first_history["replacement"]["index_record_id"],
            baseline_b["index_record_id"],
        )

        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / task["task_id"]
                / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        replacement_event = next(
            event
            for event in events
            if event["type"] == "index_recorded"
            and (event["payload"].get("index_records") or [{}])[0]
            .get("current", {})
            .get("index_record_id")
            == baseline_b["index_record_id"]
        )
        event_change = replacement_event["payload"]["index_records"][0]
        self.assertEqual(event_change["previous"], baseline_a)
        self.assertEqual(event_change["current"], baseline_b)
        self.assertEqual(event_change["history_entry"], first_history)

        other_repo_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            second_id,
            "--index-id",
            project_a,
            expected_code=2,
        )
        self.assertEqual(
            other_repo_denied["error"]["code"], "INDEX_ID_CONFLICT"
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                for conflict in other_repo_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

        # A baseline may return to one of its own historical project IDs.
        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_a,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_b,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            [item["index_id"] for item in task["repositories"][0]["index_history"]],
            [project_a, project_b, project_a],
        )

        task = self.route_indexed_task_to_workspace(task)
        cross_role_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            cross_role_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                for conflict in cross_role_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

    def test_workspace_index_replacements_are_audited_and_generation_scoped(self) -> None:
        first, _ = self.make_repo("workspace-history-first")
        second, _ = self.make_repo("workspace-history-second")
        task = self.ready_workspace_task(
            first, second, task_id="workspace-index-history"
        )
        first_id = task["repositories"][0]["id"]
        second_id = task["repositories"][1]["id"]
        project_a = "workspace-history-project-a"
        project_b = "workspace-history-project-b"
        metadata = json.dumps({"persistence": False})

        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_a = dev_flow._copy_state(
            task["repositories"][0]["workspace_index"]
        )
        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_b,
            "--metadata-json",
            metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_b = dev_flow._copy_state(
            task["repositories"][0]["workspace_index"]
        )
        history = task["repositories"][0]["index_history"]
        self.assertEqual(len(history), 1)
        first_history = history[0]
        for key, value in workspace_a.items():
            self.assertEqual(first_history[key], value)
        self.assertEqual(first_history["replacement_role"], "workspace")
        self.assertEqual(first_history["replacement_project"], project_b)
        self.assertEqual(
            first_history["replacement_record_id"],
            workspace_b["index_record_id"],
        )

        other_repo_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            second_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
            expected_code=2,
        )
        self.assertEqual(
            other_repo_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                for conflict in other_repo_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

        # Same repository, role and generation may return to its own A project.
        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_a_again = task["repositories"][0]["workspace_index"]
        self.assertEqual(workspace_a_again["index_id"], project_a)
        self.assertEqual(
            [item["index_id"] for item in task["repositories"][0]["index_history"]],
            [project_a, project_b],
        )
        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / task["task_id"]
                / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        return_to_a = next(
            event
            for event in reversed(events)
            if event["type"] == "index_recorded"
            and (event["payload"].get("index_records") or [{}])[0]
            .get("current", {})
            .get("index_record_id")
            == workspace_a_again["index_record_id"]
        )
        self.assertEqual(
            return_to_a["payload"]["index_records"][0]["previous"],
            workspace_b,
        )

        self.mutate(
            "transition",
            task,
            "INDEXED",
            "--note",
            "move to the next workspace generation",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        cross_role_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            first_id,
            "--index-id",
            project_a,
            expected_code=2,
        )
        self.assertEqual(
            cross_role_denied["error"]["code"], "INDEX_ID_CONFLICT"
        )

        task = self.route_indexed_task_to_workspace(task)
        old_generation_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
            expected_code=2,
        )
        self.assertEqual(
            old_generation_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                and conflict.get("workspace_generation") == 0
                for conflict in old_generation_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

    def test_dual_index_roles_paths_and_read_only_phase_selection(self) -> None:
        repo, _ = self.make_repo("dual-index-selection")
        task = self.ready_workspace_task(
            repo, task_id="dual-index-selection"
        )
        repository = task["repositories"][0]
        baseline = repository["index"]
        workspace = repository["workspace"]
        self.assertEqual(baseline["role"], "baseline")
        self.assertEqual(
            baseline["repo_path"], repository["analysis_workspace"]["path"]
        )
        self.assertNotEqual(baseline["repo_path"], workspace["path"])

        before = self.cli("show", task["task_id"])
        selection = before["index_selection"]
        self.assertFalse(selection["automatic"])
        self.assertEqual(selection["selected_role"], "workspace")
        selected = selection["repositories"][0]
        self.assertIsNone(selected["recorded_project"])
        self.assertEqual(
            selected["recommended_project"],
            "devflow-dual-index-selection-dual-index-selection-workspace-r0",
        )
        self.assertEqual(
            selected["baseline"]["recorded_project"], baseline["index_id"]
        )
        self.assertEqual(selected["baseline"]["role"], "baseline")
        self.assertEqual(selected["workspace"]["role"], "workspace")

        response = self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--index-id",
            "actual-workspace-project",
            "--metadata-json",
            json.dumps({"persistence": False, "mode": "incremental"}),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_index = task["repositories"][0]["workspace_index"]
        self.assertEqual(response["role"], "workspace")
        self.assertEqual(workspace_index["role"], "workspace")
        self.assertEqual(workspace_index["repo_path"], workspace["path"])
        self.assertEqual(workspace_index["workspace_generation"], 0)
        self.assertEqual(
            workspace_index["workspace_plan_sha256"],
            task["workspace"]["plan"]["sha256"],
        )
        self.assertEqual(
            workspace_index["fingerprint_sha256"],
            dev_flow._fingerprint_repo(Path(workspace["path"]))["sha256"],
        )
        selected = response["index_selection"]["repositories"][0]
        self.assertEqual(selected["recorded_project"], "actual-workspace-project")
        self.assertNotEqual(
            selected["recorded_project"], selected["recommended_project"]
        )

        baseline_phase = dev_flow._copy_state(task)
        baseline_phase["status"] = "ROUTE_APPROVED"
        baseline_selection = dev_flow._result("probe", baseline_phase)[
            "index_selection"
        ]
        self.assertEqual(baseline_selection["selected_role"], "baseline")
        self.assertEqual(
            baseline_selection["repositories"][0]["recorded_project"],
            baseline["index_id"],
        )
        blocked_phase = dev_flow._copy_state(task)
        blocked_phase["status"] = "BLOCKED"
        blocked_phase["blocked"] = {"from_status": "ROUTE_APPROVED"}
        self.assertEqual(
            dev_flow._index_selection(blocked_phase)["selected_role"],
            "baseline",
        )
        done_phase = dev_flow._copy_state(task)
        done_phase["status"] = "DONE"
        self.assertEqual(
            dev_flow._index_selection(done_phase)["selected_role"],
            "workspace",
        )

    def test_workspace_index_gate_detects_changes_and_refresh_preserves_baseline_digest(self) -> None:
        repo, _ = self.make_repo("workspace-index-freshness")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-freshness"
        )
        missing = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(missing["error"]["code"], "WORKSPACE_INDEX_REQUIRED")

        baseline_digest = dev_flow._index_provenance_sha256(task)
        task = self.record_workspace_indexes(task)
        first_index = task["repositories"][0]["workspace_index"]
        self.assertEqual(
            dev_flow._index_provenance_sha256(task), baseline_digest
        )
        workspace = Path(task["repositories"][0]["workspace"]["path"])
        (workspace / "tracked.txt").write_text(
            "implementation changed\n", encoding="utf-8"
        )
        stale = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(stale["error"]["code"], "STALE_WORKSPACE_INDEX")
        self.assertEqual(
            stale["error"]["details"]["repositories"][0]["reason"],
            "workspace content changed after indexing",
        )

        task = self.record_workspace_indexes(task)
        refreshed = task["repositories"][0]["workspace_index"]
        self.assertEqual(refreshed["index_id"], first_index["index_id"])
        self.assertNotEqual(
            refreshed["index_record_id"], first_index["index_record_id"]
        )
        self.assertNotEqual(
            refreshed["fingerprint_sha256"],
            first_index["fingerprint_sha256"],
        )
        self.assertEqual(
            dev_flow._index_provenance_sha256(task), baseline_digest
        )

        git(workspace, "add", "tracked.txt")
        staged = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(staged["error"]["code"], "STALE_WORKSPACE_INDEX")
        task = self.record_workspace_indexes(task)

        (workspace / "new-untracked.txt").write_text(
            "untracked implementation evidence\n", encoding="utf-8"
        )
        untracked = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(untracked["error"]["code"], "STALE_WORKSPACE_INDEX")
        task = self.record_workspace_indexes(task)

        git(workspace, "add", "new-untracked.txt")
        git(workspace, "commit", "-q", "-m", "advance indexed workspace")
        committed = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(committed["error"]["code"], "STALE_WORKSPACE_INDEX")
        task = self.record_workspace_indexes(task)
        self.assertEqual(
            dev_flow._index_provenance_sha256(task), baseline_digest
        )
        transitioned = self.mutate("transition", task, "PLANNING")
        self.assertEqual(transitioned["status"], "PLANNING")

    def test_workspace_index_freshness_guards_execution_and_review_gates(self) -> None:
        repo, _ = self.make_repo("workspace-index-downstream-gates")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-downstream-gates"
        )
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        contract = self.root / "workspace-index-gate-contract.md"
        contract.write_text("approved gate contract\n", encoding="utf-8")
        plan = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "downstream gate contract approved",
            "--artifact-sha256",
            plan["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace = Path(task["repositories"][0]["workspace"]["path"])

        (workspace / "tracked.txt").write_text(
            "planning drift\n", encoding="utf-8"
        )
        implementing_denied = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "IMPLEMENTING",
            expected_code=2,
        )
        self.assertEqual(
            implementing_denied["error"]["code"], "STALE_WORKSPACE_INDEX"
        )
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)

        (workspace / "tracked.txt").write_text(
            "implementation drift\n", encoding="utf-8"
        )
        verifying_denied = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "VERIFYING",
            expected_code=2,
        )
        self.assertEqual(
            verifying_denied["error"]["code"], "STALE_WORKSPACE_INDEX"
        )
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "VERIFYING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "true",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state(task["task_id"], self.data)

        (workspace / "tracked.txt").write_text(
            "review drift\n", encoding="utf-8"
        )
        review_denied = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(
            review_denied["error"]["code"], "STALE_WORKSPACE_INDEX"
        )
        task = self.record_workspace_indexes(task)
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "true",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        snapshot = self.mutate("review-snapshot", task)
        self.assertEqual(snapshot["status"], "REVIEWING")

    def test_workspace_index_ids_are_isolated_and_multi_repo_gate_is_complete(self) -> None:
        first, _ = self.make_repo("workspace-index-first")
        second, _ = self.make_repo("workspace-index-second")
        task = self.ready_workspace_task(
            first, second, task_id="workspace-index-multi"
        )
        repositories = task["repositories"]
        first_id = repositories[0]["id"]
        second_id = repositories[1]["id"]
        first_project = dev_flow._recommended_index_name(
            task, repositories[0], "workspace"
        )

        missing_id = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            expected_code=2,
        )
        self.assertEqual(
            missing_id["error"]["code"], "WORKSPACE_INDEX_ID_REQUIRED"
        )
        missing_persistence = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            first_project,
            expected_code=2,
        )
        self.assertEqual(
            missing_persistence["error"]["code"],
            "PERSISTENT_WORKSPACE_INDEX_UNSUPPORTED",
        )
        persistent = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            first_project,
            "--metadata-json",
            json.dumps({"persistence": True}),
            expected_code=2,
        )
        self.assertEqual(
            persistent["error"]["code"],
            "PERSISTENT_WORKSPACE_INDEX_UNSUPPORTED",
        )
        same_for_all = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--index-id",
            "one-project-for-two-repositories",
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            same_for_all["error"]["code"], "WORKSPACE_INDEX_ID_CONFLICT"
        )
        baseline_conflict = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            repositories[1]["index"]["index_id"],
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            baseline_conflict["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )

        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            first_project,
            "--metadata-json",
            json.dumps({"persistence": False}),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        partial = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(partial["error"]["code"], "WORKSPACE_INDEX_REQUIRED")
        self.assertEqual(
            partial["error"]["details"]["repository_ids"], [second_id]
        )
        cross_repo_conflict = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            second_id,
            "--index-id",
            first_project,
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            cross_repo_conflict["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        task = self.record_workspace_indexes(task)
        transitioned = self.mutate("transition", task, "PLANNING")
        self.assertEqual(transitioned["status"], "PLANNING")

    def test_workspace_index_receipt_tampering_requires_refresh(self) -> None:
        repo, _ = self.make_repo("workspace-index-receipt")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-receipt"
        )
        receipt = self.root / "workspace-index-receipt.json"
        receipt.write_text('{"indexed": true}\n', encoding="utf-8")
        task = self.record_workspace_indexes(task, receipt=receipt)
        original = task["repositories"][0]["workspace_index"]["receipt"]
        receipt.write_text('{"indexed": false}\n', encoding="utf-8")
        stale = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(stale["error"]["code"], "STALE_WORKSPACE_INDEX")
        self.assertIn(
            "receipt",
            stale["error"]["details"]["repositories"][0]["reason"],
        )
        task = self.record_workspace_indexes(task, receipt=receipt)
        refreshed = task["repositories"][0]["workspace_index"]["receipt"]
        self.assertNotEqual(refreshed["sha256"], original["sha256"])
        self.mutate("transition", task, "PLANNING")

    def test_reassessment_archives_workspace_index_and_requires_new_generation_project(self) -> None:
        repo, _ = self.make_repo("workspace-index-reassessment")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-reassessment"
        )
        task = self.record_workspace_indexes(task)
        old_index = task["repositories"][0]["workspace_index"]
        old_project = old_index["index_id"]
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "transition",
            task,
            "INDEXED",
            "--note",
            "impact must be reassessed",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        repository = task["repositories"][0]
        self.assertIsNone(repository["workspace_index"])
        self.assertEqual(
            repository["workspace_history"][-1]["workspace_index"][
                "index_record_id"
            ],
            old_index["index_record_id"],
        )
        self.assertEqual(task["workspace"]["generation"], 1)
        self.assertEqual(
            dev_flow._index_selection(task)["selected_role"], "baseline"
        )
        baseline_reuse_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--index-id",
            old_project,
            expected_code=2,
        )
        self.assertEqual(
            baseline_reuse_denied["error"]["code"], "INDEX_ID_CONFLICT"
        )

        impact = self.root / "workspace-index-reassessed-impact.md"
        impact.write_text("reassessed impact\n", encoding="utf-8")
        impact_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "impact",
            "--path",
            str(impact),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "set-route",
            task,
            "direct",
            "--reason",
            "reassessed bounded change",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "reassessed route approved",
            "--artifact-sha256",
            impact_response["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        plan = self.mutate("prepare-workspace", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "new generation workspace approved",
            "--artifact-sha256",
            plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("prepare-workspace", task, "--execute")
        task = dev_flow.load_state(task["task_id"], self.data)
        old_project_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--index-id",
            old_project,
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            old_project_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        task = self.record_workspace_indexes(task)
        new_index = task["repositories"][0]["workspace_index"]
        self.assertNotEqual(new_index["index_id"], old_project)
        self.assertTrue(new_index["index_id"].endswith("-workspace-r1"))

    def test_schema_v1_state_without_additive_index_fields_remains_compatible(self) -> None:
        repo, _ = self.make_repo("legacy-workspace-index")
        task = self.start(repo, task_id="legacy-workspace-index")["task"]
        state_path = (
            self.data / "tasks" / task["task_id"] / "state.json"
        )
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy["repositories"][0].pop("workspace_index", None)
        legacy["repositories"][0].pop("index_history", None)
        dev_flow._atomic_write_json(state_path, legacy)

        loaded = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(loaded["schema_version"], 1)
        self.assertIsNone(loaded["repositories"][0]["workspace_index"])
        self.assertEqual(loaded["repositories"][0]["index_history"], [])
        shown = self.cli("show", task["task_id"])
        self.assertIsNone(shown["task"]["repositories"][0]["workspace_index"])
        self.assertEqual(shown["task"]["repositories"][0]["index_history"], [])
        self.assertIsNone(shown["index_selection"]["selected_role"])
        self.mutate("preflight", loaded)
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn("workspace_index", persisted["repositories"][0])
        self.assertEqual(persisted["repositories"][0]["index_history"], [])
        self.assertEqual(persisted["schema_version"], 1)

    def test_approval_events_preserve_overwritten_and_cleared_history(self) -> None:
        repo, _ = self.make_repo("approval-audit")
        task = self.start(repo, task_id="approval-audit")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        first = self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "first approval",
        )["approval"]
        task = dev_flow.load_state(task["task_id"], self.data)
        second = self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "replacement approval",
            "--allow-fetch",
        )["approval"]
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("preflight", task)
        cleared = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("baseline-fetch", cleared["approvals"])
        events_path = self.data / "tasks" / task["task_id"] / "events.jsonl"
        approval_events = [
            event
            for event in map(json.loads, events_path.read_text(encoding="utf-8").splitlines())
            if event["type"] == "gate_approved"
        ]
        self.assertEqual(len(approval_events), 2)
        self.assertEqual(
            [event["payload"]["approval"]["approval_id"] for event in approval_events],
            [first["approval_id"], second["approval_id"]],
        )
        self.assertEqual(
            [event["payload"]["approval"]["note"] for event in approval_events],
            ["first approval", "replacement approval"],
        )
        self.assertFalse(approval_events[0]["payload"]["approval"]["fetch_allowed"])
        self.assertTrue(approval_events[1]["payload"]["approval"]["fetch_allowed"])

    def test_directory_artifact_hash_changes_with_content(self) -> None:
        repo, _ = self.make_repo("artifact")
        task = self.start(repo)["task"]
        directory = self.root / "openspec-plan"
        (directory / "specs").mkdir(parents=True)
        (directory / "proposal.md").write_text("proposal one\n", encoding="utf-8")
        (directory / "specs" / "requirements.md").write_text("requirement\n", encoding="utf-8")
        first = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "directory-evidence",
            "--path",
            str(directory),
        )
        self.assertEqual(first["artifact"]["artifact_type"], "directory")
        self.assertEqual(first["artifact"]["file_count"], 2)
        task = dev_flow.load_state(task["task_id"], self.data)
        (directory / "proposal.md").write_text("proposal two\n", encoding="utf-8")
        drift_state = {
            "artifacts": [first["artifact"]],
            "approvals": {
                "evidence": {"artifact_sha256": first["artifact"]["sha256"]}
            },
        }
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._require_gate_for_latest_artifact(
                drift_state, "evidence", "directory-evidence"
            )
        self.assertEqual(captured.exception.code, "ARTIFACT_CHANGED")
        second = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "directory-evidence",
            "--path",
            str(directory),
        )
        self.assertNotEqual(first["artifact"]["sha256"], second["artifact"]["sha256"])

    def test_latest_passing_tests_are_aggregated_per_repository(self) -> None:
        first, _ = self.make_repo("test-first")
        second, _ = self.make_repo("test-second")
        first_repo = {"id": "first", "path": str(first), "workspace": None}
        second_repo = {"id": "second", "path": str(second), "workspace": None}
        first_fingerprint = dev_flow._fingerprint_repo(first)
        second_fingerprint = dev_flow._fingerprint_repo(second)
        plan_path = self.root / "aggregate-contract.md"
        plan_path.write_text("approved plan\n", encoding="utf-8")
        plan_sha = dev_flow._sha256_file(plan_path)
        approved_at = "2026-07-21T00:00:00.000Z"
        state = {
            "repositories": [first_repo, second_repo],
            "route": {"value": "direct"},
            "artifacts": [
                {
                    "artifact_id": "plan-1",
                    "kind": "direct-contract",
                    "path": str(plan_path),
                    "sha256": plan_sha,
                }
            ],
            "approvals": {
                "plan": {
                    "approval_id": "plan-approval-1",
                    "artifact_sha256": plan_sha,
                    "approved_at": approved_at,
                }
            },
            "tests": [
                {
                    "name": "integration",
                    "command": "run integration",
                    "passed": True,
                    "repository_ids": ["first"],
                    "fingerprints": {"first": first_fingerprint},
                    "plan_artifact_sha256": plan_sha,
                    "plan_approval_id": "plan-approval-1",
                    "recorded_at": "2026-07-21T00:00:01.000Z",
                },
                {
                    "name": "integration",
                    "command": "run integration",
                    "passed": True,
                    "repository_ids": ["second"],
                    "fingerprints": {"second": second_fingerprint},
                    "plan_artifact_sha256": plan_sha,
                    "plan_approval_id": "plan-approval-1",
                    "recorded_at": "2026-07-21T00:00:02.000Z",
                },
            ],
        }
        plan_gate = mock.patch.object(
            dev_flow,
            "_require_current_plan_gate",
            side_effect=lambda value, _kind: (
                value["approvals"]["plan"],
                value["artifacts"][0],
            ),
        )
        plan_gate.start()
        self.addCleanup(plan_gate.stop)
        self.assertEqual(dev_flow._latest_passing_test_is_current(state), (True, None))
        state["approvals"]["plan"]["approval_id"] = "plan-approval-2"
        current, reason = dev_flow._latest_passing_test_is_current(state)
        self.assertFalse(current)
        self.assertIn("current plan approval", reason)
        for repository_id, fingerprint, timestamp in (
            ("first", first_fingerprint, "2026-07-21T00:00:03.000Z"),
            ("second", second_fingerprint, "2026-07-21T00:00:04.000Z"),
        ):
            state["tests"].append(
                {
                    "name": "integration",
                    "command": "run integration",
                    "passed": True,
                    "repository_ids": [repository_id],
                    "fingerprints": {repository_id: fingerprint},
                    "plan_artifact_sha256": plan_sha,
                    "plan_approval_id": "plan-approval-2",
                    "recorded_at": timestamp,
                }
            )
        self.assertEqual(dev_flow._latest_passing_test_is_current(state), (True, None))
        state["tests"].append(
            {
                "name": "integration",
                "command": "run integration",
                "passed": False,
                "repository_ids": ["first"],
                "fingerprints": {"first": first_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:05.000Z",
            }
        )
        current, reason = dev_flow._latest_passing_test_is_current(state)
        self.assertFalse(current)
        self.assertIn("integration", reason)
        state["tests"].append(
            {
                "name": "lint",
                "command": "run lint",
                "passed": True,
                "repository_ids": ["first"],
                "fingerprints": {"first": first_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:06.000Z",
            }
        )
        current, reason = dev_flow._latest_passing_test_is_current(state)
        self.assertFalse(current)
        self.assertIn("integration", reason)
        state["tests"].append(
            {
                "name": "integration",
                "command": "run integration",
                "passed": True,
                "repository_ids": ["first"],
                "fingerprints": {"first": first_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:07.000Z",
            }
        )
        self.assertEqual(dev_flow._latest_passing_test_is_current(state), (True, None))
        state["tests"].append(
            {
                "name": "e2e",
                "command": "run e2e",
                "passed": False,
                "repository_ids": ["second"],
                "fingerprints": {"second": second_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:08.000Z",
            }
        )
        current, reason = dev_flow._latest_passing_test_is_current(state)
        self.assertFalse(current)
        self.assertIn("second", reason)

    def test_unrecorded_workspace_rejects_wrong_base_and_foreign_repo(self) -> None:
        repo, _ = self.make_repo("workspace-source")
        repo = repo.resolve()
        (repo / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
        git(repo, "add", ".gitignore")
        git(repo, "commit", "-q", "-m", "add ignore rule")
        base = git(repo, "rev-parse", "HEAD")
        tree = git(repo, "rev-parse", "HEAD^{tree}")
        ahead = git(repo, "commit-tree", tree, "-p", base, "-m", "unrelated old work")
        branch = "codex/collision"
        git(repo, "update-ref", f"refs/heads/{branch}", ahead)
        wrong_base_plan = {
            "repository_id": "source",
            "source_path": str(repo),
            "path": str((self.root / "wrong-base-workspace").resolve()),
            "branch": branch,
            "base_sha": base,
            "strategy": "worktree",
            "previously_recorded": False,
        }
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._execute_worktree(wrong_base_plan)
        self.assertEqual(captured.exception.code, "WORKSPACE_BASE_MISMATCH")
        self.assertFalse(Path(wrong_base_plan["path"]).exists())

        source_checkout_plan = {
            "repository_id": "source",
            "source_path": str(repo),
            "path": str(repo),
            "branch": "main",
            "base_sha": base,
            "strategy": "worktree",
            "previously_recorded": False,
        }
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._execute_worktree(source_checkout_plan)
        self.assertEqual(captured.exception.code, "WORKSPACE_COLLISION")
        self.assertFalse(captured.exception.details["linked_worktree"])

        foreign, _ = self.make_repo("workspace-foreign")
        foreign_plan = {
            "repository_id": "source",
            "source_path": str(repo),
            "path": str(foreign),
            "branch": "main",
            "base_sha": base,
            "strategy": "worktree",
            "previously_recorded": False,
        }
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._execute_worktree(foreign_plan)
        self.assertEqual(captured.exception.code, "WORKSPACE_COLLISION")
        self.assertFalse(captured.exception.details["same_common_dir"])

        unowned_branch = "codex/recover-clean"
        unowned_path = (self.root / "unowned-linked-worktree").resolve()
        git(
            repo,
            "worktree",
            "add",
            "-b",
            unowned_branch,
            str(unowned_path),
            base,
        )
        unowned_plan = {
            "repository_id": "source",
            "source_path": str(repo),
            "path": str(unowned_path),
            "branch": unowned_branch,
            "base_sha": base,
            "strategy": "worktree",
            "owner_task_id": "recovery-task",
            "previously_recorded": False,
        }
        recovered = dev_flow._execute_worktree(unowned_plan)
        self.assertFalse(recovered["created"])
        self.assertTrue(recovered["recovered_unrecorded"])
        self.assertEqual(
            Path(git(unowned_path, "rev-parse", "--show-toplevel")).resolve(),
            unowned_path,
        )

        for dirty_kind in ("cached", "unstaged", "untracked", "ignored"):
            with self.subTest(dirty_kind=dirty_kind):
                dirty_branch = f"codex/unowned-{dirty_kind}"
                dirty_path = (
                    self.root / f"unowned-linked-worktree-{dirty_kind}"
                ).resolve()
                git(
                    repo,
                    "worktree",
                    "add",
                    "-b",
                    dirty_branch,
                    str(dirty_path),
                    base,
                )
                if dirty_kind == "cached":
                    (dirty_path / "cached.txt").write_text("cached\n", encoding="utf-8")
                    git(dirty_path, "add", "cached.txt")
                elif dirty_kind == "unstaged":
                    (dirty_path / "tracked.txt").write_text(
                        "unstaged\n", encoding="utf-8"
                    )
                elif dirty_kind == "untracked":
                    (dirty_path / "untracked.txt").write_text(
                        "untracked\n", encoding="utf-8"
                    )
                else:
                    (dirty_path / "residual.ignored").write_text(
                        "ignored\n", encoding="utf-8"
                    )
                dirty_plan = {
                    **unowned_plan,
                    "path": str(dirty_path),
                    "branch": dirty_branch,
                }
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._execute_worktree(dirty_plan)
                self.assertEqual(captured.exception.code, "WORKSPACE_COLLISION")
                details = captured.exception.details
                self.assertEqual(details["reason"], "unrecorded_worktree_not_clean")
                self.assertTrue(details["dirty"])
                self.assertTrue(details["linked_worktree"])
                self.assertTrue(details["same_common_dir"])
                self.assertEqual(Path(details["actual_root"]).resolve(), dirty_path)
                self.assertTrue(details["status_porcelain"])

    def test_workspace_plan_rejects_source_and_analysis_overlap(self) -> None:
        repo, _ = self.make_repo("workspace-overlap")
        analysis_path = self.root / "analysis-owned"
        record = {
            "id": "workspace-overlap",
            "path": str(repo),
            "protected_branches": ["main", "master", "trunk"],
            "baseline": {
                "base_branch": "main",
                "base_sha": git(repo, "rev-parse", "HEAD"),
            },
            "analysis_workspace": {"path": str(analysis_path), "ready": True},
            "workspace": None,
        }
        state = {
            "task_id": "overlap-task",
            "workspace": {"generation": 0},
            "repositories": [record],
        }
        for invalid_path in (
            repo,
            analysis_path,
            analysis_path / "nested",
            self.data,
            self.data / "tasks" / "another-task",
            self.data / "analysis" / "another-task",
            self.data / "workspace-registry.json",
            self.data / "workspace-registry.lock",
            self.data / "workspaces" / "another-task" / record["id"],
            self.data / "workspaces" / state["task_id"] / "r1" / record["id"],
        ):
            with self.subTest(path=invalid_path):
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._workspace_plan(
                        state,
                        [record],
                        self.data,
                        None,
                        str(invalid_path),
                    )
                self.assertEqual(captured.exception.code, "WORKSPACE_NOT_ISOLATED")
        self.assertFalse((self.data / "workspace-registry.json").exists())

        worktree_container = self.root / "user-worktree-container"
        worktree_container.mkdir()
        user_worktree = worktree_container / "registered"
        git(
            repo,
            "worktree",
            "add",
            "-q",
            "-b",
            "user-owned-worktree",
            str(user_worktree),
            "HEAD",
        )
        for invalid_path in (
            user_worktree,
            user_worktree / "nested",
            worktree_container,
        ):
            with self.subTest(registered_worktree_overlap=invalid_path):
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._workspace_plan(
                        state,
                        [record],
                        self.data,
                        "codex/isolated-candidate",
                        str(invalid_path),
                    )
                self.assertEqual(captured.exception.code, "WORKSPACE_NOT_ISOLATED")
        self.assertFalse((user_worktree / "nested").exists())

        symbolic_branch = "codex/symbolic-workspace"
        git(
            repo,
            "symbolic-ref",
            f"refs/heads/{symbolic_branch}",
            "refs/heads/main",
        )
        symbolic_path = self.root / "symbolic-workspace"
        with self.assertRaises(dev_flow.FlowError) as symbolic_error:
            dev_flow._workspace_plan(
                state,
                [record],
                self.data,
                symbolic_branch,
                str(symbolic_path),
            )
        self.assertEqual(
            symbolic_error.exception.code, "SYMBOLIC_WORKSPACE_BRANCH"
        )
        self.assertFalse(symbolic_path.exists())

    def test_controller_worktree_creation_disables_checkout_hooks(self) -> None:
        repo, _ = self.make_repo("workspace-hook-dirty")
        repo = repo.resolve()
        (repo / ".gitignore").write_text("generated.ignored\n", encoding="utf-8")
        git(repo, "add", ".gitignore")
        git(repo, "commit", "-q", "-m", "ignore generated hook output")
        hook = repo / ".git" / "hooks" / "post-checkout"
        external_marker = self.root / "post-checkout-hook-ran"
        hook.write_text(
            "#!/bin/sh\n"
            "worktree=$(git rev-parse --show-toplevel)\n"
            ": > \"$worktree/generated.ignored\"\n"
            f": > \"{external_marker}\"\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        plan = {
            "repository_id": "workspace-hook-dirty",
            "source_path": str(repo),
            "path": str((self.root / "hook-dirty-workspace").resolve()),
            "branch": "codex/hook-dirty",
            "base_sha": git(repo, "rev-parse", "HEAD"),
            "strategy": "worktree",
            "owner_task_id": "hook-dirty-task",
            "previously_recorded": False,
        }
        outcome = dev_flow._execute_worktree(plan)
        self.assertTrue(outcome["ready"])
        self.assertTrue(outcome["created"])
        self.assertFalse(Path(plan["path"], "generated.ignored").exists())
        self.assertFalse(external_marker.exists())

    def test_workspace_plan_must_cover_every_repository(self) -> None:
        first, _ = self.make_repo("plan-first")
        second, _ = self.make_repo("plan-second")
        impact = self.root / "multi-impact.md"
        impact.write_text("impact\n", encoding="utf-8")
        impact_sha = dev_flow._sha256_file(impact)
        repositories = []
        for repo_id, path in (("first", first), ("second", second)):
            repositories.append(
                {
                    "id": repo_id,
                    "path": str(path),
                    "canonical_path": str(path),
                    "protected_branches": ["main", "master", "trunk"],
                    "baseline": {
                        "base_branch": "main",
                        "base_sha": git(path, "rev-parse", "HEAD"),
                    },
                    "workspace": None,
                    "workspace_history": [],
                }
            )
        task_id = "all-repo-plan"
        state = {
            "schema_version": dev_flow.SCHEMA_VERSION,
            "task_id": task_id,
            "requirement": "multi repository plan",
            "status": "ROUTE_APPROVED",
            "revision": 1,
            "created_at": "2026-07-21T00:00:00.000Z",
            "updated_at": "2026-07-21T00:00:00.000Z",
            "route": {"value": "direct"},
            "repositories": repositories,
            "artifacts": [
                {
                    "artifact_id": "impact-1",
                    "kind": "impact",
                    "path": str(impact),
                    "sha256": impact_sha,
                }
            ],
            "approvals": {
                "route": {
                    "approval_id": "route-1",
                    "artifact_sha256": impact_sha,
                }
            },
            "tests": [],
            "review_snapshots": [],
            "workspace": {"strategy": "worktree", "ready": False, "generation": 0},
            "blocked": None,
            "cancelled": None,
        }
        state_path = self.data / "tasks" / task_id / "state.json"
        dev_flow._atomic_write_json(state_path, state)
        response = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            "1",
            "--repo",
            "first",
            expected_code=2,
        )
        self.assertEqual(response["error"]["code"], "INCOMPLETE_WORKSPACE_PLAN")

    def test_workspace_claims_block_cross_task_path_and_branch_reuse(self) -> None:
        repo, _ = self.make_repo("shared-claim-source")
        repo = repo.resolve()
        base_sha = git(repo, "rev-parse", "HEAD")

        def write_route_approved_state(task_id: str) -> dict:
            repository_id = "shared-claim-source"
            state = {
                "schema_version": dev_flow.SCHEMA_VERSION,
                "task_id": task_id,
                "requirement": "claim one isolated workspace",
                "status": "ROUTE_APPROVED",
                "revision": 1,
                "created_at": "2026-07-21T00:00:00.000Z",
                "updated_at": "2026-07-21T00:00:00.000Z",
                "route": None,
                "repositories": [
                    {
                        "id": repository_id,
                        "path": str(repo),
                        "canonical_path": str(repo),
                        "protected_branches": ["main", "master", "trunk"],
                        "preflight": None,
                        "baseline": {
                            "base_branch": "main",
                            "base_sha": base_sha,
                        },
                        "analysis_workspace": None,
                        "index": {
                            "index_record_id": f"index-{task_id}",
                            "commit_sha": base_sha,
                            "index_id": f"memory-{task_id}",
                            "receipt": None,
                            "metadata": {},
                            "impact_degraded_approval_id": None,
                        },
                        "workspace": None,
                        "workspace_history": [],
                    }
                ],
                "artifacts": [],
                "approvals": {},
                "tests": [],
                "review_snapshots": [],
                "impact_generation": 0,
                "planning_generation": 0,
                "workspace": {
                    "strategy": "worktree",
                    "ready": False,
                    "generation": 0,
                },
                "blocked": None,
                "cancelled": None,
            }
            index_digest = dev_flow._index_provenance_sha256(state)
            impact_path = self.root / f"{task_id}-impact.md"
            impact_path.write_text("shared repository impact\n", encoding="utf-8")
            impact_sha = dev_flow._sha256_file(impact_path)
            impact_id = f"impact-{task_id}"
            state["artifacts"].append(
                {
                    "artifact_id": impact_id,
                    "kind": "impact",
                    "path": str(impact_path),
                    "sha256": impact_sha,
                    "metadata": {
                        "index_provenance_sha256": index_digest,
                        "impact_generation": 0,
                    },
                }
            )
            state["route"] = {
                "value": "direct",
                "reason": "bounded shared repository change",
                "impact_artifact_id": impact_id,
                "impact_sha256": impact_sha,
                "index_provenance_sha256": index_digest,
                "impact_generation": 0,
            }
            state["approvals"]["route"] = {
                "approval_id": f"route-{task_id}",
                "artifact_sha256": impact_sha,
                "artifact_id": impact_id,
                "index_provenance_sha256": index_digest,
                "impact_generation": 0,
            }
            dev_flow._atomic_write_json(
                self.data / "tasks" / task_id / "state.json", state
            )
            return state

        first = write_route_approved_state("claim-owner")
        second = write_route_approved_state("claim-contender")
        claimed_path = (self.root / "claimed-workspace").resolve()
        claimed_branch = "codex/shared-claim"
        first_plan = self.cli(
            "prepare-workspace",
            first["task_id"],
            "--expected-revision",
            str(first["revision"]),
            "--path",
            str(claimed_path),
            "--branch",
            claimed_branch,
        )
        registry_path = self.data / "workspace-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        owner_claims = [
            claim
            for claim in registry["claims"]
            if claim["task_id"] == first["task_id"]
        ]
        self.assertEqual(len(owner_claims), 1)
        self.assertFalse(claimed_path.exists())

        same_path = self.cli(
            "prepare-workspace",
            second["task_id"],
            "--expected-revision",
            str(second["revision"]),
            "--path",
            str(claimed_path),
            "--branch",
            "codex/different-branch",
            expected_code=2,
        )
        self.assertEqual(
            same_path["error"]["code"], "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(same_path["error"]["details"]["conflict"], "path")
        self.assertFalse(claimed_path.exists())

        same_branch_path = (self.root / "different-claim-path").resolve()
        same_branch = self.cli(
            "prepare-workspace",
            second["task_id"],
            "--expected-revision",
            str(second["revision"]),
            "--path",
            str(same_branch_path),
            "--branch",
            claimed_branch,
            expected_code=2,
        )
        self.assertEqual(
            same_branch["error"]["code"], "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(same_branch["error"]["details"]["conflict"], "branch")
        self.assertFalse(same_branch_path.exists())
        prefixed_branch_path = (self.root / "prefixed-claim-path").resolve()
        prefixed_branch = self.cli(
            "prepare-workspace",
            second["task_id"],
            "--expected-revision",
            str(second["revision"]),
            "--path",
            str(prefixed_branch_path),
            "--branch",
            f"{claimed_branch}/nested",
            expected_code=2,
        )
        self.assertEqual(
            prefixed_branch["error"]["code"], "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(
            prefixed_branch["error"]["details"]["conflict"], "branch"
        )
        self.assertFalse(prefixed_branch_path.exists())
        self.assertEqual(
            dev_flow.load_state(second["task_id"], self.data)["revision"], 1
        )

        first = dev_flow.load_state(first["task_id"], self.data)
        self.mutate(
            "approve",
            first,
            "--gate",
            "workspace",
            "--note",
            "the durable claim and exact plan are approved",
            "--artifact-sha256",
            first_plan["plan_artifact"]["sha256"],
        )
        first = dev_flow.load_state(first["task_id"], self.data)
        executed = self.mutate(
            "prepare-workspace",
            first,
            "--execute",
            "--path",
            str(claimed_path),
            "--branch",
            claimed_branch,
        )
        self.assertTrue(executed["complete"])
        ready = dev_flow.load_state(first["task_id"], self.data)
        ready = self.record_workspace_indexes(ready)
        receipt = ready["repositories"][0]["workspace"]["workspace_claim"]
        self.assertEqual(receipt["plan_sha256"], first_plan["plan_artifact"]["sha256"])

        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        claimed = next(
            claim
            for claim in registry["claims"]
            if claim["claim_id"] == receipt["claim_id"]
        )
        claimed["branch"] = "codex/tampered-claim"
        dev_flow._atomic_write_json(registry_path, registry)
        stale_receipt = self.cli(
            "transition",
            ready["task_id"],
            "--expected-revision",
            str(ready["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(
            stale_receipt["error"]["code"], "STALE_WORKSPACE_INDEX"
        )

    def test_workspace_claim_rejects_sibling_plans_for_the_same_branch_store(self) -> None:
        repo, _ = self.make_repo("sibling-claim-source")
        linked_source = self.root / "sibling-linked-source"
        git(
            repo,
            "worktree",
            "add",
            "-q",
            "-b",
            "sibling-source",
            str(linked_source),
            "HEAD",
        )
        state = {
            "task_id": "sibling-claims",
            "workspace": {"generation": 0},
        }
        branch = "codex/sibling-claims"
        plans = [
            {
                "repository_id": "first",
                "source_path": str(repo),
                "path": str(self.root / "sibling-workspace-first"),
                "branch": branch,
            },
            {
                "repository_id": "second",
                "source_path": str(linked_source),
                "path": str(self.root / "sibling-workspace-second"),
                "branch": branch,
            },
        ]
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._claim_workspace_plan(self.data, state, "a" * 64, plans)
        self.assertEqual(
            captured.exception.code, "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(captured.exception.details["conflict"], "branch")
        self.assertFalse((self.data / "workspace-registry.json").exists())
        self.assertFalse(Path(plans[0]["path"]).exists())
        self.assertFalse(Path(plans[1]["path"]).exists())

    def test_multi_repo_workspace_overrides_are_exact_and_executable(self) -> None:
        first, _ = self.make_repo("override-first")
        second, _ = self.make_repo("override-second")
        first = first.resolve()
        second = second.resolve()
        task_id = "all-repo-overrides"
        repositories = []
        for repo_id, path in (("first", first), ("second", second)):
            base_sha = git(path, "rev-parse", "HEAD")
            repositories.append(
                {
                    "id": repo_id,
                    "path": str(path),
                    "canonical_path": str(path),
                    "protected_branches": ["main", "master", "trunk"],
                    "baseline": {"base_branch": "main", "base_sha": base_sha},
                    "index": {
                        "index_record_id": f"index-{repo_id}",
                        "commit_sha": base_sha,
                        "index_id": f"memory-{repo_id}",
                        "receipt": None,
                        "metadata": {},
                        "impact_degraded_approval_id": None,
                    },
                    "workspace": None,
                    "workspace_history": [],
                }
            )
        state = {
            "schema_version": dev_flow.SCHEMA_VERSION,
            "task_id": task_id,
            "requirement": "multi repository workspace overrides",
            "status": "ROUTE_APPROVED",
            "revision": 1,
            "created_at": "2026-07-21T00:00:00.000Z",
            "updated_at": "2026-07-21T00:00:00.000Z",
            "route": None,
            "repositories": repositories,
            "artifacts": [],
            "approvals": {},
            "tests": [],
            "review_snapshots": [],
            "impact_generation": 0,
            "planning_generation": 0,
            "workspace": {"strategy": "worktree", "ready": False, "generation": 0},
            "blocked": None,
            "cancelled": None,
        }
        index_digest = dev_flow._index_provenance_sha256(state)
        impact_path = self.root / "override-impact.md"
        impact_path.write_text("all repositories covered\n", encoding="utf-8")
        impact_sha = dev_flow._sha256_file(impact_path)
        impact_id = "override-impact"
        state["artifacts"].append(
            {
                "artifact_id": impact_id,
                "kind": "impact",
                "path": str(impact_path),
                "sha256": impact_sha,
                "metadata": {
                    "index_provenance_sha256": index_digest,
                    "impact_generation": 0,
                },
            }
        )
        state["route"] = {
            "value": "direct",
            "reason": "bounded change",
            "impact_artifact_id": impact_id,
            "impact_sha256": impact_sha,
            "index_provenance_sha256": index_digest,
            "impact_generation": 0,
        }
        state["approvals"]["route"] = {
            "approval_id": "route-approval",
            "artifact_sha256": impact_sha,
            "artifact_id": impact_id,
            "index_provenance_sha256": index_digest,
            "impact_generation": 0,
        }
        dev_flow._atomic_write_json(
            self.data / "tasks" / task_id / "state.json", state
        )
        revision = "1"
        custom_path = (self.root / "custom-first-workspace").resolve()
        other_path = (self.root / "different-first-workspace").resolve()

        unknown = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"missing={custom_path}",
            expected_code=2,
        )
        self.assertEqual(unknown["error"]["code"], "REPOSITORY_NOT_FOUND")
        duplicate = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"first={custom_path}",
            "--workspace-path",
            f"first={other_path}",
            expected_code=2,
        )
        self.assertEqual(
            duplicate["error"]["code"], "DUPLICATE_WORKSPACE_OVERRIDE"
        )
        relative = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            "first=relative/path",
            expected_code=2,
        )
        self.assertEqual(relative["error"]["code"], "INVALID_ARGUMENT")
        shared_path = (self.root / "shared-workspace").resolve()
        collision = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"first={shared_path}",
            "--workspace-path",
            f"second={shared_path}",
            expected_code=2,
        )
        self.assertEqual(collision["error"]["code"], "WORKSPACE_PLAN_COLLISION")

        planned = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"first={custom_path}",
            "--workspace-branch",
            "first=codex/custom-first",
        )
        by_id = {plan["repository_id"]: plan for plan in planned["plans"]}
        self.assertEqual(by_id["first"]["path"], str(custom_path))
        self.assertEqual(by_id["first"]["branch"], "codex/custom-first")
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "exact multi-repository workspace plan approved",
            "--artifact-sha256",
            planned["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task_id, self.data)
        mismatch = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            str(task["revision"]),
            "--execute",
            "--workspace-path",
            f"first={other_path}",
            "--workspace-branch",
            "first=codex/custom-first",
            expected_code=2,
        )
        self.assertEqual(mismatch["error"]["code"], "WORKSPACE_PLAN_MISMATCH")
        executed = self.mutate(
            "prepare-workspace",
            task,
            "--execute",
            "--workspace-path",
            f"first={custom_path}",
            "--workspace-branch",
            "first=codex/custom-first",
        )
        self.assertTrue(executed["complete"])
        self.assertTrue(custom_path.is_dir())
        self.assertEqual(git(custom_path, "branch", "--show-current"), "codex/custom-first")

    def test_absent_scope_configuration_stays_active_everywhere(self) -> None:
        elsewhere = self.root / "unrelated"
        elsewhere.mkdir()
        response = self.cli("scope", "--check", str(elsewhere))
        self.assertEqual(response["effective"]["mode"], "all")
        self.assertEqual(response["summary"], "active in every directory")
        self.assertFalse(response["changed"])
        self.assertTrue(response["check"]["in_scope"])
        self.assertEqual(response["check"]["rule"], "default")
        # Reading the scope must not create configuration the user never asked for.
        self.assertFalse(Path(response["config_path"]).exists())

    def test_first_included_directory_activates_the_allowlist(self) -> None:
        included = self.root / "included"
        included.mkdir()
        excluded = self.root / "elsewhere"
        excluded.mkdir()
        response = self.cli("scope", "--add", str(included))
        self.assertTrue(response["changed"])
        self.assertEqual(response["scope"]["mode"], "allowlist")
        self.assertEqual(response["scope"]["include"], self.canonical(included))
        self.assertEqual(response["missing_paths"], [])
        self.assertTrue(
            self.cli("scope", "--check", str(included / "nested" / "deep"))["check"][
                "in_scope"
            ]
        )
        self.assertFalse(self.cli("scope", "--check", str(excluded))["check"]["in_scope"])
        # A second addition must not silently flip the mode back.
        second = self.cli("scope", "--add", str(excluded))
        self.assertEqual(second["scope"]["mode"], "allowlist")
        self.assertEqual(second["scope"]["include"], self.canonical(included, excluded))
        repeated = self.cli("scope", "--add", str(included))
        self.assertFalse(repeated["changed"])

    def test_scope_matching_prefers_the_deepest_configured_directory(self) -> None:
        work = self.root / "work"
        vendor = work / "vendor"
        mine = vendor / "mine"
        mine.mkdir(parents=True)
        self.cli(
            "scope",
            "--add",
            str(work),
            "--add-exclude",
            str(vendor),
            "--add",
            str(mine),
        )
        for path, expected, rule in (
            (work / "app", True, "include"),
            (vendor / "other", False, "exclude"),
            (mine / "deep", True, "include"),
            (self.root / "outside", False, "default"),
        ):
            with self.subTest(path=path):
                check = self.cli("scope", "--check", str(path))["check"]
                self.assertEqual(check["in_scope"], expected)
                self.assertEqual(check["rule"], rule)
        # An exactly overlapping pair resolves to the exclusion.
        self.cli("scope", "--add-exclude", str(work))
        self.assertFalse(self.cli("scope", "--check", str(work / "app"))["check"]["in_scope"])

    def test_denylist_mode_excludes_without_an_allowlist(self) -> None:
        skipped = self.root / "skipped"
        skipped.mkdir()
        response = self.cli("scope", "--mode", "all", "--add-exclude", str(skipped))
        self.assertEqual(response["scope"]["mode"], "all")
        self.assertEqual(response["summary"], "active in every directory except the excluded ones")
        self.assertFalse(self.cli("scope", "--check", str(skipped / "a"))["check"]["in_scope"])
        self.assertTrue(self.cli("scope", "--check", str(self.root))["check"]["in_scope"])

    def test_environment_overrides_the_stored_scope(self) -> None:
        stored = self.root / "stored"
        stored.mkdir()
        override = self.root / "override"
        override.mkdir()
        self.cli("scope", "--add", str(stored))
        with mock.patch.dict(os.environ, {dev_flow.SCOPE_INCLUDE_ENV: str(override)}):
            response = self.cli("scope", "--check", str(stored))
            self.assertEqual(response["overrides"], {"include": dev_flow.SCOPE_INCLUDE_ENV})
            self.assertEqual(response["effective"]["include"], self.canonical(override))
            # The stored configuration is reported unchanged next to the override.
            self.assertEqual(response["scope"]["include"], self.canonical(stored))
            self.assertFalse(response["check"]["in_scope"])
            self.assertTrue(self.cli("scope", "--check", str(override))["check"]["in_scope"])
        with mock.patch.dict(
            os.environ,
            {dev_flow.SCOPE_EXCLUDE_ENV: str(stored / "vendor")},
        ):
            response = self.cli("scope", "--check", str(stored / "vendor" / "x"))
            self.assertEqual(response["effective"]["mode"], "allowlist")
            self.assertFalse(response["check"]["in_scope"])
        self.assertTrue(self.cli("scope", "--check", str(stored))["check"]["in_scope"])

    def test_scope_edits_are_validated_and_reversible(self) -> None:
        included = self.root / "included"
        included.mkdir()
        self.cli("scope", "--add", str(included))
        missing = self.cli("scope", "--add", str(self.root / "not-created"))
        self.assertEqual(missing["missing_paths"], self.canonical(self.root / "not-created"))
        unknown = self.cli("scope", "--remove", str(self.root / "never"), expected_code=2)
        self.assertEqual(unknown["error"]["code"], "SCOPE_PATH_NOT_CONFIGURED")
        invalid = self.cli("scope", "--mode", "sometimes", expected_code=2)
        self.assertEqual(invalid["error"]["code"], "INVALID_ARGUMENT")
        muted = self.cli(
            "scope",
            "--remove",
            str(included),
            "--remove",
            str(self.root / "not-created"),
            "--check",
            str(included),
        )
        self.assertEqual(muted["summary"], "inactive in every directory")
        self.assertFalse(muted["check"]["in_scope"])
        cleared = self.cli("scope", "--clear", "--check", str(self.root / "anywhere"))
        self.assertEqual(cleared["scope"], {"mode": "all", "include": [], "exclude": []})
        self.assertTrue(cleared["check"]["in_scope"])

    def test_unusable_scope_configuration_is_reported(self) -> None:
        config = self.data / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("{ not json", encoding="utf-8")
        unreadable = self.cli("scope", expected_code=2)
        self.assertEqual(unreadable["error"]["code"], "CONFIG_INVALID")
        config.write_text(
            json.dumps({"schema_version": 1, "scope": {"mode": "sometimes"}}),
            encoding="utf-8",
        )
        bad_mode = self.cli("scope", expected_code=2)
        self.assertEqual(bad_mode["error"]["code"], "CONFIG_INVALID")
        blocked = self.cli("scope", "--add", str(self.root), expected_code=2)
        self.assertEqual(blocked["error"]["code"], "CONFIG_INVALID")
        # Clearing is the recovery path and must not need a readable file.
        recovered = self.cli("scope", "--clear")
        self.assertTrue(recovered["changed"])
        self.assertEqual(recovered["scope"], {"mode": "all", "include": [], "exclude": []})

    def test_start_refuses_a_repository_outside_the_configured_scope(self) -> None:
        repo, _ = self.make_repo("scoped")
        included = self.root / "included"
        included.mkdir()
        self.cli("scope", "--add", str(included))
        rejected = self.cli(
            "start",
            "--task-id",
            "out-of-scope",
            "--requirement",
            "Implement deterministic flow",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(rejected["error"]["code"], "OUT_OF_SCOPE")
        self.assertEqual(rejected["error"]["details"]["path"], str(repo.resolve()))
        self.assertEqual(
            rejected["error"]["details"]["config_path"],
            str(dev_flow.config_path(self.data)),
        )
        self.assertFalse((self.data / "tasks" / "out-of-scope").exists())
        self.cli("scope", "--add", str(repo))
        accepted = self.start(repo, task_id="in-scope")
        self.assertEqual(accepted["task"]["status"], "INTAKE")

    def start_lite(self, *repos: Path, task_id: str = "lite-1") -> dict:
        arguments = [
            "start",
            "--task-id",
            task_id,
            "--flow",
            "lite",
            "--requirement",
            "Fix a bounded bug in place",
        ]
        for repo in repos:
            arguments.extend(["--repo", str(repo)])
        return self.cli(*arguments)

    def approved_lite_task(
        self, repo: Path, *, task_id: str = "lite-1", allow_dirty: bool = False
    ) -> dict:
        self.start_lite(repo, task_id=task_id)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state(task_id, self.data)
        arguments = ["--gate", "lite", "--note", "in-place fix approved"]
        if allow_dirty:
            arguments.append("--allow-dirty")
        self.mutate("approve", task, *arguments)
        return dev_flow.load_state(task_id, self.data)

    def test_lite_flow_runs_in_place_to_done(self) -> None:
        repo, _ = self.make_repo("lite-repo")
        response = self.start_lite(repo)
        self.assertEqual(response["flow"], "lite")
        task = response["task"]
        self.assertEqual(task["flow"], "lite")
        self.assertEqual(task["workspace"]["strategy"], "in-place")
        self.assertIsNone(response["index_selection"]["selected_role"])

        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-1", self.data)
        self.assertEqual(task["status"], "PREFLIGHTED")

        approved = self.mutate(
            "approve", task, "--gate", "lite", "--note", "fix in place"
        )
        self.assertTrue(approved["approval"]["preflight_evidence_sha256"])
        self.assertEqual(
            approved["approval"]["preflight_evidence_sha256"],
            dev_flow._lite_preflight_evidence_sha256(
                dev_flow.load_state("lite-1", self.data)
            ),
        )

        task = dev_flow.load_state("lite-1", self.data)
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-1", self.data)
        self.assertEqual(task["status"], "IMPLEMENTING")
        self.assertIsNone(
            dev_flow._index_selection(task)["selected_role"]
        )

        (repo / "tracked.txt").write_text("fixed in place\n", encoding="utf-8")
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-1", self.data)

        recorded = self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        self.assertIn("lite_approval_id", recorded["test"])
        self.assertNotIn("plan_artifact_sha256", recorded["test"])
        task = dev_flow.load_state("lite-1", self.data)
        self.mutate("transition", task, "--to", "DONE")
        self.assertEqual(dev_flow.load_state("lite-1", self.data)["status"], "DONE")

    def test_lite_flow_rejects_full_flow_commands_and_gates(self) -> None:
        repo, _ = self.make_repo("lite-guard")
        self.start_lite(repo, task_id="lite-guard")
        task = dev_flow.load_state("lite-guard", self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-guard", self.data)

        for arguments in (
            ["approve", "--gate", "baseline-fetch", "--note", "no"],
            ["baseline", "--materialize"],
            ["record-index", "--index-id", "nope"],
            ["set-route", "direct", "--reason", "no"],
            ["prepare-workspace"],
            ["review-snapshot"],
        ):
            with self.subTest(command=arguments[0], arguments=arguments[1:]):
                rejected = self.mutate(
                    arguments[0], task, *arguments[1:], expected_code=2
                )
                self.assertEqual(rejected["error"]["code"], "FLOW_MISMATCH")

        blocked_transition = self.mutate(
            "transition", task, "--to", "BASELINED", expected_code=2
        )
        self.assertEqual(
            blocked_transition["error"]["code"], "INVALID_TRANSITION"
        )
        self.assertEqual(
            blocked_transition["error"]["details"]["allowed"],
            ["BLOCKED", "CANCELLED", "IMPLEMENTING"],
        )

        full_repo, _ = self.make_repo("full-guard")
        self.start(full_repo, task_id="full-guard")
        full_task = dev_flow.load_state("full-guard", self.data)
        rejected = self.mutate(
            "approve",
            full_task,
            "--gate",
            "lite",
            "--note",
            "not applicable",
            expected_code=2,
        )
        self.assertEqual(rejected["error"]["code"], "FLOW_MISMATCH")

    def test_lite_gate_requires_allow_dirty_and_a_fresh_preflight(self) -> None:
        repo, _ = self.make_repo("lite-dirty")
        (repo / "tracked.txt").write_text("uncommitted\n", encoding="utf-8")
        self.start_lite(repo, task_id="lite-dirty")
        task = dev_flow.load_state("lite-dirty", self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-dirty", self.data)

        rejected = self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "dirty tree",
            expected_code=2,
        )
        self.assertEqual(rejected["error"]["code"], "DIRTY_APPROVAL_REQUIRED")

        approved = self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "dirty tree accepted",
            "--allow-dirty",
        )
        self.assertTrue(approved["approval"]["dirty_allowed"])

        # A refreshed preflight invalidates the earlier lite approval.
        task = dev_flow.load_state("lite-dirty", self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-dirty", self.data)
        self.assertNotIn("lite", task["approvals"])
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "APPROVAL_REQUIRED")

    def test_lite_implementation_entry_rejects_checkout_drift(self) -> None:
        repo, _ = self.make_repo("lite-drift")
        task = self.approved_lite_task(repo, task_id="lite-drift")

        (repo / "tracked.txt").write_text("early edit\n", encoding="utf-8")
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(
            rejected["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED"
        )

        (repo / "tracked.txt").write_text("initial lite-drift\n", encoding="utf-8")
        git(repo, "checkout", "-q", "-b", "elsewhere")
        task = dev_flow.load_state("lite-drift", self.data)
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CHECKOUT_DRIFT")

        git(repo, "checkout", "-q", "main")
        task = dev_flow.load_state("lite-drift", self.data)
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        self.assertEqual(
            dev_flow.load_state("lite-drift", self.data)["status"],
            "IMPLEMENTING",
        )

    def test_lite_done_requires_current_passing_tests(self) -> None:
        repo, _ = self.make_repo("lite-verify")
        task = self.approved_lite_task(repo, task_id="lite-verify")
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-verify", self.data)
        (repo / "tracked.txt").write_text("candidate fix\n", encoding="utf-8")
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-verify", self.data)

        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "1",
        )
        task = dev_flow.load_state("lite-verify", self.data)
        rejected = self.mutate(
            "transition", task, "--to", "DONE", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CURRENT_TEST_REQUIRED")

        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-verify", self.data)
        (repo / "tracked.txt").write_text("changed after tests\n", encoding="utf-8")
        rejected = self.mutate(
            "transition", task, "--to", "DONE", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CURRENT_TEST_REQUIRED")

        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-verify", self.data)
        self.mutate("transition", task, "--to", "DONE")
        self.assertEqual(
            dev_flow.load_state("lite-verify", self.data)["status"], "DONE"
        )

    def test_lite_rework_reopens_scope_with_note_and_invalidates_tests(self) -> None:
        repo, _ = self.make_repo("lite-rework")
        task = self.approved_lite_task(repo, task_id="lite-rework")
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-rework", self.data)
        (repo / "tracked.txt").write_text("first attempt\n", encoding="utf-8")
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-rework", self.data)

        rejected = self.mutate(
            "transition", task, "--to", "PREFLIGHTED", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "INVALID_ARGUMENT")
        self.mutate(
            "transition",
            task,
            "--to",
            "PREFLIGHTED",
            "--note",
            "scope grew beyond the approved fix",
        )
        task = dev_flow.load_state("lite-rework", self.data)
        self.assertEqual(task["status"], "PREFLIGHTED")

        # The edited tree no longer matches the approved snapshot, so a fresh
        # preflight and a new dirty-approval are required to continue.
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(
            rejected["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED"
        )
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "wider fix approved",
            "--allow-dirty",
        )
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-rework", self.data)

        # Tests recorded under the earlier approval are historical only.
        rejected = self.mutate(
            "transition", task, "--to", "DONE", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CURRENT_TEST_REQUIRED")
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate("transition", task, "--to", "DONE")
        self.assertEqual(
            dev_flow.load_state("lite-rework", self.data)["status"], "DONE"
        )


if __name__ == "__main__":
    unittest.main()
