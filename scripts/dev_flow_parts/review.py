# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Test recording, review snapshots, transitions, and cancellation.
from __future__ import annotations

import copy as _review_copy
import hashlib as _review_hashlib
import io as _review_io
import os as _review_os
import re as _review_re
import tarfile as _review_tarfile
from dataclasses import dataclass as _review_dataclass
from pathlib import Path as _ReviewPath
from types import MappingProxyType as _ReviewMappingProxyType
from typing import Mapping as _ReviewMapping
from typing import Sequence as _ReviewSequence


_V3_REVIEW_EFFECT_PLAN_SCHEMA = "dev-flow-v3-review-effect-plan/v1"
_V3_REVIEW_EFFECT_OBSERVATION_SCHEMA = (
    "dev-flow-v3-review-effect-observation/v1"
)
_V3_REVIEW_EFFECT_RECEIPT_SCHEMA = (
    "dev-flow-v3-review-effect-receipt/v1"
)
_V3_REVIEW_EFFECT_PLAN_DOMAIN = b"dev-flow-v3-review-effect-plan-v1\0"
_V3_REVIEW_EFFECT_OBSERVATION_DOMAIN = (
    b"dev-flow-v3-review-effect-observation-v1\0"
)
_V3_REVIEW_EFFECT_RECEIPT_DOMAIN = (
    b"dev-flow-v3-review-effect-receipt-v1\0"
)
_V3_REVIEW_EXECUTION_ID_DOMAIN = (
    b"dev-flow-v3-review-execution-id-v1\0"
)
_V3_REVIEW_SNAPSHOT_ID_DOMAIN = (
    b"dev-flow-v3-review-snapshot-id-v1\0"
)
_V3_REVIEW_ATTEMPT_ID_DOMAIN = (
    b"dev-flow-v3-review-attempt-id-v1\0"
)
_V3_REVIEW_ACTION_EVIDENCE_SCHEMA = (
    "dev-flow-v3-review-action-evidence/v1"
)
_V3_REVIEW_SHA256 = _review_re.compile(r"[0-9a-f]{64}")
_V3_REVIEW_EXPECTED_EFFECT_IDS = {
    ("full", "IMPLEMENTING", "record-test"): (
        "full.implementing.record-test.v1.effect"
    ),
    ("full", "VERIFYING", "record-test"): (
        "full.verifying.record-test.v1.effect"
    ),
    ("lite", "IMPLEMENTING", "record-test"): (
        "lite.implementing.record-test.v1.effect"
    ),
    ("lite", "VERIFYING", "record-test"): (
        "lite.verifying.record-test.v1.effect"
    ),
    ("full", "VERIFYING", "review-snapshot"): (
        "full.verifying.review-snapshot.v1.effect"
    ),
}


def _v3_review_error(
    code: str,
    message: str,
    *,
    details: _ReviewMapping[str, object] | None = None,
) -> FlowError:
    return FlowError(code, message, details=dict(details or {}))


def _v3_review_thaw(value: object) -> object:
    if isinstance(value, _ReviewMapping):
        return {
            str(key): _v3_review_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_v3_review_thaw(item) for item in value]
    return _review_copy.deepcopy(value)


