#!/usr/bin/env python3
"""Run Stage 1 acceptance journeys against one installed V6 snapshot.

This runner intentionally imports only the Python standard library.  Every
controller, Hook, and package-validation observation crosses an installed
process boundary through ``scripts/dev_flow_python_launcher``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


EVIDENCE_SCHEMA = "dev-flow-installed-stage1-evidence/v1"
EXTERNAL_EVIDENCE_SCHEMA = "dev-flow-stage1-external-evidence/v1"
DRIVER_RESULT_SCHEMA = "dev-flow-driver-result/v1"
RETAINED_V5_EVIDENCE_SCHEMA = "dev-flow-retained-v5-inspection/v1"
CONTRACT_SCHEMA = "dev-flow-delivery-contract/v1"
OFFICIAL_WORKFLOWS = (
    "bugfix",
    "feature",
    "full",
    "investigation",
    "lite",
    "refactor",
)
EXPECTED_SKILLS = (
    "analyze-change-impact",
    "follow-dev-flow",
    "review-dev-flow-change",
)
VOLATILE_TREE_NAMES = {
    ".DS_Store",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
VERSION_V6 = re.compile(r"^6\.0\.0\+codex\.[0-9A-Za-z.-]+$")
VERSION_V5 = re.compile(r"^5\.0\.0\+codex\.[0-9A-Za-z.-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AcceptanceFailure(RuntimeError):
    """One installed acceptance assertion failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _strict_json(text: str, label: str) -> object:
    def pairs(items: Iterable[Tuple[str, object]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise AcceptanceFailure(
                    "{} contains duplicate JSON key {!r}".format(label, key)
                )
            result[key] = value
        return result

    def constant(value: str) -> object:
        raise AcceptanceFailure(
            "{} contains non-finite JSON value {}".format(label, value)
        )

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except AcceptanceFailure:
        raise
    except (TypeError, ValueError) as exc:
        raise AcceptanceFailure("{} is not valid JSON: {}".format(label, exc)) from exc


def _read_json_object(path: Path, label: str) -> dict:
    try:
        value = _strict_json(path.read_text(encoding="utf-8"), label)
    except OSError as exc:
        raise AcceptanceFailure("cannot read {}: {}".format(label, exc)) from exc
    _require(isinstance(value, dict), "{} must contain a JSON object".format(label))
    return value


def _sha256_value(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _validate_external_driver_evidence(value: object) -> list:
    _require(isinstance(value, list), "external driver_executions must be a list")
    summaries = []
    tools = set()
    for index, item in enumerate(value):
        label = "external driver_executions[{}]".format(index)
        _require(isinstance(item, Mapping), "{} must be an object".format(label))
        _require(
            item.get("execution") == "actual-tool-execution",
            "{} is not actual tool execution evidence".format(label),
        )
        _require(
            _sha256_value(item.get("output_sha256")),
            "{} output_sha256 is invalid".format(label),
        )
        result = item.get("result")
        _require(isinstance(result, Mapping), "{} result must be an object".format(label))
        required = {"schema", "status", "tool", "phase", "details", "limitations"}
        _require(
            required.issubset(result),
            "{} result omits common driver envelope fields".format(label),
        )
        _require(
            result.get("schema") == DRIVER_RESULT_SCHEMA,
            "{} result schema is invalid".format(label),
        )
        tool = result.get("tool")
        _require(
            tool in {"openspec", "codebase-memory", "independent-review"},
            "{} result tool is invalid".format(label),
        )
        _require(tool not in tools, "external driver evidence repeats {}".format(tool))
        _require(
            result.get("status") in {"available", "degraded"},
            "{} result is not a completed driver execution".format(label),
        )
        _require(
            isinstance(result.get("phase"), str) and result.get("phase"),
            "{} result phase is invalid".format(label),
        )
        _require(
            isinstance(result.get("details"), Mapping),
            "{} result details must be an object".format(label),
        )
        limitations = result.get("limitations")
        _require(
            isinstance(limitations, list)
            and all(isinstance(entry, str) for entry in limitations),
            "{} result limitations must be a string list".format(label),
        )
        tools.add(str(tool))
        summaries.append(
            {
                "execution": "actual-tool-execution",
                "output_sha256": item.get("output_sha256"),
                "result": dict(result),
            }
        )
    _require(
        tools == {"openspec", "codebase-memory", "independent-review"},
        "external driver evidence must cover openspec, codebase-memory, and independent-review",
    )
    return summaries


def _validate_retained_v5_external_evidence(
    value: object,
    retained: Mapping[str, object],
) -> dict:
    _require(isinstance(value, Mapping), "external retained_v5 must be an object")
    _require(
        value.get("schema") == RETAINED_V5_EVIDENCE_SCHEMA,
        "external retained_v5 schema is invalid",
    )
    _require(
        value.get("root_snapshot_digest") == retained.get("snapshot_digest_before"),
        "external retained_v5 evidence is bound to another installed V5 snapshot",
    )
    _require(value.get("read_only") is True, "external retained_v5 inspection is not read-only")
    _require(
        value.get("operations") == ["list", "show"],
        "external retained_v5 inspection must record list then show",
    )
    _require(
        _sha256_value(value.get("controller_locator_sha256")),
        "external retained_v5 controller locator digest is invalid",
    )
    before = value.get("before")
    after = value.get("after")
    _require(
        isinstance(before, Mapping) and isinstance(after, Mapping),
        "external retained_v5 before/after evidence is invalid",
    )
    for phase, observation in (("before", before), ("after", after)):
        _require(
            _sha256_value(observation.get("state_digest"))
            and _sha256_value(observation.get("list_output_sha256"))
            and _sha256_value(observation.get("show_output_sha256")),
            "external retained_v5 {} digests are invalid".format(phase),
        )
        task = observation.get("task")
        _require(
            isinstance(task, Mapping)
            and isinstance(task.get("task_id"), str)
            and task.get("task_id"),
            "external retained_v5 {} task summary is invalid".format(phase),
        )
    _require(
        before.get("state_digest") == after.get("state_digest")
        and before.get("task") == after.get("task"),
        "retained V5 controller state changed during installed V6 journeys",
    )
    return {
        "schema": RETAINED_V5_EVIDENCE_SCHEMA,
        "root_snapshot_digest": value.get("root_snapshot_digest"),
        "controller_locator_sha256": value.get("controller_locator_sha256"),
        "operations": ["list", "show"],
        "read_only": True,
        "before": dict(before),
        "after": dict(after),
        "unchanged": True,
    }


def _validate_external_release_evidence(
    value: object,
    installed_digest: str,
    retained: object,
) -> dict:
    _require(isinstance(value, Mapping), "external release evidence must be an object")
    _require(
        value.get("schema") == EXTERNAL_EVIDENCE_SCHEMA,
        "external release evidence schema is invalid",
    )
    _require(
        value.get("installed_snapshot_digest") == installed_digest,
        "external release evidence is bound to another installed V6 snapshot",
    )
    driver_executions = _validate_external_driver_evidence(
        value.get("driver_executions")
    )
    _require(
        isinstance(retained, Mapping)
        and retained.get("status") != "not-provided",
        "retained V5 installed snapshot is required for release evidence",
    )
    retained_external = _validate_retained_v5_external_evidence(
        value.get("retained_v5"), retained
    )
    return {
        "schema": EXTERNAL_EVIDENCE_SCHEMA,
        "installed_snapshot_digest": installed_digest,
        "driver_executions": driver_executions,
        "retained_v5": retained_external,
    }


def _tree_digest(root: Path, *, ignore_volatile: bool) -> str:
    """Hash path identity, kind, executable bits, and bytes without following links."""
    _require(root.is_dir(), "tree root is not a directory: {}".format(root))
    digest = hashlib.sha256()
    digest.update(b"dev-flow-tree-snapshot/v1\x00")
    pending = [root]
    entries = []
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            raise AcceptanceFailure("cannot enumerate {}: {}".format(directory, exc)) from exc
        for child in children:
            relative = child.relative_to(root)
            if ignore_volatile and any(part in VOLATILE_TREE_NAMES for part in relative.parts):
                continue
            if ignore_volatile and child.suffix == ".pyc":
                continue
            entries.append(child)
            try:
                mode = child.lstat().st_mode
            except OSError as exc:
                raise AcceptanceFailure("cannot inspect {}: {}".format(child, exc)) from exc
            if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                pending.append(child)
    for path in sorted(entries, key=lambda item: os.fsencode(str(item.relative_to(root)))):
        relative = os.fsencode(str(path.relative_to(root)))
        try:
            info = path.lstat()
        except OSError as exc:
            raise AcceptanceFailure("cannot inspect {}: {}".format(path, exc)) from exc
        if stat.S_ISREG(info.st_mode):
            marker = b"F"
        elif stat.S_ISDIR(info.st_mode):
            marker = b"D"
        elif stat.S_ISLNK(info.st_mode):
            marker = b"L"
        else:
            marker = b"O"
        digest.update(marker)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update((info.st_mode & 0o111).to_bytes(2, "big"))
        if marker == b"F":
            try:
                with path.open("rb") as stream:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
            except OSError as exc:
                raise AcceptanceFailure("cannot hash {}: {}".format(path, exc)) from exc
        elif marker == b"L":
            try:
                target = os.fsencode(os.readlink(str(path)))
            except OSError as exc:
                raise AcceptanceFailure("cannot read link {}: {}".format(path, exc)) from exc
            digest.update(len(target).to_bytes(8, "big"))
            digest.update(target)
    return digest.hexdigest()


def _projection_summary(projection: object) -> object:
    if not isinstance(projection, Mapping):
        return projection
    action = projection.get("action")
    action_summary = None
    if isinstance(action, Mapping):
        binding = action.get("binding")
        action_summary = {
            "node_id": action.get("node_id"),
            "action_id": action.get("action_id"),
            "handler": action.get("handler"),
            "payload": action.get("payload"),
            "artifact": action.get("artifact"),
            "driver": action.get("driver"),
            "retry_budget": action.get("retry_budget"),
            "blocked": action.get("blocked"),
            "binding": (
                {
                    "digest": binding.get("digest"),
                    "task_revision": binding.get("task_revision"),
                    "contract_revision": binding.get("contract_revision"),
                    "starting_snapshot_digest": binding.get(
                        "starting_snapshot_digest"
                    ),
                    "input_record_ids": [
                        item.get("record_id")
                        for item in binding.get("inputs", [])
                        if isinstance(item, Mapping)
                    ],
                }
                if isinstance(binding, Mapping)
                else None
            ),
        }
    repository = projection.get("repository")
    repository_summary = None
    if isinstance(repository, Mapping):
        repository_summary = {
            "id": repository.get("id"),
            "path": repository.get("path"),
            "snapshot": repository.get("snapshot"),
        }
    return {
        "schema": projection.get("schema"),
        "task_id": projection.get("task_id"),
        "revision": projection.get("revision"),
        "workflow": projection.get("workflow"),
        "status": projection.get("status"),
        "current_node": projection.get("current_node"),
        "contract": projection.get("contract"),
        "repository": repository_summary,
        "action": action_summary,
        "dossier": projection.get("dossier"),
        "done": projection.get("done"),
    }


def _task_summary(task: object) -> object:
    if not isinstance(task, Mapping):
        return task
    records = task.get("records")
    return {
        "schema_version": task.get("schema_version"),
        "product_identity": task.get("product_identity"),
        "task_id": task.get("task_id"),
        "revision": task.get("revision"),
        "workflow": task.get("workflow"),
        "status": task.get("status"),
        "current_node": task.get("current_node"),
        "record_count": len(records) if isinstance(records, list) else None,
        "effective_contract": task.get("effective_contract"),
        "effective_contract_digest": task.get("effective_contract_digest"),
    }


def _command_result_summary(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    if value.get("ok") is False:
        return value
    command = value.get("command")
    if command == "start":
        return {"ok": True, "command": command, "task": _task_summary(value.get("task"))}
    if command == "next":
        return {
            "ok": True,
            "command": command,
            "projection": _projection_summary(value.get("projection")),
        }
    if command in ("apply", "revise-contract", "decide", "cancel"):
        return {
            "ok": True,
            "command": command,
            "receipt": value.get("receipt"),
            "projection": _projection_summary(value.get("projection")),
        }
    if command == "show":
        return {"ok": True, "command": command, "task": _task_summary(value.get("task"))}
    if command == "list":
        tasks = value.get("tasks")
        return {
            "ok": True,
            "command": command,
            "tasks": [
                _task_summary(task)
                for task in tasks
                if isinstance(task, Mapping)
            ] if isinstance(tasks, list) else None,
        }
    if "hookSpecificOutput" in value:
        specific = value.get("hookSpecificOutput")
        context = (
            specific.get("additionalContext")
            if isinstance(specific, Mapping)
            else None
        )
        return {
            "hook_event_name": (
                specific.get("hookEventName")
                if isinstance(specific, Mapping)
                else None
            ),
            "has_additional_context": isinstance(context, str),
            "context_kind": (
                "current-task"
                if isinstance(context, str) and "Current Dev Flow V6 task" in context
                else "availability"
            ),
        }
    if "platform" in value and "errors" in value:
        return {
            "ok": value.get("ok"),
            "platform": value.get("platform"),
            "builtin_workflows": value.get("builtin_workflows"),
            "workflow_identities": value.get("workflow_identities"),
            "errors": value.get("errors"),
        }
    return value


class CommandRecorder:
    """Run one fresh process per call and retain canonical command evidence."""

    def __init__(
        self,
        evidence: dict,
        replacements: Sequence[Tuple[Path, str]],
        environment: Mapping[str, str],
    ) -> None:
        self.evidence = evidence
        self.replacements = tuple(
            sorted(
                ((str(path.resolve()), token) for path, token in replacements),
                key=lambda item: len(item[0]),
                reverse=True,
            )
        )
        self.environment = dict(environment)

    def _display(self, text: str) -> str:
        result = text
        for actual, token in self.replacements:
            result = result.replace(actual, token)
        return result

    def _display_value(self, value: object) -> object:
        if isinstance(value, str):
            return self._display(value)
        if isinstance(value, list):
            return [self._display_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._display_value(item) for key, item in value.items()}
        return value

    def _display_argv(self, argv: Sequence[str]) -> list:
        """Keep commands exact except for the already-evidenced binding envelope."""
        displayed = [self._display(str(item)) for item in argv]
        for index, item in enumerate(displayed[:-1]):
            if item != "--binding-json":
                continue
            try:
                binding = json.loads(displayed[index + 1])
            except (TypeError, ValueError):
                continue
            if isinstance(binding, dict):
                displayed[index + 1] = _json_text(
                    {
                        "schema": binding.get("schema"),
                        "digest": binding.get("digest"),
                        "task_revision": binding.get("task_revision"),
                        "contract_revision": binding.get("contract_revision"),
                        "starting_snapshot_digest": binding.get(
                            "starting_snapshot_digest"
                        ),
                        "input_record_ids": [
                            entry.get("record_id")
                            for entry in binding.get("inputs", [])
                            if isinstance(entry, dict)
                        ],
                    }
                )
        return displayed

    def run_json(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        kind: str,
        input_text: Optional[str] = None,
        timeout: int = 60,
    ) -> Tuple[dict, int]:
        index = len(self.evidence["commands"]) + 1
        entry = {
            "process_index": index,
            "fresh_process": True,
            "kind": kind,
            "argv": self._display_argv(argv),
            "cwd": self._display(str(cwd.resolve())),
        }
        try:
            completed = subprocess.run(
                [str(item) for item in argv],
                cwd=str(cwd),
                env=self.environment,
                input=input_text,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            entry["result"] = {"started": False, "error": self._display(str(exc))}
            self.evidence["commands"].append(entry)
            raise AcceptanceFailure(
                "process {} could not complete: {}".format(index, exc)
            ) from exc
        entry["returncode"] = completed.returncode
        if completed.stderr:
            entry["stderr"] = self._display(completed.stderr.strip())
        try:
            parsed = _strict_json(completed.stdout, "process {} stdout".format(index))
        except AcceptanceFailure:
            entry["stdout"] = self._display(completed.stdout.strip())
            self.evidence["commands"].append(entry)
            raise
        _require(
            isinstance(parsed, dict),
            "process {} must return one JSON object".format(index),
        )
        entry["result"] = self._display_value(_command_result_summary(parsed))
        self.evidence["commands"].append(entry)
        _require(
            completed.returncode == 0,
            "process {} failed with exit {}: {}".format(
                index,
                completed.returncode,
                completed.stderr.strip() or completed.stdout.strip(),
            ),
        )
        _require(parsed.get("ok") is not False, "process {} returned failure JSON".format(index))
        return parsed, index

    def run_text(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        kind: str,
        extra_environment: Optional[Mapping[str, str]] = None,
        timeout: int = 30,
    ) -> int:
        index = len(self.evidence["commands"]) + 1
        environment = dict(self.environment)
        environment.update(extra_environment or {})
        entry = {
            "process_index": index,
            "fresh_process": True,
            "kind": kind,
            "argv": self._display_argv(argv),
            "cwd": self._display(str(cwd.resolve())),
        }
        try:
            completed = subprocess.run(
                [str(item) for item in argv],
                cwd=str(cwd),
                env=environment,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            entry["result"] = {"started": False, "error": self._display(str(exc))}
            self.evidence["commands"].append(entry)
            raise AcceptanceFailure(
                "process {} could not complete: {}".format(index, exc)
            ) from exc
        entry["returncode"] = completed.returncode
        entry["result"] = {
            "stdout": self._display(completed.stdout.strip()),
            "stderr": self._display(completed.stderr.strip()),
        }
        self.evidence["commands"].append(entry)
        _require(
            completed.returncode == 0,
            "process {} failed with exit {}: {}".format(
                index,
                completed.returncode,
                completed.stderr.strip() or completed.stdout.strip(),
            ),
        )
        return index


class InstalledController:
    def __init__(
        self,
        recorder: CommandRecorder,
        launcher: Path,
        handler: Path,
        data_dir: Path,
        cwd: Path,
        kind_prefix: str = "v6-cli",
    ) -> None:
        self.recorder = recorder
        self.launcher = launcher
        self.handler = handler
        self.data_dir = data_dir
        self.cwd = cwd
        self.kind_prefix = kind_prefix

    def _call(self, command: str, arguments: Sequence[str] = ()) -> Tuple[dict, int]:
        return self.recorder.run_json(
            (
                str(self.launcher),
                str(self.handler),
                "--data-dir",
                str(self.data_dir),
                command,
                *arguments,
            ),
            cwd=self.cwd,
            kind="{}:{}".format(self.kind_prefix, command),
        )

    def start(
        self,
        task_id: str,
        workflow: str,
        repository: Path,
        requirement: str,
        contract: Optional[Mapping[str, object]] = None,
    ) -> Tuple[dict, int]:
        arguments = [
            "--requirement",
            requirement,
            "--workflow",
            workflow,
            "--repo",
            str(repository),
            "--task-id",
            task_id,
        ]
        if contract is not None:
            arguments.extend(("--contract-json", _json_text(contract)))
        return self._call("start", arguments)

    def next(self, task_id: str) -> Tuple[dict, int]:
        return self._call("next", (task_id,))

    def show(self, task_id: str) -> Tuple[dict, int]:
        return self._call("show", (task_id,))

    def apply(
        self,
        task_id: str,
        projection: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> Tuple[dict, int]:
        action = projection.get("action")
        _require(isinstance(action, Mapping), "projection action is unavailable")
        binding = action.get("binding")
        _require(isinstance(binding, Mapping), "projection action binding is unavailable")
        return self._call(
            "apply",
            (
                task_id,
                "--action",
                str(action.get("action_id")),
                "--payload-json",
                _json_text(payload),
                "--binding-json",
                _json_text(binding),
            ),
        )

    def decide(self, task_id: str, decision: Mapping[str, object]) -> Tuple[dict, int]:
        return self._call(
            "decide",
            (task_id, "--decision-json", _json_text(decision)),
        )

    def revise(
        self,
        task_id: str,
        contract: Mapping[str, object],
        reason: str,
        actor_label: str,
    ) -> Tuple[dict, int]:
        return self._call(
            "revise-contract",
            (
                task_id,
                "--contract-json",
                _json_text(contract),
                "--reason",
                reason,
                "--actor-label",
                actor_label,
            ),
        )

    def cancel(self, task_id: str, reason: str) -> Tuple[dict, int]:
        return self._call("cancel", (task_id, "--reason", reason))


class Stage1Acceptance:
    def __init__(
        self,
        plugin_root: Path,
        scratch: Path,
        retained_v5_root: Optional[Path],
        retained_v5_data: Optional[Path],
        evidence: dict,
    ) -> None:
        self.plugin_root = plugin_root
        self.scratch = scratch
        self.retained_v5_root = retained_v5_root
        self.retained_v5_data = retained_v5_data
        self.evidence = evidence
        self.launcher = plugin_root / "scripts" / "dev_flow_python_launcher"
        self.cli_handler = plugin_root / "scripts" / "dev_flow.py"
        environment = dict(os.environ)
        environment.update(
            {
                "DEV_FLOW_PYTHON": sys.executable,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "TZ": "UTC",
            }
        )
        replacements = [(scratch, "<SCRATCH>"), (plugin_root, "<PLUGIN_ROOT>")]
        if retained_v5_root is not None:
            replacements.append((retained_v5_root, "<RETAINED_V5_ROOT>"))
        if retained_v5_data is not None:
            replacements.append((retained_v5_data, "<RETAINED_V5_DATA>"))
        self.recorder = CommandRecorder(evidence, replacements, environment)
        self.source_sequence: Dict[str, int] = {}

    def _controller(self, name: str, repository: Path) -> InstalledController:
        return InstalledController(
            self.recorder,
            self.launcher,
            self.cli_handler,
            self.scratch / "data" / name,
            repository,
        )

    def _make_repository(self, name: str) -> Path:
        repository = self.scratch / "repos" / name
        repository.mkdir(parents=True)
        self.recorder.run_text(
            ("git", "init", "-q"), cwd=repository, kind="git:init"
        )
        self.recorder.run_text(
            ("git", "symbolic-ref", "HEAD", "refs/heads/main"),
            cwd=repository,
            kind="git:branch",
        )
        (repository / "README.md").write_text(
            "# Installed Stage 1 scratch repository\n", encoding="utf-8"
        )
        self.recorder.run_text(
            ("git", "add", "README.md"), cwd=repository, kind="git:add"
        )
        commit_environment = {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
        self.recorder.run_text(
            (
                "git",
                "-c",
                "user.name=Stage 1 Acceptance",
                "-c",
                "user.email=stage1@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "deterministic baseline",
            ),
            cwd=repository,
            kind="git:commit",
            extra_environment=commit_environment,
        )
        return repository

    def _projection(self, response: Mapping[str, object]) -> Mapping[str, object]:
        projection = response.get("projection")
        _require(isinstance(projection, Mapping), "CLI response has no projection")
        return projection

    def _next(
        self, controller: InstalledController, task_id: str, node: Optional[str] = None
    ) -> Tuple[Mapping[str, object], int]:
        response, process_index = controller.next(task_id)
        projection = self._projection(response)
        if node is not None:
            _require(
                projection.get("current_node") == node,
                "{} expected node {}, got {}".format(
                    task_id, node, projection.get("current_node")
                ),
            )
        return projection, process_index

    def _append_source(self, repository: Path, task_id: str, node_id: str) -> str:
        sequence = self.source_sequence.get(task_id, 0) + 1
        self.source_sequence[task_id] = sequence
        relative = "journey.log"
        with (repository / relative).open("a", encoding="utf-8") as stream:
            stream.write("{}:{}:{}\n".format(sequence, task_id, node_id))
        return relative

    def _resource_payload(
        self,
        repository: Path,
        task_id: str,
        version: int,
    ) -> dict:
        change = "openspec/changes/{}".format(task_id)
        directory = repository / change
        directory.mkdir(parents=True, exist_ok=True)
        proposal = directory / "proposal.md"
        tasks = directory / "tasks.md"
        proposal.write_text(
            "# Installed plan {}\n\nGoverning obligation v{}.\n".format(
                task_id, version
            ),
            encoding="utf-8",
        )
        tasks.write_text(
            "- [ ] verify installed journey v{}\n".format(version),
            encoding="utf-8",
        )
        return {
            "items": [
                {
                    "path": "{}/proposal.md".format(change),
                    "role": "governing",
                    "normalizer": "none",
                },
                {
                    "path": "{}/tasks.md".format(change),
                    "role": "reported",
                    "normalizer": "none",
                },
                {
                    "path": "{}/tasks.md".format(change),
                    "role": "governing",
                    "normalizer": "openspec-tasks-v1",
                },
            ]
        }

    def _standard_payload(
        self,
        projection: Mapping[str, object],
        repository: Path,
        task_id: str,
        *,
        driver_status: str = "available",
        review_unavailable: bool = False,
        resource_version: int = 1,
        passed: bool = True,
        unverified_criteria: Sequence[str] = (),
        remaining_risks: Optional[Mapping[str, object]] = None,
    ) -> dict:
        action = projection.get("action")
        _require(isinstance(action, Mapping), "{} has no current action".format(task_id))
        payload_types = action.get("payload")
        _require(isinstance(payload_types, Mapping), "{} action payload is invalid".format(task_id))
        contract = projection.get("contract")
        criterion_ids = (
            contract.get("criterion_ids", []) if isinstance(contract, Mapping) else []
        )
        driver = action.get("driver")
        driver_tool = driver.get("tool") if isinstance(driver, Mapping) else None
        node_id = str(action.get("node_id"))
        payload = {}
        for field in sorted(str(item) for item in payload_types):
            if field == "summary":
                payload[field] = "{} {} completed".format(task_id, node_id)
            elif field == "driver_result":
                payload[field] = {
                    "schema": DRIVER_RESULT_SCHEMA,
                    "status": "unavailable" if review_unavailable else driver_status,
                    "tool": driver_tool,
                    "phase": node_id,
                    "details": {
                        "evidence_class": "controller-contract-simulation",
                        "purpose": (
                            "Exercise installed controller validation, persistence, "
                            "fallback, and replay behavior"
                        ),
                    },
                    "limitations": [
                        "This payload is generated by the installed acceptance runner and is not actual tool execution evidence."
                    ],
                }
            elif field == "resources":
                payload[field] = self._resource_payload(
                    repository, task_id, resource_version
                )
            elif field == "evidence":
                payload[field] = {"finding": "installed behavior confirmed"}
            elif field == "passed":
                payload[field] = passed
            elif field == "command":
                payload[field] = "python3 -m unittest focused-installed-check"
            elif field == "coverage":
                payload[field] = {
                    str(criterion_id): (
                        "unverified"
                        if criterion_id in set(unverified_criteria)
                        else "proven"
                    )
                    for criterion_id in criterion_ids
                }
            elif field == "outcome":
                payload[field] = "unavailable" if review_unavailable else "approved"
            elif field == "assurance":
                payload[field] = "self" if review_unavailable else "independent"
            elif field == "findings":
                payload[field] = {}
            elif field == "remaining_risks":
                payload[field] = dict(remaining_risks or {})
            elif field == "handoff":
                payload[field] = "Ready for the installed user"
            else:
                raise AcceptanceFailure(
                    "unsupported official payload field {} at {}".format(field, node_id)
                )
        return payload

    def _apply(
        self,
        controller: InstalledController,
        task_id: str,
        repository: Path,
        projection: Mapping[str, object],
        next_process: int,
        payload: Mapping[str, object],
        *,
        prepared_source_paths: Sequence[str] = (),
    ) -> Mapping[str, object]:
        action = projection.get("action")
        _require(isinstance(action, Mapping), "{} has no current action".format(task_id))
        artifact = action.get("artifact")
        workspace = artifact.get("workspace") if isinstance(artifact, Mapping) else None
        source_paths = list(prepared_source_paths)
        if workspace == "produces-source" and action.get("handler") != "preflight":
            source_paths.append(
                self._append_source(repository, task_id, str(action.get("node_id")))
            )
        _require(
            not (
                workspace == "produces-source"
                and action.get("handler") != "preflight"
                and not source_paths
            ),
            "{} {} declared produces-source without a source edit".format(
                task_id, action.get("node_id")
            ),
        )
        response, apply_process = controller.apply(task_id, projection, payload)
        resulting = self._projection(response)
        binding = action.get("binding")
        driver = action.get("driver")
        driver_result = payload.get("driver_result")
        action_evidence = {
            "task_id": task_id,
            "node_id": action.get("node_id"),
            "action_id": action.get("action_id"),
            "handler": action.get("handler"),
            "workspace": workspace,
            "next_process": next_process,
            "apply_process": apply_process,
            "binding_digest": (
                binding.get("digest") if isinstance(binding, Mapping) else None
            ),
            "starting_snapshot_digest": (
                binding.get("starting_snapshot_digest")
                if isinstance(binding, Mapping)
                else None
            ),
            "payload": payload,
            "source_edits": sorted(set(source_paths)),
            "source_authority_observed": (
                "baseline-capture-no-edit"
                if workspace == "produces-source" and action.get("handler") == "preflight"
                else "edit-performed"
                if workspace == "produces-source"
                else "no-edit"
            ),
            "result": {
                "revision": resulting.get("revision"),
                "status": resulting.get("status"),
                "current_node": resulting.get("current_node"),
                "done": resulting.get("done"),
            },
        }
        self.evidence["actions"].append(action_evidence)
        if isinstance(driver, Mapping):
            path = {
                "task_id": task_id,
                "node_id": action.get("node_id"),
                "tool": driver.get("tool"),
                "optional": driver.get("optional"),
                "fallback": driver.get("fallback"),
                "result": driver_result,
                "evidence_class": "controller-contract-simulation",
                "qualifies_as_driver_execution": False,
                "next_process": next_process,
                "apply_process": apply_process,
            }
            self.evidence["driver_paths"].append(path)
        return resulting

    def _artifact(self, task: Mapping[str, object], artifact_type: str) -> dict:
        records = task.get("records")
        _require(isinstance(records, list), "task record ledger is unavailable")
        for record in reversed(records):
            if not isinstance(record, Mapping):
                continue
            artifact = record.get("artifact")
            if isinstance(artifact, Mapping) and artifact.get("type") == artifact_type:
                return {"record": dict(record), "artifact": dict(artifact)}
        raise AcceptanceFailure("task has no {} artifact".format(artifact_type))

    def _baseline_summary(self, pair: Mapping[str, object]) -> dict:
        record = pair["record"]
        artifact = pair["artifact"]
        snapshot = artifact.get("snapshot")
        _require(isinstance(snapshot, Mapping), "baseline snapshot is unavailable")
        return {
            "record_id": record.get("record_id"),
            "record_digest": record.get("digest"),
            "artifact_type": artifact.get("type"),
            "artifact_digest": artifact.get("digest"),
            "contract_revision": artifact.get("contract_revision"),
            "snapshot": {
                key: snapshot.get(key)
                for key in (
                    "schema",
                    "digest",
                    "head",
                    "branch",
                    "clean",
                    "status_sha256",
                    "status_bytes",
                )
            },
        }

    def _dossier_summary(self, pair: Mapping[str, object]) -> dict:
        record = pair["record"]
        artifact = pair["artifact"]
        body = artifact.get("body")
        _require(isinstance(body, Mapping), "Delivery Dossier body is unavailable")
        artifacts = body.get("artifacts")
        return {
            "record_id": record.get("record_id"),
            "record_digest": record.get("digest"),
            "artifact_digest": artifact.get("digest"),
            "schema": body.get("schema"),
            "outcome": body.get("outcome"),
            "contract_revision": (
                body.get("contract", {}).get("revision")
                if isinstance(body.get("contract"), Mapping)
                else None
            ),
            "contract_digest": body.get("contract_digest"),
            "coverage": body.get("coverage"),
            "verification": body.get("verification"),
            "review": body.get("review"),
            "review_assurance": body.get("review_assurance"),
            "decisions": body.get("decisions"),
            "artifacts": artifacts,
            "repository_baseline_digest": (
                body.get("repository_baseline", {}).get("digest")
                if isinstance(body.get("repository_baseline"), Mapping)
                else None
            ),
            "repository_snapshot_digest": (
                body.get("repository_snapshot", {}).get("digest")
                if isinstance(body.get("repository_snapshot"), Mapping)
                else None
            ),
            "remaining_risks": body.get("remaining_risks"),
            "handoff_recommendation": body.get("handoff_recommendation"),
        }

    def _inspect_terminal(
        self,
        controller: InstalledController,
        task_id: str,
        terminal_projection: Mapping[str, object],
        *,
        expected_status: str,
        expected_outcome: str,
        baseline_type: str = "repository-baseline",
    ) -> dict:
        _require(terminal_projection.get("done") is True, "{} is not terminal".format(task_id))
        _require(
            terminal_projection.get("status") == expected_status,
            "{} expected status {}, got {}".format(
                task_id, expected_status, terminal_projection.get("status")
            ),
        )
        response, show_process = controller.show(task_id)
        task = response.get("task")
        _require(isinstance(task, Mapping), "{} show view is unavailable".format(task_id))
        baseline = self._baseline_summary(self._artifact(task, baseline_type))
        dossier = self._dossier_summary(self._artifact(task, "delivery-dossier"))
        _require(
            dossier.get("schema") == "dev-flow-delivery-dossier/v1",
            "{} dossier schema is invalid".format(task_id),
        )
        _require(
            dossier.get("outcome") == expected_outcome,
            "{} dossier expected outcome {}, got {}".format(
                task_id, expected_outcome, dossier.get("outcome")
            ),
        )
        projection_dossier = terminal_projection.get("dossier")
        _require(
            isinstance(projection_dossier, Mapping)
            and projection_dossier.get("outcome") == expected_outcome
            and projection_dossier.get("current") is True,
            "{} terminal dossier projection is not current".format(task_id),
        )
        self.evidence["baselines"][task_id] = baseline
        outcome = {
            "task_id": task_id,
            "workflow": task.get("workflow"),
            "revision": task.get("revision"),
            "status": task.get("status"),
            "current_node": task.get("current_node"),
            "show_process": show_process,
            "dossier": dossier,
        }
        self.evidence["outcomes"][task_id] = outcome
        return outcome

    def _record_task(self, task_id: str) -> None:
        self.evidence["task_ids"].append(task_id)

    def _driver_status(self, workflow: str, tool: object) -> str:
        degraded = {
            ("bugfix", "codebase-memory"),
            ("bugfix", "openspec"),
            ("full", "openspec"),
            ("refactor", "codebase-memory"),
        }
        return "degraded" if (workflow, tool) in degraded else "available"

    def _complete_success(
        self,
        controller: InstalledController,
        task_id: str,
        repository: Path,
        workflow: str,
        *,
        feature_review_waiver: bool = False,
    ) -> Mapping[str, object]:
        steps = 0
        waiver_recorded = False
        while True:
            projection, next_process = self._next(controller, task_id)
            if projection.get("done") is True:
                return projection
            steps += 1
            _require(steps <= 32, "{} exceeded the bounded workflow length".format(task_id))
            action = projection.get("action")
            _require(isinstance(action, Mapping), "{} action is unavailable".format(task_id))
            review_unavailable = False
            if (
                feature_review_waiver
                and action.get("handler") == "review.record"
                and not waiver_recorded
            ):
                decision = {
                    "id": "installed-review-waiver",
                    "kind": "assurance-waiver",
                    "subject": str(action.get("node_id")),
                    "outcome": "waived",
                    "rationale": (
                        "Independent reviewer is unavailable in the installed "
                        "single-operator acceptance journey"
                    ),
                    "actor_label": "installed-acceptance",
                }
                _, decision_process = controller.decide(task_id, decision)
                self.evidence["decisions"].append(
                    {
                        "task_id": task_id,
                        "process_index": decision_process,
                        "decision": decision,
                    }
                )
                waiver_recorded = True
                projection, next_process = self._next(controller, task_id, "review")
                action = projection.get("action")
                _require(isinstance(action, Mapping), "review action disappeared after waiver")
                review_unavailable = True
            driver = action.get("driver")
            tool = driver.get("tool") if isinstance(driver, Mapping) else None
            payload = self._standard_payload(
                projection,
                repository,
                task_id,
                driver_status=self._driver_status(workflow, tool),
                review_unavailable=review_unavailable,
            )
            self._apply(
                controller,
                task_id,
                repository,
                projection,
                next_process,
                payload,
            )

    def official_success_journeys(self) -> None:
        for workflow in OFFICIAL_WORKFLOWS:
            task_id = "stage1-official-{}".format(workflow)
            repository = self._make_repository("official-{}".format(workflow))
            controller = self._controller("official-{}".format(workflow), repository)
            started, start_process = controller.start(
                task_id,
                workflow,
                repository,
                "Installed {} delivery".format(workflow),
            )
            task = started.get("task")
            _require(isinstance(task, Mapping), "{} start task is unavailable".format(task_id))
            workflow_view = task.get("workflow")
            _require(
                isinstance(workflow_view, Mapping)
                and workflow_view.get("id") == workflow
                and workflow_view.get("version") == 6,
                "{} did not start the installed V6 workflow".format(task_id),
            )
            self._record_task(task_id)
            terminal = self._complete_success(
                controller,
                task_id,
                repository,
                workflow,
                feature_review_waiver=(workflow == "feature"),
            )
            outcome = self._inspect_terminal(
                controller,
                task_id,
                terminal,
                expected_status="DONE",
                expected_outcome="success",
            )
            if workflow == "feature":
                assurance = outcome["dossier"].get("review_assurance")
                _require(
                    isinstance(assurance, Mapping)
                    and assurance.get("status") == "waived"
                    and assurance.get("remaining_risk")
                    == "independent review assurance was explicitly waived",
                    "feature dossier did not retain the exact assurance waiver risk",
                )
            self.evidence["journeys"].append(
                {
                    "name": "official-success-{}".format(workflow),
                    "task_id": task_id,
                    "start_process": start_process,
                    "outcome": "success",
                }
            )

    def restart_resume_journey(self) -> None:
        task_id = "stage1-restart-resume"
        repository = self._make_repository("restart-resume")
        controller = self._controller("restart-resume", repository)
        _, start_process = controller.start(
            task_id, "lite", repository, "Resume after every installed process exits"
        )
        self._record_task(task_id)
        preflight, preflight_next = self._next(controller, task_id, "preflight")
        self._apply(
            controller,
            task_id,
            repository,
            preflight,
            preflight_next,
            {},
        )
        interrupted, show_process = controller.show(task_id)
        interrupted_task = interrupted.get("task")
        _require(
            isinstance(interrupted_task, Mapping)
            and interrupted_task.get("revision") == 1
            and interrupted_task.get("current_node") == "implement",
            "restart interruption state was not durably observable",
        )
        resumed_controller = self._controller("restart-resume", repository)
        resumed_projection, resumed_process = self._next(
            resumed_controller, task_id, "implement"
        )
        payload = self._standard_payload(
            resumed_projection, repository, task_id
        )
        self._apply(
            resumed_controller,
            task_id,
            repository,
            resumed_projection,
            resumed_process,
            payload,
        )
        terminal = self._complete_success(
            resumed_controller, task_id, repository, "lite"
        )
        self._inspect_terminal(
            resumed_controller,
            task_id,
            terminal,
            expected_status="DONE",
            expected_outcome="success",
        )
        self.evidence["journeys"].append(
            {
                "name": "process-restart-resume",
                "task_id": task_id,
                "start_process": start_process,
                "interruption_show_process": show_process,
                "resume_next_process": resumed_process,
                "fresh_process_per_command": True,
                "outcome": "success",
            }
        )

    def cancellation_journey(self) -> None:
        task_id = "stage1-cancel"
        repository = self._make_repository("cancel")
        controller = self._controller("cancel", repository)
        _, start_process = controller.start(
            task_id, "lite", repository, "Cancel this installed delivery"
        )
        self._record_task(task_id)
        projection, next_process = self._next(controller, task_id, "preflight")
        self._apply(
            controller, task_id, repository, projection, next_process, {}
        )
        cancelled, cancel_process = controller.cancel(
            task_id, "Installed acceptance cancellation"
        )
        terminal = self._projection(cancelled)
        _require(terminal.get("done") is True, "cancelled task is not terminal")
        _require(terminal.get("status") == "CANCELLED", "cancelled task status is wrong")
        shown, show_process = controller.show(task_id)
        task = shown.get("task")
        _require(isinstance(task, Mapping), "cancelled task show view is unavailable")
        baseline = self._baseline_summary(self._artifact(task, "repository-baseline"))
        self.evidence["baselines"][task_id] = baseline
        self.evidence["outcomes"][task_id] = {
            "task_id": task_id,
            "status": task.get("status"),
            "current_node": task.get("current_node"),
            "revision": task.get("revision"),
            "show_process": show_process,
        }
        self.evidence["journeys"].append(
            {
                "name": "cancellation",
                "task_id": task_id,
                "start_process": start_process,
                "cancel_process": cancel_process,
                "outcome": "cancelled",
            }
        )

    def verification_exhaustion_journey(self) -> None:
        task_id = "stage1-verification-exhausted"
        repository = self._make_repository("verification-exhausted")
        controller = self._controller("verification-exhausted", repository)
        _, start_process = controller.start(
            task_id, "lite", repository, "Retain bounded verification failure"
        )
        self._record_task(task_id)
        projection, process_index = self._next(controller, task_id, "preflight")
        self._apply(controller, task_id, repository, projection, process_index, {})
        projection, process_index = self._next(controller, task_id, "implement")
        self._apply(
            controller,
            task_id,
            repository,
            projection,
            process_index,
            self._standard_payload(projection, repository, task_id),
        )
        retry_evidence = []
        for attempt in (1, 2):
            projection, process_index = self._next(controller, task_id, "verify")
            action = projection.get("action")
            retry_evidence.append(
                action.get("retry_budget") if isinstance(action, Mapping) else None
            )
            failed_payload = self._standard_payload(
                projection,
                repository,
                task_id,
                passed=False,
                unverified_criteria=("requirement",),
            )
            resulting = self._apply(
                controller,
                task_id,
                repository,
                projection,
                process_index,
                failed_payload,
            )
            if attempt == 1:
                _require(
                    resulting.get("current_node") == "verification_rework",
                    "first verification failure did not enter rework",
                )
                rework, rework_process = self._next(
                    controller, task_id, "verification_rework"
                )
                self._apply(
                    controller,
                    task_id,
                    repository,
                    rework,
                    rework_process,
                    self._standard_payload(rework, repository, task_id),
                )
            else:
                _require(
                    resulting.get("current_node")
                    == "finalize_verification_incomplete",
                    "verification exhaustion did not enter incomplete finalization",
                )
        finalize, finalize_process = self._next(
            controller, task_id, "finalize_verification_incomplete"
        )
        terminal = self._apply(
            controller,
            task_id,
            repository,
            finalize,
            finalize_process,
            self._standard_payload(
                finalize,
                repository,
                task_id,
                remaining_risks={"verification": "focused command still fails"},
            ),
        )
        terminal, terminal_next = self._next(controller, task_id)
        outcome = self._inspect_terminal(
            controller,
            task_id,
            terminal,
            expected_status="INCOMPLETE",
            expected_outcome="incomplete",
        )
        _require(
            outcome["dossier"].get("remaining_risks")
            == {"verification": "focused command still fails"},
            "incomplete dossier did not retain verification risk",
        )
        self.evidence["journeys"].append(
            {
                "name": "verification-rework-exhaustion",
                "task_id": task_id,
                "start_process": start_process,
                "terminal_next_process": terminal_next,
                "retry_budgets": retry_evidence,
                "outcome": "incomplete",
            }
        )

    def criterion_waiver_journey(self) -> None:
        task_id = "stage1-criterion-waiver"
        repository = self._make_repository("criterion-waiver")
        controller = self._controller("criterion-waiver", repository)
        contract = {
            "schema": CONTRACT_SCHEMA,
            "revision": 1,
            "summary": "Installed delivery with one optional criterion",
            "acceptance_criteria": [
                {"id": "required", "statement": "Installed delivery works"},
                {"id": "optional", "statement": "Optional environment is checked"},
            ],
            "scope": ["Current scratch repository"],
            "constraints": ["Single operator"],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }
        _, start_process = controller.start(
            task_id,
            "lite",
            repository,
            "Exercise criterion waiver",
            contract,
        )
        self._record_task(task_id)
        preflight, next_process = self._next(controller, task_id, "preflight")
        self._apply(controller, task_id, repository, preflight, next_process, {})
        decision = {
            "id": "installed-criterion-waiver",
            "kind": "criterion-waiver",
            "subject": "optional",
            "outcome": "waived",
            "rationale": "The optional environment is outside this installed acceptance",
            "actor_label": "installed-acceptance",
        }
        _, decision_process = controller.decide(task_id, decision)
        self.evidence["decisions"].append(
            {
                "task_id": task_id,
                "process_index": decision_process,
                "decision": decision,
            }
        )
        implement, next_process = self._next(controller, task_id, "implement")
        self._apply(
            controller,
            task_id,
            repository,
            implement,
            next_process,
            self._standard_payload(implement, repository, task_id),
        )
        verify, next_process = self._next(controller, task_id, "verify")
        self._apply(
            controller,
            task_id,
            repository,
            verify,
            next_process,
            self._standard_payload(
                verify,
                repository,
                task_id,
                unverified_criteria=("optional",),
            ),
        )
        terminal = self._complete_success(controller, task_id, repository, "lite")
        outcome = self._inspect_terminal(
            controller,
            task_id,
            terminal,
            expected_status="DONE",
            expected_outcome="success",
        )
        coverage = outcome["dossier"].get("coverage")
        _require(
            isinstance(coverage, Mapping)
            and coverage.get("required", {}).get("status") == "proven"
            and coverage.get("optional", {}).get("status") == "waived",
            "criterion waiver was not authoritative dossier coverage",
        )
        self.evidence["journeys"].append(
            {
                "name": "criterion-waiver",
                "task_id": task_id,
                "start_process": start_process,
                "decision_process": decision_process,
                "outcome": "success",
            }
        )

    def revision_and_resources_journey(self) -> None:
        task_id = "stage1-contract-revision"
        repository = self._make_repository("contract-revision")
        controller = self._controller("contract-revision", repository)
        _, start_process = controller.start(
            task_id,
            "feature",
            repository,
            "Exercise installed contract and resource recovery",
        )
        self._record_task(task_id)

        preflight, process_index = self._next(controller, task_id, "preflight")
        self._apply(controller, task_id, repository, preflight, process_index, {})
        impact, process_index = self._next(controller, task_id, "impact")
        self._apply(
            controller,
            task_id,
            repository,
            impact,
            process_index,
            self._standard_payload(impact, repository, task_id),
        )
        planning, process_index = self._next(controller, task_id, "planning")
        planning_payload = self._standard_payload(
            planning, repository, task_id, resource_version=1
        )
        self._apply(
            controller,
            task_id,
            repository,
            planning,
            process_index,
            planning_payload,
            prepared_source_paths=(
                "openspec/changes/{}/proposal.md".format(task_id),
                "openspec/changes/{}/tasks.md".format(task_id),
            ),
        )

        implementation, process_index = self._next(controller, task_id, "implement")
        tasks_path = (
            repository
            / "openspec"
            / "changes"
            / task_id
            / "tasks.md"
        )
        tasks_path.write_text(
            "- [x] verify installed journey v1\n", encoding="utf-8"
        )
        self._apply(
            controller,
            task_id,
            repository,
            implementation,
            process_index,
            self._standard_payload(implementation, repository, task_id),
            prepared_source_paths=(
                "openspec/changes/{}/tasks.md".format(task_id),
            ),
        )
        semantic_show, semantic_show_process = controller.show(task_id)
        semantic_task = semantic_show.get("task")
        _require(isinstance(semantic_task, Mapping), "semantic resource view is unavailable")
        plan_pair = self._artifact(semantic_task, "delivery-plan")
        plan_record_id = plan_pair["record"].get("record_id")
        freshness = semantic_task.get("artifact_freshness")
        _require(
            isinstance(freshness, Mapping)
            and freshness.get(plan_record_id, {}).get("current") is True,
            "OpenSpec task checkbox-only edit invalidated the governing plan",
        )
        resources_before = plan_pair["artifact"].get("resources")
        current_resources = semantic_task.get("current_snapshot", {}).get("resources")
        _require(
            isinstance(resources_before, list) and isinstance(current_resources, list),
            "resource snapshots are unavailable",
        )

        def resource(items: Sequence[object], normalizer: str) -> Mapping[str, object]:
            for item in items:
                if (
                    isinstance(item, Mapping)
                    and item.get("path")
                    == "openspec/changes/{}/tasks.md".format(task_id)
                    and item.get("normalizer") == normalizer
                ):
                    return item
            raise AcceptanceFailure("tasks resource {} is absent".format(normalizer))

        reported_before = resource(resources_before, "none")
        reported_after = resource(current_resources, "none")
        governed_before = resource(resources_before, "openspec-tasks-v1")
        governed_after = resource(current_resources, "openspec-tasks-v1")
        _require(
            reported_before.get("raw_sha256") != reported_after.get("raw_sha256"),
            "reported task checkbox bytes did not change",
        )
        _require(
            governed_before.get("semantic_sha256")
            == governed_after.get("semantic_sha256"),
            "OpenSpec task checkbox normalization was not semantically stable",
        )

        documentation, process_index = self._next(controller, task_id, "documentation")
        self._apply(
            controller,
            task_id,
            repository,
            documentation,
            process_index,
            self._standard_payload(documentation, repository, task_id),
        )
        verification, process_index = self._next(controller, task_id, "verify")
        self._apply(
            controller,
            task_id,
            repository,
            verification,
            process_index,
            self._standard_payload(
                verification,
                repository,
                task_id,
                passed=False,
                unverified_criteria=("requirement",),
            ),
        )
        rework, process_index = self._next(
            controller, task_id, "verification_rework"
        )
        self._apply(
            controller,
            task_id,
            repository,
            rework,
            process_index,
            self._standard_payload(rework, repository, task_id),
        )
        documentation, process_index = self._next(controller, task_id, "documentation")
        self._apply(
            controller,
            task_id,
            repository,
            documentation,
            process_index,
            self._standard_payload(documentation, repository, task_id),
        )
        retry_projection, retry_process = self._next(controller, task_id, "verify")
        retry_action = retry_projection.get("action")
        retry_before_revision = (
            retry_action.get("retry_budget") if isinstance(retry_action, Mapping) else None
        )
        _require(
            isinstance(retry_before_revision, Mapping)
            and retry_before_revision.get("attempts_used") == 1,
            "verification retry budget was not consumed before revision",
        )

        proposal_path = (
            repository
            / "openspec"
            / "changes"
            / task_id
            / "proposal.md"
        )
        proposal_path.write_text(
            "# Substantive change\n\nThe governing obligation changed.\n",
            encoding="utf-8",
        )
        blocked, blocked_process = self._next(controller, task_id, "verify")
        blocked_action = blocked.get("action")
        _require(
            isinstance(blocked_action, Mapping)
            and blocked_action.get("binding") is None
            and blocked_action.get("blocked", {}).get("code")
            == "ARTIFACT_INPUT_MISSING",
            "substantive governing resource edit did not invalidate the action",
        )

        revised_contract = {
            "schema": CONTRACT_SCHEMA,
            "revision": 2,
            "summary": "Recovered installed delivery scope",
            "acceptance_criteria": [
                {
                    "id": "requirement",
                    "statement": "The revised installed scope is verified",
                }
            ],
            "scope": ["Recovered scratch repository delivery"],
            "constraints": ["Single repository", "Single operator"],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }
        revised, revision_process = controller.revise(
            task_id,
            revised_contract,
            "Governing OpenSpec obligation changed",
            "installed-acceptance",
        )
        revised_projection = self._projection(revised)
        _require(
            revised_projection.get("contract", {}).get("revision") == 2
            and revised_projection.get("current_node") == "impact",
            "accepted contract revision did not restart at the workflow revision target",
        )
        revision_show, revision_show_process = controller.show(task_id)
        revision_task = revision_show.get("task")
        _require(isinstance(revision_task, Mapping), "revision task view is unavailable")
        revision_source = self._artifact(revision_task, "revision-source")
        _require(
            revision_source["artifact"].get("contract_revision") == 2,
            "revision-source did not bind the revised contract",
        )

        impact, process_index = self._next(controller, task_id, "impact")
        self._apply(
            controller,
            task_id,
            repository,
            impact,
            process_index,
            self._standard_payload(
                impact, repository, task_id, driver_status="degraded"
            ),
        )
        planning, process_index = self._next(controller, task_id, "planning")
        planning_payload = self._standard_payload(
            planning, repository, task_id, resource_version=2
        )
        self._apply(
            controller,
            task_id,
            repository,
            planning,
            process_index,
            planning_payload,
            prepared_source_paths=(
                "openspec/changes/{}/proposal.md".format(task_id),
                "openspec/changes/{}/tasks.md".format(task_id),
            ),
        )
        implementation, process_index = self._next(controller, task_id, "implement")
        self._apply(
            controller,
            task_id,
            repository,
            implementation,
            process_index,
            self._standard_payload(implementation, repository, task_id),
        )
        documentation, process_index = self._next(controller, task_id, "documentation")
        self._apply(
            controller,
            task_id,
            repository,
            documentation,
            process_index,
            self._standard_payload(documentation, repository, task_id),
        )
        fresh_verify, fresh_retry_process = self._next(controller, task_id, "verify")
        fresh_action = fresh_verify.get("action")
        fresh_retry_budget = (
            fresh_action.get("retry_budget") if isinstance(fresh_action, Mapping) else None
        )
        _require(
            isinstance(fresh_retry_budget, Mapping)
            and fresh_retry_budget.get("attempts_used") == 0
            and fresh_retry_budget.get("remaining")
            == fresh_retry_budget.get("max_attempts"),
            "contract revision did not establish a fresh assurance budget",
        )
        self._apply(
            controller,
            task_id,
            repository,
            fresh_verify,
            fresh_retry_process,
            self._standard_payload(fresh_verify, repository, task_id),
        )
        terminal = self._complete_success(controller, task_id, repository, "feature")
        outcome = self._inspect_terminal(
            controller,
            task_id,
            terminal,
            expected_status="DONE",
            expected_outcome="success",
            baseline_type="revision-source",
        )
        _require(
            outcome["dossier"].get("contract_revision") == 2,
            "terminal dossier did not use the revised contract",
        )
        self.evidence["journeys"].append(
            {
                "name": "contract-revision-and-openspec-resources",
                "task_id": task_id,
                "start_process": start_process,
                "checkbox_semantic_show_process": semantic_show_process,
                "checkbox_reported_raw_changed": True,
                "checkbox_governing_semantic_stable": True,
                "checkbox_resource_hashes": {
                    "reported_raw_before": reported_before.get("raw_sha256"),
                    "reported_raw_after": reported_after.get("raw_sha256"),
                    "governing_semantic_before": governed_before.get(
                        "semantic_sha256"
                    ),
                    "governing_semantic_after": governed_after.get(
                        "semantic_sha256"
                    ),
                },
                "retry_projection_process": retry_process,
                "retry_budget_before_revision": retry_before_revision,
                "blocked_process": blocked_process,
                "blocked_code": "ARTIFACT_INPUT_MISSING",
                "revision_process": revision_process,
                "revision_show_process": revision_show_process,
                "revision_source_record_id": revision_source["record"].get("record_id"),
                "fresh_retry_process": fresh_retry_process,
                "fresh_retry_budget": fresh_retry_budget,
                "outcome": "success",
            }
        )

    def inspect_assets(self) -> None:
        required = (
            ".codex-plugin/plugin.json",
            "hooks/hooks.json",
            "hooks/dev_flow_hook.py",
            "scripts/dev_flow.py",
            "scripts/dev_flow_python_launcher",
            "scripts/validate_package.py",
            "src/dev_flow_orchestrator/cli.py",
        )
        missing = [item for item in required if not (self.plugin_root / item).is_file()]
        _require(not missing, "installed snapshot is missing assets: {}".format(missing))
        _require(os.access(str(self.launcher), os.X_OK), "installed launcher is not executable")
        manifest = _read_json_object(
            self.plugin_root / ".codex-plugin" / "plugin.json", "plugin manifest"
        )
        version = manifest.get("version")
        _require(
            isinstance(version, str) and VERSION_V6.fullmatch(version) is not None,
            "installed manifest is not a V6 cache version",
        )
        _require(
            manifest.get("name") == "dev-flow-orchestrator"
            and manifest.get("skills") == "./skills/",
            "installed manifest identity or skill root is invalid",
        )
        workflows = []
        for workflow in OFFICIAL_WORKFLOWS:
            path = self.plugin_root / "workflows" / "{}.yaml".format(workflow)
            _require(path.is_file(), "installed workflow is missing: {}".format(workflow))
            document = path.read_text(encoding="utf-8")
            _require(
                "schema: dev-flow-workflow/v2" in document
                and re.search(r"(?m)^id:\s*{}\s*$".format(re.escape(workflow)), document)
                is not None
                and re.search(r"(?m)^version:\s*6\s*$", document) is not None
                and "delivery-dossier" in document,
                "installed workflow asset is not the expected V6 contract: {}".format(
                    workflow
                ),
            )
            workflows.append(
                {
                    "id": workflow,
                    "path": "workflows/{}.yaml".format(workflow),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        skills = []
        for skill in EXPECTED_SKILLS:
            path = self.plugin_root / "skills" / skill / "SKILL.md"
            agent = self.plugin_root / "skills" / skill / "agents" / "openai.yaml"
            _require(path.is_file(), "installed Skill is missing: {}".format(skill))
            _require(agent.is_file(), "installed Skill agent metadata is missing: {}".format(skill))
            document = path.read_text(encoding="utf-8")
            _require(
                re.search(r"(?m)^name:\s*{}\s*$".format(re.escape(skill)), document)
                is not None,
                "installed Skill metadata is invalid: {}".format(skill),
            )
            skills.append(
                {
                    "id": skill,
                    "path": "skills/{}/SKILL.md".format(skill),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "agent_sha256": hashlib.sha256(agent.read_bytes()).hexdigest(),
                }
            )
        hooks = _read_json_object(
            self.plugin_root / "hooks" / "hooks.json", "Hook manifest"
        )
        hook_document = _json_text(hooks)
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse"):
            _require(event in hook_document, "installed Hook manifest omits {}".format(event))
        _require(
            "dev_flow_python_launcher" in hook_document
            and "dev_flow_hook.py" in hook_document,
            "installed Hook manifest does not use the public bootstrap",
        )
        self.evidence["installed"].update(
            {
                "version": version,
                "manifest": manifest,
                "assets": {
                    "workflows": workflows,
                    "skills": skills,
                    "hook_manifest_sha256": hashlib.sha256(
                        (self.plugin_root / "hooks" / "hooks.json").read_bytes()
                    ).hexdigest(),
                    "launcher_executable": True,
                },
            }
        )

    def run_package_validator(self) -> None:
        result, process_index = self.recorder.run_json(
            (
                str(self.launcher),
                str(self.plugin_root / "scripts" / "validate_package.py"),
            ),
            cwd=self.plugin_root,
            kind="installed-package-validator",
            timeout=120,
        )
        _require(result.get("ok") is True, "installed package validator did not pass")
        self.evidence["package_validation"] = {
            "process_index": process_index,
            "result": _command_result_summary(result),
        }

    def retained_v5_before(self) -> None:
        if self.retained_v5_root is None:
            self.evidence["retained_v5"] = {
                "status": "not-provided",
                "snapshot_inspection": "skipped",
                "read_only_inspection": "skipped",
            }
            return
        _require(self.retained_v5_root.is_dir(), "retained V5 root is not a directory")
        launcher = self.retained_v5_root / "scripts" / "dev_flow_python_launcher"
        handler = self.retained_v5_root / "scripts" / "dev_flow.py"
        _require(launcher.is_file() and os.access(str(launcher), os.X_OK), "retained V5 launcher is unavailable")
        _require(handler.is_file(), "retained V5 CLI handler is unavailable")
        manifest_path = self.retained_v5_root / ".codex-plugin" / "plugin.json"
        manifest = _read_json_object(manifest_path, "retained V5 plugin manifest")
        version = manifest.get("version")
        _require(
            manifest.get("name") == "dev-flow-orchestrator"
            and isinstance(version, str)
            and VERSION_V5.fullmatch(version) is not None,
            "retained plugin root is not an installed V5 snapshot",
        )
        root_digest = _tree_digest(self.retained_v5_root, ignore_volatile=True)
        retained = {
            "status": "snapshot-verified",
            "root": str(self.retained_v5_root),
            "version": version,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "snapshot_algorithm": "dev-flow-tree-snapshot/v1",
            "snapshot_digest_before": root_digest,
            "snapshot_digest_after": None,
            "snapshot_immutable_during_run": None,
            "launcher_executable": True,
        }
        self.evidence["retained_v5"] = retained
        if self.retained_v5_data is None:
            retained["status"] = "snapshot-verified-inspection-required"
            retained["data_evidence"] = {
                "status": "unverified",
                "authority": "exact retained V5 controller locator",
                "operations": ["list", "show"],
                "phases": ["before-v6-journeys", "after-v6-journeys"],
                "runner_access": "not-requested",
                "reason": (
                    "An active V5 Hook may correctly deny passing protected V5 "
                    "data to an external runner; separately captured read-only "
                    "list/show evidence is required before the release gate can pass."
                ),
            }
            return
        _require(self.retained_v5_data.is_dir(), "retained V5 data is not a directory")
        digest = _tree_digest(self.retained_v5_data, ignore_volatile=False)
        controller = InstalledController(
            self.recorder,
            launcher,
            handler,
            self.retained_v5_data,
            self.retained_v5_root,
            kind_prefix="retained-v5-read-only",
        )
        listed, list_process = controller._call("list")
        tasks = listed.get("tasks")
        _require(isinstance(tasks, list), "retained V5 list result has no tasks")
        inspections = []
        for item in tasks:
            _require(isinstance(item, Mapping), "retained V5 list item is invalid")
            task_id = item.get("task_id")
            _require(isinstance(task_id, str) and task_id, "retained V5 task id is invalid")
            shown, show_process = controller.show(task_id)
            task = shown.get("task")
            _require(isinstance(task, Mapping), "retained V5 show result is invalid")
            inspections.append(
                {
                    "task_id": task_id,
                    "show_process": show_process,
                    "revision": task.get("revision"),
                    "status": task.get("status"),
                    "current_node": task.get("current_node"),
                    "workflow": task.get("workflow"),
                }
            )
        retained["status"] = "snapshot-and-data-inspected"
        retained["data_evidence"] = {
            "status": "inspected-read-only",
            "data_digest_before": digest,
            "list_process": list_process,
            "task_ids": [item["task_id"] for item in inspections],
            "inspections": inspections,
            "operations": ["list", "show"],
            "read_only": True,
        }

    def retained_v5_after(self) -> None:
        if self.retained_v5_root is None:
            return
        retained = self.evidence["retained_v5"]
        root_after = _tree_digest(self.retained_v5_root, ignore_volatile=True)
        root_before = retained.get("snapshot_digest_before")
        retained["snapshot_digest_after"] = root_after
        retained["snapshot_immutable_during_run"] = root_before == root_after
        _require(
            root_before == root_after,
            "retained V5 plugin snapshot changed during V6 acceptance journeys",
        )
        if self.retained_v5_data is None:
            return
        after = _tree_digest(self.retained_v5_data, ignore_volatile=False)
        data_evidence = retained["data_evidence"]
        before = data_evidence.get("data_digest_before")
        data_evidence["data_digest_after"] = after
        data_evidence["unchanged"] = before == after
        _require(before == after, "retained V5 data changed during V6 acceptance journeys")

    def hook_bootstrap(self) -> None:
        task_id = "stage1-hook-bootstrap"
        repository = self._make_repository("hook-bootstrap")
        plugin_data = self.scratch / "hook-plugin-data"
        controller = InstalledController(
            self.recorder,
            self.launcher,
            self.cli_handler,
            plugin_data / "v6",
            repository,
        )
        _, start_process = controller.start(
            task_id,
            "lite",
            repository,
            "Expose installed Hook controller context",
        )
        self._record_task(task_id)
        payload = {
            "hook_event_name": "SessionStart",
            "cwd": str(repository),
            "session_id": "installed-stage1",
        }
        hook_environment = dict(self.recorder.environment)
        hook_environment["PLUGIN_DATA"] = str(plugin_data)
        original_environment = self.recorder.environment
        self.recorder.environment = hook_environment
        try:
            output, hook_process = self.recorder.run_json(
                (
                    str(self.launcher),
                    str(self.plugin_root / "hooks" / "dev_flow_hook.py"),
                ),
                cwd=repository,
                kind="installed-hook:SessionStart",
                input_text=_json_text(payload),
                timeout=30,
            )
        finally:
            self.recorder.environment = original_environment
        specific = output.get("hookSpecificOutput")
        context = specific.get("additionalContext") if isinstance(specific, Mapping) else None
        _require(
            isinstance(context, str)
            and "Current Dev Flow V6 task" in context
            and task_id in context
            and "locator=" in context
            and "projection=" in context
            and str((plugin_data / "v6").resolve()) in context,
            "installed Hook bootstrap did not inject the V6 task and locator",
        )
        locator_text = context.split(" locator=", 1)[1].split(" projection=", 1)[0]
        projected_text = context.split(" projection=", 1)[1]
        projected = _strict_json(projected_text, "installed Hook projection")
        _require(
            isinstance(projected, Mapping) and projected.get("task_id") == task_id,
            "installed Hook projection does not identify its current task",
        )
        preflight, preflight_next_process = self._next(
            controller, task_id, "preflight"
        )
        self._apply(
            controller,
            task_id,
            repository,
            preflight,
            preflight_next_process,
            {},
        )
        cancelled, cancel_process = controller.cancel(
            task_id, "Hook bootstrap inspection complete"
        )
        cancelled_projection = self._projection(cancelled)
        _require(
            cancelled_projection.get("done") is True
            and cancelled_projection.get("status") == "CANCELLED",
            "Hook bootstrap task did not cancel after preflight",
        )
        shown, show_process = controller.show(task_id)
        shown_task = shown.get("task")
        _require(isinstance(shown_task, Mapping), "Hook task show view is unavailable")
        self.evidence["baselines"][task_id] = self._baseline_summary(
            self._artifact(shown_task, "repository-baseline")
        )
        self.evidence["outcomes"][task_id] = {
            "task_id": task_id,
            "status": shown_task.get("status"),
            "current_node": shown_task.get("current_node"),
            "revision": shown_task.get("revision"),
            "show_process": show_process,
        }
        self.evidence["hook"] = {
            "task_id": task_id,
            "start_process": start_process,
            "hook_process": hook_process,
            "preflight_next_process": preflight_next_process,
            "cancel_process": cancel_process,
            "show_process": show_process,
            "plugin_data_namespace": "v6",
            "session_start_context": {
                "locator": self.recorder._display(locator_text),
                "projection": self.recorder._display_value(
                    _projection_summary(projected)
                ),
            },
            "bootstrap_verified": True,
            "codex_new_task_pickup": "manual-unverified",
        }

    def run(self) -> None:
        self.inspect_assets()
        self.retained_v5_before()
        self.official_success_journeys()
        self.restart_resume_journey()
        self.cancellation_journey()
        self.verification_exhaustion_journey()
        self.criterion_waiver_journey()
        self.revision_and_resources_journey()
        self.hook_bootstrap()
        statuses = {
            path.get("result", {}).get("status")
            for path in self.evidence["driver_paths"]
            if isinstance(path.get("result"), Mapping)
        }
        _require(
            {"available", "degraded", "unavailable"}.issubset(statuses),
            "installed controller simulations did not cover available, degraded, and unavailable driver payloads",
        )
        self.evidence["controller_driver_simulation"] = {
            "evidence_class": "controller-contract-simulation",
            "qualifies_as_driver_execution": False,
            "statuses": sorted(statuses),
            "purpose": (
                "Exercise installed controller validation, fallback routing, "
                "persistence, and dossier projection"
            ),
        }
        self.retained_v5_after()
        self.run_package_validator()
        self.evidence["task_ids"] = sorted(set(self.evidence["task_ids"]))
        self.evidence["process_model"] = {
            "fresh_subprocess_per_command": True,
            "invocation_count": len(self.evidence["commands"]),
            "state_resumed_across_processes": True,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run macOS Stage 1 journeys through an installed immutable "
            "dev-flow-orchestrator snapshot."
        )
    )
    parser.add_argument(
        "--plugin-root",
        required=True,
        help="installed immutable plugin cache snapshot (a source root is valid only for focused self-tests)",
    )
    parser.add_argument(
        "--retained-v5-root",
        help=(
            "optional retained installed V5 plugin root; root-only mode verifies "
            "the snapshot and marks data list/show as external-controller evidence"
        ),
    )
    parser.add_argument(
        "--retained-v5-data",
        help="optional retained V5 data directory, paired with --retained-v5-root",
    )
    parser.add_argument(
        "--external-evidence",
        help=(
            "JSON evidence from actual OpenSpec, codebase-memory, independent-review, "
            "and retained V5 controller executions; required for a verified release gate"
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    plugin_root = Path(arguments.plugin_root).expanduser().resolve()
    retained_root = (
        Path(arguments.retained_v5_root).expanduser().resolve()
        if arguments.retained_v5_root
        else None
    )
    retained_data = (
        Path(arguments.retained_v5_data).expanduser().resolve()
        if arguments.retained_v5_data
        else None
    )
    external_evidence_path = (
        Path(arguments.external_evidence).expanduser().resolve()
        if arguments.external_evidence
        else None
    )
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "ok": False,
        "execution_ok": False,
        "platform": "macOS-current-host",
        "serialization": {
            "format": "canonical-json",
            "sort_keys": True,
            "path_tokens": ["<PLUGIN_ROOT>", "<SCRATCH>", "<RETAINED_V5_ROOT>", "<RETAINED_V5_DATA>"],
        },
        "installed": {
            "path": str(plugin_root),
            "snapshot_algorithm": "dev-flow-tree-snapshot/v1",
            "snapshot_digest_before": None,
            "snapshot_digest_after": None,
            "immutable_during_run": None,
        },
        "task_ids": [],
        "baselines": {},
        "commands": [],
        "actions": [],
        "driver_paths": [],
        "controller_driver_simulation": None,
        "external_evidence": None,
        "decisions": [],
        "journeys": [],
        "outcomes": {},
        "hook": None,
        "package_validation": None,
        "retained_v5": None,
        "process_model": None,
        "release_gate": {
            "status": "unverified",
            "blockers": [
                "actual driver execution evidence has not been validated",
                "retained V5 controller inspection evidence has not been validated",
            ],
        },
        "manual_unverified": [
            {
                "check": "new-Codex-task Hook and Skill pickup",
                "status": "manual-unverified",
                "reason": (
                    "Subprocesses prove the installed Hook bootstrap and Skill assets, "
                    "but cannot create a real new Codex task or exercise the Codex plugin loader."
                ),
            },
            {
                "check": "native Windows and Linux behavior",
                "status": "not-run",
                "reason": "Stage 1 installed validation is intentionally macOS-current-host only.",
            },
        ],
        "errors": [],
    }
    try:
        _require(sys.platform == "darwin", "installed Stage 1 acceptance is macOS-only")
        _require(plugin_root.is_dir(), "plugin root is not a directory")
        _require(
            retained_data is None or retained_root is not None,
            "--retained-v5-data requires --retained-v5-root",
        )
        before = _tree_digest(plugin_root, ignore_volatile=True)
        evidence["installed"]["snapshot_digest_before"] = before
        with tempfile.TemporaryDirectory(prefix="dev-flow-installed-stage1-") as temporary:
            scratch = Path(temporary).resolve()
            runner = Stage1Acceptance(
                plugin_root,
                scratch,
                retained_root,
                retained_data,
                evidence,
            )
            runner.run()
        after = _tree_digest(plugin_root, ignore_volatile=True)
        evidence["installed"]["snapshot_digest_after"] = after
        evidence["installed"]["immutable_during_run"] = before == after
        _require(before == after, "installed plugin snapshot changed during acceptance")
        evidence["execution_ok"] = True
        if external_evidence_path is None:
            evidence["release_gate"] = {
                "status": "unverified",
                "blockers": [
                    "actual OpenSpec, codebase-memory, and independent-review executions were not provided",
                    "retained V5 list/show before-and-after evidence was not provided",
                ],
            }
        else:
            external = _read_json_object(
                external_evidence_path, "external Stage 1 release evidence"
            )
            validated = _validate_external_release_evidence(
                external,
                before,
                evidence.get("retained_v5"),
            )
            evidence["external_evidence"] = validated
            retained_external = validated["retained_v5"]
            retained_view = evidence.get("retained_v5")
            if isinstance(retained_view, dict):
                retained_view["status"] = "snapshot-and-external-data-inspected"
                retained_view["data_evidence"] = {
                    "status": "external-controller-evidence-verified",
                    "inspection": retained_external,
                }
            evidence["release_gate"] = {
                "status": "verified-with-manual-pickup-condition",
                "blockers": [],
                "manual_condition": "new-Codex-task Hook and Skill pickup",
            }
            evidence["ok"] = True
    except (AcceptanceFailure, OSError, UnicodeError, ValueError) as exc:
        evidence["errors"].append(str(exc))
        if evidence.get("execution_ok"):
            evidence["release_gate"] = {
                "status": "invalid-external-evidence",
                "blockers": [str(exc)],
            }
        if plugin_root.is_dir():
            try:
                after = _tree_digest(plugin_root, ignore_volatile=True)
                evidence["installed"]["snapshot_digest_after"] = after
                before = evidence["installed"].get("snapshot_digest_before")
                evidence["installed"]["immutable_during_run"] = (
                    before == after if isinstance(before, str) else None
                )
            except (AcceptanceFailure, OSError) as digest_exc:
                evidence["errors"].append(
                    "could not hash final plugin snapshot: {}".format(digest_exc)
                )
    print(_json_text(evidence))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
