#!/usr/bin/env python3
"""Run Stage 1 acceptance journeys against one installed product snapshot.

This runner intentionally imports only the Python standard library.  Every
controller, Hook, and package-validation observation crosses an installed
process boundary through ``scripts/dev_flow_python_launcher``.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit


MODEL_VERSION = "0.4.0"
SEMANTIC_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


def _product_schema(kind: str) -> str:
    return "dev-flow-{}/{}".format(kind, MODEL_VERSION)


EVIDENCE_SCHEMA = _product_schema("installed-evidence")
EXTERNAL_EVIDENCE_SCHEMA = _product_schema("external-evidence")
DRIVER_RESULT_SCHEMA = _product_schema("driver-result")
CONTRACT_SCHEMA = _product_schema("delivery-contract")
AGENT_PROTOCOL_SCHEMA = _product_schema("agent")
VERIFICATION_COVERAGE_SCHEMA = _product_schema("verification-coverage")
DELIVERY_DOSSIER_SCHEMA = _product_schema("delivery-dossier")
WORKFLOW_SCHEMA = _product_schema("workflow")
TREE_SNAPSHOT_SCHEMA = _product_schema("tree-snapshot")
TASK_CHANGE_CLAIMS_SCHEMA = _product_schema("task-change-claims")
OPENSPEC_TASKS_NORMALIZER = "openspec-tasks/{}".format(MODEL_VERSION)
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


def _validate_external_release_evidence(
    value: object,
    installed_digest: str,
) -> dict:
    _require(isinstance(value, Mapping), "external release evidence must be an object")
    _require(
        value.get("schema") == EXTERNAL_EVIDENCE_SCHEMA,
        "external release evidence schema is invalid",
    )
    _require(
        value.get("installed_snapshot_digest") == installed_digest,
        "external release evidence is bound to another installed product snapshot",
    )
    driver_executions = _validate_external_driver_evidence(
        value.get("driver_executions")
    )
    return {
        "schema": EXTERNAL_EVIDENCE_SCHEMA,
        "installed_snapshot_digest": installed_digest,
        "driver_executions": driver_executions,
    }


def _tree_digest(root: Path, *, ignore_volatile: bool) -> str:
    """Hash path identity, kind, executable bits, and bytes without following links."""
    _require(root.is_dir(), "tree root is not a directory: {}".format(root))
    digest = hashlib.sha256()
    digest.update(TREE_SNAPSHOT_SCHEMA.encode("ascii") + b"\x00")
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
    repository_set = projection.get("repository_set")
    repository_set_summary = None
    if isinstance(repository_set, Mapping):
        members = repository_set.get("repositories")
        repository_set_summary = {
            "id": repository_set.get("id"),
            "digest": repository_set.get("digest"),
            "repositories": [
                {
                    "id": member.get("id"),
                    "path": member.get("path"),
                    "snapshot": member.get("snapshot"),
                }
                for member in members
                if isinstance(member, Mapping)
            ]
            if isinstance(members, list)
            else None,
        }
    return {
        "schema": projection.get("schema"),
        "task_id": projection.get("task_id"),
        "revision": projection.get("revision"),
        "workflow": projection.get("workflow"),
        "status": projection.get("status"),
        "current_node": projection.get("current_node"),
        "contract": projection.get("contract"),
        "repository_set": repository_set_summary,
        "action": action_summary,
        "dossier": projection.get("dossier"),
        "done": projection.get("done"),
    }


def _task_summary(task: object) -> object:
    if not isinstance(task, Mapping):
        return task
    records = task.get("records")
    return {
        "version": task.get("version"),
        "product_identity": task.get("product_identity"),
        "task_id": task.get("task_id"),
        "revision": task.get("revision"),
        "workflow": task.get("workflow"),
        "status": task.get("status"),
        "current_node": task.get("current_node"),
        "record_count": len(records) if isinstance(records, list) else None,
        "effective_contract": task.get("effective_contract"),
        "effective_contract_digest": task.get("effective_contract_digest"),
        "repository_set_id": task.get("repository_set_id"),
        "repositories": task.get("repositories"),
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
                if isinstance(context, str)
                and "Current Dev Flow " in context
                and " task" in context
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

    def run_json_failure(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        kind: str,
        timeout: int = 60,
    ) -> Tuple[dict, int]:
        """Record one expected controller rejection without hiding its evidence."""
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
        parsed = _strict_json(completed.stdout, "process {} stdout".format(index))
        _require(
            isinstance(parsed, dict),
            "process {} must return one JSON object".format(index),
        )
        entry["result"] = self._display_value(_command_result_summary(parsed))
        self.evidence["commands"].append(entry)
        _require(
            completed.returncode != 0 and parsed.get("ok") is False,
            "process {} did not produce the expected rejection".format(index),
        )
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
        kind_prefix: str = "product-cli",
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

    def start_repositories(
        self,
        task_id: str,
        workflow: str,
        repositories: Sequence[Path],
        requirement: str,
        contract: Optional[Mapping[str, object]] = None,
    ) -> Tuple[dict, int]:
        arguments = [
            "--requirement",
            requirement,
            "--workflow",
            workflow,
        ]
        for repository in repositories:
            arguments.extend(("--repo", str(repository)))
        arguments.extend(("--task-id", task_id))
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

    def apply_failure(
        self,
        task_id: str,
        projection: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> Tuple[dict, int]:
        action = projection.get("action")
        _require(isinstance(action, Mapping), "projection action is unavailable")
        binding = action.get("binding")
        _require(isinstance(binding, Mapping), "projection action binding is unavailable")
        return self.recorder.run_json_failure(
            (
                str(self.launcher),
                str(self.handler),
                "--data-dir",
                str(self.data_dir),
                "apply",
                task_id,
                "--action",
                str(action.get("action_id")),
                "--payload-json",
                _json_text(payload),
                "--binding-json",
                _json_text(binding),
            ),
            cwd=self.cwd,
            kind="{}:apply-expected-failure".format(self.kind_prefix),
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
        ownership_claims: Mapping[str, object],
        reason: str,
        actor_label: str,
    ) -> Tuple[dict, int]:
        return self._call(
            "revise-contract",
            (
                task_id,
                "--contract-json",
                _json_text(contract),
                "--ownership-claims-json",
                _json_text(ownership_claims),
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
        evidence: dict,
    ) -> None:
        self.plugin_root = plugin_root
        self.scratch = scratch
        self.evidence = evidence
        manifest = _read_json_object(
            plugin_root / ".codex-plugin" / "plugin.json", "plugin manifest"
        )
        self.release_version = manifest.get("version")
        _require(
            isinstance(self.release_version, str)
            and SEMANTIC_VERSION.fullmatch(self.release_version) is not None,
            "installed manifest release version is invalid",
        )
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
        repository_id: str,
    ) -> dict:
        change = "openspec/changes/{}".format(task_id)
        directory = repository / change
        directory.mkdir(parents=True, exist_ok=True)
        proposal = directory / "proposal.md"
        tasks = directory / "tasks.md"
        proposal.write_text(
            "# Installed plan {}\n\nGoverning obligation revision {}.\n".format(
                task_id, version
            ),
            encoding="utf-8",
        )
        tasks.write_text(
            "- [ ] verify installed journey revision {}\n".format(version),
            encoding="utf-8",
        )
        items = [
            {
                "repository_id": repository_id,
                "path": "{}/proposal.md".format(change),
                "role": "governing",
                "normalizer": "none",
            },
            {
                "repository_id": repository_id,
                "path": "{}/tasks.md".format(change),
                "role": "reported",
                "normalizer": "none",
            },
            {
                "repository_id": repository_id,
                "path": "{}/tasks.md".format(change),
                "role": "governing",
                "normalizer": OPENSPEC_TASKS_NORMALIZER,
            },
        ]
        return {"items": items}

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
        repository_set = projection.get("repository_set")
        members = (
            repository_set.get("repositories")
            if isinstance(repository_set, Mapping)
            else None
        )
        member_records = (
            tuple(item for item in members if isinstance(item, Mapping))
            if isinstance(members, list)
            else ()
        )
        repository_ids = tuple(
            str(item.get("id"))
            for item in member_records
            if isinstance(item.get("id"), str)
        )
        repository_id = next(
            (
                str(item.get("id"))
                for item in member_records
                if item.get("path") == str(repository)
                and isinstance(item.get("id"), str)
            ),
            None,
        )
        _require(
            projection.get("schema") == AGENT_PROTOCOL_SCHEMA
            and 1 <= len(repository_ids) <= 8
            and len(set(repository_ids)) == len(repository_ids)
            and repository_id is not None,
            "{} repository-set projection is incomplete".format(task_id),
        )
        integration_command = "python3 -m unittest focused-installed-integration-check"
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
                            "driver outcome routing, and replay behavior"
                        ),
                    },
                    "limitations": [
                        "This payload is generated by the installed acceptance runner and is not actual tool execution evidence."
                    ],
                }
            elif field == "resources":
                payload[field] = self._resource_payload(
                    repository,
                    task_id,
                    resource_version,
                    repository_id=repository_id,
                )
            elif field == "assurance_result":
                obligation = action.get("current_obligation")
                _require(
                    isinstance(obligation, Mapping)
                    and isinstance(obligation.get("obligation_id"), str),
                    "{} assurance action has no current obligation".format(task_id),
                )
                assurance_passed = passed
                result = {
                    "obligation_id": obligation["obligation_id"],
                    "passed": assurance_passed,
                    "evidence": [{
                        "kind": "installed-command",
                        "reference": integration_command,
                        "summary": "Installed controller assurance simulation completed",
                    }],
                    "limitations": [],
                }
                if obligation.get("kind") == "independent-review":
                    review_contract = action.get("review_contract")
                    _require(
                        isinstance(review_contract, Mapping),
                        "{} review action has no review contract".format(task_id),
                    )
                    assurance_passed = passed and not review_unavailable
                    result["passed"] = assurance_passed
                    result["review"] = {
                        "reviewer_available": not review_unavailable,
                        "independent": not review_unavailable,
                        "reviewer_digest": "a" * 64,
                        "review_scope_digest": review_contract.get("review_scope_digest"),
                        "guidance_digest": review_contract.get("guidance_digest"),
                        "workspace_digest": review_contract.get("workspace_digest"),
                        "findings": [],
                        "claimed_outcome": (
                            "approved" if assurance_passed else "unavailable"
                        ),
                    }
                payload[field] = result
            elif field == "evidence":
                payload[field] = {"finding": "installed behavior confirmed"}
            elif field == "passed":
                payload[field] = passed
            elif field == "command":
                payload[field] = integration_command
            elif field == "coverage":
                criteria = {
                    str(criterion_id): (
                        "unverified"
                        if criterion_id in set(unverified_criteria)
                        else "proven"
                    )
                    for criterion_id in criterion_ids
                }
                payload[field] = {
                    "schema": VERIFICATION_COVERAGE_SCHEMA,
                    "criteria": criteria,
                    "repositories": {
                        member_id: {
                            "command": (
                                "python3 -m unittest focused-installed-{}-check".format(
                                    member_id
                                )
                            ),
                            "passed": passed,
                        }
                        for member_id in repository_ids
                    },
                    "integration": {
                        "command": integration_command,
                        "passed": passed,
                    },
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
            resources = payload.get("resources")
            resource_items = (
                resources.get("items") if isinstance(resources, Mapping) else None
            )
            if isinstance(resource_items, list):
                source_paths.extend(
                    str(item["path"])
                    for item in resource_items
                    if isinstance(item, Mapping)
                    and isinstance(item.get("path"), str)
                )
            if "ownership_claims" not in payload:
                contract = projection.get("contract")
                criterion_ids = (
                    contract.get("criterion_ids")
                    if isinstance(contract, Mapping)
                    else None
                )
                _require(
                    isinstance(criterion_ids, list) and bool(criterion_ids),
                    "{} source action has no accepted criteria".format(task_id),
                )
                repository_set = projection.get("repository_set")
                members = (
                    repository_set.get("repositories")
                    if isinstance(repository_set, Mapping)
                    else None
                )
                repository_id = next(
                    (
                        str(item["id"])
                        for item in members
                        if isinstance(item, Mapping)
                        and item.get("path") == str(repository)
                        and isinstance(item.get("id"), str)
                    ),
                    None,
                ) if isinstance(members, list) else None
                _require(
                    repository_id is not None,
                    "{} source action has no repository identity".format(task_id),
                )
                payload = {
                    **dict(payload),
                    "ownership_claims": {
                        "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                        "claims": [
                            {
                                "repository_id": repository_id,
                                "path": path,
                                "classification": "implementation",
                                "criterion_ids": sorted(str(item) for item in criterion_ids),
                                "purpose": "Exercise the installed task-owned source interval",
                            }
                            for path in sorted(set(source_paths))
                        ],
                    },
                }
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

    def _revision_claims(
        self,
        task: Mapping[str, object],
        criterion_id: str,
    ) -> dict:
        records = task.get("records")
        _require(isinstance(records, list), "task record ledger is unavailable")
        manifest = None
        for record in reversed(records):
            artifact = record.get("artifact") if isinstance(record, Mapping) else None
            body = artifact.get("body") if isinstance(artifact, Mapping) else None
            candidate = body.get("task_change_manifest") if isinstance(body, Mapping) else None
            if isinstance(candidate, Mapping):
                manifest = candidate
                break
        _require(isinstance(manifest, Mapping), "current task-change manifest is unavailable")
        return {
            "schema": TASK_CHANGE_CLAIMS_SCHEMA,
            "claims": [{
                "repository_id": entry.get("repository_id"),
                "path": entry.get("path"),
                "classification": entry.get("classification"),
                "criterion_ids": [criterion_id],
                "purpose": "Reconcile installed journey ownership to the revised contract",
            } for entry in manifest.get("entries", ()) if isinstance(entry, Mapping)],
        }

    def _baseline_summary(self, pair: Mapping[str, object]) -> dict:
        record = pair["record"]
        artifact = pair["artifact"]
        snapshot = artifact.get("snapshot")
        _require(isinstance(snapshot, Mapping), "baseline snapshot is unavailable")
        snapshot_summary = {
            key: snapshot.get(key)
            for key in (
                "schema",
                "digest",
                "head",
                "branch",
                "clean",
                "status_sha256",
                "status_bytes",
                "repository_set_id",
            )
        }
        members = snapshot.get("repositories")
        if isinstance(members, list):
            snapshot_summary["repositories"] = [
                {
                    "repository_id": member.get("repository_id"),
                    "snapshot": member.get("snapshot"),
                }
                for member in members
                if isinstance(member, Mapping)
            ]
        return {
            "record_id": record.get("record_id"),
            "record_digest": record.get("digest"),
            "artifact_type": artifact.get("type"),
            "artifact_digest": artifact.get("digest"),
            "contract_revision": artifact.get("contract_revision"),
            "snapshot": snapshot_summary,
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
            "assurance_plan": body.get("assurance_plan"),
            "obligation_states": body.get("obligation_states"),
            "assurance_budget": body.get("assurance_budget"),
            "decision": body.get("decision"),
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
            "repository_set": body.get("repository_set"),
            "changed_repositories": body.get("changed_repositories"),
            "verification_attempts": body.get("verification_attempts"),
            "resources": body.get("resources"),
            "aggregate_freshness": body.get("aggregate_freshness"),
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
        _require(
            terminal_projection.get("schema") == AGENT_PROTOCOL_SCHEMA,
            "{} terminal projection schema is invalid".format(task_id),
        )
        baseline = self._baseline_summary(self._artifact(task, baseline_type))
        dossier = self._dossier_summary(self._artifact(task, "delivery-dossier"))
        _require(
            dossier.get("schema") == DELIVERY_DOSSIER_SCHEMA,
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
        if (workflow, tool) == ("investigation", "codebase-memory"):
            return "unavailable"
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
    ) -> Mapping[str, object]:
        steps = 0
        while True:
            projection, next_process = self._next(controller, task_id)
            if projection.get("done") is True:
                return projection
            steps += 1
            _require(steps <= 32, "{} exceeded the bounded workflow length".format(task_id))
            action = projection.get("action")
            _require(isinstance(action, Mapping), "{} action is unavailable".format(task_id))
            driver = action.get("driver")
            tool = driver.get("tool") if isinstance(driver, Mapping) else None
            payload = self._standard_payload(
                projection,
                repository,
                task_id,
                driver_status=self._driver_status(workflow, tool),
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
            started, start_process = controller.start_repositories(
                task_id,
                workflow,
                (repository,),
                "Installed {} delivery".format(workflow),
            )
            task = started.get("task")
            _require(isinstance(task, Mapping), "{} start task is unavailable".format(task_id))
            workflow_view = task.get("workflow")
            _require(
                isinstance(workflow_view, Mapping)
                and workflow_view.get("id") == workflow
                and workflow_view.get("version") == MODEL_VERSION,
                "{} did not start the installed current workflow".format(task_id),
            )
            self._record_task(task_id)
            terminal = self._complete_success(
                controller,
                task_id,
                repository,
                workflow,
            )
            outcome = self._inspect_terminal(
                controller,
                task_id,
                terminal,
                expected_status="DONE",
                expected_outcome="success",
            )
            self.evidence["journeys"].append(
                {
                    "name": "official-success-{}".format(workflow),
                    "task_id": task_id,
                    "start_process": start_process,
                    "outcome": "success",
                }
            )

    def exact_set_journey(self) -> None:
        task_id = "stage1-exact-set"
        primary = self._make_repository("exact-set-primary")
        secondary = self._make_repository("exact-set-secondary")
        plugin_data = self.scratch / "exact-set-plugin-data"
        primary_controller = InstalledController(
            self.recorder,
            self.launcher,
            self.cli_handler,
            plugin_data / MODEL_VERSION,
            primary,
        )
        secondary_controller = InstalledController(
            self.recorder,
            self.launcher,
            self.cli_handler,
            plugin_data / MODEL_VERSION,
            secondary,
        )
        started, start_process = primary_controller.start_repositories(
            task_id,
            "feature",
            (primary, secondary),
            "Deliver one installed change across an exact repository set",
        )
        task = started.get("task")
        members = task.get("repositories") if isinstance(task, Mapping) else None
        _require(
            isinstance(members, list) and len(members) == 2,
            "exact-set start did not persist both repositories",
        )
        repository_ids = tuple(
            str(item.get("id"))
            for item in members
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        )
        _require(
            len(repository_ids) == 2 and len(set(repository_ids)) == 2,
            "exact-set start did not derive two repository IDs",
        )
        self._record_task(task_id)

        primary_projection, primary_next_process = self._next(
            primary_controller, task_id, "preflight"
        )
        secondary_projection, secondary_resume_process = self._next(
            secondary_controller, task_id, "preflight"
        )
        for projection in (primary_projection, secondary_projection):
            repository_set = projection.get("repository_set")
            projected_members = (
                repository_set.get("repositories")
                if isinstance(repository_set, Mapping)
                else None
            )
            _require(
                projection.get("schema") == AGENT_PROTOCOL_SCHEMA
                and isinstance(projected_members, list)
                and {
                    item.get("id")
                    for item in projected_members
                    if isinstance(item, Mapping)
                }
                == set(repository_ids),
                "secondary-member resume did not return the complete current projection",
            )

        hook_environment = dict(self.recorder.environment)
        hook_environment["PLUGIN_DATA"] = str(plugin_data)
        original_environment = self.recorder.environment
        self.recorder.environment = hook_environment
        try:
            hook_output, secondary_hook_process = self.recorder.run_json(
                (
                    str(self.launcher),
                    str(self.plugin_root / "hooks" / "dev_flow_hook.py"),
                ),
                cwd=secondary,
                kind="installed-hook:exact-set-secondary-SessionStart",
                input_text=_json_text(
                    {
                        "hook_event_name": "SessionStart",
                        "cwd": str(secondary),
                        "session_id": "installed-exact-set-secondary",
                    }
                ),
                timeout=30,
            )
        finally:
            self.recorder.environment = original_environment
        specific = hook_output.get("hookSpecificOutput")
        context = (
            specific.get("additionalContext")
            if isinstance(specific, Mapping)
            else None
        )
        _require(
            isinstance(context, str)
            and "Current Dev Flow {} task".format(self.release_version) in context
            and task_id in context
            and "projection=" in context,
            "installed Hook did not discover the exact-set task from its secondary member",
        )
        hook_projection = _strict_json(
            context.split(" projection=", 1)[1],
            "installed exact-set secondary Hook projection",
        )
        hook_repository_set = (
            hook_projection.get("repository_set")
            if isinstance(hook_projection, Mapping)
            else None
        )
        hook_members = (
            hook_repository_set.get("repositories")
            if isinstance(hook_repository_set, Mapping)
            else None
        )
        _require(
            isinstance(hook_projection, Mapping)
            and hook_projection.get("schema") == AGENT_PROTOCOL_SCHEMA
            and hook_projection.get("task_id") == task_id
            and isinstance(hook_members, list)
            and {
                item.get("id")
                for item in hook_members
                if isinstance(item, Mapping)
            }
            == set(repository_ids),
            "installed secondary-member Hook pickup omitted repository-set scope",
        )

        stale_action = primary_projection.get("action")
        stale_binding = (
            stale_action.get("binding") if isinstance(stale_action, Mapping) else None
        )
        _require(
            isinstance(stale_binding, Mapping),
            "exact-set preflight binding is unavailable",
        )
        drift_path = secondary / "member-drift.txt"
        drift_path.write_text("secondary member drift\n", encoding="utf-8")
        rejected, drift_rejection_process = secondary_controller.apply_failure(
            task_id,
            primary_projection,
            {},
        )
        error = rejected.get("error")
        _require(
            isinstance(error, Mapping)
            and error.get("code") == "ACTION_BINDING_STALE",
            "secondary-member drift did not reject the stale aggregate binding",
        )

        fresh_preflight, fresh_preflight_process = self._next(
            secondary_controller, task_id, "preflight"
        )
        fresh_action = fresh_preflight.get("action")
        fresh_binding = (
            fresh_action.get("binding") if isinstance(fresh_action, Mapping) else None
        )
        _require(
            isinstance(fresh_binding, Mapping)
            and fresh_binding.get("starting_snapshot_digest")
            != stale_binding.get("starting_snapshot_digest"),
            "secondary-member drift did not change the aggregate snapshot binding",
        )
        self._apply(
            secondary_controller,
            task_id,
            secondary,
            fresh_preflight,
            fresh_preflight_process,
            {},
        )
        terminal = self._complete_success(
            secondary_controller,
            task_id,
            primary,
            "feature",
        )
        outcome = self._inspect_terminal(
            secondary_controller,
            task_id,
            terminal,
            expected_status="DONE",
            expected_outcome="success",
        )
        dossier = outcome["dossier"]
        repository_set = dossier.get("repository_set")
        dossier_members = (
            repository_set.get("members")
            if isinstance(repository_set, Mapping)
            else None
        )
        _require(
            dossier.get("schema") == DELIVERY_DOSSIER_SCHEMA
            and isinstance(dossier_members, list)
            and {
                item.get("repository_id")
                for item in dossier_members
                if isinstance(item, Mapping)
            }
            == set(repository_ids),
            "aggregate dossier does not identify both exact-set members",
        )
        assurance_plan = dossier.get("assurance_plan")
        obligations = (
            assurance_plan.get("obligations")
            if isinstance(assurance_plan, Mapping)
            else None
        )
        obligation_states = dossier.get("obligation_states")
        repository_results = {
            str(repository_id)
            for obligation in obligations
            if isinstance(obligation, Mapping)
            and obligation.get("kind") == "repository-check"
            for repository_id in obligation.get("repository_ids", [])
        } if isinstance(obligations, list) else set()
        integrations = [
            obligation
            for obligation in obligations
            if isinstance(obligation, Mapping)
            and obligation.get("kind") == "integration-check"
        ] if isinstance(obligations, list) else []
        _require(
            repository_results == set(repository_ids)
            and (
                any(
                    set(item.get("repository_ids", [])) == set(repository_ids)
                    for item in integrations
                )
                or (
                    isinstance(assurance_plan.get("not_required"), Mapping)
                    and assurance_plan["not_required"].get("integration") is True
                )
            )
            and isinstance(obligation_states, list)
            and all(
                isinstance(item, Mapping)
                and item.get("state") in ("satisfied", "reused", "waived")
                for item in obligation_states
            ),
            "aggregate dossier does not retain complete structured verification",
        )
        resources = dossier.get("resources")
        scoped_repository_ids = {
            item.get("resource", {}).get("repository_id")
            for item in resources
            if isinstance(item, Mapping)
            and isinstance(item.get("resource"), Mapping)
        } if isinstance(resources, list) else set()
        _require(
            bool(scoped_repository_ids)
            and scoped_repository_ids.issubset(set(repository_ids)),
            "aggregate dossier does not retain repository-scoped resources",
        )
        aggregate_freshness = dossier.get("aggregate_freshness")
        _require(
            isinstance(aggregate_freshness, Mapping)
            and aggregate_freshness.get("current") is True,
            "aggregate dossier freshness is not current",
        )
        self.evidence["journeys"].append(
            {
                "name": "exact-set-secondary-resume-drift-resources-dossier",
                "task_id": task_id,
                "repository_ids": list(repository_ids),
                "start_process": start_process,
                "primary_next_process": primary_next_process,
                "secondary_resume_process": secondary_resume_process,
                "secondary_hook_process": secondary_hook_process,
                "secondary_hook_schema": hook_projection.get("schema"),
                "drift_rejection_process": drift_rejection_process,
                "drift_error": error.get("code"),
                "stale_aggregate_digest": stale_binding.get(
                    "starting_snapshot_digest"
                ),
                "fresh_aggregate_digest": fresh_binding.get(
                    "starting_snapshot_digest"
                ),
                "scoped_resource_repository_ids": sorted(scoped_repository_ids),
                "dossier_schema": dossier.get("schema"),
                "outcome": "success",
            }
        )

    def exact_set_lite_journey(self) -> None:
        task_id = "stage1-exact-set-lite"
        primary = self._make_repository("exact-set-lite-primary")
        secondary = self._make_repository("exact-set-lite-secondary")
        controller = self._controller("exact-set-lite", primary)
        started, start_process = controller.start_repositories(
            task_id,
            "lite",
            (primary, secondary),
            "Deliver one installed lite change across an exact repository set",
        )
        task = started.get("task")
        members = task.get("repositories") if isinstance(task, Mapping) else None
        workflow = task.get("workflow") if isinstance(task, Mapping) else None
        repository_ids = tuple(
            str(item.get("id"))
            for item in members
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        ) if isinstance(members, list) else ()
        _require(
            isinstance(workflow, Mapping)
            and workflow.get("id") == "lite"
            and workflow.get("version") == MODEL_VERSION
            and len(repository_ids) == 2
            and len(set(repository_ids)) == 2,
            "exact-set lite start did not persist the installed membership",
        )
        self._record_task(task_id)

        projection, membership_process = self._next(
            controller, task_id, "preflight"
        )
        repository_set = projection.get("repository_set")
        projected_members = (
            repository_set.get("repositories")
            if isinstance(repository_set, Mapping)
            else None
        )
        _require(
            projection.get("schema") == AGENT_PROTOCOL_SCHEMA
            and isinstance(projected_members, list)
            and {
                item.get("id")
                for item in projected_members
                if isinstance(item, Mapping)
            }
            == set(repository_ids),
            "exact-set lite projection did not preserve the complete membership",
        )

        terminal = self._complete_success(
            controller,
            task_id,
            primary,
            "lite",
        )
        outcome = self._inspect_terminal(
            controller,
            task_id,
            terminal,
            expected_status="DONE",
            expected_outcome="success",
        )
        dossier = outcome["dossier"]
        dossier_repository_set = dossier.get("repository_set")
        dossier_members = (
            dossier_repository_set.get("members")
            if isinstance(dossier_repository_set, Mapping)
            else None
        )
        dossier_repository_ids = {
            item.get("repository_id")
            for item in dossier_members
            if isinstance(item, Mapping)
        } if isinstance(dossier_members, list) else set()
        _require(
            dossier.get("schema") == DELIVERY_DOSSIER_SCHEMA
            and dossier_repository_ids == set(repository_ids),
            "exact-set lite success dossier did not preserve both members",
        )
        aggregate_freshness = dossier.get("aggregate_freshness")
        _require(
            isinstance(aggregate_freshness, Mapping)
            and aggregate_freshness.get("current") is True,
            "exact-set lite success dossier is not aggregate-current",
        )
        self.evidence["journeys"].append(
            {
                "name": "exact-set-lite-success-dossier",
                "task_id": task_id,
                "workflow": "lite",
                "repository_ids": list(repository_ids),
                "dossier_repository_ids": sorted(dossier_repository_ids),
                "start_process": start_process,
                "membership_process": membership_process,
                "projection_schema": projection.get("schema"),
                "dossier_schema": dossier.get("schema"),
                "outcome": "success",
            }
        )

    def restart_resume_journey(self) -> None:
        task_id = "stage1-restart-resume"
        repository = self._make_repository("restart-resume")
        controller = self._controller("restart-resume", repository)
        _, start_process = controller.start_repositories(
            task_id,
            "lite",
            (repository,),
            "Resume after every installed process exits",
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
            and interrupted_task.get("current_node") == "impact",
            "restart interruption state was not durably observable",
        )
        resumed_controller = self._controller("restart-resume", repository)
        resumed_projection, resumed_process = self._next(
            resumed_controller, task_id, "impact"
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
        _, start_process = controller.start_repositories(
            task_id,
            "lite",
            (repository,),
            "Cancel this installed delivery",
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
        _, start_process = controller.start_repositories(
            task_id,
            "lite",
            (repository,),
            "Retain bounded verification failure",
        )
        self._record_task(task_id)
        projection, process_index = self._next(controller, task_id, "preflight")
        self._apply(controller, task_id, repository, projection, process_index, {})
        projection, process_index = self._next(controller, task_id, "impact")
        self._apply(
            controller,
            task_id,
            repository,
            projection,
            process_index,
            self._standard_payload(projection, repository, task_id),
        )
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
            "constraints": ["One Codex"],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }
        _, start_process = controller.start_repositories(
            task_id,
            "lite",
            (repository,),
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
        impact, next_process = self._next(controller, task_id, "impact")
        self._apply(
            controller,
            task_id,
            repository,
            impact,
            next_process,
            self._standard_payload(impact, repository, task_id),
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
        _, start_process = controller.start_repositories(
            task_id,
            "feature",
            (repository,),
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
            "- [x] verify installed journey revision 1\n", encoding="utf-8"
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
        current_snapshot = semantic_task.get("current_snapshot")
        current_members = (
            current_snapshot.get("repositories")
            if isinstance(current_snapshot, Mapping)
            else None
        )
        resource_repository_ids = {
            item.get("repository_id")
            for item in resources_before
            if isinstance(item, Mapping)
        } if isinstance(resources_before, list) else set()
        resource_repository_id = next(iter(resource_repository_ids), None)
        current_member = next(
            (
                item
                for item in current_members
                if isinstance(item, Mapping)
                and item.get("repository_id") == resource_repository_id
            ),
            None,
        ) if isinstance(current_members, list) else None
        member_snapshot = (
            current_member.get("snapshot")
            if isinstance(current_member, Mapping)
            else None
        )
        current_resources = (
            member_snapshot.get("resources")
            if isinstance(member_snapshot, Mapping)
            else None
        )
        _require(
            isinstance(resources_before, list)
            and len(resource_repository_ids) == 1
            and isinstance(current_resources, list),
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
        governed_before = resource(resources_before, OPENSPEC_TASKS_NORMALIZER)
        governed_after = resource(current_resources, OPENSPEC_TASKS_NORMALIZER)
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
        retry_projection, retry_process = self._next(controller, task_id, "verify")
        retry_action = retry_projection.get("action")
        retry_before_revision = (
            retry_action.get("retry_budget") if isinstance(retry_action, Mapping) else None
        )
        assurance_before_revision = (
            retry_action.get("assurance") if isinstance(retry_action, Mapping) else None
        )
        aggregate_budget = (
            assurance_before_revision.get("budget")
            if isinstance(assurance_before_revision, Mapping)
            else None
        )
        _require(
            isinstance(retry_before_revision, Mapping)
            and isinstance(aggregate_budget, Mapping)
            and aggregate_budget.get("used", {}).get("verification") == 1,
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
            "constraints": ["Immutable exact repository set", "One Codex"],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }
        before_revision_response, _ = controller.show(task_id)
        before_revision_task = before_revision_response.get("task")
        _require(
            isinstance(before_revision_task, Mapping),
            "pre-revision task view is unavailable",
        )
        revised, revision_process = controller.revise(
            task_id,
            revised_contract,
            self._revision_claims(before_revision_task, "requirement"),
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
            == fresh_retry_budget.get("allowance"),
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
            "src/dev_flow_orchestrator/web.py",
            "src/dev_flow_orchestrator/web_views.py",
            "src/dev_flow_orchestrator/web_assets/index.html",
            "src/dev_flow_orchestrator/web_assets/app.js",
            "src/dev_flow_orchestrator/web_assets/styles.css",
        )
        missing = [item for item in required if not (self.plugin_root / item).is_file()]
        _require(not missing, "installed snapshot is missing assets: {}".format(missing))
        _require(os.access(str(self.launcher), os.X_OK), "installed launcher is not executable")
        manifest = _read_json_object(
            self.plugin_root / ".codex-plugin" / "plugin.json", "plugin manifest"
        )
        version = manifest.get("version")
        _require(
            version == self.release_version,
            "installed manifest release version changed during validation",
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
                "schema: {}".format(WORKFLOW_SCHEMA) in document
                and re.search(r"(?m)^id:\s*{}\s*$".format(re.escape(workflow)), document)
                is not None
                and re.search(
                    r'(?m)^version:\s*"{}"\s*$'.format(
                        re.escape(MODEL_VERSION)
                    ),
                    document,
                )
                is not None
                and "delivery-dossier" in document,
                "installed workflow asset is not the expected product contract: {}".format(
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
                    "web_ui": {
                        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (
                            self.plugin_root / "src/dev_flow_orchestrator/web.py",
                            self.plugin_root / "src/dev_flow_orchestrator/web_views.py",
                            self.plugin_root / "src/dev_flow_orchestrator/web_assets/index.html",
                            self.plugin_root / "src/dev_flow_orchestrator/web_assets/app.js",
                            self.plugin_root / "src/dev_flow_orchestrator/web_assets/styles.css",
                        )
                    },
                },
            }
        )

    def web_ui_journey(self) -> None:
        task_id = "stage1-web-ui"
        repository = self._make_repository("web-ui")
        data_dir = self.scratch / "web-ui-data"
        controller = InstalledController(
            self.recorder,
            self.launcher,
            self.cli_handler,
            data_dir,
            repository,
            kind_prefix="installed-web-ui",
        )
        _, start_process = controller.start_repositories(
            task_id,
            "lite",
            (repository,),
            "Inspect installed task state through the local read-only Web UI",
        )
        before = _tree_digest(data_dir, ignore_volatile=True)
        process = subprocess.Popen(
            (
                str(self.launcher),
                str(self.cli_handler),
                "--data-dir",
                str(data_dir),
                "web",
            ),
            cwd=str(repository),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.recorder.environment,
        )
        checks = []
        try:
            _require(process.stdout is not None, "installed Web UI has no startup stream")
            receipt = _strict_json(process.stdout.readline(), "installed Web UI receipt")
            _require(isinstance(receipt, Mapping), "installed Web UI receipt is not an object")
            parsed = urlsplit(str(receipt.get("url", "")))
            token_values = parse_qs(parsed.fragment).get("token", ())
            _require(
                parsed.hostname == "127.0.0.1"
                and isinstance(parsed.port, int)
                and len(token_values) == 1,
                "installed Web UI receipt is not loopback with fragment authority",
            )
            token = token_values[0]

            def request(path: str, *, headers: Optional[Mapping[str, str]] = None) -> Tuple[int, Mapping[str, str], dict]:
                selected = {"Authorization": "Bearer " + token}
                if headers is not None:
                    selected.update(headers)
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
                connection.request("GET", path, headers=selected)
                response = connection.getresponse()
                body = _strict_json(
                    response.read().decode("utf-8"),
                    "installed Web UI response",
                )
                response_headers = dict(response.getheaders())
                status = response.status
                connection.close()
                _require(isinstance(body, dict), "installed Web UI response is not an object")
                return status, response_headers, body

            inventory_status, inventory_headers, inventory = request("/api/tasks")
            _require(
                inventory_status == 200
                and inventory.get("view") == "task-inventory"
                and any(
                    item.get("task_id") == task_id
                    for item in inventory.get("result", {}).get("tasks", ())
                    if isinstance(item, Mapping)
                ),
                "installed Web UI inventory did not expose the persisted task",
            )
            _require(
                inventory_headers.get("Cache-Control") == "no-store"
                and "Access-Control-Allow-Origin" not in inventory_headers,
                "installed Web UI response policy is not local no-store/no-CORS",
            )
            detail_status, _, detail = request("/api/tasks/" + task_id)
            live_status, _, live = request("/api/tasks/" + task_id + "/live")
            hostile_status, hostile_headers, hostile = request(
                "/api/tasks",
                headers={"Origin": "https://attacker.invalid"},
            )
            _require(
                detail_status == 200
                and detail.get("result", {}).get("health") == "not-evaluated"
                and live_status == 200
                and live.get("view") == "task-live-detail",
                "installed Web UI stored/live boundary did not complete",
            )
            _require(
                hostile_status == 403
                and hostile.get("error", {}).get("code") == "HTTP_ORIGIN_FORBIDDEN"
                and "Access-Control-Allow-Origin" not in hostile_headers,
                "installed Web UI hostile origin was not denied",
            )
            checks = ["inventory", "stored-detail", "live-detail", "hostile-origin"]
        finally:
            process.terminate()
            try:
                returncode = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        _require(returncode == 0, "installed Web UI did not shut down gracefully")
        after = _tree_digest(data_dir, ignore_volatile=True)
        _require(before == after, "installed Web UI observation mutated task storage")
        cancelled, cancel_process = controller.cancel(
            task_id,
            "Installed Web UI observation complete",
        )
        _require(
            self._projection(cancelled).get("status") == "CANCELLED",
            "installed Web UI evidence task did not cancel",
        )
        self.evidence["web_ui"] = {
            "task_id": task_id,
            "start_process": start_process,
            "cancel_process": cancel_process,
            "checks": checks,
            "state_tree_before": before,
            "state_tree_after": after,
            "state_unchanged": True,
            "browser": {
                "status": "manual-unverified",
                "limitation": (
                    "The installed validator has no browser-control channel and exercises HTTP only. "
                    "A separate real-browser candidate check is not bound to this immutable installed "
                    "snapshot, so installed rendering, CSP enforcement, and persistent-storage behavior "
                    "remain unverified."
                ),
            },
        }

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

    def hook_bootstrap(self) -> None:
        task_id = "stage1-hook-bootstrap"
        repository = self._make_repository("hook-bootstrap")
        plugin_data = self.scratch / "hook-plugin-data"
        controller = InstalledController(
            self.recorder,
            self.launcher,
            self.cli_handler,
            plugin_data / MODEL_VERSION,
            repository,
        )
        _, start_process = controller.start_repositories(
            task_id,
            "lite",
            (repository,),
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
            and "Current Dev Flow {} task".format(self.release_version) in context
            and task_id in context
            and "locator=" in context
            and "projection=" in context
            and str((plugin_data / MODEL_VERSION).resolve()) in context,
            "installed Hook bootstrap did not inject the current task and locator",
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
            "plugin_data_namespace": MODEL_VERSION,
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
        self.web_ui_journey()
        self.official_success_journeys()
        self.exact_set_journey()
        self.exact_set_lite_journey()
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
                "Exercise installed controller validation, driver outcome routing, "
                "persistence, and dossier projection"
            ),
        }
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
        "--external-evidence",
        help=(
            "JSON evidence from actual OpenSpec, codebase-memory, independent-review, "
            "executions; required for a verified release gate"
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    plugin_root = Path(arguments.plugin_root).expanduser().resolve()
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
            "path_tokens": ["<PLUGIN_ROOT>", "<SCRATCH>"],
        },
        "installed": {
            "path": str(plugin_root),
            "snapshot_algorithm": TREE_SNAPSHOT_SCHEMA,
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
        "process_model": None,
        "release_gate": {
            "status": "unverified",
            "blockers": [
                "actual driver execution evidence has not been validated",
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
        before = _tree_digest(plugin_root, ignore_volatile=True)
        evidence["installed"]["snapshot_digest_before"] = before
        with tempfile.TemporaryDirectory(prefix="dev-flow-installed-stage1-") as temporary:
            scratch = Path(temporary).resolve()
            runner = Stage1Acceptance(
                plugin_root,
                scratch,
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
                ],
            }
        else:
            external = _read_json_object(
                external_evidence_path, "external Stage 1 release evidence"
            )
            validated = _validate_external_release_evidence(
                external,
                before,
            )
            evidence["external_evidence"] = validated
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