def _v3_review_freeze(value: object) -> object:
    if isinstance(value, dict):
        return _ReviewMappingProxyType(
            {
                str(key): _v3_review_freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list):
        return tuple(_v3_review_freeze(item) for item in value)
    return value


def _v3_review_public(value: object) -> object:
    try:
        source = semantic_json_bytes(_v3_review_thaw(value))
        return parse_semantic_json(source)
    except Exception as exc:
        raise _v3_review_error(
            "REVIEW_EFFECT_JSON_INVALID",
            "review effect bindings require strict semantic JSON",
            details={
                "cause_code": getattr(exc, "code", type(exc).__name__)
            },
        ) from exc


def _v3_review_sha256(domain: bytes, value: object) -> str:
    return semantic_sha256(domain, _v3_review_public(value))


def _v3_review_text(value: object, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise _v3_review_error(
            "REVIEW_EFFECT_BINDING_INVALID",
            f"{role} must be non-empty text",
        )
    _v3_review_public(value)
    return value


def _v3_review_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _v3_review_error(
            "REVIEW_EFFECT_BINDING_INVALID",
            "task revision must be a non-negative integer",
        )
    return value


def _v3_review_sorted_ids(
    values: _ReviewSequence[object],
) -> tuple[str, ...]:
    normalized = tuple(
        _v3_review_text(value, "repository_id") for value in values
    )
    expected = tuple(
        sorted(set(normalized), key=lambda item: item.encode("utf-8"))
    )
    if not expected or normalized != expected:
        raise _v3_review_error(
            "REVIEW_EFFECT_BINDING_INVALID",
            "repository IDs must be non-empty, unique, and UTF-8 sorted",
        )
    return expected


def _v3_review_effect_id(
    state_value: _ReviewMapping[str, object],
    action: str,
) -> str:
    key = (
        str(state_value.get("flow")),
        str(state_value.get("status")),
        action,
    )
    effect_id = _V3_REVIEW_EXPECTED_EFFECT_IDS.get(key)
    if effect_id is None:
        raise _v3_review_error(
            "REVIEW_EFFECT_NODE_INVALID",
            "review effect is not catalog-declared at the current node",
            details={
                "flow": key[0],
                "status": key[1],
                "action": action,
            },
        )
    return effect_id


def v3_review_execution_id(
    state_value: _ReviewMapping[str, object],
    *,
    action: str,
    request_binding: _ReviewMapping[str, object],
) -> str:
    """Derive a retry-stable execution identity before any target is chosen."""

    core = {
        "task_id": state_value.get("task_id"),
        "task_revision": state_value.get("revision"),
        "workflow_ref": state_value.get("workflow_ref"),
        "flow": state_value.get("flow"),
        "status": state_value.get("status"),
        "action": action,
        "expected_effect_id": _v3_review_effect_id(
            state_value, action
        ),
        "request_binding": dict(request_binding),
    }
    return (
        action
        + "-"
        + _v3_review_sha256(
            _V3_REVIEW_EXECUTION_ID_DOMAIN, core
        )
    )


@_review_dataclass(frozen=True)
class V3ReviewEffectPlan:
    """Immutable plan plus process-local bytes for one claimed filesystem effect."""

    action: str
    expected_effect_id: str
    task_id: str
    task_revision: int
    execution_id: str
    repository_ids: tuple[str, ...]
    bindings: _ReviewMapping[str, object]
    payloads: _ReviewMapping[str, bytes]
    semantic_sha256: str

    def __post_init__(self) -> None:
        if self.action not in {"record-test", "review-snapshot"}:
            raise _v3_review_error(
                "REVIEW_EFFECT_PLAN_TYPE_INVALID",
                "review effect plan action is invalid",
            )
        _v3_review_text(self.expected_effect_id, "expected_effect_id")
        _v3_review_text(self.task_id, "task_id")
        _v3_review_revision(self.task_revision)
        _v3_review_text(self.execution_id, "execution_id")
        repository_ids = _v3_review_sorted_ids(self.repository_ids)
        bindings = _v3_review_public(dict(self.bindings))
        if not isinstance(bindings, dict):
            raise _v3_review_error(
                "REVIEW_EFFECT_BINDING_INVALID",
                "review effect bindings must be an object",
            )
        descriptors = bindings.get("payloads")
        if not isinstance(descriptors, list):
            raise _v3_review_error(
                "REVIEW_EFFECT_BINDING_INVALID",
                "review effect plan has no payload descriptors",
            )
        payloads: dict[str, bytes] = {}
        for path, content in self.payloads.items():
            if not isinstance(path, str) or not path:
                raise _v3_review_error(
                    "REVIEW_EFFECT_PAYLOAD_INVALID",
                    "review payload path must be absolute text",
                )
            if not isinstance(content, bytes):
                raise _v3_review_error(
                    "REVIEW_EFFECT_PAYLOAD_INVALID",
                    "review payload content must be bytes",
                    details={"path": path},
                )
            payloads[path] = bytes(content)
        expected_paths = [
            str(item.get("path"))
            for item in descriptors
            if isinstance(item, dict)
        ]
        if (
            expected_paths
            != sorted(
                set(expected_paths),
                key=lambda item: item.encode("utf-8"),
            )
            or set(expected_paths) != set(payloads)
        ):
            raise _v3_review_error(
                "REVIEW_EFFECT_PAYLOAD_INVALID",
                "review payload inventory differs from its immutable descriptors",
            )
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                raise _v3_review_error(
                    "REVIEW_EFFECT_PAYLOAD_INVALID",
                    "review payload descriptor is invalid",
                )
            path = str(descriptor.get("path"))
            content = payloads[path]
            if (
                not _ReviewPath(path).is_absolute()
                or descriptor.get("size") != len(content)
                or descriptor.get("sha256")
                != _review_hashlib.sha256(content).hexdigest()
            ):
                raise _v3_review_error(
                    "REVIEW_EFFECT_PAYLOAD_INVALID",
                    "review payload bytes differ from their descriptor",
                    details={"path": path},
                )
        core = {
            "schema": _V3_REVIEW_EFFECT_PLAN_SCHEMA,
            "action": self.action,
            "expected_effect_id": self.expected_effect_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "execution_id": self.execution_id,
            "repository_ids": list(repository_ids),
            "bindings": bindings,
        }
        if (
            _v3_review_sha256(_V3_REVIEW_EFFECT_PLAN_DOMAIN, core)
            != self.semantic_sha256
        ):
            raise _v3_review_error(
                "REVIEW_EFFECT_PLAN_DIGEST_MISMATCH",
                "review effect plan digest differs from its bindings",
            )
        object.__setattr__(self, "repository_ids", repository_ids)
        object.__setattr__(self, "bindings", _v3_review_freeze(bindings))
        object.__setattr__(
            self,
            "payloads",
            _ReviewMappingProxyType(
                {
                    key: payloads[key]
                    for key in sorted(
                        payloads, key=lambda item: item.encode("utf-8")
                    )
                }
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": _V3_REVIEW_EFFECT_PLAN_SCHEMA,
            "action": self.action,
            "expected_effect_id": self.expected_effect_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "execution_id": self.execution_id,
            "repository_ids": list(self.repository_ids),
            "bindings": _v3_review_thaw(self.bindings),
            "semantic_sha256": self.semantic_sha256,
        }


def _v3_review_build_plan(
    *,
    action: str,
    expected_effect_id: str,
    task_id: str,
    task_revision: int,
    execution_id: str,
    repository_ids: _ReviewSequence[str],
    bindings: _ReviewMapping[str, object],
    payloads: _ReviewMapping[str, bytes],
) -> V3ReviewEffectPlan:
    ids = tuple(
        sorted(
            set(repository_ids),
            key=lambda item: item.encode("utf-8"),
        )
    )
    public = _v3_review_public(dict(bindings))
    assert isinstance(public, dict)
    core = {
        "schema": _V3_REVIEW_EFFECT_PLAN_SCHEMA,
        "action": action,
        "expected_effect_id": expected_effect_id,
        "task_id": task_id,
        "task_revision": task_revision,
        "execution_id": execution_id,
        "repository_ids": list(ids),
        "bindings": public,
    }
    return V3ReviewEffectPlan(
        action=action,
        expected_effect_id=expected_effect_id,
        task_id=task_id,
        task_revision=task_revision,
        execution_id=execution_id,
        repository_ids=ids,
        bindings=public,
        payloads=payloads,
        semantic_sha256=_v3_review_sha256(
            _V3_REVIEW_EFFECT_PLAN_DOMAIN, core
        ),
    )


def _v3_review_task_paths(
    state_value: _ReviewMapping[str, object],
    data_root: str | _ReviewPath,
    task_dir: str | _ReviewPath,
) -> tuple[_ReviewPath, _ReviewPath, _ReviewPath]:
    if state_value.get("schema_version") != V3_TASK_SCHEMA_VERSION:
        raise _v3_review_error(
            "REVIEW_EFFECT_SCHEMA_REQUIRED",
            "typed review effects require a schema-v3 task",
        )
    task_id = _v3_review_text(state_value.get("task_id"), "task_id")
    resolved_data = _ReviewPath(data_root).expanduser().resolve(
        strict=True
    )
    resolved_task = _ReviewPath(task_dir).expanduser().resolve(
        strict=True
    )
    expected = (resolved_data / "tasks" / task_id).resolve(
        strict=False
    )
    if not _same_path(resolved_task, expected):
        raise _v3_review_error(
            "REVIEW_EFFECT_TASK_PATH_MISMATCH",
            "review effect task directory is outside its controller namespace",
            details={
                "task_dir": str(resolved_task),
                "expected_task_dir": str(expected),
            },
        )
    state_path = resolved_task / "state.json"
    if not state_path.is_file():
        raise _v3_review_error(
            "REVIEW_EFFECT_STATE_UNAVAILABLE",
            "review effect requires a durable task state",
            details={"path": str(state_path)},
        )
    return resolved_data, resolved_task, state_path


def _v3_review_profile_for_repository(
    repo: _ReviewMapping[str, object],
) -> tuple[_ReviewPath, dict[str, object]]:
    working = _ReviewPath(str(_working_path(dict(repo)))).resolve(
        strict=True
    )
    workspace = repo.get("workspace")
    baseline = repo.get("baseline")
    profile = None
    recorded_path = repo.get("path")
    recorded_identity = repo.get("path_identity")
    if isinstance(workspace, _ReviewMapping) and workspace.get(
        "ready"
    ):
        profile = workspace.get("capability_profile")
        recorded_path = workspace.get("path")
        recorded_identity = workspace.get("path_identity")
    if not isinstance(profile, _ReviewMapping):
        profile = (
            baseline.get("capability_profile")
            if isinstance(baseline, _ReviewMapping)
            else None
        )
    filesystem = (
        profile.get("filesystem")
        if isinstance(profile, _ReviewMapping)
        else None
    )
    if (
        not isinstance(filesystem, _ReviewMapping)
        or not isinstance(filesystem.get("case_sensitive"), bool)
        or not isinstance(
            filesystem.get("unicode_normalization_distinct"), bool
        )
    ):
        raise _v3_review_error(
            "REVIEW_EFFECT_FILESYSTEM_FACTS_INVALID",
            "repository has no approved filesystem capability facts",
            details={"repository_id": repo.get("id")},
        )
    _v3_workspace_seed_filesystem_facts(working, filesystem)
    if not _v3_workspace_readonly_recorded_path_matches(
        recorded_identity, recorded_path, working
    ):
        raise _v3_review_error(
            "REVIEW_EFFECT_REPOSITORY_MISMATCH",
            "working repository differs from its approved path",
            details={"repository_id": repo.get("id")},
        )
    return working, _review_copy.deepcopy(dict(filesystem))


def _v3_review_controller_filesystem_facts(
    state_value: _ReviewMapping[str, object],
    task_dir: _ReviewPath,
    repository_profiles: _ReviewSequence[
        tuple[_ReviewPath, dict[str, object]]
    ],
) -> dict[str, object]:
    for artifact in reversed(tuple(state_value.get("artifacts", ()))):
        if (
            not isinstance(artifact, _ReviewMapping)
            or artifact.get("kind") != "workspace-plan"
            or not isinstance(artifact.get("path"), str)
        ):
            continue
        try:
            source = _ReviewPath(str(artifact["path"])).read_bytes()
            evidence = parse_semantic_json(source)
        except Exception:
            continue
        authorization = (
            evidence.get("authorization")
            if isinstance(evidence, dict)
            else None
        )
        facts = (
            authorization.get("controller_filesystem_capabilities")
            if isinstance(authorization, dict)
            else None
        )
        if isinstance(facts, dict):
            _v3_workspace_seed_filesystem_facts(task_dir, facts)
            return _review_copy.deepcopy(facts)
    try:
        task_device = task_dir.stat().st_dev
    except OSError as exc:
        raise _v3_review_error(
            "REVIEW_EFFECT_FILESYSTEM_FACTS_INVALID",
            "controller task filesystem cannot be identified",
            details={"path": str(task_dir), "error": str(exc)},
        ) from exc
    matching = [
        facts
        for path, facts in repository_profiles
        if path.stat().st_dev == task_device
    ]
    if not matching or any(item != matching[0] for item in matching):
        raise _v3_review_error(
            "REVIEW_EFFECT_FILESYSTEM_FACTS_INVALID",
            "controller filesystem lacks approved capability facts",
            details={"path": str(task_dir)},
        )
    facts = _review_copy.deepcopy(matching[0])
    _v3_workspace_seed_filesystem_facts(task_dir, facts)
    return facts


def _v3_review_capture_fingerprint(
    repository_id: str,
    working: _ReviewPath,
    filesystem: _ReviewMapping[str, object],
) -> dict[str, object]:
    with _v3_workspace_readonly_git():
        first = _fingerprint_repo_once(
            working,
            filesystem_capabilities=dict(filesystem),
        )
        second = _fingerprint_repo_once(
            working,
            filesystem_capabilities=dict(filesystem),
        )
    if first.get("sha256") != second.get("sha256"):
        raise _v3_review_error(
            "REVIEW_EFFECT_REPOSITORY_CHANGED",
            "repository changed during read-only review planning",
            details={"repository_id": repository_id},
        )
    return _review_copy.deepcopy(second)


def _v3_review_fingerprint_reference(
    task_dir: _ReviewPath,
    fingerprint: _ReviewMapping[str, object],
) -> tuple[dict[str, object], bytes]:
    fingerprint_sha256 = fingerprint.get("sha256")
    if (
        not isinstance(fingerprint_sha256, str)
        or not _V3_REVIEW_SHA256.fullmatch(fingerprint_sha256)
        or _fingerprint_payload_sha256(dict(fingerprint))
        != fingerprint_sha256
    ):
        raise _v3_review_error(
            "REVIEW_EFFECT_FINGERPRINT_INVALID",
            "planned repository fingerprint is invalid",
        )
    path = (
        task_dir
        / "artifacts"
        / "fingerprints"
        / f"{fingerprint_sha256}.json"
    )
    source = _json_bytes(dict(fingerprint))
    reference = {
        "storage": _FINGERPRINT_STORAGE_KIND,
        "task_root": str(task_dir),
        "task_root_identity": _serializable_path_identity(task_dir),
        "path": str(path),
        "path_identity": _capability_path_identity(path),
        "blob_sha256": _review_hashlib.sha256(source).hexdigest(),
        "size": len(source),
        "sha256": fingerprint_sha256,
        "capability_profile_sha256": fingerprint.get(
            "capability_profile_sha256"
        ),
        "tracked_worktree_manifest_sha256": fingerprint.get(
            "tracked_worktree_manifest_sha256"
        ),
    }
    return reference, source


def _v3_review_payload_descriptor(
    path: _ReviewPath,
    content: bytes,
    kind: str,
) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": _review_hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "kind": kind,
    }


def _v3_review_approval_binding(
    state_value: dict[str, Any],
) -> dict[str, object]:
    if _flow(state_value) == "lite":
        approval = _require_gate(state_value, LITE_GATE)
        if _uses_confirmation_contract(state_value):
            risk = state_value.get("risk_assessment") or {}
            if (
                approval.get("lite_policy_sha256")
                != risk.get("policy_sha256")
            ):
                raise _v3_review_error(
                    "STALE_APPROVAL",
                    "lite approval does not bind the task risk policy",
                )
        evidence_sha256 = _lite_preflight_evidence_sha256(
            state_value
        )
        if (
            approval.get("preflight_evidence_sha256")
            != evidence_sha256
        ):
            raise _v3_review_error(
                "STALE_APPROVAL",
                "lite approval does not bind current preflight evidence",
            )
        dirty = [
            str(repo.get("id"))
            for repo in state_value.get("repositories", [])
            if bool((repo.get("preflight") or {}).get("dirty"))
        ]
        if dirty and approval.get("dirty_allowed") is not True:
            raise _v3_review_error(
                "DIRTY_NOT_APPROVED",
                "dirty preflight evidence requires explicit lite approval",
                details={"repository_ids": dirty},
            )
        return {
            "flow": "lite",
            "approval_id": approval.get("approval_id"),
            "approved_at": approval.get("approved_at"),
            "preflight_evidence_sha256": evidence_sha256,
            "lite_policy_sha256": approval.get(
                "lite_policy_sha256"
            ),
        }
    route_value = (state_value.get("route") or {}).get("value")
    plan_kind = (
        "direct-contract"
        if route_value == "direct"
        else "openspec-plan"
    )
    artifact = _latest_artifact(state_value, plan_kind)
    if not isinstance(artifact, dict):
        raise _v3_review_error(
            "ARTIFACT_REQUIRED",
            f"the plan gate requires a recorded {plan_kind} artifact",
        )
    _assert_artifact_unchanged(artifact)
    if plan_kind == "openspec-plan":
        _assert_openspec_plan_in_current_workspace(
            state_value, _ReviewPath(str(artifact["path"]))
        )
    approval = _require_gate(state_value, "plan")
    impact = _latest_artifact(state_value, "impact")
    workspace_plan = _latest_artifact(
        state_value, "workspace-plan"
    )
    route_approval = (state_value.get("approvals") or {}).get(
        "route"
    )
    workspace_approval = (state_value.get("approvals") or {}).get(
        "workspace"
    )
    if (
        not isinstance(impact, dict)
        or not isinstance(workspace_plan, dict)
        or not isinstance(route_approval, dict)
        or not isinstance(workspace_approval, dict)
    ):
        raise _v3_review_error(
            "STALE_PLAN",
            "plan approval is missing its durable route or workspace binding",
        )
    expected_context = {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "planning_generation": int(
            state_value.get("planning_generation", 0)
        ),
        "impact_generation": int(
            state_value.get("impact_generation", 0)
        ),
        "route": {
            "value": route_value,
            "approval_id": route_approval.get("approval_id"),
            "impact_artifact_id": impact.get("artifact_id"),
            "impact_sha256": impact.get("sha256"),
        },
        "workspace": {
            "generation": int(
                (state_value.get("workspace") or {}).get(
                    "generation", 0
                )
            ),
            "approval_id": workspace_approval.get("approval_id"),
            "plan_artifact_id": workspace_plan.get(
                "artifact_id"
            ),
            "plan_sha256": workspace_plan.get("sha256"),
        },
    }
    context_sha256 = _planning_context_sha256(expected_context)
    metadata = artifact.get("metadata") or {}
    if (
        not isinstance(metadata, dict)
        or metadata.get("planning_context") != expected_context
        or metadata.get("planning_context_sha256")
        != context_sha256
        or approval.get("artifact_sha256")
        != artifact.get("sha256")
        or approval.get("artifact_id")
        != artifact.get("artifact_id")
        or approval.get("planning_context_sha256")
        != context_sha256
    ):
        raise _v3_review_error(
            "STALE_APPROVAL",
            "plan approval is not bound to current durable planning facts",
        )
    return {
        "flow": "full",
        "approval_id": approval.get("approval_id"),
        "approved_at": approval.get("approved_at"),
        "artifact_id": artifact.get("artifact_id"),
        "artifact_sha256": artifact.get("sha256"),
        "artifact_kind": plan_kind,
        "planning_context_sha256": context_sha256,
    }


def _v3_review_output_record(
    output: str | _ReviewPath | None,
) -> dict[str, object] | None:
    if output is None:
        return None
    path = _ReviewPath(output).expanduser().resolve(strict=True)
    if not path.is_file():
        raise _v3_review_error(
            "REVIEW_EFFECT_OUTPUT_INVALID",
            "test output must be one regular file",
            details={"path": str(path)},
        )
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(path),
        # A foreign output volume may not have controller-approved filesystem
        # probe facts. Exact absolute path, bytes and size remain bound.
        "path_identity": None,
        "sha256": _sha256_file(path),
        "size": path.stat().st_size,
    }

def _test_identity(name: Any, command: Any) -> str:
    return _sha256_bytes(
        _json_bytes({"name": str(name or ""), "command": str(command or "")})
    )


def _test_receipt(test: dict[str, Any]) -> dict[str, Any]:
    return {
        key: test.get(key)
        for key in (
            "evidence_contract_version",
            "test_id",
            "name",
            "command",
            "test_identity",
            "exit_code",
            "passed",
            "recorded_at",
            "repository_ids",
            "capability_profile_sha256",
            "plan_artifact_sha256",
            "plan_approved_at",
            "plan_approval_id",
            "lite_approval_id",
            "lite_approved_at",
            "output",
        )
        if test.get(key) is not None
    } | {
        "fingerprint_sha256": {
            repository_id: (fingerprint or {}).get("sha256")
            for repository_id, fingerprint in (
                test.get("fingerprints") or {}
            ).items()
        }
    }


def plan_v3_record_test_effect(
    *,
    state_value: dict[str, Any],
    data_root: str | _ReviewPath,
    task_dir: str | _ReviewPath,
    execution_id: str,
    name: str,
    test_command: str,
    exit_code: int,
    repository_ids: _ReviewSequence[str] | None = None,
    output: str | _ReviewPath | None = None,
) -> V3ReviewEffectPlan:
    """Plan test evidence without filesystem mutation or capability probes."""

    _v3_review_revision(state_value.get("revision"))
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise _v3_review_error(
            "REVIEW_EFFECT_BINDING_INVALID",
            "test exit code must be an integer",
        )
    effect_id = _v3_review_effect_id(state_value, "record-test")
    task_id = _v3_review_text(state_value.get("task_id"), "task_id")
    node_id = _v3_review_text(state_value.get("status"), "status")
    execution_id = _v3_review_text(execution_id, "execution_id")
    _resolved_data, resolved_task, state_path = _v3_review_task_paths(
        state_value, data_root, task_dir
    )
    configured = {
        str(repo["id"]): repo
        for repo in state_value.get("repositories", [])
        if isinstance(repo, dict) and isinstance(repo.get("id"), str)
    }
    selected_ids = tuple(
        sorted(
            (
                set(configured)
                if repository_ids is None
                else {
                    _v3_review_text(item, "repository_id")
                    for item in repository_ids
                }
            ),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if not selected_ids or not set(selected_ids).issubset(configured):
        raise _v3_review_error(
            "REVIEW_EFFECT_REPOSITORY_MISMATCH",
            "test effect selects an unknown or empty repository set",
            details={
                "configured_repository_ids": sorted(configured),
                "selected_repository_ids": list(selected_ids),
            },
        )
    if _flow(state_value) == "full":
        for repository_id in selected_ids:
            workspace = configured[repository_id].get("workspace")
            if (
                not isinstance(workspace, dict)
                or workspace.get("ready") is not True
            ):
                raise _v3_review_error(
                    "WORKSPACE_REQUIRED",
                    "full-flow test evidence requires an approved workspace",
                    details={"repository_id": repository_id},
                )
    profiles = [
        _v3_review_profile_for_repository(configured[item])
        for item in selected_ids
    ]
    controller_facts = _v3_review_controller_filesystem_facts(
        state_value, resolved_task, profiles
    )
    _v3_workspace_seed_filesystem_facts(
        resolved_task / "artifacts" / "fingerprints",
        controller_facts,
    )
    payloads: dict[str, bytes] = {}
    repository_bindings: list[dict[str, object]] = []
    fingerprint_references: dict[str, dict[str, object]] = {}
    capability_profiles: dict[str, object] = {}
    for repository_id, (working, filesystem) in zip(
        selected_ids, profiles
    ):
        fingerprint = _v3_review_capture_fingerprint(
            repository_id, working, filesystem
        )
        reference, source = _v3_review_fingerprint_reference(
            resolved_task, fingerprint
        )
        payloads[str(reference["path"])] = source
        fingerprint_references[repository_id] = reference
        capability_profiles[repository_id] = fingerprint.get(
            "capability_profile_sha256"
        )
        repository_bindings.append(
            {
                "repository_id": repository_id,
                "working_path": str(working),
                "working_path_identity": (
                    _serializable_path_identity(working)
                ),
                "filesystem_capabilities": filesystem,
                "fingerprint": fingerprint,
                "fingerprint_reference": reference,
            }
        )
    approval_binding = _v3_review_approval_binding(state_value)
    recorded_at = state_value.get("updated_at")
    if not isinstance(recorded_at, str) or not recorded_at:
        recorded_at = approval_binding.get("approved_at")
    recorded_at = _v3_review_text(recorded_at, "recorded_at")
    test_id = "test-" + _v3_review_sha256(
        _V3_REVIEW_EXECUTION_ID_DOMAIN,
        {
            "execution_id": execution_id,
            "effect_id": effect_id,
            "task_id": task_id,
        },
    )
    test_record: dict[str, object] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "test_id": test_id,
        "name": name,
        "command": test_command,
        "test_identity": _test_identity(name, test_command),
        "exit_code": exit_code,
        "passed": exit_code == 0,
        "recorded_at": recorded_at,
        "repository_ids": list(selected_ids),
        "fingerprints": fingerprint_references,
        "capability_profile_sha256": capability_profiles,
        "output": _v3_review_output_record(output),
    }
    if approval_binding["flow"] == "lite":
        test_record.update(
            {
                "lite_approval_id": approval_binding["approval_id"],
                "lite_approved_at": approval_binding["approved_at"],
            }
        )
    else:
        test_record.update(
            {
                "plan_artifact_sha256": approval_binding[
                    "artifact_sha256"
                ],
                "plan_approved_at": approval_binding["approved_at"],
                "plan_approval_id": approval_binding["approval_id"],
            }
        )
    descriptors = [
        _v3_review_payload_descriptor(
            _ReviewPath(path), content, "fingerprint"
        )
        for path, content in payloads.items()
    ]
    descriptors.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    bindings = {
        "mode": "record-test",
        "node_id": node_id,
        "data_root": str(_resolved_data),
        "task_dir": str(resolved_task),
        "state_path": str(state_path),
        "state_sha256": _sha256_contract(state_value),
        "workflow_ref": _review_copy.deepcopy(
            state_value.get("workflow_ref")
        ),
        "approval_binding": approval_binding,
        "controller_filesystem_capabilities": controller_facts,
        "repositories": repository_bindings,
        "test_record": test_record,
        "payloads": descriptors,
    }
    return _v3_review_build_plan(
        action="record-test",
        expected_effect_id=effect_id,
        task_id=task_id,
        task_revision=int(state_value["revision"]),
        execution_id=execution_id,
        repository_ids=selected_ids,
        bindings=bindings,
        payloads=payloads,
    )


def _review_snapshot_receipt(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in (
            "evidence_contract_version",
            "snapshot_id",
            "created_at",
            "repository_ids",
            "manifest_path",
            "manifest_path_identity",
            "sha256",
        )
    }


def _v3_review_catalog_effect(
    edge: _ReviewMapping[str, object],
    plan: V3ReviewEffectPlan,
) -> _ReviewMapping[str, object]:
    effects = edge.get("effects")
    effect = (
        effects[0]
        if isinstance(effects, (list, tuple)) and len(effects) == 1
        else None
    )
    if (
        not isinstance(effect, _ReviewMapping)
        or effect.get("id") != plan.expected_effect_id
        or effect.get("dispatch") != "single-dispatch"
        or effect.get("settlement")
        != "synchronous-quiescence"
        or effect.get("recovery", {}).get("redispatch")
        != "forbidden"
    ):
        raise _v3_review_error(
            "REVIEW_EFFECT_CATALOG_MISMATCH",
            "review command did not resolve its exact claimed catalog effect",
            details={
                "edge_id": edge.get("id"),
                "expected_effect_id": plan.expected_effect_id,
            },
        )
    return effect


def _v3_review_action_outcome(
    current: dict[str, Any],
    authorization_edge: _ReviewMapping[str, object],
    completion_edge: _ReviewMapping[str, object],
    plan: V3ReviewEffectPlan,
) -> ActionOutcome:
    planned = _copy_state(current)
    result = _v3_review_result(plan)
    if plan.action == "record-test":
        planned["tests"].append(
            _review_copy.deepcopy(result["test_record"])
        )
    else:
        planned["review_snapshots"].append(
            _review_copy.deepcopy(result["snapshot"])
        )
        planned["artifacts"].append(
            _review_copy.deepcopy(result["artifact"])
        )
        planned["status"] = "REVIEWING"
    proposed_delta = _workflow_transition_exact_state_delta(
        current,
        planned,
        excluded_paths=(
            "/node_instances",
            "/orchestration",
            "/revision",
            "/updated_at",
        ),
    )
    trigger = completion_edge.get("trigger")
    action_id = (
        trigger.get("id")
        if isinstance(trigger, _ReviewMapping)
        else None
    )
    authorization_edge_id = authorization_edge.get("id")
    completion_edge_id = completion_edge.get("id")
    if (
        not isinstance(action_id, str)
        or not action_id
        or not isinstance(authorization_edge_id, str)
        or not authorization_edge_id
        or not isinstance(completion_edge_id, str)
        or not completion_edge_id
    ):
        raise _v3_review_error(
            "REVIEW_EFFECT_CATALOG_MISMATCH",
            "review action has no exact authorization/completion identity",
        )
    evidence = {
        "contract": _V3_REVIEW_ACTION_EVIDENCE_SCHEMA,
        "action": plan.action,
        "plan_sha256": plan.semantic_sha256,
        "expected_effect_id": plan.expected_effect_id,
        "authorization_action_edge_id": authorization_edge_id,
        "completion_edge_id": completion_edge_id,
        "result_sha256": _v3_review_sha256(
            _V3_REVIEW_EFFECT_OBSERVATION_DOMAIN, result
        ),
    }
    return ActionOutcome(
        action_id,
        completion_edge_id,
        evidence_records=(evidence,),
        proposed_state_delta=proposed_delta,
        audit_facts=(
            AuditFact(
                "review-effect-planned",
                evidence,
            ),
        ),
        external_postconditions=(
            {
                "contract": _V3_REVIEW_ACTION_EVIDENCE_SCHEMA,
                "plan_sha256": plan.semantic_sha256,
                "payloads_sha256": result["payloads_sha256"],
            },
        ),
    )


def _v3_review_invocation(
    current: dict[str, Any],
    task_dir: _ReviewPath,
    plan: V3ReviewEffectPlan,
    outcome: ActionOutcome,
    authorization: WorkflowActionAuthorization,
    *,
    selector: str | None,
    authorization_edge: _ReviewMapping[str, object],
    completion_edge: _ReviewMapping[str, object],
) -> WorkflowActionInvocation:
    parameters = {
        "execution_id": plan.execution_id,
        "effect_id": plan.expected_effect_id,
        "plan_sha256": plan.semantic_sha256,
        "repository_ids": list(plan.repository_ids),
        "authorization_action_edge_id": authorization_edge["id"],
        "completion_edge_id": completion_edge["id"],
    }
    evidence = {
        "contract": _V3_REVIEW_ACTION_EVIDENCE_SCHEMA,
        "plan_sha256": plan.semantic_sha256,
        "effect_id": plan.expected_effect_id,
    }
    request = WorkflowActionInvocation(
        kind="node",
        public_command=plan.action,
        selector=selector,
        action_outcome=outcome,
        action_parameters=parameters,
        evidence=evidence,
    )
    try:
        preview = preview_v3_workflow_action_transaction(
            current,
            request,
            authorization=authorization,
            task_dir=task_dir,
        )
    except (
        TransitionEngineError,
        WorkflowActionTransactionError,
    ) as exc:
        details = _workflow_transition_public(exc.details)
        raise FlowError(
            exc.code,
            exc.message,
            details=details if isinstance(details, dict) else {},
        ) from exc
    return WorkflowActionInvocation(
        kind=request.kind,
        public_command=request.public_command,
        selector=request.selector,
        action_outcome=request.action_outcome,
        action_parameters=request.action_parameters,
        evidence=request.evidence,
        confirm_intent=str(preview.intent["intent_id"]),
    )


def _v3_review_run_transaction(
    args: argparse.Namespace,
    task_dir: _ReviewPath,
    current: dict[str, Any],
    plan: V3ReviewEffectPlan,
    authorization: WorkflowActionAuthorization,
    authorization_edge: _ReviewMapping[str, object],
    completion_edge: _ReviewMapping[str, object],
    *,
    selector: str | None,
) -> WorkflowActionTransactionResult:
    effect = _v3_review_catalog_effect(authorization_edge, plan)
    outcome = _v3_review_action_outcome(
        current, authorization_edge, completion_edge, plan
    )
    invocation = _v3_review_invocation(
        current,
        task_dir,
        plan,
        outcome,
        authorization,
        selector=selector,
        authorization_edge=authorization_edge,
        completion_edge=completion_edge,
    )
    attempt_id = "attempt-" + _v3_review_sha256(
        _V3_REVIEW_ATTEMPT_ID_DOMAIN,
        {
            "execution_id": plan.execution_id,
            "effect_id": plan.expected_effect_id,
            "plan_sha256": plan.semantic_sha256,
            "request_nonce_sha256": (
                authorization.request_nonce_sha256
            ),
        },
    )
    effect_binding = WorkflowActionEffectBinding(
        effect_id=plan.expected_effect_id,
        kind="filesystem",
        scope_kinds=tuple(effect["scopes"]),
        scopes=v3_review_effect_scopes(plan),
        safe_inputs=v3_review_effect_safe_inputs(plan),
        attempt_id=attempt_id,
    )
    dispatch_observations: dict[
        str, V3ReviewEffectObservation
    ] = {}

    def dispatch(
        context: WorkflowActionDispatchContext,
    ) -> WorkflowActionEffectObservation:
        observation = dispatch_v3_review_effect(plan, context)
        dispatch_observations[context.plan.effect_id] = observation
        return WorkflowActionEffectObservation(
            task_id=context.plan.task_id,
            execution_id=context.plan.execution_id,
            effect_id=context.plan.effect_id,
            claim_id=context.plan.claim_id,
            attempt_id=context.plan.attempt_id,
            settlement="QUIESCED",
            receipt_sha256=observation.semantic_sha256,
        )

    def observe(
        context: WorkflowActionObserveContext,
    ) -> WorkflowActionEffectObservation:
        receipt = observe_v3_review_effect(
            plan,
            context,
            dispatch_observations.get(context.effect_id),
        )
        return WorkflowActionEffectObservation(
            task_id=context.task_id,
            execution_id=context.execution_id,
            effect_id=context.effect_id,
            claim_id=context.claim_id,
            attempt_id=context.attempt_id,
            settlement="QUIESCED",
            receipt_sha256=receipt.semantic_sha256,
        )

    active = task_dir / action_execution_active_path(
        plan.execution_id
    )
    archived = task_dir / action_execution_archive_path(
        plan.execution_id
    )
    try:
        if active.exists():
            result = recover_v3_workflow_action_transaction(
                task_dir,
                plan.execution_id,
                authorization=authorization,
                invocation=invocation,
            )
            if result.status in {
                "AWAITING_EFFECT_OBSERVATION",
                "QUARANTINE_REQUIRED",
            }:
                observe_v3_workflow_action_effect(
                    task_dir,
                    plan.execution_id,
                    plan.expected_effect_id,
                    authorization=authorization,
                    observer=observe,
                )
                result = recover_v3_workflow_action_transaction(
                    task_dir,
                    plan.execution_id,
                    authorization=authorization,
                    invocation=invocation,
                )
        elif archived.exists():
            result = recover_v3_workflow_action_transaction(
                task_dir,
                plan.execution_id,
                authorization=authorization,
                invocation=invocation,
            )
        else:
            result = execute_v3_workflow_action_transaction(
                current,
                task_dir,
                invocation,
                authorization=authorization,
                effect_binding=effect_binding,
                execution_id=plan.execution_id,
                dispatcher=dispatch,
                observer=observe,
            )
    except (
        TransitionEngineError,
        WorkflowActionTransactionError,
    ) as exc:
        details = _workflow_transition_public(exc.details)
        raise FlowError(
            exc.code,
            exc.message,
            details=details if isinstance(details, dict) else {},
        ) from exc
    if result.status in {
        "COMMITTED",
        "RECOVERED_COMMITTED",
        "ALREADY_CLOSED",
    }:
        if result.state is None:
            committed = load_state(current["task_id"], args.data_dir)
            result = WorkflowActionTransactionResult(
                status=result.status,
                execution_id=result.execution_id,
                state=committed,
                journal=result.journal,
                index=result.index,
                archive_path=result.archive_path,
                dispatcher_invocations=result.dispatcher_invocations,
            )
        return result
    raise FlowError(
        "WORKFLOW_ACTION_TRANSACTION_RECOVERY_REQUIRED",
        "review effect requires explicit safe recovery",
        details={
            "execution_id": plan.execution_id,
            "effect_id": plan.expected_effect_id,
            "status": result.status,
            "dispatcher_invocations": result.dispatcher_invocations,
        },
    )


def v3_record_test_command_v1(
    args: argparse.Namespace,
    task_dir: _ReviewPath,
    current: dict[str, Any],
    output_record: dict[str, Any] | None,
) -> dict[str, Any]:
    selector = str(current["status"]).lower()
    try:
        edge = resolve_v3_node_action_edge(
            current, "record-test", selector=selector
        )
    except TransitionEngineError as exc:
        raise FlowError(
            exc.code, exc.message, details=dict(exc.details)
        ) from exc
    selected = _repo_by_selector(current, args.repo)
    repository_ids = tuple(
        sorted(
            (str(repo["id"]) for repo in selected),
            key=lambda item: item.encode("utf-8"),
        )
    )
    canonical_event = edge.get("canonical_event")
    if not isinstance(canonical_event, str):
        raise _v3_review_error(
            "REVIEW_EFFECT_CATALOG_MISMATCH",
            "record-test action has no canonical event",
        )
    authorization = _manager_workflow_action_authorization_v1(
        current, event_type=canonical_event
    )
    request_binding = {
        "name": args.name,
        "test_command": args.test_command,
        "exit_code": args.exit_code,
        "repository_ids": list(repository_ids),
        "output": output_record,
        "request_nonce_sha256": (
            authorization.request_nonce_sha256
        ),
    }
    execution_id = v3_review_execution_id(
        current,
        action="record-test",
        request_binding=request_binding,
    )
    plan = plan_v3_record_test_effect(
        state_value=current,
        data_root=resolve_data_dir(args.data_dir),
        task_dir=task_dir,
        execution_id=execution_id,
        name=args.name,
        test_command=args.test_command,
        exit_code=args.exit_code,
        repository_ids=repository_ids,
        output=args.output,
    )
    result = _v3_review_run_transaction(
        args,
        task_dir,
        current,
        plan,
        authorization,
        edge,
        edge,
        selector=selector,
    )
    assert isinstance(result.state, dict)
    test_record = _v3_review_thaw(
        plan.bindings["test_record"]
    )
    assert isinstance(test_record, dict)
    return _result(
        "record-test",
        result.state,
        test=_test_receipt(test_record),
    )


def command_record_test(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    output_record: dict[str, Any] | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve(strict=True)
        output_record = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(output_path),
            "path_identity": _serializable_path_identity(output_path),
            "sha256": _sha256_file(output_path),
            "size": output_path.stat().st_size,
        }
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_action_id="evidence.test.record",
        short_v3_effect_boundary=True,
    ) as (task_dir, current):
        _assert_status(current, {"IMPLEMENTING", "VERIFYING"}, "record-test")
        if current.get("schema_version") == V3_TASK_SCHEMA_VERSION:
            return v3_record_test_command_v1(
                args, task_dir, current, output_record
            )
        if _flow(current) == "lite":
            # Lite tests bind the lite approval instead of a plan artifact:
            # re-approving the gate invalidates older results the same way a
            # plan reapproval does on the full flow.
            lite_approval = _require_lite_gate(current)
            binding = {
                "lite_approval_id": lite_approval["approval_id"],
                "lite_approved_at": lite_approval["approved_at"],
            }
        else:
            _require_workspace_ready(current)
            route_value = (current.get("route") or {}).get("value")
            plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
            plan_approval, plan_artifact = _require_current_plan_gate(
                current, plan_kind
            )
            binding = {
                "plan_artifact_sha256": plan_artifact["sha256"],
                "plan_approved_at": plan_approval["approved_at"],
                "plan_approval_id": plan_approval["approval_id"],
            }
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        captured_fingerprints = {
            repo["id"]: _fingerprint_repo(_working_path(repo))
            for repo in selected
        }
        fingerprints = {
            repository_id: _store_fingerprint(
                task_dir,
                fingerprint,
                f"test-fingerprint:{args.name}:{repository_id}",
            )
            for repository_id, fingerprint in captured_fingerprints.items()
        }
        test_record = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "test_id": str(uuid.uuid4()),
            "name": args.name,
            "command": args.test_command,
            "test_identity": _test_identity(args.name, args.test_command),
            "exit_code": args.exit_code,
            "passed": args.exit_code == 0,
            "recorded_at": utc_now(),
            "repository_ids": [repo["id"] for repo in selected],
            "fingerprints": fingerprints,
            "capability_profile_sha256": {
                repository_id: fingerprint[
                    "capability_profile_sha256"
                ]
                for repository_id, fingerprint in captured_fingerprints.items()
            },
            **binding,
            "output": output_record,
        }
        state_value["tests"].append(test_record)
        _commit_state(current, state_value, task_dir, "test_recorded", {"test_id": test_record["test_id"], "passed": test_record["passed"], "repository_ids": test_record["repository_ids"]})
    return _result(
        "record-test",
        state_value,
        test=_test_receipt(test_record),
    )


def _write_review_repo(
    snapshot_root: Path,
    repo: dict[str, Any],
    *,
    task_dir: Path | None = None,
    initial_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    working = _working_path(repo)
    _assert_evidence_supported(working)
    base_sha = (repo.get("baseline") or {}).get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")

    def capture_sections() -> tuple[
        str, dict[str, bytes], dict[str, list[str]]
    ]:
        captured_head = _git_evidence(working, "rev-parse", "HEAD")
        captured_sections = {
            "committed": _git_diff(
                working,
                "--binary",
                "--full-index",
                f"{base_sha}...HEAD",
                "--",
                text=False,
            ),
            "cached": _git_diff(
                working,
                "--binary",
                "--full-index",
                "--cached",
                "--",
                text=False,
            ),
            "unstaged": _git_diff(
                working,
                "--binary",
                "--full-index",
                "--",
                text=False,
            ),
        }
        captured_files = {
            "committed": _split_lines(
                _git_diff(
                    working,
                    "--name-status",
                    f"{base_sha}...HEAD",
                    "--",
                )
            ),
            "cached": _split_lines(
                _git_diff(
                    working, "--cached", "--name-status", "--"
                )
            ),
            "unstaged": _split_lines(
                _git_diff(working, "--name-status", "--")
            ),
        }
        return captured_head, captured_sections, captured_files

    fingerprint = (
        initial_fingerprint
        if initial_fingerprint is not None
        else _fingerprint_repo(working)
    )
    repo_dir = snapshot_root / repo["id"]
    _ensure_private_dir(repo_dir)
    head_sha, sections, section_files = capture_sections()
    if head_sha != fingerprint.get("head_sha"):
        raise FlowError(
            "REVIEW_SNAPSHOT_CHANGED",
            "repository HEAD changed before review sections were captured",
            details={
                "repository_id": repo["id"],
                "fingerprint_head": fingerprint.get("head_sha"),
                "section_head": head_sha,
            },
        )
    section_records: dict[str, Any] = {}
    for name, content in sections.items():
        path = repo_dir / f"{name}.patch"
        _atomic_write_bytes(path, content)
        section_records[name] = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(path),
            "path_identity": _serializable_path_identity(path),
            "sha256": _sha256_bytes(content),
            "size": len(content),
            "files": section_files[name],
            "range": f"{base_sha}...{head_sha}" if name == "committed" else None,
        }
    untracked_manifest_path = repo_dir / "untracked.json"
    _atomic_write_json(untracked_manifest_path, fingerprint["untracked"])
    tar_path = repo_dir / "untracked.tar"
    with tarfile.open(tar_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for item in fingerprint["untracked"]:
            relative = _untracked_filesystem_path(item)
            archive.add(working / relative, arcname=relative, recursive=False)
    _set_private_permissions(tar_path, 0o600)
    # Windows requires a writable descriptor for fsync; no bytes are changed.
    with tar_path.open("rb+") as archive_handle:
        os.fsync(archive_handle.fileno())
    _validate_untracked_archive(tar_path, fingerprint["untracked"])
    middle_fingerprint = _fingerprint_repo(working)
    verify_head, verify_sections, verify_files = capture_sections()
    final_fingerprint = _fingerprint_repo(working)
    if (
        fingerprint.get("sha256") != middle_fingerprint.get("sha256")
        or fingerprint.get("sha256") != final_fingerprint.get("sha256")
        or verify_head != head_sha
        or verify_sections != sections
        or verify_files != section_files
    ):
        raise FlowError(
            "REVIEW_SNAPSHOT_CHANGED",
            "repository changed while the complete review snapshot was being built",
            details={
                "repository_id": repo["id"],
                "before_sha256": fingerprint.get("sha256"),
                "middle_sha256": middle_fingerprint.get("sha256"),
                "after_sha256": final_fingerprint.get("sha256"),
                "before_head": head_sha,
                "after_head": verify_head,
            },
        )
    section_records["untracked"] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "manifest_path": str(untracked_manifest_path),
        "manifest_path_identity": _serializable_path_identity(
            untracked_manifest_path
        ),
        "manifest_sha256": _sha256_file(untracked_manifest_path),
        "archive_path": str(tar_path),
        "archive_path_identity": _serializable_path_identity(tar_path),
        "archive_sha256": _sha256_file(tar_path),
        "size": tar_path.stat().st_size,
        "files": fingerprint["untracked"],
    }
    fingerprint_reference = _store_fingerprint(
        task_dir if task_dir is not None else snapshot_root,
        fingerprint,
        f"review-fingerprint:{repo['id']}",
    )
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "repository_id": repo["id"],
        "working_path": str(working),
        "working_path_identity": _serializable_path_identity(working),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "capability_profile_sha256": fingerprint[
            "capability_profile_sha256"
        ],
        "tracked_worktree_manifest_sha256": fingerprint[
            "tracked_worktree_manifest_sha256"
        ],
        "fingerprint": fingerprint_reference,
        "sections": section_records,
    }


def _latest_passing_test_is_current(
    state_value: dict[str, Any],
    *,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, str | None]:
    """Require each repo's newest relevant test record to pass and remain current."""

    if _flow(state_value) == "lite":
        lite_approval = _require_lite_gate(state_value)

        def _bound_to_current_approval(test: dict[str, Any]) -> bool:
            return test.get("lite_approval_id") == lite_approval.get(
                "approval_id"
            ) and str(test.get("recorded_at", "")) >= str(
                lite_approval.get("approved_at", "")
            )

        missing_message = "no test result for the current lite approval covers repository"
    else:
        route_value = (state_value.get("route") or {}).get("value")
        plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        plan_approval, plan_artifact = _require_current_plan_gate(
            state_value, plan_kind
        )

        def _bound_to_current_approval(test: dict[str, Any]) -> bool:
            return (
                test.get("plan_artifact_sha256") == plan_artifact.get("sha256")
                and test.get("plan_approval_id")
                == plan_approval.get("approval_id")
                and str(test.get("recorded_at", ""))
                >= str(plan_approval.get("approved_at", ""))
            )

        missing_message = "no test result for the current plan approval covers repository"
    tests = state_value.get("tests", [])
    for repo in state_value["repositories"]:
        latest_by_identity: dict[str, dict[str, Any]] = {}
        for test in tests:
            if repo["id"] not in test.get("repository_ids", []):
                continue
            if not _bound_to_current_approval(test):
                continue
            identity = test.get("test_identity") or _test_identity(
                test.get("name"), test.get("command")
            )
            latest_by_identity[identity] = test
        if not latest_by_identity:
            return (
                False,
                f"{missing_message}: {repo['id']}",
            )
        current = (
            fingerprints[repo["id"]]
            if fingerprints is not None and repo["id"] in fingerprints
            else _fingerprint_repo(_working_path(repo))
        )
        for latest in latest_by_identity.values():
            label = latest.get("name") or latest.get("test_identity") or "unnamed"
            try:
                _require_current_evidence(latest, f"test:{label}")
            except FlowError as exc:
                return False, exc.message
            if not latest.get("passed"):
                return (
                    False,
                    f"latest result for test identity {label!r} failed for repository: {repo['id']}",
                )
            output = latest.get("output")
            if output is not None:
                try:
                    _require_current_evidence(
                        output, f"test-output:{label}"
                    )
                except FlowError as exc:
                    return False, exc.message
                output_path = Path(str((output or {}).get("path", "")))
                try:
                    output_sha = (
                        _sha256_file(output_path)
                        if output_path.is_file()
                        else None
                    )
                    output_size = (
                        output_path.stat().st_size
                        if output_path.is_file()
                        else None
                    )
                except OSError:
                    output_sha = None
                    output_size = None
                if (
                    output_sha != (output or {}).get("sha256")
                    or output_size != (output or {}).get("size")
                    or not _recorded_path_matches(
                        (output or {}).get("path_identity"),
                        (output or {}).get("path"),
                        output_path,
                    )
                ):
                    return (
                        False,
                        f"test output for identity {label!r} is missing or changed: {output_path}",
                    )
            try:
                recorded = _load_recorded_fingerprint(
                    latest.get("fingerprints", {}).get(repo["id"]),
                    f"test-fingerprint:{label}:{repo['id']}",
                )
            except FlowError as exc:
                return False, exc.message
            if current.get("sha256") != recorded.get("sha256"):
                return (
                    False,
                    f"repository changed after test identity {label!r} passed: {repo['id']}",
                )
            recorded_profiles = latest.get(
                "capability_profile_sha256", {}
            )
            if (
                current.get("capability_profile_sha256")
                != recorded_profiles.get(repo["id"])
            ):
                return (
                    False,
                    f"repository capability profile changed after test identity {label!r}: {repo['id']}",
                )
    return True, None


def _v3_review_latest_passing_test_is_current(
    state_value: dict[str, Any],
    approval_binding: _ReviewMapping[str, object],
    fingerprints: _ReviewMapping[str, dict[str, object]],
) -> tuple[bool, str | None]:
    """Typed planner test-currentness check using only prevalidated facts."""

    binding = _v3_review_thaw(approval_binding)
    if not isinstance(binding, dict):
        raise _v3_review_error(
            "REVIEW_EFFECT_APPROVAL_MISMATCH",
            "typed test currency requires one durable approval binding",
        )
    flow = _flow(state_value)
    if binding.get("flow") != flow:
        raise _v3_review_error(
            "REVIEW_EFFECT_APPROVAL_MISMATCH",
            "typed test currency received another approval flow",
        )

    def bound_to_approval(test: dict[str, Any]) -> bool:
        if flow == "lite":
            return (
                test.get("lite_approval_id")
                == binding.get("approval_id")
                and str(test.get("recorded_at", ""))
                >= str(binding.get("approved_at", ""))
            )
        return (
            test.get("plan_artifact_sha256")
            == binding.get("artifact_sha256")
            and test.get("plan_approval_id")
            == binding.get("approval_id")
            and str(test.get("recorded_at", ""))
            >= str(binding.get("approved_at", ""))
        )

    missing_message = (
        "no test result for the current lite approval covers repository"
        if flow == "lite"
        else "no test result for the current plan approval covers repository"
    )
    tests = state_value.get("tests", [])
    for repo in state_value["repositories"]:
        repository_id = str(repo["id"])
        latest_by_identity: dict[str, dict[str, Any]] = {}
        for test in tests:
            if (
                repository_id not in test.get("repository_ids", [])
                or not bound_to_approval(test)
            ):
                continue
            identity = test.get("test_identity") or _test_identity(
                test.get("name"), test.get("command")
            )
            latest_by_identity[str(identity)] = test
        if not latest_by_identity:
            return False, f"{missing_message}: {repository_id}"
        current = fingerprints.get(repository_id)
        if not isinstance(current, dict):
            raise _v3_review_error(
                "REVIEW_EFFECT_REPOSITORY_MISMATCH",
                "typed test currency lacks a planned repository fingerprint",
                details={"repository_id": repository_id},
            )
        for latest in latest_by_identity.values():
            label = (
                latest.get("name")
                or latest.get("test_identity")
                or "unnamed"
            )
            try:
                _require_current_evidence(latest, f"test:{label}")
            except FlowError as exc:
                return False, exc.message
            if not latest.get("passed"):
                return (
                    False,
                    f"latest result for test identity {label!r} failed for repository: {repository_id}",
                )
            output = latest.get("output")
            if output is not None:
                try:
                    _require_current_evidence(
                        output, f"test-output:{label}"
                    )
                except FlowError as exc:
                    return False, exc.message
                output_path = _ReviewPath(
                    str((output or {}).get("path", ""))
                )
                try:
                    output_sha = (
                        _sha256_file(output_path)
                        if output_path.is_file()
                        else None
                    )
                    output_size = (
                        output_path.stat().st_size
                        if output_path.is_file()
                        else None
                    )
                except OSError:
                    output_sha = None
                    output_size = None
                if (
                    output_sha != (output or {}).get("sha256")
                    or output_size != (output or {}).get("size")
                    or not _recorded_path_matches(
                        (output or {}).get("path_identity"),
                        (output or {}).get("path"),
                        output_path,
                    )
                ):
                    return (
                        False,
                        f"test output for identity {label!r} is missing or changed: {output_path}",
                    )
            try:
                recorded = _load_recorded_fingerprint(
                    latest.get("fingerprints", {}).get(repository_id),
                    f"test-fingerprint:{label}:{repository_id}",
                )
            except FlowError as exc:
                return False, exc.message
            if current.get("sha256") != recorded.get("sha256"):
                return (
                    False,
                    f"repository changed after test identity {label!r} passed: {repository_id}",
                )
            profiles = latest.get(
                "capability_profile_sha256", {}
            )
            if (
                current.get("capability_profile_sha256")
                != profiles.get(repository_id)
            ):
                return (
                    False,
                    f"repository capability profile changed after test identity {label!r}: {repository_id}",
                )
    return True, None


def _v3_review_capture_sections(
    working: _ReviewPath,
    base_sha: str,
) -> tuple[str, dict[str, bytes], dict[str, list[str]]]:
    head_sha = _git_evidence(working, "rev-parse", "HEAD")
    sections = {
        "committed": _git_diff(
            working,
            "--binary",
            "--full-index",
            f"{base_sha}...HEAD",
            "--",
            text=False,
        ),
        "cached": _git_diff(
            working,
            "--binary",
            "--full-index",
            "--cached",
            "--",
            text=False,
        ),
        "unstaged": _git_diff(
            working,
            "--binary",
            "--full-index",
            "--",
            text=False,
        ),
    }
    files = {
        "committed": _split_lines(
            _git_diff(
                working,
                "--name-status",
                f"{base_sha}...HEAD",
                "--",
            )
        ),
        "cached": _split_lines(
            _git_diff(working, "--cached", "--name-status", "--")
        ),
        "unstaged": _split_lines(
            _git_diff(working, "--name-status", "--")
        ),
    }
    return head_sha, sections, files


def _v3_review_untracked_tar_bytes(
    working: _ReviewPath,
    untracked: _ReviewSequence[dict[str, Any]],
) -> bytes:
    stream = _review_io.BytesIO()
    with _review_tarfile.open(
        fileobj=stream,
        mode="w",
        format=_review_tarfile.PAX_FORMAT,
    ) as archive:
        for item in untracked:
            relative = _untracked_filesystem_path(item)
            target = working / relative
            info = archive.gettarinfo(str(target), arcname=relative)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            if info.isfile():
                with target.open("rb") as handle:
                    archive.addfile(info, handle)
            elif info.issym():
                archive.addfile(info)
            else:
                raise _v3_review_error(
                    "REVIEW_EFFECT_UNTRACKED_INVALID",
                    "review snapshot supports only regular files and symlinks",
                    details={"path": relative},
                )
    return stream.getvalue()


def _v3_review_snapshot_repository(
    *,
    task_dir: _ReviewPath,
    snapshot_root: _ReviewPath,
    repo: dict[str, Any],
    working: _ReviewPath,
    filesystem: dict[str, object],
    fingerprint: dict[str, object],
) -> tuple[dict[str, object], dict[str, bytes]]:
    repository_id = str(repo["id"])
    baseline = repo.get("baseline")
    base_sha = (
        baseline.get("base_sha")
        if isinstance(baseline, dict)
        else None
    )
    if not isinstance(base_sha, str) or not base_sha:
        raise _v3_review_error(
            "BASELINE_REQUIRED",
            "review snapshot repository has no approved baseline",
            details={"repository_id": repository_id},
        )
    with _v3_workspace_readonly_git():
        head_sha, sections, section_files = (
            _v3_review_capture_sections(working, base_sha)
        )
        verify_head, verify_sections, verify_files = (
            _v3_review_capture_sections(working, base_sha)
        )
        final_fingerprint = _v3_review_capture_fingerprint(
            repository_id, working, filesystem
        )
    if (
        head_sha != fingerprint.get("head_sha")
        or verify_head != head_sha
        or verify_sections != sections
        or verify_files != section_files
        or final_fingerprint.get("sha256")
        != fingerprint.get("sha256")
    ):
        raise _v3_review_error(
            "REVIEW_SNAPSHOT_CHANGED",
            "repository changed while its review payload was planned",
            details={"repository_id": repository_id},
        )
    repo_root = snapshot_root / repository_id
    if not _is_within(repo_root, snapshot_root):
        raise _v3_review_error(
            "REVIEW_EFFECT_PATH_INVALID",
            "repository identity escapes the snapshot root",
            details={"repository_id": repository_id},
        )
    payloads: dict[str, bytes] = {}
    section_records: dict[str, object] = {}
    for name in ("committed", "cached", "unstaged"):
        path = repo_root / f"{name}.patch"
        content = sections[name]
        payloads[str(path)] = content
        section_records[name] = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(path),
            "path_identity": _capability_path_identity(path),
            "sha256": _review_hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "files": section_files[name],
            "range": (
                f"{base_sha}...{head_sha}"
                if name == "committed"
                else None
            ),
        }
    untracked = _review_copy.deepcopy(
        list(fingerprint.get("untracked", ()))
    )
    untracked_manifest = _json_bytes(untracked)
    manifest_path = repo_root / "untracked.json"
    tar_path = repo_root / "untracked.tar"
    tar_bytes = _v3_review_untracked_tar_bytes(working, untracked)
    payloads[str(manifest_path)] = untracked_manifest
    payloads[str(tar_path)] = tar_bytes
    section_records["untracked"] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "manifest_path": str(manifest_path),
        "manifest_path_identity": _capability_path_identity(
            manifest_path
        ),
        "manifest_sha256": _review_hashlib.sha256(
            untracked_manifest
        ).hexdigest(),
        "archive_path": str(tar_path),
        "archive_path_identity": _capability_path_identity(tar_path),
        "archive_sha256": _review_hashlib.sha256(tar_bytes).hexdigest(),
        "size": len(tar_bytes),
        "files": untracked,
    }
    reference, fingerprint_bytes = _v3_review_fingerprint_reference(
        task_dir, fingerprint
    )
    payloads[str(reference["path"])] = fingerprint_bytes
    record = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "repository_id": repository_id,
        "working_path": str(working),
        "working_path_identity": _serializable_path_identity(working),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "capability_profile_sha256": fingerprint.get(
            "capability_profile_sha256"
        ),
        "tracked_worktree_manifest_sha256": fingerprint.get(
            "tracked_worktree_manifest_sha256"
        ),
        "fingerprint": reference,
        "sections": section_records,
    }
    return record, payloads


def plan_v3_review_snapshot_effect(
    *,
    state_value: dict[str, Any],
    data_root: str | _ReviewPath,
    task_dir: str | _ReviewPath,
    execution_id: str,
    repository_ids: _ReviewSequence[str] | None = None,
) -> V3ReviewEffectPlan:
    """Capture a deterministic all-repository snapshot entirely in memory."""

    effect_id = _v3_review_effect_id(
        state_value, "review-snapshot"
    )
    task_id = _v3_review_text(state_value.get("task_id"), "task_id")
    node_id = _v3_review_text(state_value.get("status"), "status")
    revision = _v3_review_revision(state_value.get("revision"))
    execution_id = _v3_review_text(execution_id, "execution_id")
    resolved_data, resolved_task, state_path = _v3_review_task_paths(
        state_value, data_root, task_dir
    )
    configured = {
        str(repo["id"]): repo
        for repo in state_value.get("repositories", [])
        if isinstance(repo, dict) and isinstance(repo.get("id"), str)
    }
    selected_ids = tuple(
        sorted(
            (
                set(configured)
                if repository_ids is None
                else {
                    _v3_review_text(item, "repository_id")
                    for item in repository_ids
                }
            ),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if set(selected_ids) != set(configured) or not selected_ids:
        raise _v3_review_error(
            "INCOMPLETE_REVIEW",
            "schema-v3 review snapshot must cover every repository",
            details={
                "required_repository_ids": sorted(configured),
                "selected_repository_ids": list(selected_ids),
            },
        )
    for repository_id in selected_ids:
        workspace = configured[repository_id].get("workspace")
        if (
            not isinstance(workspace, dict)
            or workspace.get("ready") is not True
        ):
            raise _v3_review_error(
                "WORKSPACE_REQUIRED",
                "review snapshot requires every approved workspace",
                details={"repository_id": repository_id},
            )
    profiles = [
        _v3_review_profile_for_repository(configured[item])
        for item in selected_ids
    ]
    controller_facts = _v3_review_controller_filesystem_facts(
        state_value, resolved_task, profiles
    )
    snapshot_id = "review-" + _v3_review_sha256(
        _V3_REVIEW_SNAPSHOT_ID_DOMAIN,
        {
            "task_id": task_id,
            "execution_id": execution_id,
            "effect_id": effect_id,
        },
    )
    snapshot_root = resolved_task / "reviews" / snapshot_id
    _v3_workspace_seed_filesystem_facts(
        snapshot_root, controller_facts
    )
    fingerprints: dict[str, dict[str, object]] = {}
    for repository_id, (working, filesystem) in zip(
        selected_ids, profiles
    ):
        fingerprints[repository_id] = (
            _v3_review_capture_fingerprint(
                repository_id, working, filesystem
            )
        )
    approval_binding = _v3_review_approval_binding(state_value)
    passing, reason = _v3_review_latest_passing_test_is_current(
        state_value,
        approval_binding,
        fingerprints,
    )
    if not passing:
        raise _v3_review_error(
            "CURRENT_TEST_REQUIRED",
            reason or "a current passing test is required",
        )
    repositories: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    repository_bindings: list[dict[str, object]] = []
    for repository_id, (working, filesystem) in zip(
        selected_ids, profiles
    ):
        record, repository_payloads = (
            _v3_review_snapshot_repository(
                task_dir=resolved_task,
                snapshot_root=snapshot_root,
                repo=configured[repository_id],
                working=working,
                filesystem=filesystem,
                fingerprint=fingerprints[repository_id],
            )
        )
        repositories.append(record)
        payloads.update(repository_payloads)
        repository_bindings.append(
            {
                "repository_id": repository_id,
                "working_path": str(working),
                "filesystem_capabilities": filesystem,
                "fingerprint_sha256": fingerprints[
                    repository_id
                ]["sha256"],
            }
        )
    for repository_id, (working, filesystem) in zip(
        selected_ids, profiles
    ):
        current = _v3_review_capture_fingerprint(
            repository_id, working, filesystem
        )
        if current.get("sha256") != fingerprints[
            repository_id
        ].get("sha256"):
            raise _v3_review_error(
                "REVIEW_SNAPSHOT_CHANGED",
                "repository changed across the multi-repository snapshot",
                details={"repository_id": repository_id},
            )
    created_at = state_value.get("updated_at")
    if not isinstance(created_at, str) or not created_at:
        created_at = approval_binding.get("approved_at")
    created_at = _v3_review_text(created_at, "created_at")
    manifest = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "repository_ids": list(selected_ids),
        "repositories": repositories,
    }
    manifest_path = snapshot_root / "manifest.json"
    manifest_bytes = _json_bytes(manifest)
    payloads[str(manifest_path)] = manifest_bytes
    snapshot = {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_path_identity": _capability_path_identity(
            manifest_path
        ),
        "sha256": _review_hashlib.sha256(
            manifest_bytes
        ).hexdigest(),
    }
    artifact = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "artifact_id": "review-artifact-"
        + _v3_review_sha256(
            _V3_REVIEW_SNAPSHOT_ID_DOMAIN,
            {
                "snapshot_id": snapshot_id,
                "manifest_sha256": snapshot["sha256"],
            },
        ),
        "kind": "review-snapshot",
        "path": str(manifest_path),
        "path_identity": snapshot["manifest_path_identity"],
        "sha256": snapshot["sha256"],
        "size": len(manifest_bytes),
        "recorded_at": created_at,
        "metadata": {
            "snapshot_id": snapshot_id,
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "capability_profile_sha256": {
                repository_id: fingerprints[repository_id][
                    "capability_profile_sha256"
                ]
                for repository_id in selected_ids
            },
        },
    }
    descriptors = []
    for path, content in payloads.items():
        suffix = _ReviewPath(path).suffix
        kind = (
            "review-manifest"
            if path == str(manifest_path)
            else (
                "fingerprint"
                if "/artifacts/fingerprints/" in path.replace("\\", "/")
                else (
                    "untracked-archive"
                    if suffix == ".tar"
                    else "review-section"
                )
            )
        )
        descriptors.append(
            _v3_review_payload_descriptor(
                _ReviewPath(path), content, kind
            )
        )
    descriptors.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    bindings = {
        "mode": "review-snapshot",
        "node_id": node_id,
        "data_root": str(resolved_data),
        "task_dir": str(resolved_task),
        "state_path": str(state_path),
        "state_sha256": _sha256_contract(state_value),
        "workflow_ref": _review_copy.deepcopy(
            state_value.get("workflow_ref")
        ),
        "approval_binding": approval_binding,
        "controller_filesystem_capabilities": controller_facts,
        "repositories": repository_bindings,
        "snapshot_root": str(snapshot_root),
        "snapshot": snapshot,
        "artifact": artifact,
        "payloads": descriptors,
    }
    return _v3_review_build_plan(
        action="review-snapshot",
        expected_effect_id=effect_id,
        task_id=task_id,
        task_revision=revision,
        execution_id=execution_id,
        repository_ids=selected_ids,
        bindings=bindings,
        payloads=payloads,
    )


def v3_review_effect_safe_inputs(
    plan: V3ReviewEffectPlan,
) -> dict[str, object]:
    if type(plan) is not V3ReviewEffectPlan:
        raise _v3_review_error(
            "REVIEW_EFFECT_PLAN_TYPE_INVALID",
            "safe inputs require the exact typed review plan",
        )
    return {
        "schema": _V3_REVIEW_EFFECT_PLAN_SCHEMA,
        "action": plan.action,
        "expected_effect_id": plan.expected_effect_id,
        "plan_sha256": plan.semantic_sha256,
        "task_revision": plan.task_revision,
        "execution_id": plan.execution_id,
        "repository_ids": list(plan.repository_ids),
        "state_sha256": plan.bindings["state_sha256"],
        "payloads_sha256": _v3_review_sha256(
            _V3_REVIEW_EFFECT_PLAN_DOMAIN,
            _v3_review_thaw(plan.bindings["payloads"]),
        ),
    }


def v3_review_effect_scopes(
    plan: V3ReviewEffectPlan,
) -> dict[str, list[str]]:
    if type(plan) is not V3ReviewEffectPlan:
        raise _v3_review_error(
            "REVIEW_EFFECT_PLAN_TYPE_INVALID",
            "scopes require the exact typed review plan",
        )
    paths = {
        str(plan.bindings["task_dir"]),
        str(plan.bindings["state_path"]),
        *(
            str(item["path"])
            for item in plan.bindings["payloads"]
        ),
        *(
            str(item["working_path"])
            for item in plan.bindings["repositories"]
        ),
    }
    test_record = plan.bindings.get("test_record")
    output = (
        test_record.get("output")
        if isinstance(test_record, _ReviewMapping)
        else None
    )
    if isinstance(output, _ReviewMapping) and isinstance(
        output.get("path"), str
    ):
        paths.add(str(output["path"]))
    return normalize_scopes(
        {
            "repository_ids": list(plan.repository_ids),
            "node_ids": [
                _v3_review_text(
                    plan.bindings.get("node_id"), "node_id"
                )
            ],
            "worktree_ids": [
                (
                    "review:"
                    + plan.task_id
                    + ":"
                    + repository_id
                )
                for repository_id in plan.repository_ids
            ],
            "lease_ids": [],
            "paths": sorted(
                paths, key=lambda item: item.encode("utf-8")
            ),
            "external_resources": [],
        }
    )


def _v3_review_load_bound_state(
    plan: V3ReviewEffectPlan,
) -> dict[str, object]:
    path = _ReviewPath(str(plan.bindings["state_path"]))
    try:
        state = _read_task_state_structural_snapshot(path)
    except Exception as exc:
        raise _v3_review_error(
            "REVIEW_EFFECT_STATE_UNAVAILABLE",
            "review effect cannot load its bound task state",
            details={
                "path": str(path),
                "cause_code": getattr(exc, "code", type(exc).__name__),
            },
        ) from exc
    mismatches = []
    if state.get("task_id") != plan.task_id:
        mismatches.append("task_id")
    if state.get("revision") != plan.task_revision:
        mismatches.append("revision")
    if state.get("workflow_ref") != _v3_review_thaw(
        plan.bindings["workflow_ref"]
    ):
        mismatches.append("workflow_ref")
    if _sha256_contract(state) != plan.bindings["state_sha256"]:
        mismatches.append("state_sha256")
    if mismatches:
        raise _v3_review_error(
            "REVIEW_EFFECT_STATE_CHANGED",
            "task state changed after the review effect was planned",
            details={"fields": mismatches},
        )
    return state


def _v3_review_verify_current_repositories(
    plan: V3ReviewEffectPlan,
) -> None:
    for record in plan.bindings["repositories"]:
        repository_id = str(record["repository_id"])
        working = _ReviewPath(str(record["working_path"]))
        filesystem = record["filesystem_capabilities"]
        current = _v3_review_capture_fingerprint(
            repository_id,
            working,
            _v3_review_thaw(filesystem),
        )
        planned = record.get("fingerprint")
        expected_sha = (
            planned.get("sha256")
            if isinstance(planned, _ReviewMapping)
            else record.get("fingerprint_sha256")
        )
        if current.get("sha256") != expected_sha:
            raise _v3_review_error(
                "REVIEW_EFFECT_REPOSITORY_CHANGED",
                "repository changed after the review effect was planned",
                details={"repository_id": repository_id},
            )


def _v3_review_validate_dispatch_context(
    plan: V3ReviewEffectPlan,
    context: object,
) -> ActionDispatchPlan:
    if type(context) is not WorkflowActionDispatchContext:
        raise _v3_review_error(
            "REVIEW_EFFECT_TRANSACTION_PERMIT_REQUIRED",
            "review dispatch requires Transaction's active context",
        )
    verifier = globals().get(
        "verify_active_v3_workflow_action_dispatch_context"
    )
    if not callable(verifier):
        raise _v3_review_error(
            "REVIEW_EFFECT_TRANSACTION_AUTHORITY_UNAVAILABLE",
            "review dispatch authority verifier is unavailable",
        )
    try:
        verifier(context)
    except Exception as exc:
        raise _v3_review_error(
            "REVIEW_EFFECT_TRANSACTION_PERMIT_INACTIVE",
            "review dispatch context is forged, copied, replayed, or inactive",
            details={
                "cause_code": getattr(exc, "code", type(exc).__name__)
            },
        ) from None
    transaction_plan = context.plan
    mismatches = []
    if type(transaction_plan) is not ActionDispatchPlan:
        mismatches.append("plan_type")
    else:
        if transaction_plan.task_id != plan.task_id:
            mismatches.append("task_id")
        if transaction_plan.execution_id != plan.execution_id:
            mismatches.append("execution_id")
        if transaction_plan.effect_id != plan.expected_effect_id:
            mismatches.append("effect_id")
        if transaction_plan.safe_inputs != v3_review_effect_safe_inputs(
            plan
        ):
            mismatches.append("safe_inputs")
    if context.effect_kind != "filesystem":
        mismatches.append("effect_kind")
    if context.settlement != "synchronous-quiescence":
        mismatches.append("settlement")
    if context.scopes != v3_review_effect_scopes(plan):
        mismatches.append("scopes")
    if mismatches:
        raise _v3_review_error(
            "REVIEW_EFFECT_TRANSACTION_PERMIT_MISMATCH",
            "review dispatch context differs from its immutable plan",
            details={"fields": sorted(set(mismatches))},
        )
    assert isinstance(transaction_plan, ActionDispatchPlan)
    return transaction_plan


def _v3_review_validate_observe_context(
    plan: V3ReviewEffectPlan,
    context: object,
) -> WorkflowActionObserveContext:
    if type(context) is not WorkflowActionObserveContext:
        raise _v3_review_error(
            "REVIEW_EFFECT_OBSERVE_CONTEXT_REQUIRED",
            "review observation requires Transaction's observe-only context",
        )
    verifier = globals().get(
        "verify_active_v3_workflow_action_observe_context"
    )
    if not callable(verifier):
        raise _v3_review_error(
            "REVIEW_EFFECT_TRANSACTION_AUTHORITY_UNAVAILABLE",
            "review observe authority verifier is unavailable",
        )
    try:
        facts = verifier(context)
    except Exception as exc:
        raise _v3_review_error(
            "REVIEW_EFFECT_OBSERVE_CONTEXT_INACTIVE",
            "review observe context is forged, copied, replayed, or inactive",
            details={
                "cause_code": getattr(exc, "code", type(exc).__name__)
            },
        ) from None
    mismatches = []
    if not isinstance(facts, dict):
        mismatches.append("facts")
    else:
        expected = {
            "task_id": plan.task_id,
            "execution_id": plan.execution_id,
            "effect_id": plan.expected_effect_id,
            "safe_inputs": v3_review_effect_safe_inputs(plan),
            "scopes": v3_review_effect_scopes(plan),
            "effect_kind": "filesystem",
            "settlement": "synchronous-quiescence",
        }
        for field, expected_value in expected.items():
            if facts.get(field) != expected_value:
                mismatches.append(field)
    if mismatches:
        raise _v3_review_error(
            "REVIEW_EFFECT_OBSERVE_CONTEXT_MISMATCH",
            "review observe context differs from its immutable plan",
            details={"fields": sorted(set(mismatches))},
        )
    return context


@_review_dataclass(frozen=True)
class V3ReviewEffectObservation:
    action: str
    plan_sha256: str
    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    result: _ReviewMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        result = _v3_review_public(dict(self.result))
        if not isinstance(result, dict):
            raise _v3_review_error(
                "REVIEW_EFFECT_OBSERVATION_INVALID",
                "review observation result must be an object",
            )
        core = {
            "schema": _V3_REVIEW_EFFECT_OBSERVATION_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "effect_id": self.effect_id,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "result": result,
        }
        if (
            _v3_review_sha256(
                _V3_REVIEW_EFFECT_OBSERVATION_DOMAIN, core
            )
            != self.semantic_sha256
        ):
            raise _v3_review_error(
                "REVIEW_EFFECT_OBSERVATION_DIGEST_MISMATCH",
                "review observation digest differs from its result",
            )
        object.__setattr__(self, "result", _v3_review_freeze(result))


def _v3_review_build_observation(
    plan: V3ReviewEffectPlan,
    transaction_plan: ActionDispatchPlan,
    result: _ReviewMapping[str, object],
) -> V3ReviewEffectObservation:
    public = _v3_review_public(dict(result))
    assert isinstance(public, dict)
    core = {
        "schema": _V3_REVIEW_EFFECT_OBSERVATION_SCHEMA,
        "action": plan.action,
        "plan_sha256": plan.semantic_sha256,
        "task_id": transaction_plan.task_id,
        "execution_id": transaction_plan.execution_id,
        "effect_id": transaction_plan.effect_id,
        "claim_id": transaction_plan.claim_id,
        "attempt_id": transaction_plan.attempt_id,
        "result": public,
    }
    return V3ReviewEffectObservation(
        action=plan.action,
        plan_sha256=plan.semantic_sha256,
        task_id=transaction_plan.task_id,
        execution_id=transaction_plan.execution_id,
        effect_id=transaction_plan.effect_id,
        claim_id=transaction_plan.claim_id,
        attempt_id=transaction_plan.attempt_id,
        result=public,
        semantic_sha256=_v3_review_sha256(
            _V3_REVIEW_EFFECT_OBSERVATION_DOMAIN, core
        ),
    )


def _v3_review_result(plan: V3ReviewEffectPlan) -> dict[str, object]:
    if plan.action == "record-test":
        return {
            "test_record": _v3_review_thaw(
                plan.bindings["test_record"]
            ),
            "payloads_sha256": _v3_review_sha256(
                _V3_REVIEW_EFFECT_PLAN_DOMAIN,
                _v3_review_thaw(plan.bindings["payloads"]),
            ),
        }
    return {
        "snapshot": _v3_review_thaw(plan.bindings["snapshot"]),
        "artifact": _v3_review_thaw(plan.bindings["artifact"]),
        "payloads_sha256": _v3_review_sha256(
            _V3_REVIEW_EFFECT_PLAN_DOMAIN,
            _v3_review_thaw(plan.bindings["payloads"]),
        ),
    }


def _v3_review_verify_payloads(plan: V3ReviewEffectPlan) -> None:
    for descriptor in plan.bindings["payloads"]:
        path = _ReviewPath(str(descriptor["path"]))
        unresolved = _rollback_evidence_for(path)
        if unresolved:
            raise _v3_review_error(
                "ATOMIC_RECOVERY_REQUIRED",
                "review payload has unresolved rollback evidence",
                details={
                    "path": str(path),
                    "rollback_candidates": [
                        str(item) for item in unresolved
                    ],
                },
            )
        try:
            source = path.read_bytes()
        except OSError as exc:
            raise _v3_review_error(
                "REVIEW_EFFECT_RECEIPT_MISSING",
                "review effect payload is missing or unreadable",
                details={"path": str(path), "error": str(exc)},
            ) from exc
        if (
            len(source) != descriptor["size"]
            or _review_hashlib.sha256(source).hexdigest()
            != descriptor["sha256"]
        ):
            raise _v3_review_error(
                "REVIEW_EFFECT_RECEIPT_MISMATCH",
                "review effect payload differs from its planned bytes",
                details={"path": str(path)},
            )
    if plan.action == "record-test":
        record = plan.bindings["test_record"]
        for repository_id, reference in record["fingerprints"].items():
            _load_recorded_fingerprint(
                _v3_review_thaw(reference),
                f"test-fingerprint:{record['name']}:{repository_id}",
            )
        output = record.get("output")
        if isinstance(output, _ReviewMapping):
            path = _ReviewPath(str(output["path"]))
            try:
                current_size = path.stat().st_size
                current_sha = _sha256_file(path)
            except OSError:
                current_size = None
                current_sha = None
            if (
                current_size != output["size"]
                or current_sha != output["sha256"]
            ):
                raise _v3_review_error(
                    "REVIEW_EFFECT_OUTPUT_CHANGED",
                    "test output changed after review planning",
                    details={"path": str(path)},
                )
    else:
        snapshot = _v3_review_thaw(plan.bindings["snapshot"])
        assert isinstance(snapshot, dict)
        error = _review_snapshot_integrity_error(snapshot)
        if error:
            raise _v3_review_error(
                "REVIEW_SNAPSHOT_INVALID",
                error,
                details={"snapshot_id": snapshot.get("snapshot_id")},
            )


def dispatch_v3_review_effect(
    plan: V3ReviewEffectPlan,
    context: object,
) -> V3ReviewEffectObservation:
    """Write exact planned bytes once; leave partial bytes for reconciliation."""

    transaction_plan = _v3_review_validate_dispatch_context(
        plan, context
    )
    _v3_review_load_bound_state(plan)
    _v3_review_verify_current_repositories(plan)
    for descriptor in plan.bindings["payloads"]:
        path = _ReviewPath(str(descriptor["path"]))
        content = plan.payloads[str(path)]
        if path.exists():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise _v3_review_error(
                    "REVIEW_EFFECT_PAYLOAD_UNREADABLE",
                    "existing review payload cannot be read",
                    details={"path": str(path), "error": str(exc)},
                ) from exc
            if existing != content:
                raise _v3_review_error(
                    "REVIEW_EFFECT_PAYLOAD_COLLISION",
                    "digest-addressed review target contains other bytes",
                    details={"path": str(path)},
                )
        else:
            _atomic_write_bytes(path, content)
        if descriptor["kind"] == "untracked-archive":
            _set_private_permissions(path, 0o600)
            with path.open("rb+") as handle:
                _review_os.fsync(handle.fileno())
    _v3_review_verify_payloads(plan)
    _v3_review_verify_current_repositories(plan)
    return _v3_review_build_observation(
        plan, transaction_plan, _v3_review_result(plan)
    )


@_review_dataclass(frozen=True)
class V3ReviewEffectReceipt:
    action: str
    plan_sha256: str
    claim_id: str
    attempt_id: str
    journal_record_sha256: str
    index_record_sha256: str
    containment_record_sha256: str
    observe_context_sha256: str
    repository_ids: tuple[str, ...]
    recovered_lost_response: bool
    result: _ReviewMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        _v3_review_text(self.claim_id, "claim_id")
        _v3_review_text(self.attempt_id, "attempt_id")
        for field_name in (
            "journal_record_sha256",
            "index_record_sha256",
            "containment_record_sha256",
            "observe_context_sha256",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not _V3_REVIEW_SHA256.fullmatch(value)
            ):
                raise _v3_review_error(
                    "REVIEW_EFFECT_RECEIPT_BINDING_INVALID",
                    f"{field_name} must be lowercase SHA-256",
                )
        repository_ids = _v3_review_sorted_ids(self.repository_ids)
        result = _v3_review_public(dict(self.result))
        assert isinstance(result, dict)
        core = {
            "schema": _V3_REVIEW_EFFECT_RECEIPT_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "journal_record_sha256": self.journal_record_sha256,
            "index_record_sha256": self.index_record_sha256,
            "containment_record_sha256": (
                self.containment_record_sha256
            ),
            "observe_context_sha256": (
                self.observe_context_sha256
            ),
            "repository_ids": list(repository_ids),
            "recovered_lost_response": self.recovered_lost_response,
            "result": result,
        }
        if (
            _v3_review_sha256(
                _V3_REVIEW_EFFECT_RECEIPT_DOMAIN, core
            )
            != self.semantic_sha256
        ):
            raise _v3_review_error(
                "REVIEW_EFFECT_RECEIPT_DIGEST_MISMATCH",
                "review receipt digest differs from its result",
            )
        object.__setattr__(self, "repository_ids", repository_ids)
        object.__setattr__(self, "result", _v3_review_freeze(result))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": _V3_REVIEW_EFFECT_RECEIPT_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "journal_record_sha256": self.journal_record_sha256,
            "index_record_sha256": self.index_record_sha256,
            "containment_record_sha256": (
                self.containment_record_sha256
            ),
            "observe_context_sha256": (
                self.observe_context_sha256
            ),
            "repository_ids": list(self.repository_ids),
            "recovered_lost_response": self.recovered_lost_response,
            "result": _v3_review_thaw(self.result),
            "semantic_sha256": self.semantic_sha256,
        }


def observe_v3_review_effect(
    plan: V3ReviewEffectPlan,
    context: object,
    observation: V3ReviewEffectObservation | None = None,
) -> V3ReviewEffectReceipt:
    """Observe only durable bytes and repositories; never write or redispatch."""

    claim = _v3_review_validate_observe_context(plan, context)
    _v3_review_load_bound_state(plan)
    _v3_review_verify_payloads(plan)
    _v3_review_verify_current_repositories(plan)
    result = _v3_review_result(plan)
    if observation is not None:
        mismatches = []
        for field, expected in (
            ("action", plan.action),
            ("plan_sha256", plan.semantic_sha256),
            ("task_id", plan.task_id),
            ("execution_id", claim.execution_id),
            ("effect_id", plan.expected_effect_id),
            ("claim_id", claim.claim_id),
            ("attempt_id", claim.attempt_id),
        ):
            if getattr(observation, field, None) != expected:
                mismatches.append(field)
        if _v3_review_thaw(observation.result) != result:
            mismatches.append("result")
        if mismatches:
            raise _v3_review_error(
                "REVIEW_EFFECT_OBSERVATION_MISMATCH",
                "dispatch observation differs from durable review evidence",
                details={"fields": sorted(set(mismatches))},
            )
    core = {
        "schema": _V3_REVIEW_EFFECT_RECEIPT_SCHEMA,
        "action": plan.action,
        "plan_sha256": plan.semantic_sha256,
        "claim_id": claim.claim_id,
        "attempt_id": claim.attempt_id,
        "journal_record_sha256": claim.journal_record_sha256,
        "index_record_sha256": claim.index_record_sha256,
        "containment_record_sha256": (
            claim.containment_record_sha256
        ),
        "observe_context_sha256": (
            claim.observe_context_sha256
        ),
        "repository_ids": list(plan.repository_ids),
        "recovered_lost_response": observation is None,
        "result": result,
    }
    return V3ReviewEffectReceipt(
        action=plan.action,
        plan_sha256=plan.semantic_sha256,
        claim_id=claim.claim_id,
        attempt_id=claim.attempt_id,
        journal_record_sha256=claim.journal_record_sha256,
        index_record_sha256=claim.index_record_sha256,
        containment_record_sha256=(
            claim.containment_record_sha256
        ),
        observe_context_sha256=(
            claim.observe_context_sha256
        ),
        repository_ids=plan.repository_ids,
        recovered_lost_response=observation is None,
        result=result,
        semantic_sha256=_v3_review_sha256(
            _V3_REVIEW_EFFECT_RECEIPT_DOMAIN, core
        ),
    )


def v3_review_snapshot_command_v1(
    args: argparse.Namespace,
    task_dir: _ReviewPath,
    current: dict[str, Any],
) -> dict[str, Any]:
    try:
        edge = resolve_v3_node_action_edge(
            current, "review-snapshot"
        )
        completion_edge = (
            resolve_v3_workflow_action_completion_edge(
                current,
                edge,
                public_command="review-snapshot",
                target="REVIEWING",
            )
        )
    except (
        TransitionEngineError,
        WorkflowActionTransactionError,
    ) as exc:
        details = _workflow_transition_public(exc.details)
        raise FlowError(
            exc.code,
            exc.message,
            details=details if isinstance(details, dict) else {},
        ) from exc
    selected = _repo_by_selector(current, args.repo)
    repository_ids = tuple(
        sorted(
            (str(repo["id"]) for repo in selected),
            key=lambda item: item.encode("utf-8"),
        )
    )
    canonical_event = edge.get("canonical_event")
    if not isinstance(canonical_event, str):
        raise _v3_review_error(
            "REVIEW_EFFECT_CATALOG_MISMATCH",
            "review-snapshot action has no canonical event",
        )
    authorization = _manager_workflow_action_authorization_v1(
        current, event_type=canonical_event
    )
    execution_id = v3_review_execution_id(
        current,
        action="review-snapshot",
        request_binding={
            "repository_ids": list(repository_ids),
            "target": "REVIEWING",
            "request_nonce_sha256": (
                authorization.request_nonce_sha256
            ),
        },
    )
    plan = plan_v3_review_snapshot_effect(
        state_value=current,
        data_root=resolve_data_dir(args.data_dir),
        task_dir=task_dir,
        execution_id=execution_id,
        repository_ids=repository_ids,
    )
    result = _v3_review_run_transaction(
        args,
        task_dir,
        current,
        plan,
        authorization,
        edge,
        completion_edge,
        selector=None,
    )
    assert isinstance(result.state, dict)
    snapshot = _v3_review_thaw(plan.bindings["snapshot"])
    assert isinstance(snapshot, dict)
    return _result(
        "review-snapshot",
        result.state,
        snapshot=_review_snapshot_receipt(snapshot),
    )


def command_review_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_action_id="evidence.review-snapshot.record",
        short_v3_effect_boundary=True,
    ) as (task_dir, current):
        _assert_flow(current, "full", "review-snapshot")
        _assert_status(current, {"VERIFYING", "REVIEWING"}, "review-snapshot")
        if current.get("schema_version") == V3_TASK_SCHEMA_VERSION:
            return v3_review_snapshot_command_v1(
                args, task_dir, current
            )
        automatic_state_transition = (
            _uses_confirmation_contract(current)
            and current.get("status") == "VERIFYING"
        )
        if automatic_state_transition:
            _require_automatic_action(
                _flow(current),
                "review-snapshot",
                "VERIFYING",
                "REVIEWING",
            )
        _require_current_workspace_indexes(current)
        _require_workspace_ready(current)
        route_value = (current.get("route") or {}).get("value")
        plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        _require_current_plan_gate(current, plan_kind)
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        if len(selected) != len(state_value["repositories"]):
            raise FlowError("INCOMPLETE_REVIEW", "review-snapshot must include every configured repository")
        initial_fingerprints = {
            repo["id"]: _fingerprint_repo(_working_path(repo))
            for repo in selected
        }
        passing, reason = _latest_passing_test_is_current(
            current,
            fingerprints=initial_fingerprints,
        )
        if not passing:
            raise FlowError("CURRENT_TEST_REQUIRED", reason or "a current passing test is required")
        snapshot_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        snapshot_root = task_dir / "reviews" / snapshot_id
        try:
            repositories = [
                _write_review_repo(
                    snapshot_root,
                    repo,
                    task_dir=task_dir,
                    initial_fingerprint=initial_fingerprints[repo["id"]],
                )
                for repo in selected
            ]
            for repository in repositories:
                current_fingerprint = _fingerprint_repo(
                    Path(repository["working_path"])
                )
                recorded_fingerprint = repository.get(
                    "fingerprint"
                ) or {}
                if current_fingerprint.get(
                    "sha256"
                ) != recorded_fingerprint.get("sha256"):
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CHANGED",
                        (
                            "a repository changed after its section of the "
                            "multi-repository snapshot was captured"
                        ),
                        details={
                            "repository_id": repository[
                                "repository_id"
                            ],
                            "recorded_sha256": recorded_fingerprint.get(
                                "sha256"
                            ),
                            "current_sha256": current_fingerprint.get(
                                "sha256"
                            ),
                        },
                    )
            snapshot = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "snapshot_id": snapshot_id,
                "created_at": utc_now(),
                "repository_ids": [repo["id"] for repo in selected],
                "repositories": repositories,
            }
            manifest_path = snapshot_root / "manifest.json"
            _atomic_write_json(manifest_path, snapshot)
            snapshot["manifest_path"] = str(manifest_path)
            snapshot["manifest_path_identity"] = (
                _serializable_path_identity(manifest_path)
            )
            snapshot["sha256"] = _sha256_file(manifest_path)
            integrity_error = _review_snapshot_integrity_error(
                snapshot
            )
            if integrity_error:
                raise FlowError(
                    "REVIEW_SNAPSHOT_INVALID",
                    integrity_error,
                    details={"snapshot_id": snapshot_id},
                )
        except BaseException as exc:
            if snapshot_root.exists():
                try:
                    shutil.rmtree(snapshot_root)
                except OSError as cleanup_error:
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CLEANUP_FAILED",
                        (
                            "an incomplete review snapshot could not be "
                            "removed and was not recorded as usable"
                        ),
                        details={
                            "snapshot_root": str(snapshot_root),
                            "error": str(cleanup_error),
                            "cause": f"{type(exc).__name__}: {exc}",
                        },
                    ) from cleanup_error
            raise
        state_value["review_snapshots"].append(snapshot)
        state_value["artifacts"].append(
            {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "artifact_id": str(uuid.uuid4()),
                "kind": "review-snapshot",
                "path": str(manifest_path),
                "path_identity": _serializable_path_identity(manifest_path),
                "sha256": snapshot["sha256"],
                "size": manifest_path.stat().st_size,
                "recorded_at": utc_now(),
                "metadata": {
                    "snapshot_id": snapshot_id,
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "capability_profile_sha256": {
                        item["repository_id"]: item[
                            "capability_profile_sha256"
                        ]
                        for item in repositories
                    },
                },
            }
        )
        state_value["status"] = "REVIEWING"
        _commit_state(
            current,
            state_value,
            task_dir,
            "review_snapshot_recorded",
            {
                "snapshot_id": snapshot_id,
                "sha256": snapshot["sha256"],
                "repository_ids": snapshot["repository_ids"],
                "confirmation_mode": (
                    "automatic"
                    if automatic_state_transition
                    else (
                        "not-applicable"
                        if _uses_confirmation_contract(current)
                        else "legacy"
                    )
                ),
            },
            additional_events=(
                [
                    (
                        "state_transitioned",
                        {
                            "from": "VERIFYING",
                            "to": "REVIEWING",
                            "action": "review-snapshot",
                            "confirmation_mode": "automatic",
                        },
                    )
                ]
                if automatic_state_transition
                else None
            ),
        )
    return _result(
        "review-snapshot",
        state_value,
        snapshot=_review_snapshot_receipt(snapshot),
    )


def _snapshot_file_error(
    path_value: Any,
    expected_sha: Any,
    label: str,
    path_identity: Any = None,
) -> str | None:
    if not isinstance(path_value, str) or not path_value or not isinstance(expected_sha, str):
        return f"review snapshot has incomplete {label} integrity metadata"
    path = Path(path_value)
    if not _recorded_path_matches(path_identity, path_value, path):
        return f"review snapshot {label} path identity changed: {path}"
    if not path.is_file():
        return f"review snapshot {label} file is missing: {path}"
    try:
        current_sha = _sha256_file(path)
    except OSError as exc:
        return f"review snapshot {label} file is unreadable: {path}: {exc}"
    if current_sha != expected_sha:
        return f"review snapshot {label} file changed: {path}"
    return None


def _review_snapshot_integrity_error(snapshot: dict[str, Any]) -> str | None:
    try:
        _require_current_evidence(snapshot, "review snapshot")
    except FlowError as exc:
        return exc.message
    error = _snapshot_file_error(
        snapshot.get("manifest_path"),
        snapshot.get("sha256"),
        "manifest",
        snapshot.get("manifest_path_identity"),
    )
    if error:
        return error
    for repository in snapshot.get("repositories", []):
        repository_id = repository.get("repository_id", "unknown")
        try:
            _require_current_evidence(
                repository, f"review-repository:{repository_id}"
            )
            _load_recorded_fingerprint(
                repository.get("fingerprint"),
                f"review-fingerprint:{repository_id}",
            )
        except FlowError as exc:
            return exc.message
        sections = repository.get("sections") or {}
        for section_name in ("committed", "cached", "unstaged"):
            section = sections.get(section_name) or {}
            error = _snapshot_file_error(
                section.get("path"),
                section.get("sha256"),
                f"{repository_id}/{section_name}",
                section.get("path_identity"),
            )
            if error:
                return error
        untracked = sections.get("untracked") or {}
        error = _snapshot_file_error(
            untracked.get("manifest_path"),
            untracked.get("manifest_sha256"),
            f"{repository_id}/untracked-manifest",
            untracked.get("manifest_path_identity"),
        )
        if error:
            return error
        error = _snapshot_file_error(
            untracked.get("archive_path"),
            untracked.get("archive_sha256"),
            f"{repository_id}/untracked-archive",
            untracked.get("archive_path_identity"),
        )
        if error:
            return error
    return None


def _review_is_current(
    state_value: dict[str, Any],
    *,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, str | None]:
    snapshots = state_value.get("review_snapshots", [])
    if not snapshots:
        return False, "no review snapshot has been recorded"
    latest = snapshots[-1]
    integrity_error = _review_snapshot_integrity_error(latest)
    if integrity_error:
        return False, integrity_error
    by_id = {item["repository_id"]: item for item in latest.get("repositories", [])}
    for repo in state_value["repositories"]:
        workspace_error = _workspace_integrity_error(state_value, repo)
        if workspace_error:
            return False, workspace_error
        recorded = by_id.get(repo["id"])
        if not recorded:
            return False, f"review snapshot does not cover repository: {repo['id']}"
        current = (
            fingerprints[repo["id"]]
            if fingerprints is not None and repo["id"] in fingerprints
            else _fingerprint_repo(_working_path(repo))
        )
        if current.get("sha256") != (
            recorded.get("fingerprint") or {}
        ).get("sha256"):
            return False, f"repository changed after review snapshot: {repo['id']}"
        if current.get("capability_profile_sha256") != recorded.get(
            "capability_profile_sha256"
        ):
            return False, f"repository capability profile changed after review snapshot: {repo['id']}"
    return True, None


def _current_repository_fingerprints(
    state_value: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Observe each working repository once for equivalent currentness checks."""

    return {
        repo["id"]: _fingerprint_repo(_working_path(repo))
        for repo in state_value.get("repositories", [])
    }


TRANSITION_INTENT_NAMESPACE = "transition-intent-v1"


def _uses_confirmation_contract(state_value: dict[str, Any]) -> bool:
    return (
        int(state_value.get("schema_version", 1)) >= TASK_SCHEMA_VERSION
        and state_value.get("confirmation_contract_version")
        == CONFIRMATION_CONTRACT_VERSION
    )


def _transition_confirmation_mode(
    state_value: dict[str, Any],
    source: str,
    target: str,
    *,
    action: str = "transition",
) -> str:
    if not _uses_confirmation_contract(state_value):
        return "legacy"
    if target in TERMINAL_STATES:
        return "explicit"
    if (
        action == "transition"
        and (_flow(state_value), source, target)
        in AUTOMATIC_TRANSITION_EDGES
    ):
        return "automatic"
    return "explicit"


def _transition_side_effects(
    source: str, target: str, *, action: str
) -> list[str]:
    effects = ["task-state"]
    if target in TERMINAL_STATES:
        effects.append("irreversible-terminal-state")
    if target in {"PLANNING", "IMPLEMENTING", "INDEXED"} and source != target:
        effects.append("evidence-or-approval-invalidation")
    if target in TERMINAL_STATES or action == "cancel":
        effects.append("repository-claim-release")
    return effects


def _transition_intent_preview(
    state_value: dict[str, Any],
    source: str,
    target: str,
    *,
    action: str,
    action_parameters: dict[str, Any],
    live_risk_assessment: dict[str, Any] | None = None,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    observed: dict[str, dict[str, Any]] | None
    if fingerprints is not None:
        observed = fingerprints
    elif target == "CANCELLED":
        try:
            observed = _current_repository_fingerprints(state_value)
        except (FlowError, OSError):
            observed = None
    else:
        observed = _current_repository_fingerprints(state_value)
    compact_fingerprints: dict[str, Any]
    if observed is None:
        compact_fingerprints = {
            "status": "fingerprint-evidence-unavailable",
            "repository_ids": sorted(
                repo["id"]
                for repo in state_value.get("repositories", [])
            ),
        }
    else:
        compact_fingerprints = {
            repository_id: {
                "sha256": fingerprint.get("sha256"),
                "head_sha": fingerprint.get("head_sha"),
                "capability_profile_sha256": fingerprint.get(
                    "capability_profile_sha256"
                ),
            }
            for repository_id, fingerprint in observed.items()
        }
    latest_impact = _latest_artifact(state_value, "impact") or {}
    latest_impact_metadata = latest_impact.get("metadata") or {}
    evidence_projection = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "repository_fingerprints": compact_fingerprints,
        "impact_analysis_sha256": latest_impact_metadata.get(
            "impact_analysis_sha256"
        ),
        "route": state_value.get("route"),
        "approval_ids": {
            gate: approval.get("approval_id")
            for gate, approval in (state_value.get("approvals") or {}).items()
            if isinstance(approval, dict)
        },
        "latest_test_id": (
            (state_value.get("tests") or [{}])[-1].get("test_id")
        ),
        "latest_review_snapshot_id": (
            (state_value.get("review_snapshots") or [{}])[-1].get(
                "snapshot_id"
            )
        ),
        "risk_assessment_sha256": (
            live_risk_assessment.get("sha256")
            if isinstance(live_risk_assessment, dict)
            else (state_value.get("risk_assessment") or {}).get("sha256")
        ),
    }
    evidence_sha256 = _sha256_bytes(_json_bytes(evidence_projection))
    confirmation_mode = _transition_confirmation_mode(
        state_value, source, target, action=action
    )
    side_effects = _transition_side_effects(
        source, target, action=action
    )
    payload = {
        "task_id": state_value.get("task_id"),
        "base_revision": int(state_value.get("revision", 0)),
        "flow": _flow(state_value),
        "source_status": source,
        "target_status": target,
        "action": action,
        "action_parameters": action_parameters,
        "evidence_sha256": evidence_sha256,
        "side_effects": side_effects,
        "confirmation_mode": confirmation_mode,
    }
    digest = _sha256_bytes(
        (
            TRANSITION_INTENT_NAMESPACE
            + "\n"
        ).encode("utf-8")
        + _json_bytes(payload)
    )
    return {
        "intent_id": f"{TRANSITION_INTENT_NAMESPACE}:{digest}",
        "base_revision": payload["base_revision"],
        "from": source,
        "to": target,
        "action": action,
        "evidence_sha256": evidence_sha256,
        "side_effects": side_effects,
        "confirmation_mode": confirmation_mode,
        "requires_confirmation": confirmation_mode == "explicit",
    }


def _assert_confirmation_intent(
    preview: dict[str, Any], supplied: str | None
) -> None:
    expected = preview["intent_id"]
    if not isinstance(supplied, str) or not supplied:
        raise FlowError(
            "TRANSITION_INTENT_REQUIRED",
            "this state edge requires a preview and explicit confirmation",
            details={"preview": preview},
        )
    if not secrets.compare_digest(expected, supplied):
        raise FlowError(
            "INTENT_STALE",
            "the confirmed transition intent no longer matches live evidence",
            details={
                "received_intent_id": supplied,
                "current_preview": preview,
            },
        )


def _lite_transition_guard(
    state_value: dict[str, Any],
    target: str,
    *,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> None:
    repositories = state_value.get("repositories", [])
    if target == "PREFLIGHTED":
        if not all(
            (repo.get("preflight") or {}).get("ready")
            for repo in repositories
        ):
            raise FlowError(
                "PREFLIGHT_REQUIRED", "all repositories must pass preflight"
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("preflight"), f"preflight:{repo.get('id')}"
            )
    if target == "IMPLEMENTING":
        # Entering implementation from PREFLIGHTED must find the exact approved
        # checkouts untouched; re-entering from rework legitimately finds the
        # tree already edited, so only branch identity is revalidated there.
        _require_lite_gate(
            state_value,
            verify_worktree=state_value.get("status") == "PREFLIGHTED",
            fingerprints=fingerprints,
        )
    if target in {"VERIFYING", "DONE"}:
        _require_lite_gate(state_value, fingerprints=fingerprints)
    if target == "DONE":
        test_current, test_reason = _latest_passing_test_is_current(
            state_value, fingerprints=fingerprints
        )
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")


def _transition_guard(
    state_value: dict[str, Any],
    target: str,
    *,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> None:
    if _flow(state_value) == "lite":
        _lite_transition_guard(
            state_value, target, fingerprints=fingerprints
        )
        return
    repositories = state_value.get("repositories", [])
    if target == "PREFLIGHTED":
        if not all(
            (repo.get("preflight") or {}).get("ready")
            for repo in repositories
        ):
            raise FlowError(
                "PREFLIGHT_REQUIRED", "all repositories must pass preflight"
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("preflight"), f"preflight:{repo.get('id')}"
            )
    if target == "BASELINED":
        if not all(repo.get("baseline") for repo in repositories):
            raise FlowError(
                "BASELINE_REQUIRED",
                "all repositories must have a pinned baseline",
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("baseline"), f"baseline:{repo.get('id')}"
            )
    if target in {"INDEXED", "IMPACT_REVIEW"}:
        if not all(repo.get("index") for repo in repositories):
            raise FlowError(
                "INDEX_REQUIRED",
                "all repositories must have a recorded index",
            )
        _index_provenance_evidence(state_value)
    if target == "ROUTE_APPROVED":
        _require_route_gate(state_value)
    if target in {"PLANNING", "IMPLEMENTING", "VERIFYING"}:
        _require_current_workspace_indexes(state_value)
    if target in {"WORKSPACE_READY", "PLANNING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING", "DONE"}:
        _require_route_gate(state_value)
        _require_workspace_ready(state_value)
    if target in {"IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING", "DONE"}:
        route_value = (state_value.get("route") or {}).get("value")
        artifact_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        _require_current_plan_gate(state_value, artifact_kind)
    if target == "REVIEWING":
        current, reason = _review_is_current(state_value)
        if not current:
            raise FlowError("CURRENT_REVIEW_REQUIRED", reason or "a current review snapshot is required")
    if target in {"FINALIZING", "DONE"}:
        current_fingerprints = (
            fingerprints
            if fingerprints is not None
            else _current_repository_fingerprints(state_value)
        )
        review_current, review_reason = _review_is_current(
            state_value,
            fingerprints=current_fingerprints,
        )
        if not review_current:
            raise FlowError("CURRENT_REVIEW_REQUIRED", review_reason or "a current review snapshot is required")
        test_current, test_reason = _latest_passing_test_is_current(
            state_value,
            fingerprints=current_fingerprints,
        )
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")
        _require_review_gate(state_value)


def _v3_command_effect_at(state_value: dict[str, Any]) -> str:
    """Return a revision-bound timestamp stable across preview and apply."""

    value = state_value.get("updated_at") or state_value.get("created_at")
    if not isinstance(value, str) or not value:
        raise FlowError(
            "TASK_STATE_INVALID",
            "schema-v3 movement requires a revision-bound task timestamp",
        )
    return value


def _v3_transition_result(
    args: argparse.Namespace,
    task_dir: Path,
    current: dict[str, Any],
    target: str,
) -> dict[str, Any]:
    """Execute transition without touching legacy topology or invalidations."""

    source = current["status"]
    if source == target:
        return _result(
            "transition",
            current,
            unchanged=True,
            transition={"from": source, "to": target},
        )
    preview_only = bool(getattr(args, "preview", False))
    supplied_intent = getattr(args, "confirm_intent", None)
    action_id = (
        "transition-cancel"
        if target == "CANCELLED"
        else "transition"
    )
    event_type = "state_transitioned"
    effective_target = target
    parameters: dict[str, Any] = {
        "from": source,
        "to": target,
        "note": args.note,
    }
    state_records: dict[str, Any] = {}
    if target == "BLOCKED":
        state_records["blocked"] = {
            "phase": "manual",
            "from_status": source,
            "reason": args.note,
            "details": [],
            "at": _v3_command_effect_at(current),
        }
    if target == "CANCELLED":
        state_records["cancelled"] = {
            "reason": args.note,
            "at": _v3_command_effect_at(current),
            "by": _actor(),
            "from_status": source,
        }

    live_risk_assessment: dict[str, Any] | None = None
    if (
        _flow(current) == "lite"
        and target in {"VERIFYING", "DONE"}
    ):
        live_risk_assessment, _fingerprints = (
            _capture_lite_change_assessment(current, args.data_dir)
        )
        parameters["risk_assessment_sha256"] = (
            live_risk_assessment["sha256"]
        )
        if live_risk_assessment["decision"] != "safe":
            effective_target = "BLOCKED"
            action_id = f"lite-risk-{target.lower()}"
            event_type = "lite_risk_escalation_required"
            parameters.update(
                {
                    "attempted_target": target,
                    "required_flow": "full",
                }
            )
            state_records["blocked"] = {
                "phase": "lite-risk",
                "from_status": source,
                "required_flow": "full",
                "reason": (
                    "live change risk requires replacement with full flow"
                ),
                "details": live_risk_assessment["reasons"],
                "assessment": live_risk_assessment,
                "at": _v3_command_effect_at(current),
            }
    try:
        evaluation = v3_command_movement_evaluate_v1(
            current,
            target=effective_target,
            event_type=event_type,
            action_id=action_id,
            action_parameters=parameters,
            state_records=state_records,
            confirm_intent=supplied_intent,
            preview=preview_only,
        )
        preview = v3_command_movement_preview_v1(evaluation)
        if preview_only:
            return _result(
                "transition",
                current,
                preview=preview,
                transition_applied=False,
                required_flow=(
                    "full"
                    if effective_target == "BLOCKED"
                    and target != "BLOCKED"
                    else None
                ),
                assessment=live_risk_assessment,
                transition={
                    "from": source,
                    "to": effective_target,
                    "attempted_to": target,
                },
            )
        confirmation = {
            "intent_id": preview["intent_id"],
            "confirmation_mode": preview["confirmation_mode"],
            "evidence_sha256": preview["evidence_sha256"],
        }
        payload = {
            "from": source,
            "to": effective_target,
            "note": args.note,
            "action": action_id,
            **confirmation,
        }
        if event_type == "lite_risk_escalation_required":
            payload.update(
                {
                    "attempted_target": target,
                    "required_flow": "full",
                    "assessment_sha256": (
                        live_risk_assessment or {}
                    ).get("sha256"),
                }
            )
        state_value = v3_command_movement_commit_v1(
            current,
            evaluation,
            task_dir,
            event_type,
            payload,
            additional_events=(
                (
                    (
                        "state_transitioned",
                        {
                            "from": source,
                            "to": effective_target,
                            "reason": "lite-risk",
                            "required_flow": "full",
                            **confirmation,
                        },
                    ),
                )
                if event_type == "lite_risk_escalation_required"
                else ()
            ),
        )
    except FlowError:
        raise
    return _result(
        "transition",
        state_value,
        transition_applied=effective_target == target,
        required_flow=(
            "full"
            if effective_target == "BLOCKED" and target != "BLOCKED"
            else None
        ),
        assessment=live_risk_assessment,
        transition={
            "from": source,
            "to": effective_target,
            "attempted_to": target,
            "note": args.note,
            **confirmation,
        },
    )


def command_transition(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    target = args.to_option or args.to
    preview_only = bool(getattr(args, "preview", False))
    supplied_intent = getattr(args, "confirm_intent", None)
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_effect_policy=(
            "preview" if preview_only else "generic"
        ),
        manager_action_id="task.transition",
    ) as (task_dir, current):
        if current.get("schema_version") == V3_TASK_SCHEMA_VERSION:
            return _v3_transition_result(
                args, task_dir, current, target
            )
        if target not in ALL_STATES:
            raise FlowError(
                "INVALID_ARGUMENT",
                f"unknown target state: {target}",
                details={"allowed": sorted(ALL_STATES)},
            )
        source = current["status"]
        if source == target:
            return _result("transition", current, unchanged=True, transition={"from": source, "to": target})
        if source in TERMINAL_STATES:
            raise FlowError("INVALID_TRANSITION", f"terminal task cannot transition from {source}")
        if (
            target == "PREFLIGHTED"
            and (
                source == "INTAKE"
                or (
                    source == "BLOCKED"
                    and (current.get("blocked") or {}).get("phase")
                    == "preflight"
                )
            )
        ):
            raise FlowError(
                "PREFLIGHT_CONFIRMATION_REQUIRED",
                (
                    "initial and preflight-blocked transitions to "
                    "PREFLIGHTED require an all-repository "
                    "preflight --preview/--confirm-preview pair"
                ),
                details={"from": source, "to": target},
            )
        if target == "CANCELLED":
            if not args.note:
                raise FlowError("INVALID_ARGUMENT", "transition to CANCELLED requires --note; cancel is preferred")
        elif target == "BLOCKED":
            if not args.note:
                raise FlowError("INVALID_ARGUMENT", "transition to BLOCKED requires --note")
        elif source == "BLOCKED":
            if (current.get("blocked") or {}).get("phase") == "lite-risk":
                raise FlowError(
                    "LITE_REPLACEMENT_REQUIRED",
                    (
                        "a lite task blocked by live risk cannot resume; "
                        "cancel it and start a full-flow replacement"
                    ),
                    details={
                        "required_flow": "full",
                        "allowed": ["CANCELLED"],
                    },
                )
            expected = (current.get("blocked") or {}).get("from_status")
            if target != expected:
                raise FlowError("INVALID_TRANSITION", f"blocked task can only resume to {expected}", details={"from": source, "to": target, "allowed": [expected]})
        else:
            lite = _flow(current) == "lite"
            forward_edges = LITE_FORWARD_EDGES if lite else FORWARD_EDGES
            rework_edges = LITE_REWORK_EDGES if lite else REWORK_EDGES
            allowed = set(forward_edges.get(source, set())) | set(rework_edges.get(source, set()))
            if target not in allowed:
                raise FlowError("INVALID_TRANSITION", f"transition {source} -> {target} is not allowed", details={"from": source, "to": target, "allowed": sorted(allowed | {"BLOCKED", "CANCELLED"})})
            if (
                target == "PLANNING"
                and source in {"IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING"}
                and not args.note
            ):
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "replanning requires --note",
                    details={"from": source, "to": target},
                )
            if target == "INDEXED" and source in IMPACT_REASSESS_SOURCES and not args.note:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "impact reassessment requires --note",
                    details={"from": source, "to": target},
                )
            if (
                lite
                and target == "PREFLIGHTED"
                and source in {"IMPLEMENTING", "VERIFYING"}
                and not args.note
            ):
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "reopening lite scope evidence requires --note",
                    details={"from": source, "to": target},
                )
        live_risk_assessment: dict[str, Any] | None = None
        transition_fingerprints: dict[str, dict[str, Any]] | None = None
        if (
            _uses_confirmation_contract(current)
            and _flow(current) == "lite"
            and target in {"VERIFYING", "DONE"}
        ):
            (
                live_risk_assessment,
                transition_fingerprints,
            ) = _capture_lite_change_assessment(
                current, args.data_dir
            )
            if live_risk_assessment["decision"] != "safe":
                if preview_only:
                    return _result(
                        "transition",
                        current,
                        transition_applied=False,
                        required_flow="full",
                        assessment=live_risk_assessment,
                        transition={"from": source, "to": target},
                    )
                state_value = _copy_state(current)
                state_value["status"] = "BLOCKED"
                state_value["blocked"] = {
                    "phase": "lite-risk",
                    "from_status": source,
                    "required_flow": "full",
                    "reason": (
                        "live change risk requires replacement with full flow"
                    ),
                    "details": live_risk_assessment["reasons"],
                    "assessment": live_risk_assessment,
                    "at": utc_now(),
                }
                risk_payload = {
                    "from": source,
                    "attempted_target": target,
                    "required_flow": "full",
                    "assessment_sha256": live_risk_assessment["sha256"],
                }
                _commit_state(
                    current,
                    state_value,
                    task_dir,
                    "lite_risk_escalation_required",
                    risk_payload,
                    additional_events=[
                        (
                            "state_transitioned",
                            {
                                "from": source,
                                "to": "BLOCKED",
                                "reason": "lite-risk",
                                "required_flow": "full",
                            },
                        )
                    ],
                )
                return _result(
                    "transition",
                    state_value,
                    transition_applied=False,
                    required_flow="full",
                    assessment=live_risk_assessment,
                    transition={"from": source, "to": target},
                )
        confirmation_mode = _transition_confirmation_mode(
            current, source, target, action="transition"
        )
        if (
            _uses_confirmation_contract(current)
            and transition_fingerprints is None
            and target != "CANCELLED"
            and (
                confirmation_mode == "explicit"
                or preview_only
                or supplied_intent is not None
            )
        ):
            transition_fingerprints = (
                _current_repository_fingerprints(current)
            )
        _transition_guard(
            current, target, fingerprints=transition_fingerprints
        )
        intent_preview: dict[str, Any] | None = None
        if _uses_confirmation_contract(current):
            if (
                confirmation_mode == "explicit"
                or preview_only
                or supplied_intent is not None
            ):
                intent_preview = _transition_intent_preview(
                    current,
                    source,
                    target,
                    action="transition",
                    action_parameters={"note": args.note},
                    live_risk_assessment=live_risk_assessment,
                    fingerprints=transition_fingerprints,
                )
                if preview_only:
                    return _result(
                        "transition",
                        current,
                        preview=intent_preview,
                        transition={"from": source, "to": target},
                    )
            if (
                intent_preview is not None
                and intent_preview["requires_confirmation"]
            ):
                _assert_confirmation_intent(
                    intent_preview, supplied_intent
                )
            elif (
                intent_preview is not None
                and supplied_intent is not None
            ):
                _assert_confirmation_intent(
                    intent_preview, supplied_intent
                )
        elif preview_only or supplied_intent is not None:
            raise FlowError(
                "CONFIRMATION_CONTRACT_UNAVAILABLE",
                "schema-v1 tasks keep their legacy direct-transition behavior",
                details={"schema_version": current.get("schema_version")},
            )
        state_value = _copy_state(current)
        state_value["status"] = target
        if target == "PLANNING" and source != "BLOCKED":
            state_value["planning_generation"] = int(
                current.get("planning_generation", 0)
            ) + 1
        if target == "BLOCKED":
            state_value["blocked"] = {"phase": "manual", "from_status": source, "reason": args.note, "details": [], "at": utc_now()}
        elif source == "BLOCKED":
            state_value["blocked"] = None
        if target == "CANCELLED":
            state_value["cancelled"] = {"reason": args.note, "at": utc_now(), "by": _actor()}
        if target == "IMPLEMENTING" and source in {"VERIFYING", "REVIEWING", "FINALIZING"}:
            state_value["review_snapshots"] = []
            state_value["approvals"].pop("review", None)
        if target == "PLANNING" and source != "BLOCKED":
            state_value["review_snapshots"] = []
            state_value["approvals"].pop("plan", None)
            state_value["approvals"].pop("review", None)
        if target == "INDEXED" and source in IMPACT_REASSESS_SOURCES:
            state_value["impact_generation"] = int(
                current.get("impact_generation", 0)
            ) + 1
            state_value["route"] = None
            for gate in ("route", "workspace", "plan", "review"):
                state_value["approvals"].pop(gate, None)
            state_value["review_snapshots"] = []
            reassessed_at = utc_now()
            for repo in state_value.get("repositories", []):
                previous_workspace = repo.get("workspace")
                if previous_workspace:
                    history = repo.setdefault("workspace_history", [])
                    history.append(
                        {
                            **previous_workspace,
                            "workspace_index": repo.get("workspace_index"),
                            "retired_at": reassessed_at,
                            "retired_reason": args.note,
                        }
                    )
                repo["workspace"] = None
                repo["workspace_index"] = None
            previous_generation = int(
                (state_value.get("workspace") or {}).get("generation", 0)
            )
            state_value["workspace"] = {
                "strategy": "worktree",
                "ready": False,
                "generation": previous_generation + 1,
                "plan": None,
                "reassessed_at": reassessed_at,
            }
        confirmation = (
            {
                "intent_id": intent_preview["intent_id"],
                "confirmation_mode": intent_preview[
                    "confirmation_mode"
                ],
                "evidence_sha256": intent_preview["evidence_sha256"],
            }
            if intent_preview is not None
            else {"confirmation_mode": confirmation_mode}
        )
        _commit_state(
            current,
            state_value,
            task_dir,
            "state_transitioned",
            {
                "from": source,
                "to": target,
                "note": args.note,
                **confirmation,
            },
        )
    return _result(
        "transition",
        state_value,
        transition={
            "from": source,
            "to": target,
            "note": args.note,
            **confirmation,
        },
    )


def _v3_cancel_result(
    args: argparse.Namespace,
    task_dir: Path,
    current: dict[str, Any],
) -> dict[str, Any]:
    """Execute cancel as one pinned action edge plus one atomic event batch."""

    if current.get("status") == "CANCELLED":
        return _result(
            "cancel",
            current,
            unchanged=True,
            cancelled=current.get("cancelled"),
        )
    source = current["status"]
    preview_only = bool(getattr(args, "preview", False))
    supplied_intent = getattr(args, "confirm_intent", None)
    cancelled = {
        "reason": args.reason,
        "at": _v3_command_effect_at(current),
        "by": _actor(),
        "from_status": source,
    }
    parameters = {
        "from": source,
        "to": "CANCELLED",
        "reason": args.reason,
        "note": args.reason,
    }
    try:
        evaluation = v3_command_movement_evaluate_v1(
            current,
            target="CANCELLED",
            event_type="task_cancelled",
            action_id="cancel",
            action_parameters=parameters,
            state_records={"cancelled": cancelled},
            confirm_intent=supplied_intent,
            preview=preview_only,
        )
        preview = v3_command_movement_preview_v1(evaluation)
        if preview_only:
            return _result(
                "cancel",
                current,
                preview=preview,
                cancelled=None,
            )
        confirmation = {
            "intent_id": preview["intent_id"],
            "confirmation_mode": preview["confirmation_mode"],
            "evidence_sha256": preview["evidence_sha256"],
        }
        state_value = v3_command_movement_commit_v1(
            current,
            evaluation,
            task_dir,
            "task_cancelled",
            {
                "from": source,
                "reason": args.reason,
                **confirmation,
            },
            additional_events=(
                (
                    "state_transitioned",
                    {
                        "from": source,
                        "to": "CANCELLED",
                        **confirmation,
                    },
                ),
            ),
        )
    except FlowError:
        raise
    return _result(
        "cancel",
        state_value,
        cancelled=state_value["cancelled"],
        confirmation=confirmation,
    )


def command_cancel(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    preview_only = bool(getattr(args, "preview", False))
    supplied_intent = getattr(args, "confirm_intent", None)
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_effect_policy=(
            "preview" if preview_only else "generic"
        ),
        manager_action_id="task.cancel",
    ) as (task_dir, current):
        if current.get("schema_version") == V3_TASK_SCHEMA_VERSION:
            return _v3_cancel_result(args, task_dir, current)
        if current.get("status") == "CANCELLED":
            return _result("cancel", current, unchanged=True, cancelled=current.get("cancelled"))
        if current.get("status") == "DONE":
            raise FlowError("INVALID_STATE", "completed task cannot be cancelled")
        source = current["status"]
        intent_preview: dict[str, Any] | None = None
        if _uses_confirmation_contract(current):
            intent_preview = _transition_intent_preview(
                current,
                source,
                "CANCELLED",
                action="cancel",
                action_parameters={"reason": args.reason},
            )
            if preview_only:
                return _result(
                    "cancel",
                    current,
                    preview=intent_preview,
                    cancelled=None,
                )
            _assert_confirmation_intent(intent_preview, supplied_intent)
        elif preview_only or supplied_intent is not None:
            raise FlowError(
                "CONFIRMATION_CONTRACT_UNAVAILABLE",
                "schema-v1 tasks keep their legacy direct-cancel behavior",
                details={"schema_version": current.get("schema_version")},
            )
        state_value = _copy_state(current)
        state_value["status"] = "CANCELLED"
        state_value["cancelled"] = {"reason": args.reason, "at": utc_now(), "by": _actor(), "from_status": source}
        confirmation = (
            {
                "intent_id": intent_preview["intent_id"],
                "confirmation_mode": "explicit",
                "evidence_sha256": intent_preview["evidence_sha256"],
            }
            if intent_preview is not None
            else {"confirmation_mode": "legacy"}
        )
        _commit_state(
            current,
            state_value,
            task_dir,
            "task_cancelled",
            {"from": source, "reason": args.reason, **confirmation},
            additional_events=(
                [
                    (
                        "state_transitioned",
                        {
                            "from": source,
                            "to": "CANCELLED",
                            **confirmation,
                        },
                    )
                ]
                if intent_preview is not None
                else None
            ),
        )
    return _result(
        "cancel",
        state_value,
        cancelled=state_value["cancelled"],
        confirmation=confirmation,
    )
