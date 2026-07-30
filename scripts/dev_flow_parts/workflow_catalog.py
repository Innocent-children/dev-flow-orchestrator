# Loaded by scripts/dev_flow.py into its shared module namespace after the
# bundle identity and registry fragments.  Keep this standard-library only.
from __future__ import annotations

import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


WORKFLOW_SCHEMA = "dev-flow-workflow/v1"
CATALOG_SCHEMA = "dev-flow-workflow-catalog/v1"
ACTIVATION_SCHEMA = "dev-flow-workflow-activation/v1"
BUNDLE_IDENTITY_CONTRACT = "dev-flow-bundle-identity/v1"
SUPPORTED_BUNDLE_SCHEMA_VERSIONS = frozenset({1})
SUPPORTED_CONTRACT_REGISTRIES = frozenset(
    {"executors", "gates", "guards", "reducers"}
)
SUPPORTED_EDGE_CLASSES = frozenset(
    {"block", "cancel", "forward", "resume", "retry", "rework"}
)
SUPPORTED_CONFIRMATION_MODES = frozenset(
    {
        "action-explicit",
        "automatic",
        "explicit",
        "legacy",
        "preflight-preview",
        "safety-block",
    }
)
SUPPORTED_INDEX_ROLES = frozenset({"baseline", "origin", "workspace"})
SUPPORTED_EXECUTION_PROFILES = frozenset(
    {"multi-repository", "single-repository"}
)
SUPPORTED_SECTIONS = frozenset(
    {
        "approvals",
        "artifacts",
        "blocked",
        "cancelled",
        "index-selection",
        "repositories",
        "review-snapshots",
        "risk",
        "route",
        "summary",
        "tests",
        "workflow",
        "workspace",
    }
)
_workflow_catalog_supported_node_contracts = MappingProxyType(
    {
        "generic": frozenset({"v1"}),
        "state": frozenset({"v1"}),
    }
)
_workflow_catalog_supported_node_context_profiles = frozenset({"legacy-v1", "node-v1"})
_workflow_catalog_supported_node_approval_modes = frozenset(
    {"edge-policy", "kernel-gate", "legacy", "none"}
)
_workflow_catalog_supported_node_effect_classifications = frozenset(
    {
        "approval",
        "barrier",
        "controller",
        "external-read",
        "external-write",
        "none",
        "read-only",
        "repository-write",
    }
)
_workflow_catalog_supported_node_effects = frozenset(
    {
        "approval-request",
        "barrier-evaluation",
        "controller-transition",
        "external-read",
        "external-write",
        "legacy-adapter",
        "repository-write",
        "runtime-dispatch",
    }
)
_workflow_catalog_supported_executor_effect_classifications = MappingProxyType(
    {
        "executor.barrier/v1": frozenset({"barrier"}),
        "executor.codex-exec/v1": frozenset(
            {"external-read", "repository-write"}
        ),
        "executor.codex-thread/v1": frozenset({"repository-write"}),
        "executor.deterministic/v1": frozenset(
            {"controller", "none", "read-only"}
        ),
        "executor.external-tool/v1": frozenset(
            {"external-read", "external-write"}
        ),
        "executor.human-gate/v1": frozenset({"approval"}),
        "executor.native-subagents/v1": frozenset({"repository-write"}),
    }
)
_workflow_catalog_supported_node_retry_modes = frozenset({"bounded", "manual", "never"})
_workflow_catalog_supported_node_retry_backoffs = frozenset({"fixed", "none"})
_workflow_catalog_supported_node_retry_reasons = frozenset(
    {"executor-failure", "operator-authorized", "transient-unavailable"}
)
_workflow_catalog_supported_node_recovery_modes = frozenset(
    {"legacy", "manual", "reconcile", "restart"}
)
_workflow_catalog_supported_node_uncertain_outcomes = frozenset({"block", "quarantine"})
_workflow_catalog_supported_edge_effects = frozenset(
    {
        "approval",
        "evidence-or-approval-invalidation",
        "external-index-record",
        "git-baseline",
        "git-worktree",
        "irreversible-terminal-state",
        "repository-claim-release",
        "repository-evidence",
        "review-snapshot",
        "risk-escalation",
        "runtime-dispatch",
        "secret-publication",
        "task-state",
        "workspace-retirement",
    }
)
_workflow_catalog_supported_kernel_effects = frozenset(
    {
        "invalidate-approval",
        "invalidate-evidence",
        "record-approval",
        "record-artifact",
        "record-cancellation",
        "record-index",
        "record-manager-capability",
        "record-repository-state",
        "record-review-snapshot",
        "record-route",
        "record-test",
        "record-workspace-ownership",
        "release-repository-claim",
        "retire-workspace-ownership",
        "set-task-status",
    }
)

_workflow_catalog_id_re = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_workflow_catalog_contract_id_re = re.compile(
    r"^[a-z][a-z0-9._-]*(?:/[a-z][a-z0-9._-]*)*$"
)
_workflow_catalog_contract_version_re = re.compile(r"^v[1-9][0-9]*$")
_workflow_catalog_sha256_re = re.compile(r"^[0-9a-f]{64}$")
_workflow_catalog_json_pointer_re = re.compile(r"^(?:/(?:[^~/]|~[01])*)*$")
_workflow_catalog_schema_id_re = re.compile(
    r"^[a-z][a-z0-9._-]*(?:/[a-z][a-z0-9._-]*)*/v[1-9][0-9]*$"
)
_workflow_catalog_operation_id_re = re.compile(
    r"^[a-z][a-z0-9.-]*(?:/[a-z][a-z0-9.-]*)*/v[1-9][0-9]*$"
)
_workflow_catalog_versioned_action_id_re = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*\.v[1-9][0-9]*$"
)
_workflow_catalog_glob_characters = frozenset("*?[]")
_workflow_catalog_signed_int64_min = -(2**63)
_workflow_catalog_signed_int64_max = 2**63 - 1
_workflow_catalog_forbidden_executable_fields = frozenset(
    {
        "code",
        "command",
        "condition",
        "eval",
        "expression",
        "module",
        "module_path",
        "python",
        "script",
        "shell",
    }
)
_workflow_catalog_protected_state_roots = frozenset(
    {
        "/approvals",
        "/artifacts",
        "/evidence",
        "/evidence_records",
        "/locks",
        "/mutation_intent",
        "/node_instances",
        "/outbox",
        "/pending_outbox",
        "/quarantine",
        "/repositories",
        "/revision",
        "/review_snapshots",
        "/task_id",
        "/workflow_ref",
        "/workspace",
    }
)

_workflow_catalog_catalog_fields = frozenset(
    {"activation", "bundles", "identity_contract", "schema"}
)
_workflow_catalog_catalog_entry_fields = frozenset(
    {
        "bundle_schema_version",
        "bundle_sha256",
        "files",
        "graph",
        "graph_sha256",
        "root",
        "workflow_id",
        "workflow_version",
    }
)
_workflow_catalog_file_fields = frozenset({"kind", "path"})
_workflow_catalog_activation_fields = frozenset({"profiles", "schema"})
_workflow_catalog_activation_profile_fields = frozenset(
    {
        "active",
        "bundle_sha256",
        "execution_profile",
        "required_suites",
        "workflow_id",
        "workflow_version",
    }
)
_workflow_catalog_workflow_fields = frozenset(
    {
        "bundle_schema_version",
        "contracts",
        "edge_families",
        "edge_policies",
        "edges",
        "entry_nodes",
        "execution_profiles",
        "flow",
        "identity_contract",
        "labels",
        "legacy_adapter",
        "nodes",
        "ordered_nodes",
        "projection",
        "schema",
        "schemas",
        "task_schema_versions",
        "terminal_nodes",
        "workflow_id",
        "workflow_version",
    }
)
_workflow_catalog_workflow_optional_fields = frozenset(
    {
        "repository_orchestration",
        "shared_actions",
        "tool_capabilities",
    }
)
_workflow_catalog_tool_capability_fields = frozenset(
    {
        "schema",
        "capability_id",
        "tool_id",
        "operations",
        "result_schema",
        "scopes",
    }
)
_workflow_catalog_tool_capability_schema = (
    "dev-flow-external-tool-capability/v1"
)
_workflow_catalog_tool_operations = frozenset(
    {"external-read", "external-write"}
)
_workflow_catalog_repository_orchestration_fields = frozenset(
    {
        "action_nodes",
        "schema",
        "execution_profile",
        "map",
        "join",
        "legacy_aliases",
        "operation_matrix",
        "operation_ids",
    }
)
_workflow_catalog_repository_map_fields = frozenset(
    {"operation_id", "parent_node_id", "child_template"}
)
_workflow_catalog_repository_child_template_fields = frozenset(
    {"template_id", "node_id"}
)
_workflow_catalog_repository_join_fields = frozenset(
    {"operation_id", "node_id", "barrier_policy"}
)
_workflow_catalog_repository_barrier_policy_fields = frozenset(
    {"id", "required_outcomes"}
)
_workflow_catalog_repository_operation_contract_fields = frozenset(
    {
        "action_id",
        "effect_ids",
        "event_id",
        "operation_id",
        "validator_id",
        "write_set_id",
    }
)
_workflow_catalog_repository_legacy_alias_fields = frozenset(
    {"alias_id", "operation_ids"}
)
_workflow_catalog_repository_orchestration_schema = (
    "dev-flow-repository-orchestration/v1"
)
_workflow_catalog_repository_required_operation_ids = frozenset(
    {
        "manager.capability.authorize/v1",
        "manager.capability.revoke/v1",
        "orchestration.artifact.record/v1",
        "orchestration.assignment.issue/v1",
        "orchestration.attempt.abandon/v1",
        "orchestration.barrier.close/v1",
        "orchestration.barrier.reopen/v1",
        "orchestration.cancellation.request/v1",
        "orchestration.dispatch.handoff/v1",
        "orchestration.finalization.commit/v1",
        "orchestration.frontier.advance/v1",
        "orchestration.integration.capture/v1",
        "orchestration.integration.verify/v1",
        "orchestration.lease.expire/v1",
        "orchestration.lease.issue/v1",
        "orchestration.lease.revoke/v1",
        "orchestration.map.expand/v1",
        "orchestration.map.invalidate/v1",
        "orchestration.plan.approve/v1",
        "orchestration.plan.record/v1",
        "orchestration.reconciliation.begin/v1",
        "orchestration.reconciliation.complete/v1",
        "orchestration.result.accept/v1",
        "orchestration.result.invalidate/v1",
        "orchestration.retry.request/v1",
        "orchestration.review.record/v1",
        "orchestration.runtime-stop.record/v1",
        "orchestration.runtime.recovery.observe/v1",
        "orchestration.timeout.record/v1",
    }
)
_workflow_catalog_repository_legacy_alias_targets = MappingProxyType(
    {
        "orchestration.barrier.evaluate/v1": (
            "orchestration.barrier.close/v1",
        ),
        "orchestration.plan.expand/v1": (
            "orchestration.map.expand/v1",
        ),
        "orchestration.runtime.recover/v1": (
            "orchestration.attempt.abandon/v1",
            "orchestration.runtime.recovery.observe/v1",
        ),
        "orchestration.worker.assign/v1": (
            "orchestration.assignment.issue/v1",
            "orchestration.dispatch.handoff/v1",
            "orchestration.frontier.advance/v1",
            "orchestration.lease.issue/v1",
        ),
        "worker-result.submit/v1": (
            "orchestration.result.accept/v1",
        ),
    }
)
_workflow_catalog_repository_operation_write_sets = MappingProxyType(
    {
        "manager.capability.authorize/v1": (
            "/orchestration",
        ),
        "manager.capability.revoke/v1": (
            "/orchestration",
        ),
        "orchestration.artifact.record/v1": (
            "/orchestration/artifacts",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.assignment.issue/v1": (
            "/orchestration/assignments",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.attempt.abandon/v1": (
            "/node_instances",
            "/orchestration/attempts",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.barrier.close/v1": (
            "/orchestration/barriers",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.barrier.reopen/v1": (
            "/orchestration/barriers",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.cancellation.request/v1": (
            "/orchestration/cancellation",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.dispatch.handoff/v1": (
            "/node_instances",
            "/orchestration/dispatch",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.finalization.commit/v1": (
            "/orchestration/finalization",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.frontier.advance/v1": (
            "/node_instances",
            "/orchestration/frontier",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.integration.capture/v1": (
            "/orchestration/artifacts",
            "/orchestration/integration",
            "/orchestration/integration_verification",
            "/orchestration/manager_capabilities",
            "/orchestration/review",
        ),
        "orchestration.integration.verify/v1": (
            "/orchestration/integration",
            "/orchestration/integration_verification",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.lease.expire/v1": (
            "/orchestration/dispatch",
            "/orchestration/leases",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.lease.issue/v1": (
            "/orchestration/leases",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.lease.revoke/v1": (
            "/orchestration/leases",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.map.expand/v1": (
            "/node_instances",
            "/orchestration/expansion",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.map.invalidate/v1": (
            "/node_instances",
            "/orchestration/approval",
            "/orchestration/expansion",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.plan.approve/v1": (
            "/orchestration/approval",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.plan.record/v1": (
            "/orchestration/approval",
            "/orchestration/artifacts",
            "/orchestration/manager_capabilities",
            "/orchestration/plan",
            "/orchestration/plan_history",
        ),
        "orchestration.reconciliation.begin/v1": (
            "/orchestration/manager_capabilities",
            "/orchestration/reconciliation_probes",
        ),
        "orchestration.reconciliation.complete/v1": (
            "/orchestration/accepted_results",
            "/orchestration/cancellation",
            "/orchestration/dispatch",
            "/orchestration/leases",
            "/orchestration/manager_capabilities",
            "/orchestration/quiescence_proofs",
            "/orchestration/reconciliation_probes",
        ),
        "orchestration.result.accept/v1": (
            "/orchestration/accepted_results",
            "/orchestration/current_results",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.result.invalidate/v1": (
            "/orchestration/accepted_results",
            "/orchestration/current_results",
            "/orchestration/integration",
            "/orchestration/integration_verification",
            "/orchestration/manager_capabilities",
            "/orchestration/review",
        ),
        "orchestration.retry.request/v1": (
            "/node_instances",
            "/orchestration/manager_capabilities",
            "/orchestration/retries",
        ),
        "orchestration.review.record/v1": (
            "/orchestration/manager_capabilities",
            "/orchestration/review",
        ),
        "orchestration.runtime-stop.record/v1": (
            "/orchestration/accepted_results",
            "/orchestration/cancellation",
            "/orchestration/dispatch",
            "/orchestration/leases",
            "/orchestration/manager_capabilities",
            "/orchestration/quiescence_proofs",
        ),
        "orchestration.runtime.recovery.observe/v1": (
            "/orchestration/dispatch",
            "/orchestration/leases",
            "/orchestration/manager_capabilities",
        ),
        "orchestration.timeout.record/v1": (
            "/orchestration/manager_capabilities",
            "/orchestration/timeouts",
        ),
    }
)
_workflow_catalog_repository_manager_canonical_events = MappingProxyType(
    {
        "manager.capability.authorize/v1": (
            "manager_capability_authorized"
        ),
        "manager.capability.revoke/v1": "manager_capability_revoked",
    }
)
_workflow_catalog_repository_scoped_operation_ids = frozenset(
    {
        "orchestration.artifact.record/v1",
        "orchestration.assignment.issue/v1",
        "orchestration.attempt.abandon/v1",
        "orchestration.dispatch.handoff/v1",
        "orchestration.frontier.advance/v1",
        "orchestration.lease.expire/v1",
        "orchestration.lease.issue/v1",
        "orchestration.lease.revoke/v1",
        "orchestration.reconciliation.begin/v1",
        "orchestration.reconciliation.complete/v1",
        "orchestration.result.accept/v1",
        "orchestration.retry.request/v1",
        "orchestration.runtime-stop.record/v1",
        "orchestration.runtime.recovery.observe/v1",
        "orchestration.timeout.record/v1",
    }
)
_workflow_catalog_repository_lease_scoped_operation_ids = frozenset(
    {
        "orchestration.attempt.abandon/v1",
        "orchestration.lease.expire/v1",
        "orchestration.lease.issue/v1",
        "orchestration.lease.revoke/v1",
        "orchestration.reconciliation.begin/v1",
        "orchestration.reconciliation.complete/v1",
        "orchestration.runtime-stop.record/v1",
        "orchestration.runtime.recovery.observe/v1",
        "orchestration.timeout.record/v1",
    }
)
_workflow_catalog_repository_dispatch_operation_ids = frozenset(
    {
        "manager.capability.authorize/v1",
        "orchestration.artifact.record/v1",
        "orchestration.attempt.abandon/v1",
        "orchestration.dispatch.handoff/v1",
        "orchestration.integration.capture/v1",
        "orchestration.plan.record/v1",
        "orchestration.reconciliation.complete/v1",
        "orchestration.result.accept/v1",
        "orchestration.runtime-stop.record/v1",
    }
)
_workflow_catalog_repository_barrier_operation_ids = frozenset(
    {
        "orchestration.barrier.close/v1",
        "orchestration.barrier.reopen/v1",
    }
)
_workflow_catalog_repository_evidence_operation_ids = frozenset(
    {
        "orchestration.artifact.record/v1",
        "orchestration.attempt.abandon/v1",
        "orchestration.integration.capture/v1",
        "orchestration.plan.record/v1",
        "orchestration.reconciliation.complete/v1",
        "orchestration.result.accept/v1",
    }
)
_workflow_catalog_repository_terminal_outcomes = frozenset(
    {"SUCCEEDED"}
)
_workflow_catalog_label_fields = frozenset({"en", "zh-CN"})
_workflow_catalog_contract_fields = frozenset({"id", "registry", "version"})
_workflow_catalog_node_fields = frozenset(
    {
        "actions",
        "allowed_state_writes",
        "approval_policy",
        "context_projection",
        "contract_version",
        "effect_policy",
        "executor",
        "id",
        "index_role",
        "input_schema",
        "kind",
        "labels",
        "output_schema",
        "phase",
        "playbook",
        "produced_evidence",
        "recovery_policy",
        "required_evidence",
        "required_sections",
        "retry_policy",
        "terminal",
        "waiting",
    }
)
_workflow_catalog_playbook_fields = frozenset({"anchor", "path"})
_workflow_catalog_legacy_action_fields = frozenset(
    {"gate", "guards", "handler", "id", "reducers"}
)
_workflow_catalog_action_fields = frozenset(
    {
        *_workflow_catalog_legacy_action_fields,
        "allowed_artifact_kinds",
        "allowed_state_writes",
        "canonical_event",
        "confirmation",
        "edge_id",
        "effect_classification",
        "effects",
        "kernel_effects",
        "kernel_invalidates",
        "kernel_state_writes",
        "public_command",
        "required_suites",
        "requires_note",
        "resume_policy",
        "side_effects",
        "tool_policy",
        "trigger",
    }
)
_workflow_catalog_v4_action_fields = frozenset(
    {*_workflow_catalog_action_fields, "handler_closure"}
)
_workflow_catalog_handler_closure_fields = frozenset({"handler", "role"})
_workflow_catalog_v4_handler_closure_roles = (
    "abandoned",
    "accepted",
    "archive",
    "compensation",
    "containment",
    "control",
    "dispatch",
    "observation",
    "reattachment",
    "settlement",
    "unblock",
    "unresolved",
)
_workflow_catalog_shared_action_fields = frozenset(
    {"action", "placements"}
)
_workflow_catalog_shared_action_placement_fields = frozenset(
    {"edge_id", "node"}
)
_workflow_catalog_public_command_fields = frozenset(
    {"id", "selector", "values"}
)
_workflow_catalog_action_effect_fields = frozenset(
    {
        "concurrency",
        "dependencies",
        "dispatch",
        "id",
        "idempotency",
        "parallel_group",
        "quarantine",
        "receipt",
        "recovery",
        "scopes",
        "settlement",
        "target_controls",
    }
)
_workflow_catalog_action_quarantine_fields = frozenset(
    {"compensation", "reconciliation"}
)
_workflow_catalog_action_recovery_fields = frozenset(
    {"mode", "on_uncertain", "redispatch"}
)
_workflow_catalog_action_resume_fields = frozenset(
    {"safety_guard", "target"}
)
_workflow_catalog_action_tool_fields = frozenset(
    {
        "capabilities",
        "phase",
        "project_identity",
        "source_validation",
        "write_gate",
    }
)
_workflow_catalog_action_concurrency = frozenset(
    {"exclusive-task", "scoped"}
)
_workflow_catalog_action_settlements = frozenset(
    {"asynchronous-handoff", "synchronous-quiescence"}
)
_workflow_catalog_action_dispatch_modes = frozenset(
    {"none", "single-dispatch"}
)
_workflow_catalog_action_idempotency_modes = frozenset(
    {"execution-effect-key/v1", "not-applicable"}
)
_workflow_catalog_action_quarantine_reconciliation = frozenset(
    {"not-applicable", "target-bound/v1"}
)
_workflow_catalog_action_compensation = frozenset(
    {"new-authorized-execution/v1", "not-applicable"}
)
_workflow_catalog_action_recovery_modes = frozenset(
    {"observe-or-quarantine/v1", "re-evaluate/v1"}
)
_workflow_catalog_action_recovery_uncertain = frozenset(
    {"block", "quarantine"}
)
_workflow_catalog_action_recovery_redispatch = frozenset({"forbidden"})
_workflow_catalog_action_control_ids = frozenset(
    {
        "control.cancel/v1",
        "control.reconcile/v1",
        "control.stop/v1",
    }
)
_workflow_catalog_action_tool_phases = frozenset(
    {"baseline", "current-generation-workspace"}
)
_workflow_catalog_action_tool_project_identities = frozenset(
    {"baseline-project", "current-generation-workspace-project"}
)
_workflow_catalog_action_tool_source_validation = frozenset(
    {"source-confirmation-required"}
)
_workflow_catalog_action_tool_write_gates = frozenset(
    {"host-and-workflow", "read-only"}
)
_workflow_catalog_action_required_suites = frozenset(
    {
        "action-policy",
        "action-recovery",
        "external-tool-capability-evidence",
        "orchestration-action-matrix",
    }
)
_workflow_catalog_policy_fields = frozenset(
    {
        "allowed_state_writes",
        "automatic",
        "class",
        "confirmation",
        "gate",
        "guards",
        "handler",
        "id",
        "kernel_effects",
        "kernel_invalidates",
        "priority",
        "reducers",
        "requires_note",
        "side_effects",
        "trigger",
    }
)
_workflow_catalog_trigger_fields = frozenset({"id", "kind"})
_workflow_catalog_edge_fields = frozenset({"id", "policy", "source", "target"})
_workflow_catalog_edge_family_fields = frozenset(
    {"id_prefix", "policy", "sources", "targets"}
)
_workflow_catalog_projection_fields = frozenset(
    {
        "hook_checkpoint_max_bytes",
        "mutation_receipt_max_bytes",
        "node_result_max_bytes",
        "node_result_summary_max_bytes",
        "playbook_max_bytes",
        "profile",
        "task_next_max_bytes",
    }
)
_workflow_catalog_schema_fields = frozenset({"contracts", "documents"})
_workflow_catalog_schema_document_reference_fields = frozenset(
    {"id", "kind", "path"}
)
_workflow_catalog_schema_document_kinds = frozenset(
    {"contract-reference", "node-input", "node-output"}
)
_workflow_catalog_schema_role_properties = MappingProxyType(
    {
        "contract-reference": frozenset({"id", "registry", "version"}),
        "node-input": frozenset(
            {
                "attempt",
                "context",
                "contract",
                "expected_revision",
                "input_sha256",
                "node_instance_id",
                "task_id",
                "workflow_bundle_sha256",
            }
        ),
        "node-output": frozenset(
            {
                "artifact_refs",
                "assignment_id",
                "attempt",
                "blockers",
                "changed_paths_sha256",
                "evidence_refs",
                "input_sha256",
                "lease_id",
                "lease_nonce",
                "map_epoch",
                "node_instance_id",
                "outcome",
                "output_sha256",
                "plan_drift",
                "repository_id",
                "result_id",
                "runtime_handle",
                "schema",
                "summary",
                "task_id",
                "verification_sha256",
                "worktree_sha256",
                "workflow_bundle_sha256",
            }
        ),
    }
)
_workflow_catalog_json_schema_root_fields = frozenset(
    {
        "$id",
        "$schema",
        "$defs",
        "additionalProperties",
        "allOf",
        "properties",
        "required",
        "title",
        "type",
        "x-canonicalUtf8MaxBytes",
        "x-contentAddressedIdentity",
    }
)
_workflow_catalog_json_schema_object_fields = frozenset(
    {"additionalProperties", "allOf", "properties", "required", "type"}
)
_workflow_catalog_json_schema_string_fields = frozenset(
    {
        "enum",
        "maxLength",
        "minLength",
        "pattern",
        "type",
        "x-utf8MaxBytes",
    }
)
_workflow_catalog_json_schema_integer_fields = frozenset(
    {"maximum", "minimum", "type"}
)
_workflow_catalog_json_schema_array_fields = frozenset(
    {
        "items",
        "maxItems",
        "minItems",
        "type",
        "uniqueItems",
        "x-canonicalUtf8Order",
        "x-canonicalUtf8OrderBy",
    }
)
_workflow_catalog_json_schema_boolean_fields = frozenset({"type"})
_workflow_catalog_context_projection_fields = frozenset(
    {"max_bytes", "profile", "state_paths"}
)
_workflow_catalog_approval_policy_fields = frozenset({"gate", "mode"})
_workflow_catalog_effect_policy_fields = frozenset(
    {"classification", "effects"}
)
_workflow_catalog_retry_policy_fields = frozenset(
    {"backoff", "max_attempts", "mode", "retry_on"}
)
_workflow_catalog_recovery_policy_fields = frozenset(
    {
        "mode",
        "on_uncertain",
        "requires_receipt",
        "resume_same_attempt",
    }
)


class WorkflowCatalogError(ValueError):
    """Stable, structured validation failure for one static catalog load."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


class _workflow_catalog_JsonSemanticError(Exception):
    def __init__(self, code: str, details: Mapping[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details)


def _workflow_catalog_reject_float(literal: str) -> object:
    raise _workflow_catalog_JsonSemanticError(
        "WORKFLOW_JSON_FLOAT_FORBIDDEN", {"literal": literal[:80]}
    )


def _workflow_catalog_parse_integer(literal: str) -> int:
    digits = literal[1:] if literal.startswith("-") else literal
    if len(digits) > 19:
        raise _workflow_catalog_JsonSemanticError(
            "WORKFLOW_JSON_INTEGER_OUT_OF_RANGE",
            {"literal": literal[:80]},
        )
    value = int(literal)
    if not (
        _workflow_catalog_signed_int64_min
        <= value
        <= _workflow_catalog_signed_int64_max
    ):
        raise _workflow_catalog_JsonSemanticError(
            "WORKFLOW_JSON_INTEGER_OUT_OF_RANGE",
            {"literal": literal[:80]},
        )
    return value


def _workflow_catalog_reject_constant(literal: str) -> object:
    raise _workflow_catalog_JsonSemanticError(
        "WORKFLOW_JSON_NONFINITE_FORBIDDEN", {"literal": literal}
    )


def _workflow_catalog_unique_object(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _workflow_catalog_JsonSemanticError(
                "WORKFLOW_JSON_DUPLICATE_KEY", {"key": key}
            )
        result[key] = value
    return result


def _workflow_catalog_check_nfc(value: object, pointer: str = "") -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_JSON_UNICODE_INVALID",
                "workflow JSON strings and keys must be valid Unicode",
                details={"pointer": pointer or "/"},
            ) from exc
        if unicodedata.normalize("NFC", value) != value:
            raise WorkflowCatalogError(
                "WORKFLOW_JSON_NOT_NFC",
                "workflow JSON strings and keys must be NFC",
                details={"pointer": pointer or "/"},
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _workflow_catalog_check_nfc(item, f"{pointer}/{index}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _workflow_catalog_check_nfc(key, f"{pointer}/{key}")
            _workflow_catalog_check_nfc(item, f"{pointer}/{key}")


def _workflow_catalog_parse_json_bytes(source: bytes, *, path: str) -> object:
    if source.startswith(b"\xef\xbb\xbf"):
        raise WorkflowCatalogError(
            "WORKFLOW_JSON_BOM_FORBIDDEN",
            "workflow JSON must not contain a UTF-8 BOM",
            details={"path": path},
        )
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_JSON_UTF8_INVALID",
            "workflow JSON must be valid UTF-8",
            details={"path": path, "position": exc.start},
        ) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_workflow_catalog_unique_object,
            parse_float=_workflow_catalog_reject_float,
            parse_int=_workflow_catalog_parse_integer,
            parse_constant=_workflow_catalog_reject_constant,
        )
    except _workflow_catalog_JsonSemanticError as exc:
        raise WorkflowCatalogError(
            exc.code,
            "workflow JSON contains an ambiguous semantic value",
            details={"path": path, **exc.details},
        ) from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        details: dict[str, object] = {"path": path}
        if isinstance(exc, json.JSONDecodeError):
            details.update({"line": exc.lineno, "column": exc.colno})
        raise WorkflowCatalogError(
            "WORKFLOW_JSON_MALFORMED",
            "workflow JSON is malformed",
            details=details,
        ) from exc
    _workflow_catalog_check_nfc(value)
    return value


def _workflow_catalog_expect_object(value: object, pointer: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow value must be an object",
            details={"pointer": pointer, "type": type(value).__name__},
        )
    return value


def _workflow_catalog_expect_exact_fields(
    value: Mapping[str, object],
    fields: frozenset[str],
    pointer: str,
) -> None:
    unknown = sorted(set(value) - fields)
    missing = sorted(fields - set(value))
    if unknown:
        raise WorkflowCatalogError(
            "WORKFLOW_UNKNOWN_FIELD",
            "workflow object contains unknown fields",
            details={"pointer": pointer, "fields": unknown},
        )
    if missing:
        raise WorkflowCatalogError(
            "WORKFLOW_REQUIRED_FIELD",
            "workflow object is missing required fields",
            details={"pointer": pointer, "fields": missing},
        )


def _workflow_catalog_expect_allowed_fields(
    value: Mapping[str, object],
    allowed: frozenset[str],
    required: frozenset[str],
    pointer: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise WorkflowCatalogError(
            "WORKFLOW_UNKNOWN_FIELD",
            "workflow object contains unknown fields",
            details={"pointer": pointer, "fields": unknown},
        )
    if missing:
        raise WorkflowCatalogError(
            "WORKFLOW_REQUIRED_FIELD",
            "workflow object is missing required fields",
            details={"pointer": pointer, "fields": missing},
        )


def _workflow_catalog_expect_list(value: object, pointer: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow value must be an array",
            details={"pointer": pointer},
        )
    return value


def _workflow_catalog_expect_string(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow value must be a non-empty string",
            details={"pointer": pointer},
        )
    return value


def _workflow_catalog_expect_bool(value: object, pointer: str) -> bool:
    if not isinstance(value, bool):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow value must be a boolean",
            details={"pointer": pointer},
        )
    return value


def _workflow_catalog_expect_integer(
    value: object, pointer: str, *, minimum: int = 0
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow value must be an integer in the supported range",
            details={"pointer": pointer, "minimum": minimum},
        )
    return value


def _workflow_catalog_stable_id(value: object, pointer: str) -> str:
    text = _workflow_catalog_expect_string(value, pointer)
    if not _workflow_catalog_id_re.fullmatch(text):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_ID",
            "workflow identifier is not portable",
            details={"pointer": pointer, "value": text},
        )
    return text


def _workflow_catalog_portable_relative_path(value: object, pointer: str) -> str:
    text = _workflow_catalog_expect_string(value, pointer)
    if (
        text.startswith(("/", "\\"))
        or "\\" in text
        or "\x00" in text
        or any(char in text for char in _workflow_catalog_glob_characters)
        or re.match(r"^[A-Za-z]:", text)
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_PATH_INVALID",
            "workflow paths must be exact portable relative POSIX paths",
            details={"pointer": pointer, "path": text},
        )
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise WorkflowCatalogError(
            "WORKFLOW_PATH_INVALID",
            "workflow paths must not contain empty or traversal segments",
            details={"pointer": pointer, "path": text},
        )
    if any(unicodedata.normalize("NFC", part) != part for part in parts):
        raise WorkflowCatalogError(
            "WORKFLOW_PATH_INVALID",
            "workflow path segments must be NFC",
            details={"pointer": pointer, "path": text},
        )
    return text


def _workflow_catalog_resolve_regular_file(
    root: Path, relative_path: str, *, pointer: str
) -> Path:
    current = root
    if current.is_symlink():
        raise WorkflowCatalogError(
            "WORKFLOW_SYMLINK_FORBIDDEN",
            "workflow roots and files must not be symlinks",
            details={"pointer": pointer, "path": str(current)},
        )
    for part in relative_path.split("/"):
        current = current / part
        if current.is_symlink():
            raise WorkflowCatalogError(
                "WORKFLOW_SYMLINK_FORBIDDEN",
                "workflow roots and files must not be symlinks",
                details={"pointer": pointer, "path": relative_path},
            )
    try:
        root_resolved = root.resolve(strict=True)
        resolved = current.resolve(strict=True)
    except OSError as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_REFERENCE_MISSING",
            "a statically inventoried workflow file is missing",
            details={"pointer": pointer, "path": relative_path},
        ) from exc
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_PATH_ESCAPE",
            "workflow reference resolves outside its package-owned root",
            details={"pointer": pointer, "path": relative_path},
        ) from exc
    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_REFERENCE_MISSING",
            "a statically inventoried workflow file is unavailable",
            details={"pointer": pointer, "path": relative_path},
        ) from exc
    if not stat.S_ISREG(mode):
        raise WorkflowCatalogError(
            "WORKFLOW_SPECIAL_FILE_FORBIDDEN",
            "workflow inventories may contain regular files only",
            details={"pointer": pointer, "path": relative_path},
        )
    return resolved


def _workflow_catalog_inventory_regular_files(root: Path) -> tuple[str, ...]:
    files: list[str] = []
    for directory, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        base = Path(directory)
        for name in list(directory_names):
            child = base / name
            if child.is_symlink():
                raise WorkflowCatalogError(
                    "WORKFLOW_SYMLINK_FORBIDDEN",
                    "bundle inventories must not contain symlink directories",
                    details={"path": child.relative_to(root).as_posix()},
                )
        for name in file_names:
            child = base / name
            relative = child.relative_to(root).as_posix()
            if child.is_symlink():
                raise WorkflowCatalogError(
                    "WORKFLOW_SYMLINK_FORBIDDEN",
                    "bundle inventories must not contain symlink files",
                    details={"path": relative},
                )
            if not child.is_file():
                raise WorkflowCatalogError(
                    "WORKFLOW_SPECIAL_FILE_FORBIDDEN",
                    "bundle inventories may contain regular files only",
                    details={"path": relative},
                )
            files.append(relative)
    return tuple(sorted(files, key=lambda item: item.encode("utf-8")))


def _workflow_catalog_inventory_bundle_roots(root: Path) -> tuple[str, ...]:
    bundles_root = root / "bundles"
    if bundles_root.is_symlink():
        raise WorkflowCatalogError(
            "WORKFLOW_SYMLINK_FORBIDDEN",
            "the static bundles directory must not be a symlink",
            details={"path": "bundles"},
        )
    if not bundles_root.is_dir():
        raise WorkflowCatalogError(
            "WORKFLOW_REFERENCE_MISSING",
            "the static bundles directory is missing",
            details={"path": "bundles"},
        )
    result: list[str] = []
    try:
        children = tuple(bundles_root.iterdir())
    except OSError as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_REFERENCE_MISSING",
            "the static bundles directory is unavailable",
            details={"path": "bundles"},
        ) from exc
    for child in children:
        relative = f"bundles/{child.name}"
        _workflow_catalog_portable_relative_path(
            relative, "/bundles/inventory"
        )
        if child.is_symlink():
            raise WorkflowCatalogError(
                "WORKFLOW_SYMLINK_FORBIDDEN",
                "static bundle roots must not be symlinks",
                details={"path": relative},
            )
        if not child.is_dir():
            raise WorkflowCatalogError(
                "WORKFLOW_STATIC_INVENTORY_INVALID",
                "the bundles directory may contain bundle roots only",
                details={"path": relative},
            )
        result.append(relative)
    return tuple(
        sorted(result, key=lambda item: item.encode("utf-8"))
    )


def _workflow_catalog_labels(value: object, pointer: str) -> dict[str, str]:
    result = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        result, _workflow_catalog_label_fields, pointer
    )
    return {
        key: _workflow_catalog_expect_string(result[key], f"{pointer}/{key}")
        for key in ("en", "zh-CN")
    }


def _workflow_catalog_reject_executable_content(
    value: object, pointer: str
) -> None:
    if isinstance(value, dict):
        forbidden = sorted(
            set(value) & _workflow_catalog_forbidden_executable_fields
        )
        if forbidden:
            raise WorkflowCatalogError(
                "WORKFLOW_EXECUTABLE_CONTENT_FORBIDDEN",
                "workflow bundles may reference sealed contracts only",
                details={"pointer": pointer, "fields": forbidden},
            )
        for key, item in value.items():
            child = f"{pointer}/{key}" if pointer else f"/{key}"
            _workflow_catalog_reject_executable_content(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{pointer}/{index}" if pointer else f"/{index}"
            _workflow_catalog_reject_executable_content(item, child)


def _workflow_catalog_pointer_is_within(
    pointer: str, root: str
) -> bool:
    return pointer == root or pointer.startswith(root + "/")


def _workflow_catalog_validate_state_writes(
    value: object,
    pointer: str,
    *,
    allow_kernel_status: bool,
) -> tuple[str, ...]:
    pointers = _workflow_catalog_validate_unique_strings(value, pointer)
    for index, item in enumerate(pointers):
        item_pointer = f"{pointer}/{index}"
        if not _workflow_catalog_json_pointer_re.fullmatch(item):
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_JSON_POINTER",
                "state-write grants must be canonical JSON Pointers",
                details={"pointer": item_pointer, "value": item},
            )
        if item == "":
            raise WorkflowCatalogError(
                "WORKFLOW_PROTECTED_STATE_WRITE",
                "a workflow node or reducer cannot receive root-state authority",
                details={"pointer": item_pointer, "value": item},
            )
        if allow_kernel_status and item == "/status":
            continue
        protected = next(
            (
                root
                for root in sorted(_workflow_catalog_protected_state_roots)
                if _workflow_catalog_pointer_is_within(item, root)
            ),
            None,
        )
        if protected is not None or item == "/status":
            raise WorkflowCatalogError(
                "WORKFLOW_PROTECTED_STATE_WRITE",
                "workflow reducer grants cannot include kernel-owned state",
                details={
                    "pointer": item_pointer,
                    "value": item,
                    "protected_root": protected or "/status",
                },
            )
    return pointers


def _workflow_catalog_validate_json_schema_node(
    value: object,
    pointer: str,
    *,
    definitions: frozenset[str] = frozenset(),
    allow_partial_object: bool = False,
) -> None:
    schema = _workflow_catalog_expect_object(value, pointer)

    if "$ref" in schema:
        _workflow_catalog_expect_exact_fields(schema, {"$ref"}, pointer)
        reference = _workflow_catalog_expect_string(
            schema["$ref"], f"{pointer}/$ref"
        )
        prefix = "#/$defs/"
        name = reference[len(prefix) :] if reference.startswith(prefix) else ""
        if (
            not name
            or "/" in name
            or "~" in name
            or name not in definitions
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "bundle schemas may reference only declared local definitions",
                details={"pointer": f"{pointer}/$ref", "value": reference},
            )
        return

    if "const" in schema:
        _workflow_catalog_expect_exact_fields(schema, {"const"}, pointer)
        constant = schema["const"]
        if (
            constant is not None
            and not isinstance(constant, (str, bool, int))
        ) or isinstance(constant, float):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "schema constants must use canonical scalar JSON values",
                details={"pointer": f"{pointer}/const"},
            )
        return

    if "oneOf" in schema:
        _workflow_catalog_expect_exact_fields(schema, {"oneOf"}, pointer)
        choices = _workflow_catalog_expect_list(
            schema["oneOf"], f"{pointer}/oneOf"
        )
        if len(choices) < 2:
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "oneOf must declare at least two alternatives",
                details={"pointer": f"{pointer}/oneOf"},
            )
        for index, choice in enumerate(choices):
            _workflow_catalog_validate_json_schema_node(
                choice,
                f"{pointer}/oneOf/{index}",
                definitions=definitions,
                allow_partial_object=allow_partial_object,
            )
        return

    if allow_partial_object and set(schema) == {"properties"}:
        properties = _workflow_catalog_expect_object(
            schema["properties"], f"{pointer}/properties"
        )
        if not properties:
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "partial object constraints must declare properties",
                details={"pointer": f"{pointer}/properties"},
            )
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "schema property names must be non-empty strings",
                    details={"pointer": f"{pointer}/properties"},
                )
            _workflow_catalog_validate_json_schema_node(
                child,
                f"{pointer}/properties/{name}",
                definitions=definitions,
            )
        return

    schema_type = _workflow_catalog_expect_string(
        schema.get("type"), f"{pointer}/type"
    )
    if schema_type == "object":
        _workflow_catalog_expect_allowed_fields(
            schema,
            _workflow_catalog_json_schema_object_fields,
            frozenset(
                {"additionalProperties", "properties", "required", "type"}
            ),
            pointer,
        )
        if schema["additionalProperties"] is not False:
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "every object schema must reject additional properties",
                details={"pointer": f"{pointer}/additionalProperties"},
            )
        properties = _workflow_catalog_expect_object(
            schema["properties"], f"{pointer}/properties"
        )
        if not properties:
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "typed object schemas must declare at least one property",
                details={"pointer": f"{pointer}/properties"},
            )
        required = _workflow_catalog_validate_unique_strings(
            schema["required"], f"{pointer}/required"
        )
        if set(required) != set(properties):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "strict object schemas must require every declared property",
                details={
                    "pointer": pointer,
                    "required": list(required),
                    "properties": sorted(properties),
                },
            )
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "schema property names must be non-empty strings",
                    details={"pointer": f"{pointer}/properties"},
            )
            _workflow_catalog_validate_json_schema_node(
                child,
                f"{pointer}/properties/{name}",
                definitions=definitions,
            )
        all_of = schema.get("allOf", [])
        if not isinstance(all_of, list):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "allOf must be an array of schema constraints",
                details={"pointer": f"{pointer}/allOf"},
            )
        for index, constraint in enumerate(all_of):
            _workflow_catalog_validate_json_schema_node(
                constraint,
                f"{pointer}/allOf/{index}",
                definitions=definitions,
                allow_partial_object=True,
            )
        return
    if schema_type == "string":
        _workflow_catalog_expect_allowed_fields(
            schema,
            _workflow_catalog_json_schema_string_fields,
            frozenset({"type"}),
            pointer,
        )
        has_bounds = any(
            field in schema for field in ("minLength", "maxLength", "pattern")
        )
        if has_bounds and not all(
            field in schema for field in ("maxLength", "pattern")
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "bounded string schemas require maxLength and pattern",
                details={"pointer": pointer},
            )
        if has_bounds:
            minimum = (
                _workflow_catalog_expect_integer(
                    schema["minLength"],
                    f"{pointer}/minLength",
                    minimum=0,
                )
                if "minLength" in schema
                else 0
            )
            maximum = _workflow_catalog_expect_integer(
                schema["maxLength"], f"{pointer}/maxLength", minimum=1
            )
            if minimum > maximum:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "string schema bounds are inverted",
                    details={"pointer": pointer},
                )
            pattern = _workflow_catalog_expect_string(
                schema["pattern"], f"{pointer}/pattern"
            )
            try:
                re.compile(pattern)
            except re.error as exc:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "string schema pattern is invalid",
                    details={"pointer": f"{pointer}/pattern"},
                ) from exc
        enum = schema.get("enum")
        if enum is not None:
            values = _workflow_catalog_validate_unique_strings(
                enum, f"{pointer}/enum"
            )
            if not values:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "string enum schemas must declare at least one value",
                    details={"pointer": f"{pointer}/enum"},
                )
        if not has_bounds and enum is None:
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "string schemas must be bounded or enumerate exact values",
                details={"pointer": pointer},
            )
        utf8_limit = schema.get("x-utf8MaxBytes")
        if utf8_limit is not None:
            _workflow_catalog_expect_integer(
                utf8_limit, f"{pointer}/x-utf8MaxBytes", minimum=1
            )
        return
    if schema_type == "integer":
        _workflow_catalog_expect_allowed_fields(
            schema,
            _workflow_catalog_json_schema_integer_fields,
            frozenset({"minimum", "type"}),
            pointer,
        )
        minimum = _workflow_catalog_expect_integer(
            schema["minimum"], f"{pointer}/minimum"
        )
        if "maximum" in schema:
            maximum = _workflow_catalog_expect_integer(
                schema["maximum"], f"{pointer}/maximum"
            )
            if minimum > maximum:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "integer schema bounds are inverted",
                    details={"pointer": pointer},
                )
        return
    if schema_type == "array":
        _workflow_catalog_expect_allowed_fields(
            schema,
            _workflow_catalog_json_schema_array_fields,
            frozenset({"items", "type"}),
            pointer,
        )
        minimum = (
            _workflow_catalog_expect_integer(
                schema["minItems"], f"{pointer}/minItems", minimum=0
            )
            if "minItems" in schema
            else 0
        )
        if "maxItems" in schema:
            maximum = _workflow_catalog_expect_integer(
                schema["maxItems"], f"{pointer}/maxItems", minimum=0
            )
            if minimum > maximum:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "array schema bounds are inverted",
                    details={"pointer": pointer},
                )
        if "uniqueItems" in schema:
            _workflow_catalog_expect_bool(
                schema["uniqueItems"], f"{pointer}/uniqueItems"
            )
        if (
            "x-canonicalUtf8Order" in schema
            and schema["x-canonicalUtf8Order"] is not True
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "canonical UTF-8 ordering extension must be true",
                details={"pointer": f"{pointer}/x-canonicalUtf8Order"},
            )
        if "x-canonicalUtf8OrderBy" in schema:
            order_by = _workflow_catalog_expect_string(
                schema["x-canonicalUtf8OrderBy"],
                f"{pointer}/x-canonicalUtf8OrderBy",
            )
            if not order_by:
                raise WorkflowCatalogError(
                    "WORKFLOW_SCHEMA_INVALID",
                    "canonical ordering field must be non-empty",
                    details={
                        "pointer": f"{pointer}/x-canonicalUtf8OrderBy"
                    },
                )
        _workflow_catalog_validate_json_schema_node(
            schema["items"],
            f"{pointer}/items",
            definitions=definitions,
        )
        return
    if schema_type == "boolean":
        _workflow_catalog_expect_exact_fields(
            schema, _workflow_catalog_json_schema_boolean_fields, pointer
        )
        return
    if schema_type == "null":
        _workflow_catalog_expect_exact_fields(schema, {"type"}, pointer)
        return
    raise WorkflowCatalogError(
        "WORKFLOW_SCHEMA_INVALID",
        "bundle schemas use an unsupported JSON Schema type",
        details={"pointer": f"{pointer}/type", "type": schema_type},
    )


def _workflow_catalog_validate_schema_document(
    value: object,
    pointer: str,
    expected_id: str,
    expected_kind: str,
) -> None:
    schema = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_allowed_fields(
        schema,
        _workflow_catalog_json_schema_root_fields,
        frozenset(
            {
                "$id",
                "$schema",
                "additionalProperties",
                "properties",
                "required",
                "type",
            }
        ),
        pointer,
    )
    if schema["$id"] != expected_id:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_ID_MISMATCH",
            "schema document identity does not match its bundle reference",
            details={
                "pointer": f"{pointer}/$id",
                "expected": expected_id,
                "actual": schema["$id"],
            },
        )
    if (
        schema["$schema"]
        != "https://json-schema.org/draft/2020-12/schema"
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_VERSION_UNSUPPORTED",
            "bundle schemas must use JSON Schema draft 2020-12",
            details={"pointer": f"{pointer}/$schema"},
        )
    definitions = _workflow_catalog_expect_object(
        schema.get("$defs", {}), f"{pointer}/$defs"
    )
    definition_names = frozenset(definitions)
    for name, definition in definitions.items():
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "~" in name
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "local schema definition names must be portable",
                details={"pointer": f"{pointer}/$defs"},
            )
        _workflow_catalog_validate_json_schema_node(
            definition,
            f"{pointer}/$defs/{name}",
            definitions=definition_names,
        )
    body = {
        key: schema[key]
        for key in _workflow_catalog_json_schema_object_fields
        if key in schema
    }
    _workflow_catalog_validate_json_schema_node(
        body, pointer, definitions=definition_names
    )
    if "title" in schema:
        _workflow_catalog_expect_string(
            schema["title"], f"{pointer}/title"
        )
    if "x-canonicalUtf8MaxBytes" in schema:
        _workflow_catalog_expect_integer(
            schema["x-canonicalUtf8MaxBytes"],
            f"{pointer}/x-canonicalUtf8MaxBytes",
            minimum=1,
        )
    if "x-contentAddressedIdentity" in schema:
        identity_field = _workflow_catalog_expect_string(
            schema["x-contentAddressedIdentity"],
            f"{pointer}/x-contentAddressedIdentity",
        )
        properties = _workflow_catalog_expect_object(
            schema["properties"], f"{pointer}/properties"
        )
        if identity_field not in properties:
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_INVALID",
                "content-addressed identity must name a declared property",
                details={
                    "pointer": f"{pointer}/x-contentAddressedIdentity",
                    "field": identity_field,
                },
            )
    expected_properties = _workflow_catalog_schema_role_properties[
        expected_kind
    ]
    actual_properties = set(
        _workflow_catalog_expect_object(
            schema["properties"], f"{pointer}/properties"
        )
    )
    if actual_properties != expected_properties:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_ROLE_MISMATCH",
            "typed schema properties do not match the declared schema role",
            details={
                "pointer": f"{pointer}/properties",
                "kind": expected_kind,
                "expected": sorted(expected_properties),
                "actual": sorted(actual_properties),
            },
        )


@dataclass(frozen=True, order=True)
class ContractReference:
    registry: str
    identifier: str
    version: str


def _workflow_catalog_contract_reference(
    value: object, pointer: str
) -> ContractReference:
    item = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        item, _workflow_catalog_contract_fields, pointer
    )
    registry = _workflow_catalog_expect_string(
        item["registry"], f"{pointer}/registry"
    )
    if registry not in SUPPORTED_CONTRACT_REGISTRIES:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_CONTRACT",
            "workflow contract names an unsupported registry",
            details={"pointer": pointer, "registry": registry},
        )
    identifier = _workflow_catalog_expect_string(item["id"], f"{pointer}/id")
    if not _workflow_catalog_contract_id_re.fullmatch(identifier):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_CONTRACT",
            "workflow contract ID is not portable",
            details={"pointer": pointer, "id": identifier},
        )
    version = _workflow_catalog_expect_string(
        item["version"], f"{pointer}/version"
    )
    if not _workflow_catalog_contract_version_re.fullmatch(version):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_CONTRACT",
            "workflow contract version must use vN",
            details={"pointer": pointer, "version": version},
        )
    if not identifier.endswith(f"/{version}"):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_CONTRACT",
            "workflow contract ID suffix must match its contract version",
            details={
                "pointer": pointer,
                "id": identifier,
                "version": version,
            },
        )
    return ContractReference(registry, identifier, version)


class StaticContractResolver:
    """Small sealed resolver used by catalog tests and staged integrations."""

    def __init__(
        self, references: Iterable[ContractReference | tuple[str, str, str]]
    ) -> None:
        normalized = []
        for item in references:
            if isinstance(item, ContractReference):
                normalized.append(item)
            else:
                normalized.append(ContractReference(*item))
        self._references = frozenset(normalized)
        self.sealed = True

    @property
    def references(self) -> frozenset[ContractReference]:
        return self._references

    def resolve(
        self, registry: str, identifier: str, version: str
    ) -> ContractReference:
        reference = ContractReference(registry, identifier, version)
        if reference not in self._references:
            raise KeyError(reference)
        return reference

    def identity_handlers(
        self, _references: Sequence[ContractReference]
    ) -> tuple[object, ...]:
        return ()


def _workflow_catalog_resolve_contract(
    resolver: object, reference: ContractReference
) -> object:
    if not bool(getattr(resolver, "sealed", False)):
        raise WorkflowCatalogError(
            "WORKFLOW_REGISTRY_UNSEALED",
            "workflow contracts must resolve against sealed registries",
        )
    try:
        direct = getattr(resolver, "resolve", None)
        if callable(direct):
            return direct(
                reference.registry,
                reference.identifier,
                reference.version,
            )
        typed_registry = getattr(resolver, reference.registry)
        return typed_registry.resolve(reference.identifier, reference.version)
    except Exception as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNKNOWN",
            "workflow references an unknown executable contract",
            details={
                "registry": reference.registry,
                "id": reference.identifier,
                "version": reference.version,
            },
        ) from exc


def _workflow_catalog_freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {
                key: _workflow_catalog_freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list):
        return tuple(_workflow_catalog_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class WorkflowBundle:
    workflow_id: str
    workflow_version: int
    bundle_schema_version: int
    graph_sha256: str
    bundle_sha256: str
    root: Path
    graph: Mapping[str, object]
    resources: Mapping[str, tuple[str, bytes]]
    nodes: Mapping[str, Mapping[str, object]]
    edges: tuple[Mapping[str, object], ...]
    action_edges: tuple[Mapping[str, object], ...]
    contracts: tuple[ContractReference, ...]
    execution_profiles: tuple[str, ...]
    repository_orchestration: Mapping[str, object] | None
    active_profiles: tuple[str, ...]

    @property
    def key(self) -> tuple[str, int]:
        return (self.workflow_id, self.workflow_version)

    def node(self, node_id: str) -> Mapping[str, object]:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_NODE_UNKNOWN",
                "workflow node is not defined",
                details={"node_id": node_id},
            ) from exc

    @property
    def tool_capabilities(self) -> tuple[Mapping[str, object], ...]:
        value = self.graph.get("tool_capabilities", ())
        return tuple(value) if isinstance(value, tuple) else ()

    def tool_capability(
        self, capability_id: str
    ) -> Mapping[str, object]:
        _workflow_catalog_versioned_operation_id(
            capability_id, "/capability_id"
        )
        matches = tuple(
            item
            for item in self.tool_capabilities
            if item.get("capability_id") == capability_id
        )
        if len(matches) != 1:
            raise WorkflowCatalogError(
                "WORKFLOW_TOOL_CAPABILITY_UNKNOWN",
                "external-tool capability is not declared by this bundle",
                details={"capability_id": capability_id},
            )
        return matches[0]

    @property
    def movement_edges(self) -> tuple[Mapping[str, object], ...]:
        return self.edges

    def legal_movement_edges(
        self, source: str
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(edge for edge in self.edges if edge["source"] == source)

    def legal_action_edges(
        self, source: str
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(
            edge for edge in self.action_edges if edge["source"] == source
        )

    def legal_edges(self, source: str) -> tuple[Mapping[str, object], ...]:
        return tuple(
            sorted(
                (
                    *self.legal_movement_edges(source),
                    *self.legal_action_edges(source),
                ),
                key=lambda item: str(item["id"]).encode("utf-8"),
            )
        )

    def resolve_action_handler(
        self,
        action_id: str,
        role: str,
        *,
        call_target: ContractReference | None = None,
    ) -> ContractReference:
        """Resolve one identity-covered V4 handler and reject substitutions."""

        _workflow_catalog_stable_id(action_id, "/action_id")
        _workflow_catalog_stable_id(role, "/role")
        if role not in _workflow_catalog_v4_handler_closure_roles:
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CLOSURE_INVALID",
                "V4 action handler role is unsupported",
                details={"action_id": action_id, "role": role},
            )
        matches: set[ContractReference] = set()
        for edge in self.action_edges:
            trigger = edge.get("trigger")
            if (
                not isinstance(trigger, Mapping)
                or trigger.get("id") != action_id
            ):
                continue
            closure = edge.get("handler_closure")
            if not isinstance(closure, (list, tuple)):
                continue
            for item in closure:
                if not isinstance(item, Mapping) or item.get("role") != role:
                    continue
                handler = item.get("handler")
                if not isinstance(handler, Mapping):
                    continue
                try:
                    matches.add(
                        ContractReference(
                            str(handler["registry"]),
                            str(handler["id"]),
                            str(handler["version"]),
                        )
                    )
                except KeyError:
                    continue
        if len(matches) != 1:
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CLOSURE_UNKNOWN",
                "action does not resolve to one exact identity-covered handler",
                details={
                    "action_id": action_id,
                    "role": role,
                    "match_count": len(matches),
                },
            )
        resolved = next(iter(matches))
        if call_target is not None and not isinstance(
            call_target, ContractReference
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CALL_TARGET_UNPINNED",
                "recovery call target must be one exact contract reference",
                details={
                    "action_id": action_id,
                    "role": role,
                    "actual_type": type(call_target).__name__,
                },
            )
        if call_target is not None and call_target != resolved:
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CALL_TARGET_UNPINNED",
                "recovery call target differs from the bundle-pinned handler",
                details={
                    "action_id": action_id,
                    "role": role,
                    "expected": {
                        "registry": resolved.registry,
                        "id": resolved.identifier,
                        "version": resolved.version,
                    },
                    "actual": {
                        "registry": call_target.registry,
                        "id": call_target.identifier,
                        "version": call_target.version,
                    },
                },
            )
        return resolved

    def resolve_public_action(
        self,
        source: str,
        command: str,
        *,
        selector: str | None = None,
    ) -> Mapping[str, object]:
        """Resolve one exact schema-v3 node action without legacy fallback."""

        _workflow_catalog_stable_id(source, "/source")
        _workflow_catalog_stable_id(command, "/command")
        if selector is not None:
            if command == "orchestration":
                _workflow_catalog_versioned_operation_id(
                    selector, "/selector"
                )
            else:
                _workflow_catalog_stable_id(selector, "/selector")
        local_command_edges = []
        local_selector_edges = []
        for edge in self.legal_action_edges(source):
            public_command = edge.get("public_command")
            if (
                not isinstance(public_command, Mapping)
                or public_command.get("id") != command
            ):
                continue
            local_command_edges.append(edge)
            values = public_command.get("values")
            if not isinstance(values, (list, tuple)):
                continue
            if (not values and selector is None) or selector in values:
                local_selector_edges.append(edge)
        if len(local_selector_edges) == 1:
            return local_selector_edges[0]
        if len(local_selector_edges) > 1:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_SELECTION_AMBIGUOUS",
                "public command selector resolved more than one action edge",
                details={
                    "source": source,
                    "command": command,
                    "selector": selector,
                    "edge_ids": sorted(
                        str(edge["id"]) for edge in local_selector_edges
                    ),
                },
            )
        command_exists = bool(local_command_edges) or any(
            isinstance(edge.get("public_command"), Mapping)
            and edge["public_command"].get("id") == command
            for edge in self.action_edges
        ) or any(
            isinstance(edge.get("trigger"), Mapping)
            and edge["trigger"].get("id") == command
            for edge in self.edges
        )
        code = (
            "WORKFLOW_ACTION_SELECTOR_UNDECLARED"
            if local_command_edges
            else (
                "WORKFLOW_ACTION_PLACEMENT_INVALID"
                if command_exists
                else "WORKFLOW_ACTION_UNDECLARED"
            )
        )
        raise WorkflowCatalogError(
            code,
            "public mutation command is not declared at the exact current "
            "node and selector",
            details={
                "source": source,
                "command": command,
                "selector": selector,
                "available_edge_ids": sorted(
                    str(edge["id"]) for edge in local_command_edges
                ),
            },
        )


@dataclass(frozen=True)
class WorkflowCatalog:
    bundles: Mapping[tuple[str, int], WorkflowBundle]
    bundles_by_identity: Mapping[str, WorkflowBundle]
    activations: tuple[Mapping[str, object], ...]
    sealed: bool = True

    def resolve(
        self, workflow_id: str, workflow_version: int
    ) -> WorkflowBundle:
        try:
            return self.bundles[(workflow_id, workflow_version)]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_BUNDLE_UNKNOWN",
                "workflow bundle is not present in the static catalog",
                details={
                    "workflow_id": workflow_id,
                    "workflow_version": workflow_version,
                },
            ) from exc

    def resolve_identity(self, bundle_sha256: str) -> WorkflowBundle:
        try:
            return self.bundles_by_identity[bundle_sha256]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_BUNDLE_UNKNOWN",
                "workflow bundle identity is not present in the static catalog",
                details={"bundle_sha256": bundle_sha256},
            ) from exc


def _workflow_catalog_validate_unique_strings(
    value: object,
    pointer: str,
    *,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    result = tuple(
        _workflow_catalog_expect_string(item, f"{pointer}/{index}")
        for index, item in enumerate(
            _workflow_catalog_expect_list(value, pointer)
        )
    )
    if len(result) != len(set(result)):
        raise WorkflowCatalogError(
            "WORKFLOW_DUPLICATE_ID",
            "workflow array values must be unique",
            details={"pointer": pointer},
        )
    if allowed is not None:
        unknown = sorted(set(result) - allowed)
        if unknown:
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_FIELD",
                "workflow array contains unsupported values",
                details={"pointer": pointer, "values": unknown},
            )
    return result


def _workflow_catalog_versioned_operation_id(
    value: object, pointer: str
) -> str:
    operation_id = _workflow_catalog_expect_string(value, pointer)
    if not _workflow_catalog_operation_id_re.fullmatch(operation_id):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository orchestration operation IDs must be canonical and versioned",
            details={"pointer": pointer, "operation_id": operation_id},
        )
    return operation_id


def _workflow_catalog_repository_semantic_identities(
    operation_id: str,
) -> Mapping[str, object]:
    stem, separator, version = operation_id.rpartition("/")
    if separator != "/" or not _workflow_catalog_contract_version_re.fullmatch(
        version
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository operation cannot derive its semantic identities",
            details={"operation_id": operation_id},
        )
    suffix = f".{version}"
    return MappingProxyType(
        {
            "action_id": f"{stem}{suffix}",
            "validator_id": f"{stem}.validator{suffix}",
            "event_id": f"{stem}.event{suffix}",
            "write_set_id": f"{stem}.write-set{suffix}",
            "effect_ids": (f"{stem}.effect{suffix}",),
        }
    )


def _workflow_catalog_repository_action_policy(
    operation_id: str,
) -> Mapping[str, object]:
    scoped = (
        operation_id
        in _workflow_catalog_repository_scoped_operation_ids
    )
    lease_scoped = (
        operation_id
        in _workflow_catalog_repository_lease_scoped_operation_ids
    )
    dispatch = (
        operation_id
        in _workflow_catalog_repository_dispatch_operation_ids
    )
    barrier = (
        operation_id
        in _workflow_catalog_repository_barrier_operation_ids
    )
    manager = operation_id.startswith("manager.capability.")
    if lease_scoped:
        scopes = ("lease", "node", "repository", "worktree")
    elif scoped:
        scopes = ("node", "repository", "worktree")
    elif operation_id == "manager.capability.authorize/v1":
        scopes = ("secret-channel", "task")
    else:
        scopes = ("task",)
    if barrier:
        handler_id = "executor.barrier/v1"
        classification = "barrier"
    elif operation_id in {
        "orchestration.dispatch.handoff/v1",
        "orchestration.runtime-stop.record/v1",
    }:
        handler_id = "executor.native-subagents/v1"
        classification = "repository-write"
    else:
        handler_id = "executor.deterministic/v1"
        classification = "controller"
    side_effects = (
        ("secret-publication", "task-state")
        if operation_id == "manager.capability.authorize/v1"
        else (
            ("runtime-dispatch", "task-state")
            if operation_id
            in {
                "orchestration.dispatch.handoff/v1",
                "orchestration.runtime-stop.record/v1",
            }
            else (
                ("repository-evidence", "task-state")
                if operation_id
                in _workflow_catalog_repository_evidence_operation_ids
                else ("task-state",)
            )
        )
    )
    return MappingProxyType(
        {
            "handler_id": handler_id,
            "guard_ids": (
                ("guard.manager-registry-action/v1",)
                if manager
                else ()
            ),
            "reducer_ids": (
                ("reducer.manager-registry-action/v1",)
                if manager
                else ("reducer.action-outcome/v1",)
            ),
            "kernel_effects": (
                ("record-manager-capability",)
                if manager
                else ("record-repository-state",)
            ),
            "side_effects": side_effects,
            "classification": classification,
            "scopes": scopes,
            "concurrency": "scoped" if scoped else "exclusive-task",
            "settlement": (
                "asynchronous-handoff"
                if operation_id
                == "orchestration.dispatch.handoff/v1"
                else "synchronous-quiescence"
            ),
            "dispatch": "single-dispatch" if dispatch else "none",
            "idempotency": (
                "execution-effect-key/v1"
                if dispatch
                else "not-applicable"
            ),
            "target_controls": (
                (
                    "control.cancel/v1",
                    "control.reconcile/v1",
                    "control.stop/v1",
                )
                if dispatch
                else ()
            ),
            "reconciliation": (
                "target-bound/v1" if dispatch else "not-applicable"
            ),
            "compensation": (
                "new-authorized-execution/v1"
                if dispatch
                else "not-applicable"
            ),
            "recovery_mode": (
                "observe-or-quarantine/v1"
                if dispatch
                else "re-evaluate/v1"
            ),
            "on_uncertain": (
                "quarantine" if dispatch else "block"
            ),
        }
    )


def _workflow_catalog_validate_repository_orchestration(
    value: object,
    *,
    profiles: tuple[str, ...],
    legacy_adapter: bool,
    nodes: Mapping[str, Mapping[str, object]],
    action_edges: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    pointer = "/repository_orchestration"
    supports_multi = "multi-repository" in profiles
    if value is None:
        if supports_multi and not legacy_adapter:
            raise WorkflowCatalogError(
                "WORKFLOW_ORCHESTRATION_REQUIRED",
                "schema-v3 multi-repository workflows require static orchestration metadata",
                details={"pointer": pointer},
            )
        return None
    if legacy_adapter or not supports_multi:
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_FORBIDDEN",
            "repository orchestration metadata is valid only for schema-v3 multi-repository profiles",
            details={"pointer": pointer},
        )
    orchestration = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        orchestration,
        _workflow_catalog_repository_orchestration_fields,
        pointer,
    )
    if (
        orchestration["schema"]
        != _workflow_catalog_repository_orchestration_schema
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository orchestration schema is unsupported",
            details={
                "pointer": f"{pointer}/schema",
                "schema": orchestration["schema"],
            },
        )
    if orchestration["execution_profile"] != "multi-repository":
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository orchestration must bind the multi-repository profile",
            details={"pointer": f"{pointer}/execution_profile"},
        )

    map_value = _workflow_catalog_expect_object(
        orchestration["map"], f"{pointer}/map"
    )
    _workflow_catalog_expect_exact_fields(
        map_value,
        _workflow_catalog_repository_map_fields,
        f"{pointer}/map",
    )
    map_operation_id = _workflow_catalog_versioned_operation_id(
        map_value["operation_id"], f"{pointer}/map/operation_id"
    )
    map_parent_id = _workflow_catalog_stable_id(
        map_value["parent_node_id"], f"{pointer}/map/parent_node_id"
    )
    child_template = _workflow_catalog_expect_object(
        map_value["child_template"],
        f"{pointer}/map/child_template",
    )
    _workflow_catalog_expect_exact_fields(
        child_template,
        _workflow_catalog_repository_child_template_fields,
        f"{pointer}/map/child_template",
    )
    template_id = _workflow_catalog_versioned_operation_id(
        child_template["template_id"],
        f"{pointer}/map/child_template/template_id",
    )
    child_node_id = _workflow_catalog_stable_id(
        child_template["node_id"],
        f"{pointer}/map/child_template/node_id",
    )
    if template_id != map_operation_id:
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository child template identity must equal the map operation identity",
            details={
                "pointer": f"{pointer}/map/child_template/template_id",
                "map_operation_id": map_operation_id,
                "template_id": template_id,
            },
        )

    join_value = _workflow_catalog_expect_object(
        orchestration["join"], f"{pointer}/join"
    )
    _workflow_catalog_expect_exact_fields(
        join_value,
        _workflow_catalog_repository_join_fields,
        f"{pointer}/join",
    )
    join_operation_id = _workflow_catalog_versioned_operation_id(
        join_value["operation_id"], f"{pointer}/join/operation_id"
    )
    join_node_id = _workflow_catalog_stable_id(
        join_value["node_id"], f"{pointer}/join/node_id"
    )
    if (
        map_operation_id == join_operation_id
        or join_node_id in {map_parent_id, child_node_id}
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository map and join identities must be distinct",
            details={"pointer": pointer},
        )
    barrier_policy = _workflow_catalog_expect_object(
        join_value["barrier_policy"],
        f"{pointer}/join/barrier_policy",
    )
    _workflow_catalog_expect_exact_fields(
        barrier_policy,
        _workflow_catalog_repository_barrier_policy_fields,
        f"{pointer}/join/barrier_policy",
    )
    _workflow_catalog_versioned_operation_id(
        barrier_policy["id"],
        f"{pointer}/join/barrier_policy/id",
    )
    required_outcomes = _workflow_catalog_validate_unique_strings(
        barrier_policy["required_outcomes"],
        f"{pointer}/join/barrier_policy/required_outcomes",
        allowed=_workflow_catalog_repository_terminal_outcomes,
    )
    if set(required_outcomes) != set(
        _workflow_catalog_repository_terminal_outcomes
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "the v1 repository barrier requires every current child to succeed",
            details={
                "pointer": (
                    f"{pointer}/join/barrier_policy/required_outcomes"
                )
            },
        )

    operation_ids = tuple(
        _workflow_catalog_versioned_operation_id(
            item, f"{pointer}/operation_ids/{index}"
        )
        for index, item in enumerate(
            _workflow_catalog_expect_list(
                orchestration["operation_ids"],
                f"{pointer}/operation_ids",
            )
        )
    )
    if len(operation_ids) != len(set(operation_ids)):
        raise WorkflowCatalogError(
            "WORKFLOW_DUPLICATE_ID",
            "repository orchestration operation IDs must be unique",
            details={"pointer": f"{pointer}/operation_ids"},
        )
    canonical_operation_ids = tuple(
        sorted(operation_ids, key=lambda item: item.encode("utf-8"))
    )
    if operation_ids != canonical_operation_ids:
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository orchestration operation IDs must use canonical order",
            details={"pointer": f"{pointer}/operation_ids"},
        )
    if set(operation_ids) != set(
        _workflow_catalog_repository_required_operation_ids
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository orchestration operations must match the supported controller surface",
            details={
                "pointer": f"{pointer}/operation_ids",
                "missing": sorted(
                    _workflow_catalog_repository_required_operation_ids
                    - set(operation_ids)
                ),
                "unknown": sorted(
                    set(operation_ids)
                    - _workflow_catalog_repository_required_operation_ids
                ),
            },
        )

    operation_matrix_values = _workflow_catalog_expect_list(
        orchestration["operation_matrix"],
        f"{pointer}/operation_matrix",
    )
    normalized_matrix: list[dict[str, object]] = []
    matrix_operation_ids: list[str] = []
    semantic_id_owners: dict[str, tuple[str, str]] = {}
    for index, supplied in enumerate(operation_matrix_values):
        item_pointer = f"{pointer}/operation_matrix/{index}"
        item = _workflow_catalog_expect_object(supplied, item_pointer)
        _workflow_catalog_expect_exact_fields(
            item,
            _workflow_catalog_repository_operation_contract_fields,
            item_pointer,
        )
        operation_id = _workflow_catalog_versioned_operation_id(
            item["operation_id"], f"{item_pointer}/operation_id"
        )
        expected = _workflow_catalog_repository_semantic_identities(
            operation_id
        )
        normalized: dict[str, object] = {"operation_id": operation_id}
        for field in (
            "action_id",
            "validator_id",
            "event_id",
            "write_set_id",
        ):
            semantic_id = _workflow_catalog_stable_id(
                item[field], f"{item_pointer}/{field}"
            )
            if not _workflow_catalog_versioned_action_id_re.fullmatch(
                semantic_id
            ):
                raise WorkflowCatalogError(
                    "WORKFLOW_ORCHESTRATION_SEMANTIC_OVERLOAD",
                    "repository semantic identities must be explicitly versioned",
                    details={
                        "pointer": f"{item_pointer}/{field}",
                        "semantic_id": semantic_id,
                    },
                )
            if semantic_id != expected[field]:
                raise WorkflowCatalogError(
                    "WORKFLOW_ORCHESTRATION_SEMANTIC_OVERLOAD",
                    "repository operation semantic identity does not bind its exact role",
                    details={
                        "pointer": f"{item_pointer}/{field}",
                        "operation_id": operation_id,
                        "field": field,
                        "expected": expected[field],
                        "actual": semantic_id,
                    },
                )
            previous = semantic_id_owners.get(semantic_id)
            if previous is not None:
                raise WorkflowCatalogError(
                    "WORKFLOW_ORCHESTRATION_SEMANTIC_OVERLOAD",
                    "one repository semantic identity cannot name two roles or operations",
                    details={
                        "semantic_id": semantic_id,
                        "first": list(previous),
                        "second": [operation_id, field],
                    },
                )
            semantic_id_owners[semantic_id] = (operation_id, field)
            normalized[field] = semantic_id
        effect_ids = _workflow_catalog_validate_canonical_strings(
            item["effect_ids"], f"{item_pointer}/effect_ids"
        )
        for effect_index, effect_id in enumerate(effect_ids):
            if not _workflow_catalog_versioned_action_id_re.fullmatch(
                effect_id
            ):
                raise WorkflowCatalogError(
                    "WORKFLOW_ORCHESTRATION_SEMANTIC_OVERLOAD",
                    "repository effect identities must be explicitly versioned",
                    details={
                        "pointer": (
                            f"{item_pointer}/effect_ids/{effect_index}"
                        ),
                        "effect_id": effect_id,
                    },
                )
            previous = semantic_id_owners.get(effect_id)
            if previous is not None:
                raise WorkflowCatalogError(
                    "WORKFLOW_ORCHESTRATION_SEMANTIC_OVERLOAD",
                    "one repository effect identity cannot be shared",
                    details={
                        "effect_id": effect_id,
                        "first": list(previous),
                        "second": [operation_id, "effect_ids"],
                    },
                )
            semantic_id_owners[effect_id] = (
                operation_id,
                "effect_ids",
            )
        if effect_ids != expected["effect_ids"]:
            raise WorkflowCatalogError(
                "WORKFLOW_ORCHESTRATION_SEMANTIC_OVERLOAD",
                "repository operation effect identity is overloaded or incomplete",
                details={
                    "pointer": f"{item_pointer}/effect_ids",
                    "operation_id": operation_id,
                    "expected": list(expected["effect_ids"]),
                    "actual": list(effect_ids),
                },
            )
        normalized["effect_ids"] = list(effect_ids)
        matrix_operation_ids.append(operation_id)
        normalized_matrix.append(normalized)
    if matrix_operation_ids != list(operation_ids):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "repository operation matrix must exactly follow the authoritative operation order",
            details={
                "pointer": f"{pointer}/operation_matrix",
                "expected": list(operation_ids),
                "actual": matrix_operation_ids,
            },
        )

    legacy_alias_values = _workflow_catalog_expect_list(
        orchestration["legacy_aliases"],
        f"{pointer}/legacy_aliases",
    )
    normalized_aliases: list[dict[str, object]] = []
    alias_ids: list[str] = []
    alias_targets: dict[str, tuple[str, ...]] = {}
    for index, supplied in enumerate(legacy_alias_values):
        item_pointer = f"{pointer}/legacy_aliases/{index}"
        item = _workflow_catalog_expect_object(supplied, item_pointer)
        _workflow_catalog_expect_exact_fields(
            item,
            _workflow_catalog_repository_legacy_alias_fields,
            item_pointer,
        )
        alias_id = _workflow_catalog_versioned_operation_id(
            item["alias_id"], f"{item_pointer}/alias_id"
        )
        targets = _workflow_catalog_validate_canonical_strings(
            item["operation_ids"],
            f"{item_pointer}/operation_ids",
            allowed=_workflow_catalog_repository_required_operation_ids,
        )
        if not targets:
            raise WorkflowCatalogError(
                "WORKFLOW_ORCHESTRATION_LEGACY_ALIAS_INVALID",
                "legacy repository aliases require at least one authoritative target",
                details={"pointer": f"{item_pointer}/operation_ids"},
            )
        if alias_id in _workflow_catalog_repository_required_operation_ids:
            raise WorkflowCatalogError(
                "WORKFLOW_ORCHESTRATION_LEGACY_ALIAS_INVALID",
                "an authoritative repository operation cannot also be a legacy alias",
                details={"alias_id": alias_id},
            )
        alias_ids.append(alias_id)
        alias_targets[alias_id] = targets
        normalized_aliases.append(
            {"alias_id": alias_id, "operation_ids": list(targets)}
        )
    canonical_alias_ids = sorted(
        alias_ids, key=lambda item: item.encode("utf-8")
    )
    if (
        alias_ids != canonical_alias_ids
        or len(alias_ids) != len(set(alias_ids))
        or alias_targets
        != dict(_workflow_catalog_repository_legacy_alias_targets)
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_LEGACY_ALIAS_INVALID",
            "legacy repository aliases must exactly preserve the frozen overloaded surface",
            details={
                "pointer": f"{pointer}/legacy_aliases",
                "expected": {
                    key: list(value)
                    for key, value in (
                        _workflow_catalog_repository_legacy_alias_targets.items()
                    )
                },
                "actual": {
                    key: list(value)
                    for key, value in alias_targets.items()
                },
            },
        )

    action_node_ids = frozenset(
        _workflow_catalog_validate_canonical_strings(
            orchestration["action_nodes"],
            f"{pointer}/action_nodes",
        )
    )
    invalid_action_nodes = sorted(
        node_id
        for node_id in action_node_ids
        if node_id not in nodes or nodes[node_id].get("terminal") is True
    )
    if not action_node_ids or invalid_action_nodes:
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_ACTION_PLACEMENT_INVALID",
            "repository orchestration action nodes must be existing non-terminal nodes",
            details={
                "pointer": f"{pointer}/action_nodes",
                "nodes": invalid_action_nodes,
            },
        )
    matrix_by_operation = {
        str(item["operation_id"]): item for item in normalized_matrix
    }
    legacy_alias_set = frozenset(alias_ids)
    declared_action_ids = {
        str(item["action_id"]) for item in normalized_matrix
    }
    for operation_id in operation_ids:
        contract = matrix_by_operation[operation_id]
        action_id = str(contract["action_id"])
        matches = tuple(
            edge
            for edge in action_edges
            if isinstance(edge.get("trigger"), Mapping)
            and edge["trigger"].get("id") == action_id
        )
        sources = {
            str(edge.get("source"))
            for edge in matches
            if edge.get("source") == edge.get("target")
        }
        if (
            len(matches) != len(action_node_ids)
            or sources != set(action_node_ids)
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_ORCHESTRATION_ACTION_PLACEMENT_INVALID",
                "every authoritative repository operation must be one same-node action at every live node",
                details={
                    "operation_id": operation_id,
                    "action_id": action_id,
                    "expected_nodes": sorted(action_node_ids),
                    "actual_nodes": sorted(sources),
                    "edge_count": len(matches),
                },
            )
        expected_public = (
            {
                "id": "manager-authorize",
                "selector": "authority",
                "values": ("operator",),
            }
            if operation_id == "manager.capability.authorize/v1"
            else (
                {
                    "id": "manager-revoke",
                    "selector": "authority",
                    "values": ("operator",),
                }
                if operation_id == "manager.capability.revoke/v1"
                else {
                    "id": "orchestration",
                    "selector": "operation",
                    "values": (operation_id,),
                }
            )
        )
        canonical_event = (
            _workflow_catalog_repository_manager_canonical_events.get(
                operation_id, contract["event_id"]
            )
        )
        expected_writes = (
            _workflow_catalog_repository_operation_write_sets[operation_id]
        )
        expected_policy = _workflow_catalog_repository_action_policy(
            operation_id
        )
        for edge in matches:
            public = edge.get("public_command")
            effects = edge.get("effects")
            handler = edge.get("handler")
            guards = edge.get("guards")
            reducers = edge.get("reducers")
            effect = (
                effects[0]
                if isinstance(effects, (tuple, list))
                and len(effects) == 1
                and isinstance(effects[0], Mapping)
                else None
            )
            quarantine = (
                effect.get("quarantine")
                if isinstance(effect, Mapping)
                else None
            )
            recovery = (
                effect.get("recovery")
                if isinstance(effect, Mapping)
                else None
            )
            if (
                not isinstance(public, Mapping)
                or {
                    "id": public.get("id"),
                    "selector": public.get("selector"),
                    "values": tuple(public.get("values", ())),
                }
                != expected_public
                or edge.get("canonical_event") != canonical_event
                or tuple(edge.get("kernel_state_writes", ()))
                != expected_writes
                or not isinstance(effects, (tuple, list))
                or tuple(
                    str(effect.get("id"))
                    for effect in effects
                    if isinstance(effect, Mapping)
                )
                != tuple(contract["effect_ids"])
                or not isinstance(handler, Mapping)
                or handler.get("id") != expected_policy["handler_id"]
                or not isinstance(guards, (tuple, list))
                or tuple(
                    str(reference.get("id"))
                    for reference in guards
                    if isinstance(reference, Mapping)
                )
                != expected_policy["guard_ids"]
                or not isinstance(reducers, (tuple, list))
                or tuple(
                    str(reference.get("id"))
                    for reference in reducers
                    if isinstance(reference, Mapping)
                )
                != expected_policy["reducer_ids"]
                or edge.get("gate") is not None
                or edge.get("confirmation") != "action-explicit"
                or edge.get("requires_note") is not False
                or tuple(edge.get("allowed_state_writes", ()))
                or tuple(edge.get("kernel_effects", ()))
                != expected_policy["kernel_effects"]
                or tuple(edge.get("kernel_invalidates", ()))
                or tuple(edge.get("side_effects", ()))
                != expected_policy["side_effects"]
                or edge.get("effect_classification")
                != expected_policy["classification"]
                or tuple(edge.get("allowed_artifact_kinds", ()))
                or edge.get("resume_policy") is not None
                or edge.get("tool_policy") is not None
                or tuple(edge.get("required_suites", ()))
                != (
                    "action-policy",
                    "action-recovery",
                    "orchestration-action-matrix",
                )
                or not isinstance(effect, Mapping)
                or tuple(effect.get("scopes", ()))
                != expected_policy["scopes"]
                or effect.get("concurrency")
                != expected_policy["concurrency"]
                or tuple(effect.get("dependencies", ()))
                or effect.get("parallel_group") is not None
                or effect.get("settlement")
                != expected_policy["settlement"]
                or effect.get("receipt")
                != "dev-flow-action-receipt/v1"
                or effect.get("dispatch") != expected_policy["dispatch"]
                or effect.get("idempotency")
                != expected_policy["idempotency"]
                or tuple(effect.get("target_controls", ()))
                != expected_policy["target_controls"]
                or not isinstance(quarantine, Mapping)
                or quarantine.get("reconciliation")
                != expected_policy["reconciliation"]
                or quarantine.get("compensation")
                != expected_policy["compensation"]
                or not isinstance(recovery, Mapping)
                or recovery.get("mode")
                != expected_policy["recovery_mode"]
                or recovery.get("on_uncertain")
                != expected_policy["on_uncertain"]
                or recovery.get("redispatch") != "forbidden"
            ):
                raise WorkflowCatalogError(
                    "WORKFLOW_ORCHESTRATION_ACTION_BINDING_INVALID",
                    "repository operation edge differs from its sealed action, event, write-set, or effect identity",
                    details={
                        "operation_id": operation_id,
                        "edge_id": edge.get("id"),
                    },
                )
    for edge in action_edges:
        trigger = edge.get("trigger")
        public = edge.get("public_command")
        trigger_id = (
            trigger.get("id") if isinstance(trigger, Mapping) else None
        )
        values = (
            tuple(public.get("values", ()))
            if isinstance(public, Mapping)
            and public.get("id") == "orchestration"
            else ()
        )
        if (
            any(value in legacy_alias_set for value in values)
            or (
                values
                and any(
                    value
                    not in _workflow_catalog_repository_required_operation_ids
                    for value in values
                )
            )
            or (
                isinstance(trigger_id, str)
                and trigger_id.startswith("orchestration.")
                and trigger_id.endswith(".v1")
                and trigger_id not in declared_action_ids
                and values
            )
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_ORCHESTRATION_LEGACY_ALIAS_INVALID",
                "legacy or undeclared repository operation cannot compile as an authoritative schema-v3 edge",
                details={"edge_id": edge.get("id"), "values": list(values)},
            )

    missing_nodes = sorted(
        {map_parent_id, child_node_id, join_node_id} - set(nodes)
    )
    if missing_nodes:
        raise WorkflowCatalogError(
            "WORKFLOW_REFERENCE_DANGLING",
            "repository orchestration references unknown workflow nodes",
            details={"pointer": pointer, "nodes": missing_nodes},
        )
    repository_executors = frozenset(
        {
            "executor.codex-exec/v1",
            "executor.codex-thread/v1",
            "executor.native-subagents/v1",
        }
    )
    for role, node_id in (
        ("map-parent", map_parent_id),
        ("repository-child", child_node_id),
    ):
        node = nodes[node_id]
        executor = node.get("executor")
        effect_policy = node.get("effect_policy")
        executor_id = (
            executor.get("id") if isinstance(executor, Mapping) else None
        )
        effect_classification = (
            effect_policy.get("classification")
            if isinstance(effect_policy, Mapping)
            else None
        )
        if (
            node.get("kind") != "generic"
            or executor_id not in repository_executors
            or effect_classification != "repository-write"
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_ORCHESTRATION_NODE_MISMATCH",
                "repository map nodes require a repository-write dispatch executor",
                details={
                    "pointer": pointer,
                    "role": role,
                    "node_id": node_id,
                },
            )
    join_node = nodes[join_node_id]
    join_executor = join_node.get("executor")
    join_effect = join_node.get("effect_policy")
    if (
        join_node.get("kind") != "generic"
        or not isinstance(join_executor, Mapping)
        or join_executor.get("id") != "executor.barrier/v1"
        or not isinstance(join_effect, Mapping)
        or join_effect.get("classification") != "barrier"
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_NODE_MISMATCH",
            "repository join requires the sealed barrier executor",
            details={
                "pointer": f"{pointer}/join/node_id",
                "node_id": join_node_id,
            },
        )
    normalized_orchestration = dict(orchestration)
    normalized_orchestration["operation_ids"] = list(operation_ids)
    normalized_orchestration["operation_matrix"] = normalized_matrix
    normalized_orchestration["legacy_aliases"] = normalized_aliases
    return _workflow_catalog_freeze(  # type: ignore[return-value]
        normalized_orchestration
    )


def _workflow_catalog_validate_schema_id(
    value: object,
    pointer: str,
    declared_schemas: Mapping[str, str],
    *,
    expected_kind: str,
) -> str:
    schema_id = _workflow_catalog_expect_string(value, pointer)
    if not _workflow_catalog_schema_id_re.fullmatch(schema_id):
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_REFERENCE_INVALID",
            "node schema references must use portable versioned identities",
            details={"pointer": pointer, "schema": schema_id},
        )
    if schema_id not in declared_schemas:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_UNKNOWN",
            "node references a schema absent from its sealed bundle",
            details={"pointer": pointer, "schema": schema_id},
        )
    actual_kind = declared_schemas[schema_id]
    if actual_kind != expected_kind:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_ROLE_MISMATCH",
            "node schema reference has the wrong typed role",
            details={
                "pointer": pointer,
                "schema": schema_id,
                "expected_kind": expected_kind,
                "actual_kind": actual_kind,
            },
        )
    return schema_id


def _workflow_catalog_validate_evidence_types(
    value: object, pointer: str
) -> tuple[str, ...]:
    evidence = _workflow_catalog_validate_unique_strings(value, pointer)
    for index, item in enumerate(evidence):
        _workflow_catalog_stable_id(item, f"{pointer}/{index}")
    return evidence


def _workflow_catalog_validate_context_projection(
    value: object,
    pointer: str,
    *,
    kind: str,
) -> None:
    projection = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        projection, _workflow_catalog_context_projection_fields, pointer
    )
    profile = _workflow_catalog_expect_string(
        projection["profile"], f"{pointer}/profile"
    )
    if profile not in _workflow_catalog_supported_node_context_profiles:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_CONTEXT_INVALID",
            "node context projection profile is unsupported",
            details={"pointer": f"{pointer}/profile", "profile": profile},
        )
    expected_profile = "legacy-v1" if kind == "state" else "node-v1"
    if profile != expected_profile:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_CONTEXT_INVALID",
            "node kind and context projection profile do not match",
            details={
                "pointer": f"{pointer}/profile",
                "expected": expected_profile,
                "actual": profile,
            },
        )
    state_paths = _workflow_catalog_validate_unique_strings(
        projection["state_paths"], f"{pointer}/state_paths"
    )
    for index, item in enumerate(state_paths):
        if not _workflow_catalog_json_pointer_re.fullmatch(item) or item == "":
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_JSON_POINTER",
                "context state paths must be bounded JSON Pointers",
                details={
                    "pointer": f"{pointer}/state_paths/{index}",
                    "value": item,
                },
            )
    max_bytes = _workflow_catalog_expect_integer(
        projection["max_bytes"],
        f"{pointer}/max_bytes",
        minimum=1,
    )
    if max_bytes > 65536:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_CONTEXT_INVALID",
            "node context projection exceeds the controller ceiling",
            details={
                "pointer": f"{pointer}/max_bytes",
                "max_bytes": max_bytes,
                "ceiling": 65536,
            },
        )


def _workflow_catalog_validate_approval_policy(
    value: object,
    pointer: str,
    *,
    kind: str,
    declared_contracts: frozenset[ContractReference],
) -> set[ContractReference]:
    policy = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        policy, _workflow_catalog_approval_policy_fields, pointer
    )
    mode = _workflow_catalog_expect_string(
        policy["mode"], f"{pointer}/mode"
    )
    if mode not in _workflow_catalog_supported_node_approval_modes:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_APPROVAL_INVALID",
            "node approval mode is unsupported",
            details={"pointer": f"{pointer}/mode", "mode": mode},
        )
    if kind == "state" and mode != "legacy":
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_APPROVAL_INVALID",
            "state/v1 compatibility nodes must use legacy approval policy",
            details={"pointer": f"{pointer}/mode"},
        )
    if kind == "generic" and mode == "legacy":
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_APPROVAL_INVALID",
            "generic executable nodes cannot use legacy approval policy",
            details={"pointer": f"{pointer}/mode"},
        )
    gate_value = policy["gate"]
    if gate_value is None:
        if mode == "kernel-gate":
            raise WorkflowCatalogError(
                "WORKFLOW_NODE_APPROVAL_INVALID",
                "kernel-gate approval policy requires a sealed gate contract",
                details={"pointer": f"{pointer}/gate"},
            )
        return set()
    if mode != "kernel-gate":
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_APPROVAL_INVALID",
            "only kernel-gate approval policy may reference a gate",
            details={"pointer": f"{pointer}/gate"},
        )
    gate = _workflow_catalog_contract_reference(
        gate_value, f"{pointer}/gate"
    )
    if gate.registry != "gates" or gate not in declared_contracts:
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNDECLARED",
            "node approval gate is not declared by the bundle",
            details={"pointer": f"{pointer}/gate"},
        )
    return {gate}


def _workflow_catalog_validate_effect_policy(
    value: object, pointer: str
) -> str:
    policy = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        policy, _workflow_catalog_effect_policy_fields, pointer
    )
    classification = _workflow_catalog_expect_string(
        policy["classification"], f"{pointer}/classification"
    )
    if classification not in _workflow_catalog_supported_node_effect_classifications:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "node effect classification is unsupported",
            details={
                "pointer": f"{pointer}/classification",
                "classification": classification,
            },
        )
    effects = _workflow_catalog_validate_unique_strings(
        policy["effects"], f"{pointer}/effects"
    )
    unknown_effects = sorted(set(effects) - _workflow_catalog_supported_node_effects)
    if unknown_effects:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "node effect policy names unsupported effects",
            details={
                "pointer": f"{pointer}/effects",
                "effects": unknown_effects,
            },
        )
    if (classification == "none") != (not effects):
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "none classification and an empty effect set must match",
            details={"pointer": pointer},
        )
    return classification


def _workflow_catalog_validate_retry_policy(
    value: object, pointer: str
) -> str:
    policy = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        policy, _workflow_catalog_retry_policy_fields, pointer
    )
    mode = _workflow_catalog_expect_string(
        policy["mode"], f"{pointer}/mode"
    )
    if mode not in _workflow_catalog_supported_node_retry_modes:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RETRY_INVALID",
            "node retry mode is unsupported",
            details={"pointer": f"{pointer}/mode", "mode": mode},
        )
    max_attempts = _workflow_catalog_expect_integer(
        policy["max_attempts"],
        f"{pointer}/max_attempts",
        minimum=1,
    )
    if max_attempts > 10:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RETRY_INVALID",
            "node retry attempts exceed the controller limit",
            details={"pointer": f"{pointer}/max_attempts"},
        )
    backoff = _workflow_catalog_expect_string(
        policy["backoff"], f"{pointer}/backoff"
    )
    if backoff not in _workflow_catalog_supported_node_retry_backoffs:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RETRY_INVALID",
            "node retry backoff is unsupported",
            details={"pointer": f"{pointer}/backoff", "backoff": backoff},
        )
    retry_on = _workflow_catalog_validate_unique_strings(
        policy["retry_on"], f"{pointer}/retry_on"
    )
    unknown_reasons = sorted(set(retry_on) - _workflow_catalog_supported_node_retry_reasons)
    if unknown_reasons:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RETRY_INVALID",
            "node retry policy names unsupported reasons",
            details={
                "pointer": f"{pointer}/retry_on",
                "reasons": unknown_reasons,
            },
        )
    if mode == "never":
        valid = max_attempts == 1 and backoff == "none" and not retry_on
    elif mode == "bounded":
        valid = max_attempts >= 2 and backoff == "fixed" and bool(retry_on)
    else:
        valid = (
            max_attempts >= 2
            and backoff == "none"
            and retry_on == ("operator-authorized",)
        )
    if not valid:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RETRY_INVALID",
            "node retry fields are inconsistent with the selected mode",
            details={"pointer": pointer, "mode": mode},
        )
    return mode


def _workflow_catalog_validate_recovery_policy(
    value: object,
    pointer: str,
    *,
    kind: str,
    effect_classification: str,
) -> str:
    policy = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        policy, _workflow_catalog_recovery_policy_fields, pointer
    )
    mode = _workflow_catalog_expect_string(
        policy["mode"], f"{pointer}/mode"
    )
    if mode not in _workflow_catalog_supported_node_recovery_modes:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RECOVERY_INVALID",
            "node recovery mode is unsupported",
            details={"pointer": f"{pointer}/mode", "mode": mode},
        )
    uncertain = _workflow_catalog_expect_string(
        policy["on_uncertain"], f"{pointer}/on_uncertain"
    )
    if uncertain not in _workflow_catalog_supported_node_uncertain_outcomes:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RECOVERY_INVALID",
            "node uncertain-outcome policy is unsupported",
            details={
                "pointer": f"{pointer}/on_uncertain",
                "value": uncertain,
            },
        )
    receipt = _workflow_catalog_expect_bool(
        policy["requires_receipt"], f"{pointer}/requires_receipt"
    )
    resume = _workflow_catalog_expect_bool(
        policy["resume_same_attempt"],
        f"{pointer}/resume_same_attempt",
    )
    if kind == "state":
        valid = (
            mode == "legacy"
            and uncertain == "block"
            and not receipt
            and not resume
        )
    elif mode == "legacy":
        valid = False
    elif effect_classification in {"external-write", "repository-write"}:
        valid = (
            mode in {"manual", "reconcile"}
            and uncertain == "quarantine"
            and receipt
            and (not resume or mode == "reconcile")
        )
    else:
        valid = (
            mode in {"restart", "reconcile"}
            and uncertain == "block"
            and (not resume or (mode == "reconcile" and receipt))
        )
    if not valid:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RECOVERY_INVALID",
            "node recovery fields do not safely cover its effect class",
            details={
                "pointer": pointer,
                "mode": mode,
                "effect_classification": effect_classification,
            },
        )
    return mode


def _workflow_catalog_validate_canonical_strings(
    value: object,
    pointer: str,
    *,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    result = _workflow_catalog_validate_unique_strings(
        value, pointer, allowed=allowed
    )
    canonical = tuple(sorted(result, key=lambda item: item.encode("utf-8")))
    if result != canonical:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action policy arrays must use canonical UTF-8 ordering",
            details={
                "pointer": pointer,
                "expected": list(canonical),
                "actual": list(result),
            },
        )
    return result


def _workflow_catalog_validate_kernel_state_writes(
    value: object, pointer: str
) -> tuple[str, ...]:
    result = _workflow_catalog_validate_canonical_strings(value, pointer)
    for index, item in enumerate(result):
        if (
            not _workflow_catalog_json_pointer_re.fullmatch(item)
            or item == ""
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_JSON_POINTER",
                "kernel action writes must use bounded non-root JSON Pointers",
                details={
                    "pointer": f"{pointer}/{index}",
                    "value": item,
                },
            )
    return result


def _workflow_catalog_validate_action_effect(
    value: object,
    pointer: str,
    *,
    classification: str,
) -> dict[str, object]:
    effect = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        effect, _workflow_catalog_action_effect_fields, pointer
    )
    effect_id = _workflow_catalog_stable_id(
        effect["id"], f"{pointer}/id"
    )
    scopes = _workflow_catalog_validate_canonical_strings(
        effect["scopes"], f"{pointer}/scopes"
    )
    if not scopes:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "every action effect requires at least one canonical scope",
            details={"pointer": f"{pointer}/scopes"},
        )
    concurrency = _workflow_catalog_expect_string(
        effect["concurrency"], f"{pointer}/concurrency"
    )
    if concurrency not in _workflow_catalog_action_concurrency:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action effect concurrency class is unsupported",
            details={
                "pointer": f"{pointer}/concurrency",
                "value": concurrency,
            },
        )
    dependencies = _workflow_catalog_validate_canonical_strings(
        effect["dependencies"], f"{pointer}/dependencies"
    )
    parallel_group_value = effect["parallel_group"]
    parallel_group = (
        None
        if parallel_group_value is None
        else _workflow_catalog_stable_id(
            parallel_group_value, f"{pointer}/parallel_group"
        )
    )
    settlement = _workflow_catalog_expect_string(
        effect["settlement"], f"{pointer}/settlement"
    )
    if settlement not in _workflow_catalog_action_settlements:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action effect settlement contract is unsupported",
            details={"pointer": f"{pointer}/settlement"},
        )
    receipt = _workflow_catalog_expect_string(
        effect["receipt"], f"{pointer}/receipt"
    )
    if not _workflow_catalog_schema_id_re.fullmatch(receipt):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action effect receipt must name a versioned schema",
            details={"pointer": f"{pointer}/receipt", "value": receipt},
        )
    dispatch = _workflow_catalog_expect_string(
        effect["dispatch"], f"{pointer}/dispatch"
    )
    if dispatch not in _workflow_catalog_action_dispatch_modes:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action effect dispatch mode is unsupported",
            details={"pointer": f"{pointer}/dispatch"},
        )
    idempotency = _workflow_catalog_expect_string(
        effect["idempotency"], f"{pointer}/idempotency"
    )
    if idempotency not in _workflow_catalog_action_idempotency_modes:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action effect idempotency policy is unsupported",
            details={"pointer": f"{pointer}/idempotency"},
        )
    target_controls = _workflow_catalog_validate_canonical_strings(
        effect["target_controls"],
        f"{pointer}/target_controls",
        allowed=_workflow_catalog_action_control_ids,
    )
    quarantine = _workflow_catalog_expect_object(
        effect["quarantine"], f"{pointer}/quarantine"
    )
    _workflow_catalog_expect_exact_fields(
        quarantine,
        _workflow_catalog_action_quarantine_fields,
        f"{pointer}/quarantine",
    )
    reconciliation = _workflow_catalog_expect_string(
        quarantine["reconciliation"],
        f"{pointer}/quarantine/reconciliation",
    )
    compensation = _workflow_catalog_expect_string(
        quarantine["compensation"],
        f"{pointer}/quarantine/compensation",
    )
    if (
        reconciliation
        not in _workflow_catalog_action_quarantine_reconciliation
        or compensation not in _workflow_catalog_action_compensation
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action effect quarantine closure is unsupported",
            details={"pointer": f"{pointer}/quarantine"},
        )
    recovery = _workflow_catalog_expect_object(
        effect["recovery"], f"{pointer}/recovery"
    )
    _workflow_catalog_expect_exact_fields(
        recovery,
        _workflow_catalog_action_recovery_fields,
        f"{pointer}/recovery",
    )
    recovery_mode = _workflow_catalog_expect_string(
        recovery["mode"], f"{pointer}/recovery/mode"
    )
    uncertain = _workflow_catalog_expect_string(
        recovery["on_uncertain"],
        f"{pointer}/recovery/on_uncertain",
    )
    redispatch = _workflow_catalog_expect_string(
        recovery["redispatch"], f"{pointer}/recovery/redispatch"
    )
    if (
        recovery_mode not in _workflow_catalog_action_recovery_modes
        or uncertain not in _workflow_catalog_action_recovery_uncertain
        or redispatch not in _workflow_catalog_action_recovery_redispatch
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action effect recovery contract is unsupported",
            details={"pointer": f"{pointer}/recovery"},
        )
    if dispatch == "none":
        valid = (
            idempotency == "not-applicable"
            and not target_controls
            and reconciliation == "not-applicable"
            and compensation == "not-applicable"
            and recovery_mode == "re-evaluate/v1"
            and uncertain == "block"
        )
    else:
        valid = (
            idempotency == "execution-effect-key/v1"
            and target_controls
            == tuple(
                sorted(
                    _workflow_catalog_action_control_ids,
                    key=lambda item: item.encode("utf-8"),
                )
            )
            and reconciliation == "target-bound/v1"
            and compensation == "new-authorized-execution/v1"
            and recovery_mode == "observe-or-quarantine/v1"
            and uncertain == "quarantine"
        )
    if not valid:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "dispatch, idempotency, controls, quarantine, and recovery must "
            "form one closed action-effect contract",
            details={"pointer": pointer, "dispatch": dispatch},
        )
    if (
        settlement == "asynchronous-handoff"
        and dispatch != "single-dispatch"
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "asynchronous handoff requires one single-dispatch effect",
            details={"pointer": f"{pointer}/settlement"},
        )
    result = dict(effect)
    result["id"] = effect_id
    result["scopes"] = list(scopes)
    result["dependencies"] = list(dependencies)
    result["parallel_group"] = parallel_group
    return result


def _workflow_catalog_validate_action(
    value: object,
    pointer: str,
    *,
    node_id: str,
    node_allowed_state_writes: tuple[str, ...],
    declared_contracts: frozenset[ContractReference],
    flow: str,
    legacy_adapter: bool,
    workflow_version: int,
) -> tuple[
    str,
    dict[str, object],
    set[ContractReference],
    dict[str, object] | None,
    str | None,
]:
    action = _workflow_catalog_expect_object(value, pointer)
    fields = (
        _workflow_catalog_legacy_action_fields
        if legacy_adapter
        else (
            _workflow_catalog_v4_action_fields
            if workflow_version >= 4
            else _workflow_catalog_action_fields
        )
    )
    _workflow_catalog_expect_exact_fields(action, fields, pointer)
    action_id = _workflow_catalog_stable_id(
        action["id"], f"{pointer}/id"
    )
    references: set[ContractReference] = set()
    handler = _workflow_catalog_contract_reference(
        action["handler"], f"{pointer}/handler"
    )
    if handler.registry != "executors":
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_CONTRACT",
            "node action handlers must use the executor registry",
            details={"pointer": f"{pointer}/handler"},
        )
    references.add(handler)
    for field, expected_registry in (
        ("guards", "guards"),
        ("reducers", "reducers"),
    ):
        for contract_index, contract_value in enumerate(
            _workflow_catalog_expect_list(
                action[field], f"{pointer}/{field}"
            )
        ):
            reference = _workflow_catalog_contract_reference(
                contract_value,
                f"{pointer}/{field}/{contract_index}",
            )
            if reference.registry != expected_registry:
                raise WorkflowCatalogError(
                    "WORKFLOW_INVALID_CONTRACT",
                    "node action contract uses the wrong registry",
                    details={
                        "pointer": f"{pointer}/{field}/{contract_index}"
                    },
                )
            references.add(reference)
    gate_value = action["gate"]
    if gate_value is not None:
        gate = _workflow_catalog_contract_reference(
            gate_value, f"{pointer}/gate"
        )
        if gate.registry != "gates":
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_CONTRACT",
                "node action gate must use the gate registry",
                details={"pointer": f"{pointer}/gate"},
            )
        references.add(gate)
    handler_closure: list[dict[str, object]] | None = None
    if workflow_version >= 4 and not legacy_adapter:
        handler_closure = []
        closure_references: set[ContractReference] = set()
        roles: list[str] = []
        for index, item_value in enumerate(
            _workflow_catalog_expect_list(
                action["handler_closure"],
                f"{pointer}/handler_closure",
            )
        ):
            item_pointer = f"{pointer}/handler_closure/{index}"
            item = _workflow_catalog_expect_object(item_value, item_pointer)
            _workflow_catalog_expect_exact_fields(
                item,
                _workflow_catalog_handler_closure_fields,
                item_pointer,
            )
            role = _workflow_catalog_expect_string(
                item["role"], f"{item_pointer}/role"
            )
            handler_reference = _workflow_catalog_contract_reference(
                item["handler"], f"{item_pointer}/handler"
            )
            expected_identifier = f"executor.v4-{role}/v2"
            if (
                role not in _workflow_catalog_v4_handler_closure_roles
                or handler_reference.registry != "executors"
                or handler_reference.identifier != expected_identifier
                or handler_reference.version != "v2"
            ):
                raise WorkflowCatalogError(
                    "WORKFLOW_HANDLER_CLOSURE_INVALID",
                    "V4 action closure must bind each role to its exact "
                    "versioned executor contract",
                    details={
                        "pointer": item_pointer,
                        "role": role,
                        "expected_id": expected_identifier,
                    },
                )
            roles.append(role)
            closure_references.add(handler_reference)
            handler_closure.append(
                {
                    "role": role,
                    "handler": dict(item["handler"]),
                }
            )
        if tuple(roles) != _workflow_catalog_v4_handler_closure_roles:
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CLOSURE_INVALID",
                "V4 action closure must contain every transitive handler role "
                "exactly once in canonical UTF-8 order",
                details={
                    "pointer": f"{pointer}/handler_closure",
                    "expected": list(
                        _workflow_catalog_v4_handler_closure_roles
                    ),
                    "actual": roles,
                },
            )
        references.update(closure_references)
    if not references.issubset(declared_contracts):
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNDECLARED",
            "node action references a contract absent from bundle declarations",
            details={"pointer": pointer},
        )
    if legacy_adapter:
        return action_id, dict(action), references, None, None
    if not _workflow_catalog_versioned_action_id_re.fullmatch(action_id):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "schema-v3 semantic action IDs must be explicitly versioned",
            details={"pointer": f"{pointer}/id", "action_id": action_id},
        )

    edge_id = _workflow_catalog_stable_id(
        action["edge_id"], f"{pointer}/edge_id"
    )
    if not _workflow_catalog_versioned_action_id_re.fullmatch(edge_id):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "schema-v3 action-edge IDs must be explicitly versioned",
            details={"pointer": f"{pointer}/edge_id", "edge_id": edge_id},
        )
    public_command = _workflow_catalog_expect_object(
        action["public_command"], f"{pointer}/public_command"
    )
    _workflow_catalog_expect_exact_fields(
        public_command,
        _workflow_catalog_public_command_fields,
        f"{pointer}/public_command",
    )
    command_id = _workflow_catalog_stable_id(
        public_command["id"], f"{pointer}/public_command/id"
    )
    selector_value = public_command["selector"]
    selector = (
        None
        if selector_value is None
        else _workflow_catalog_stable_id(
            selector_value, f"{pointer}/public_command/selector"
        )
    )
    selector_values = _workflow_catalog_validate_canonical_strings(
        public_command["values"], f"{pointer}/public_command/values"
    )
    for index, item in enumerate(selector_values):
        if command_id == "orchestration" and selector == "operation":
            _workflow_catalog_versioned_operation_id(
                item, f"{pointer}/public_command/values/{index}"
            )
        else:
            _workflow_catalog_stable_id(
                item, f"{pointer}/public_command/values/{index}"
            )
    if (selector is None) != (not selector_values):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "a public command selector and its canonical values must be "
            "declared together",
            details={"pointer": f"{pointer}/public_command"},
        )
    trigger = _workflow_catalog_expect_object(
        action["trigger"], f"{pointer}/trigger"
    )
    _workflow_catalog_expect_exact_fields(
        trigger, _workflow_catalog_trigger_fields, f"{pointer}/trigger"
    )
    if trigger["kind"] != "action" or trigger["id"] != action_id:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "same-node action triggers must bind the exact semantic action ID",
            details={"pointer": f"{pointer}/trigger"},
        )
    canonical_event = _workflow_catalog_stable_id(
        action["canonical_event"], f"{pointer}/canonical_event"
    )
    confirmation = _workflow_catalog_expect_string(
        action["confirmation"], f"{pointer}/confirmation"
    )
    if confirmation not in SUPPORTED_CONFIRMATION_MODES or confirmation in {
        "automatic",
        "legacy",
    }:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "same-node actions require one explicit non-legacy confirmation "
            "contract",
            details={"pointer": f"{pointer}/confirmation"},
        )
    requires_note = _workflow_catalog_expect_bool(
        action["requires_note"], f"{pointer}/requires_note"
    )
    guard_ids = tuple(
        reference.identifier
        for reference in references
        if reference.registry == "guards"
    )
    if requires_note != ("guard.note-required/v1" in guard_ids):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_NOTE_POLICY_MISMATCH",
            "requires_note and guard.note-required/v1 must be bidirectionally "
            "consistent",
            details={"pointer": pointer, "action_id": action_id},
        )
    allowed_writes = _workflow_catalog_validate_state_writes(
        action["allowed_state_writes"],
        f"{pointer}/allowed_state_writes",
        allow_kernel_status=False,
    )
    outside_node = sorted(
        set(allowed_writes) - set(node_allowed_state_writes)
    )
    if outside_node:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action reducer writes must be a subset of its node write grants",
            details={"pointer": pointer, "paths": outside_node},
        )
    kernel_writes = _workflow_catalog_validate_kernel_state_writes(
        action["kernel_state_writes"],
        f"{pointer}/kernel_state_writes",
    )
    invalidates = _workflow_catalog_validate_kernel_state_writes(
        action["kernel_invalidates"],
        f"{pointer}/kernel_invalidates",
    )
    overlap = sorted(
        set(allowed_writes) & (set(kernel_writes) | set(invalidates))
    )
    if overlap:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "node and kernel action-write sets must be disjoint",
            details={"pointer": pointer, "paths": overlap},
        )
    kernel_effects = _workflow_catalog_validate_canonical_strings(
        action["kernel_effects"], f"{pointer}/kernel_effects"
    )
    unknown_kernel_effects = sorted(
        set(kernel_effects) - _workflow_catalog_supported_kernel_effects
    )
    if unknown_kernel_effects or not kernel_effects:
        raise WorkflowCatalogError(
            "WORKFLOW_KERNEL_EFFECT_INVALID",
            "same-node actions require a non-empty supported kernel effect set",
            details={
                "pointer": f"{pointer}/kernel_effects",
                "effects": unknown_kernel_effects,
            },
        )
    side_effects = _workflow_catalog_validate_canonical_strings(
        action["side_effects"], f"{pointer}/side_effects"
    )
    unknown_side_effects = sorted(
        set(side_effects) - _workflow_catalog_supported_edge_effects
    )
    if unknown_side_effects or not side_effects:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "same-node actions require a non-empty supported effect set",
            details={
                "pointer": f"{pointer}/side_effects",
                "effects": unknown_side_effects,
            },
        )
    classification = _workflow_catalog_expect_string(
        action["effect_classification"],
        f"{pointer}/effect_classification",
    )
    supported_effect_classes = (
        _workflow_catalog_supported_executor_effect_classifications.get(
            handler.identifier
        )
    )
    if (
        classification
        not in _workflow_catalog_supported_node_effect_classifications
        or supported_effect_classes is None
        or classification not in supported_effect_classes
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "action effect class is incompatible with its sealed executor",
            details={
                "pointer": f"{pointer}/effect_classification",
                "executor": handler.identifier,
                "classification": classification,
            },
        )
    effects: list[dict[str, object]] = []
    effect_ids: set[str] = set()
    for index, effect_value in enumerate(
        _workflow_catalog_expect_list(
            action["effects"], f"{pointer}/effects"
        )
    ):
        effect = _workflow_catalog_validate_action_effect(
            effect_value,
            f"{pointer}/effects/{index}",
            classification=classification,
        )
        effect_id = str(effect["id"])
        if effect_id in effect_ids:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "action effect IDs must be unique",
                details={"pointer": f"{pointer}/effects/{index}"},
            )
        effect_ids.add(effect_id)
        effects.append(effect)
    if not effects:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "every schema-v3 action requires at least one exact effect",
            details={"pointer": f"{pointer}/effects"},
        )
    for effect in effects:
        unknown_dependencies = sorted(
            set(effect["dependencies"]) - effect_ids
        )
        if unknown_dependencies or effect["id"] in effect["dependencies"]:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_POLICY_INVALID",
                "action effect dependencies must reference other effects in "
                "the same action",
                details={
                    "pointer": f"{pointer}/effects",
                    "dependencies": unknown_dependencies,
                },
            )
    visiting: set[str] = set()
    visited: set[str] = set()
    dependencies_by_id = {
        str(effect["id"]): tuple(effect["dependencies"])
        for effect in effects
    }

    def visit(effect_id: str) -> None:
        if effect_id in visiting:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_POLICY_INVALID",
                "action effect dependencies must be acyclic",
                details={"pointer": f"{pointer}/effects"},
            )
        if effect_id in visited:
            return
        visiting.add(effect_id)
        for dependency in dependencies_by_id[effect_id]:
            visit(str(dependency))
        visiting.remove(effect_id)
        visited.add(effect_id)

    for effect_id in sorted(effect_ids):
        visit(effect_id)
    artifact_kinds = _workflow_catalog_validate_canonical_strings(
        action["allowed_artifact_kinds"],
        f"{pointer}/allowed_artifact_kinds",
    )
    for index, item in enumerate(artifact_kinds):
        _workflow_catalog_stable_id(
            item, f"{pointer}/allowed_artifact_kinds/{index}"
        )
    if command_id == "record-artifact":
        if (
            selector != "kind"
            or not artifact_kinds
            or selector_values != artifact_kinds
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_POLICY_INVALID",
                "record-artifact actions must exactly allowlist their kind "
                "selector values",
                details={"pointer": pointer},
            )
    elif artifact_kinds:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "only record-artifact actions may declare artifact kinds",
            details={"pointer": f"{pointer}/allowed_artifact_kinds"},
        )
    resume_policy_value = action["resume_policy"]
    if resume_policy_value is None:
        resume_policy = None
    else:
        resume_policy = _workflow_catalog_expect_object(
            resume_policy_value, f"{pointer}/resume_policy"
        )
        _workflow_catalog_expect_exact_fields(
            resume_policy,
            _workflow_catalog_action_resume_fields,
            f"{pointer}/resume_policy",
        )
        if resume_policy["target"] != "blocked.from_status":
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_RESUME_POLICY_INVALID",
                "resume actions must target the exact recorded blocked status",
                details={"pointer": f"{pointer}/resume_policy/target"},
            )
        safety_guard = resume_policy["safety_guard"]
        if safety_guard is not None:
            _workflow_catalog_expect_string(
                safety_guard,
                f"{pointer}/resume_policy/safety_guard",
            )
        if flow == "lite" and safety_guard != "guard.lite-risk-safe/v1":
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_RESUME_POLICY_INVALID",
                "lite resume requires the current safety/risk guard",
                details={"pointer": f"{pointer}/resume_policy"},
            )
    tool_policy_value = action["tool_policy"]
    if tool_policy_value is None:
        tool_policy = None
    else:
        tool_policy = _workflow_catalog_expect_object(
            tool_policy_value, f"{pointer}/tool_policy"
        )
        _workflow_catalog_expect_exact_fields(
            tool_policy,
            _workflow_catalog_action_tool_fields,
            f"{pointer}/tool_policy",
        )
        capabilities = _workflow_catalog_validate_canonical_strings(
            tool_policy["capabilities"],
            f"{pointer}/tool_policy/capabilities",
        )
        if not capabilities:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
                "external-tool actions require least-capability declarations",
                details={"pointer": f"{pointer}/tool_policy/capabilities"},
            )
        for index, capability in enumerate(capabilities):
            _workflow_catalog_versioned_operation_id(
                capability,
                f"{pointer}/tool_policy/capabilities/{index}",
            )
        phase = _workflow_catalog_expect_string(
            tool_policy["phase"], f"{pointer}/tool_policy/phase"
        )
        project_identity = _workflow_catalog_expect_string(
            tool_policy["project_identity"],
            f"{pointer}/tool_policy/project_identity",
        )
        source_validation = _workflow_catalog_expect_string(
            tool_policy["source_validation"],
            f"{pointer}/tool_policy/source_validation",
        )
        write_gate = _workflow_catalog_expect_string(
            tool_policy["write_gate"], f"{pointer}/tool_policy/write_gate"
        )
        expected_project = {
            "baseline": "baseline-project",
            "current-generation-workspace": (
                "current-generation-workspace-project"
            ),
        }.get(phase)
        if (
            phase not in _workflow_catalog_action_tool_phases
            or project_identity
            not in _workflow_catalog_action_tool_project_identities
            or project_identity != expected_project
            or source_validation
            not in _workflow_catalog_action_tool_source_validation
            or write_gate not in _workflow_catalog_action_tool_write_gates
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
                "external-tool policy does not bind one exact phase, distinct "
                "project identity, source validation, and write gate",
                details={"pointer": f"{pointer}/tool_policy"},
            )
    if (handler.identifier == "executor.external-tool/v1") != (
        tool_policy is not None
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
            "external-tool executor and explicit tool policy must match",
            details={"pointer": f"{pointer}/tool_policy"},
        )
    if (
        classification == "external-write"
        and (
            tool_policy is None
            or tool_policy["write_gate"] != "host-and-workflow"
        )
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
            "external writes require both current host approval and one "
            "request-bound workflow authorization",
            details={"pointer": f"{pointer}/tool_policy/write_gate"},
        )
    required_suites = _workflow_catalog_validate_canonical_strings(
        action["required_suites"],
        f"{pointer}/required_suites",
        allowed=_workflow_catalog_action_required_suites,
    )
    base_suites = {"action-policy", "action-recovery"}
    if not base_suites.issubset(required_suites) or (
        tool_policy is not None
        and "external-tool-capability-evidence" not in required_suites
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "action closure does not name every required compatibility suite",
            details={"pointer": f"{pointer}/required_suites"},
        )
    normalized = dict(action)
    normalized["public_command"] = {
        "id": command_id,
        "selector": selector,
        "values": list(selector_values),
    }
    normalized["effects"] = effects
    normalized["allowed_artifact_kinds"] = list(artifact_kinds)
    normalized["required_suites"] = list(required_suites)
    normalized["resume_policy"] = resume_policy
    normalized["tool_policy"] = tool_policy
    if handler_closure is not None:
        normalized["handler_closure"] = handler_closure
    action_edge = {
        "id": edge_id,
        "source": node_id,
        "target": node_id,
        "policy": "node-action",
        "class": "action",
        "trigger": dict(trigger),
        "public_command": dict(normalized["public_command"]),
        "canonical_event": canonical_event,
        "handler": dict(action["handler"]),
        **(
            {}
            if handler_closure is None
            else {"handler_closure": handler_closure}
        ),
        "guards": list(action["guards"]),
        "reducers": list(action["reducers"]),
        "gate": (
            None if action["gate"] is None else dict(action["gate"])
        ),
        "confirmation": confirmation,
        "automatic": False,
        "requires_note": requires_note,
        "allowed_state_writes": list(allowed_writes),
        "kernel_state_writes": list(kernel_writes),
        "kernel_effects": list(kernel_effects),
        "kernel_invalidates": list(invalidates),
        "side_effects": list(side_effects),
        "effect_classification": classification,
        "effects": effects,
        "allowed_artifact_kinds": list(artifact_kinds),
        "resume_policy": resume_policy,
        "tool_policy": tool_policy,
        "tool_capabilities": (
            []
            if tool_policy is None
            else list(tool_policy["capabilities"])
        ),
        "required_suites": list(required_suites),
        "priority": 100,
    }
    semantic_fields = {
        key: action_edge[key]
        for key in (
            "canonical_event",
            "public_command",
            "handler",
            *(
                ()
                if handler_closure is None
                else ("handler_closure",)
            ),
            "guards",
            "reducers",
            "gate",
            "confirmation",
            "requires_note",
            "allowed_state_writes",
            "kernel_state_writes",
            "kernel_effects",
            "kernel_invalidates",
            "side_effects",
            "effect_classification",
            "effects",
            "allowed_artifact_kinds",
            "resume_policy",
            "tool_policy",
            "tool_capabilities",
            "required_suites",
        )
    }
    semantic_fingerprint = json.dumps(
        semantic_fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        action_id,
        normalized,
        references,
        action_edge,
        semantic_fingerprint,
    )


def _workflow_catalog_validate_node(
    value: object,
    pointer: str,
    declared_contracts: frozenset[ContractReference],
    declared_schemas: Mapping[str, str],
    inventory: Mapping[str, str],
    playbook_limit: int,
    bundle_root: Path,
    *,
    legacy_adapter: bool,
    flow: str,
    workflow_version: int,
) -> tuple[
    str,
    dict[str, object],
    set[ContractReference],
    set[str],
    str,
    tuple[dict[str, object], ...],
    dict[str, str],
]:
    node = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_reject_executable_content(node, pointer)
    _workflow_catalog_expect_exact_fields(
        node, _workflow_catalog_node_fields, pointer
    )
    node_id = _workflow_catalog_stable_id(node["id"], f"{pointer}/id")
    kind = _workflow_catalog_expect_string(
        node["kind"], f"{pointer}/kind"
    )
    contract_version = _workflow_catalog_expect_string(
        node["contract_version"], f"{pointer}/contract_version"
    )
    if (
        kind not in _workflow_catalog_supported_node_contracts
        or contract_version
        not in _workflow_catalog_supported_node_contracts.get(kind, ())
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_CONTRACT_UNSUPPORTED",
            "workflow node kind or contract version is unsupported",
            details={
                "pointer": pointer,
                "kind": kind,
                "contract_version": contract_version,
                "compatibility_blocker": True,
            },
        )
    expected_kind = "state" if legacy_adapter else "generic"
    if kind != expected_kind:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_CONTRACT_MISMATCH",
            "legacy adapters and schema-v3 workflows use distinct node kinds",
            details={
                "pointer": f"{pointer}/kind",
                "expected": expected_kind,
                "actual": kind,
            },
        )
    input_schema = _workflow_catalog_validate_schema_id(
        node["input_schema"],
        f"{pointer}/input_schema",
        declared_schemas,
        expected_kind="node-input",
    )
    output_schema = _workflow_catalog_validate_schema_id(
        node["output_schema"],
        f"{pointer}/output_schema",
        declared_schemas,
        expected_kind="node-output",
    )
    if input_schema == output_schema:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_REFERENCE_INVALID",
            "node input and output schemas must have distinct identities",
            details={"pointer": pointer, "schema": input_schema},
        )
    _workflow_catalog_validate_evidence_types(
        node["required_evidence"], f"{pointer}/required_evidence"
    )
    _workflow_catalog_validate_evidence_types(
        node["produced_evidence"], f"{pointer}/produced_evidence"
    )
    _workflow_catalog_validate_context_projection(
        node["context_projection"],
        f"{pointer}/context_projection",
        kind=kind,
    )
    _workflow_catalog_labels(node["labels"], f"{pointer}/labels")
    _workflow_catalog_stable_id(node["phase"], f"{pointer}/phase")
    _workflow_catalog_expect_bool(node["terminal"], f"{pointer}/terminal")
    _workflow_catalog_expect_bool(node["waiting"], f"{pointer}/waiting")
    node_allowed_state_writes = _workflow_catalog_validate_state_writes(
        node["allowed_state_writes"],
        f"{pointer}/allowed_state_writes",
        allow_kernel_status=False,
    )
    action_ids: set[str] = set()
    action_references: set[ContractReference] = set()
    action_edges: list[dict[str, object]] = []
    action_semantics: dict[str, str] = {}
    public_selections: dict[tuple[str, str | None], str] = {}
    normalized_actions: list[dict[str, object]] = []
    for index, action_value in enumerate(
        _workflow_catalog_expect_list(
            node["actions"], f"{pointer}/actions"
        )
    ):
        action_pointer = f"{pointer}/actions/{index}"
        (
            action_id,
            action,
            references,
            action_edge,
            semantic_fingerprint,
        ) = _workflow_catalog_validate_action(
            action_value,
            action_pointer,
            node_id=node_id,
            node_allowed_state_writes=node_allowed_state_writes,
            declared_contracts=declared_contracts,
            flow=flow,
            legacy_adapter=legacy_adapter,
            workflow_version=workflow_version,
        )
        if action_id in action_ids:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "node action IDs must be unique within the node",
                details={"pointer": action_pointer, "id": action_id},
            )
        action_ids.add(action_id)
        normalized_actions.append(action)
        action_references.update(references)
        if action_edge is not None:
            public_command = action_edge["public_command"]
            command_id = str(public_command["id"])
            selector_values = tuple(public_command["values"])
            for selector_value in selector_values or (None,):
                selection_key = (command_id, selector_value)
                previous_edge_id = public_selections.get(selection_key)
                if previous_edge_id is not None:
                    raise WorkflowCatalogError(
                        "WORKFLOW_ACTION_SELECTION_AMBIGUOUS",
                        "a node public command selector must compile to one "
                        "exact action edge",
                        details={
                            "pointer": action_pointer,
                            "node_id": node_id,
                            "command": command_id,
                            "selector": selector_value,
                            "edge_ids": [
                                previous_edge_id,
                                str(action_edge["id"]),
                            ],
                        },
                    )
                public_selections[selection_key] = str(action_edge["id"])
            action_edges.append(action_edge)
        if semantic_fingerprint is not None:
            action_semantics[action_id] = semantic_fingerprint
    node = dict(node)
    node["actions"] = normalized_actions
    if not action_references.issubset(declared_contracts):
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNDECLARED",
            "node action references a contract absent from bundle declarations",
            details={"pointer": f"{pointer}/actions"},
        )
    approval_references = _workflow_catalog_validate_approval_policy(
        node["approval_policy"],
        f"{pointer}/approval_policy",
        kind=kind,
        declared_contracts=declared_contracts,
    )
    effect_classification = _workflow_catalog_validate_effect_policy(
        node["effect_policy"], f"{pointer}/effect_policy"
    )
    retry_mode = _workflow_catalog_validate_retry_policy(
        node["retry_policy"], f"{pointer}/retry_policy"
    )
    _workflow_catalog_validate_recovery_policy(
        node["recovery_policy"],
        f"{pointer}/recovery_policy",
        kind=kind,
        effect_classification=effect_classification,
    )
    if kind == "state" and retry_mode != "never":
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_RETRY_INVALID",
            "state/v1 compatibility nodes cannot create executor retries",
            details={"pointer": f"{pointer}/retry_policy"},
        )
    sections = _workflow_catalog_validate_unique_strings(
        node["required_sections"],
        f"{pointer}/required_sections",
        allowed=SUPPORTED_SECTIONS,
    )
    if not sections:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "every node must declare at least one required response section",
            details={"pointer": f"{pointer}/required_sections"},
        )
    index_role = node["index_role"]
    if index_role is not None and index_role not in SUPPORTED_INDEX_ROLES:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "node index role is unsupported",
            details={"pointer": f"{pointer}/index_role"},
        )
    executor = _workflow_catalog_contract_reference(
        node["executor"], f"{pointer}/executor"
    )
    if executor.registry != "executors" or executor not in declared_contracts:
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNDECLARED",
            "node executor is not declared by the bundle",
            details={"pointer": f"{pointer}/executor"},
        )
    supported_effect_classes = _workflow_catalog_supported_executor_effect_classifications.get(
        executor.identifier
    )
    if (
        supported_effect_classes is None
        or effect_classification not in supported_effect_classes
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "node effect class is incompatible with its sealed executor",
            details={
                "pointer": f"{pointer}/effect_policy/classification",
                "executor": executor.identifier,
                "classification": effect_classification,
            },
        )
    if kind == "state" and (
        executor.identifier != "executor.deterministic/v1"
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_CONTRACT_MISMATCH",
            "state/v1 is a frozen deterministic compatibility node whose "
            "actions retain the exact five-field legacy shape",
            details={"pointer": pointer, "node_id": node_id},
        )
    playbook = _workflow_catalog_expect_object(
        node["playbook"], f"{pointer}/playbook"
    )
    _workflow_catalog_expect_exact_fields(
        playbook,
        _workflow_catalog_playbook_fields,
        f"{pointer}/playbook",
    )
    playbook_path = _workflow_catalog_portable_relative_path(
        playbook["path"], f"{pointer}/playbook/path"
    )
    playbook_anchor = _workflow_catalog_stable_id(
        playbook["anchor"], f"{pointer}/playbook/anchor"
    )
    if inventory.get(playbook_path) != "T":
        raise WorkflowCatalogError(
            "WORKFLOW_REFERENCE_DANGLING",
            "node playbook must resolve to one inventoried text file",
            details={"pointer": f"{pointer}/playbook/path", "path": playbook_path},
        )
    playbook_file = _workflow_catalog_resolve_regular_file(
        bundle_root, playbook_path, pointer=f"{pointer}/playbook/path"
    )
    size = playbook_file.stat().st_size
    if size > playbook_limit:
        raise WorkflowCatalogError(
            "WORKFLOW_PLAYBOOK_TOO_LARGE",
            "node playbook exceeds the bundle projection budget",
            details={
                "path": playbook_path,
                "size": size,
                "max_bytes": playbook_limit,
            },
        )
    playbook_text = playbook_file.read_text(encoding="utf-8")
    heading = f"## {playbook_anchor}"
    if sum(line == heading for line in playbook_text.splitlines()) != 1:
        raise WorkflowCatalogError(
            "WORKFLOW_PLAYBOOK_ANCHOR_INVALID",
            "node playbook anchors must resolve to one exact level-two heading",
            details={
                "pointer": f"{pointer}/playbook/anchor",
                "path": playbook_path,
                "anchor": playbook_anchor,
            },
        )
    return (
        node_id,
        dict(node),
        {executor, *action_references, *approval_references},
        {input_schema, output_schema},
        playbook_path,
        tuple(action_edges),
        action_semantics,
    )


def _workflow_catalog_validate_policy(
    value: object,
    pointer: str,
    declared_contracts: frozenset[ContractReference],
    *,
    flow: str,
    legacy_adapter: bool,
) -> tuple[str, dict[str, object], set[ContractReference]]:
    policy = _workflow_catalog_expect_object(value, pointer)
    _workflow_catalog_expect_exact_fields(
        policy, _workflow_catalog_policy_fields, pointer
    )
    policy_id = _workflow_catalog_stable_id(
        policy["id"], f"{pointer}/id"
    )
    edge_class = _workflow_catalog_expect_string(
        policy["class"], f"{pointer}/class"
    )
    if edge_class not in SUPPORTED_EDGE_CLASSES:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "edge policy class is unsupported",
            details={"pointer": f"{pointer}/class", "value": edge_class},
        )
    confirmation = _workflow_catalog_expect_string(
        policy["confirmation"], f"{pointer}/confirmation"
    )
    if confirmation not in SUPPORTED_CONFIRMATION_MODES:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "edge confirmation mode is unsupported",
            details={"pointer": f"{pointer}/confirmation"},
        )
    automatic = _workflow_catalog_expect_bool(
        policy["automatic"], f"{pointer}/automatic"
    )
    if automatic != (confirmation == "automatic") and confirmation != "legacy":
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "automatic must exactly match automatic confirmation mode",
            details={"pointer": pointer},
        )
    requires_note = _workflow_catalog_expect_bool(
        policy["requires_note"], f"{pointer}/requires_note"
    )
    _workflow_catalog_expect_integer(
        policy["priority"], f"{pointer}/priority"
    )
    trigger = _workflow_catalog_expect_object(
        policy["trigger"], f"{pointer}/trigger"
    )
    _workflow_catalog_expect_exact_fields(
        trigger,
        _workflow_catalog_trigger_fields,
        f"{pointer}/trigger",
    )
    if trigger["kind"] not in {"action", "transition"}:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "edge trigger kind must be action or transition",
            details={"pointer": f"{pointer}/trigger/kind"},
        )
    _workflow_catalog_stable_id(
        trigger["id"], f"{pointer}/trigger/id"
    )
    references: set[ContractReference] = set()
    handler = _workflow_catalog_contract_reference(
        policy["handler"], f"{pointer}/handler"
    )
    if handler.registry != "executors":
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_CONTRACT",
            "edge handlers must resolve through the executor registry",
            details={"pointer": f"{pointer}/handler"},
        )
    references.add(handler)
    for field, expected_registry in (
        ("guards", "guards"),
        ("reducers", "reducers"),
    ):
        for index, item in enumerate(
            _workflow_catalog_expect_list(
                policy[field], f"{pointer}/{field}"
            )
        ):
            reference = _workflow_catalog_contract_reference(
                item, f"{pointer}/{field}/{index}"
            )
            if reference.registry != expected_registry:
                raise WorkflowCatalogError(
                    "WORKFLOW_INVALID_CONTRACT",
                    "workflow contract is in the wrong registry",
                    details={"pointer": f"{pointer}/{field}/{index}"},
                )
            references.add(reference)
    gate_value = policy["gate"]
    if gate_value is not None:
        gate = _workflow_catalog_contract_reference(
            gate_value, f"{pointer}/gate"
        )
        if gate.registry != "gates":
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_CONTRACT",
                "edge gate must resolve through the gate registry",
                details={"pointer": f"{pointer}/gate"},
            )
        references.add(gate)
    if not references.issubset(declared_contracts):
        missing = sorted(references - declared_contracts)
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNDECLARED",
            "edge policy references a contract absent from bundle declarations",
            details={
                "pointer": pointer,
                "contracts": [
                    {
                        "registry": item.registry,
                        "id": item.identifier,
                        "version": item.version,
                    }
                    for item in missing
                ],
            },
        )
    guard_ids = {
        reference.identifier
        for reference in references
        if reference.registry == "guards"
    }
    if requires_note != ("guard.note-required/v1" in guard_ids):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_NOTE_POLICY_MISMATCH",
            "requires_note and guard.note-required/v1 must be bidirectionally "
            "consistent",
            details={"pointer": pointer, "policy_id": policy_id},
        )
    if not legacy_adapter and edge_class == "resume":
        if "guard.blocked-resume/v1" not in guard_ids:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_RESUME_POLICY_INVALID",
                "schema-v3 resume must target blocked.from_status through its "
                "sealed guard",
                details={"pointer": pointer, "policy_id": policy_id},
            )
        if (
            flow == "lite"
            and trigger["id"] == "transition"
            and "guard.lite-risk-safe/v1" not in guard_ids
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_RESUME_POLICY_INVALID",
                "generic lite resume requires the current safety/risk guard",
                details={"pointer": pointer, "policy_id": policy_id},
            )
    allowed_writes = _workflow_catalog_validate_state_writes(
        policy["allowed_state_writes"],
        f"{pointer}/allowed_state_writes",
        allow_kernel_status=True,
    )
    invalidates = _workflow_catalog_validate_unique_strings(
        policy["kernel_invalidates"], f"{pointer}/kernel_invalidates"
    )
    for index, item in enumerate(invalidates):
        if not _workflow_catalog_json_pointer_re.fullmatch(item) or item == "":
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_JSON_POINTER",
                "kernel invalidations must use bounded JSON Pointers",
                details={
                    "pointer": f"{pointer}/kernel_invalidates/{index}",
                    "value": item,
                },
            )
    overlap = sorted(set(allowed_writes) & set(invalidates))
    if overlap:
        raise WorkflowCatalogError(
            "WORKFLOW_PROTECTED_STATE_WRITE",
            "kernel-owned invalidations cannot also be reducer grants",
            details={"pointer": pointer, "paths": overlap},
        )
    side_effects = _workflow_catalog_validate_unique_strings(
        policy["side_effects"], f"{pointer}/side_effects"
    )
    unknown_side_effects = sorted(set(side_effects) - _workflow_catalog_supported_edge_effects)
    if unknown_side_effects:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "edge policy names unsupported external effects",
            details={
                "pointer": f"{pointer}/side_effects",
                "effects": unknown_side_effects,
            },
        )
    kernel_effects = _workflow_catalog_validate_unique_strings(
        policy["kernel_effects"], f"{pointer}/kernel_effects"
    )
    unknown_kernel_effects = sorted(
        set(kernel_effects) - _workflow_catalog_supported_kernel_effects
    )
    if unknown_kernel_effects:
        raise WorkflowCatalogError(
            "WORKFLOW_KERNEL_EFFECT_INVALID",
            "edge policy names unsupported kernel effects",
            details={
                "pointer": f"{pointer}/kernel_effects",
                "effects": unknown_kernel_effects,
            },
        )
    if "set-task-status" not in kernel_effects:
        raise WorkflowCatalogError(
            "WORKFLOW_KERNEL_EFFECT_INVALID",
            "every workflow transition must declare kernel-owned status movement",
            details={"pointer": f"{pointer}/kernel_effects"},
        )
    if invalidates and not {
        "invalidate-approval",
        "invalidate-evidence",
    }.intersection(kernel_effects):
        raise WorkflowCatalogError(
            "WORKFLOW_KERNEL_EFFECT_INVALID",
            "kernel invalidations require an explicit invalidation effect",
            details={"pointer": pointer},
        )
    if not side_effects:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_EFFECT_INVALID",
            "edge effect requirements must classify task-state movement",
            details={"pointer": f"{pointer}/side_effects"},
        )
    return policy_id, dict(policy), references


def _workflow_catalog_expanded_edges(
    graph: Mapping[str, object],
    policies: Mapping[str, Mapping[str, object]],
    nodes: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    exact_ids: set[str] = set()

    def add(
        edge_id: str,
        source: str,
        target: str,
        policy_id: str,
        pointer: str,
    ) -> None:
        if edge_id in exact_ids:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "edge IDs must be unique after family expansion",
                details={"pointer": pointer, "id": edge_id},
            )
        if source not in nodes or target not in nodes:
            raise WorkflowCatalogError(
                "WORKFLOW_REFERENCE_DANGLING",
                "edge refers to an unknown source or target node",
                details={
                    "pointer": pointer,
                    "source": source,
                    "target": target,
                },
            )
        try:
            policy = policies[policy_id]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_REFERENCE_DANGLING",
                "edge refers to an unknown policy",
                details={"pointer": pointer, "policy": policy_id},
            ) from exc
        edge = {
            "id": edge_id,
            "source": source,
            "target": target,
            "policy": policy_id,
            **dict(policy),
        }
        edge["id"] = edge_id
        exact_ids.add(edge_id)
        result.append(edge)

    for index, value in enumerate(
        _workflow_catalog_expect_list(graph["edges"], "/edges")
    ):
        pointer = f"/edges/{index}"
        edge = _workflow_catalog_expect_object(value, pointer)
        _workflow_catalog_expect_exact_fields(
            edge, _workflow_catalog_edge_fields, pointer
        )
        add(
            _workflow_catalog_stable_id(
                edge["id"], f"{pointer}/id"
            ),
            _workflow_catalog_stable_id(
                edge["source"], f"{pointer}/source"
            ),
            _workflow_catalog_stable_id(
                edge["target"], f"{pointer}/target"
            ),
            _workflow_catalog_stable_id(
                edge["policy"], f"{pointer}/policy"
            ),
            pointer,
        )
    for index, value in enumerate(
        _workflow_catalog_expect_list(
            graph["edge_families"], "/edge_families"
        )
    ):
        pointer = f"/edge_families/{index}"
        family = _workflow_catalog_expect_object(value, pointer)
        _workflow_catalog_expect_exact_fields(
            family, _workflow_catalog_edge_family_fields, pointer
        )
        prefix = _workflow_catalog_stable_id(
            family["id_prefix"], f"{pointer}/id_prefix"
        )
        sources = _workflow_catalog_validate_unique_strings(
            family["sources"], f"{pointer}/sources"
        )
        targets = _workflow_catalog_validate_unique_strings(
            family["targets"], f"{pointer}/targets"
        )
        if (
            not sources
            or not targets
            or (len(sources) > 1 and len(targets) > 1)
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_EDGE_FAMILY",
                "edge families must expand one source or one target, "
                "not a cross product",
                details={"pointer": pointer},
            )
        policy_id = _workflow_catalog_stable_id(
            family["policy"], f"{pointer}/policy"
        )
        for source in sources:
            source_id = _workflow_catalog_stable_id(
                source, f"{pointer}/sources"
            )
            for target in targets:
                target_id = _workflow_catalog_stable_id(
                    target, f"{pointer}/targets"
                )
                suffix = (
                    source_id.lower().replace("_", "-")
                    + "."
                    + target_id.lower().replace("_", "-")
                )
                add(
                    f"{prefix}.{suffix}",
                    source_id,
                    target_id,
                    policy_id,
                    pointer,
                )
    return tuple(
        sorted(result, key=lambda item: str(item["id"]).encode("utf-8"))
    )


def _workflow_catalog_validate_graph_topology(
    nodes: Mapping[str, Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    entries: tuple[str, ...],
    terminals: tuple[str, ...],
) -> None:
    node_ids = set(nodes)
    entry_set = set(entries)
    terminal_set = set(terminals)
    if not entry_set or not terminal_set:
        raise WorkflowCatalogError(
            "WORKFLOW_GRAPH_INCOMPLETE",
            "workflow graph requires entry and terminal nodes",
        )
    if not entry_set.issubset(node_ids) or not terminal_set.issubset(node_ids):
        raise WorkflowCatalogError(
            "WORKFLOW_REFERENCE_DANGLING",
            "entry or terminal node is not defined",
        )
    for node_id, node in nodes.items():
        if bool(node["terminal"]) != (node_id in terminal_set):
            raise WorkflowCatalogError(
                "WORKFLOW_TERMINAL_MISMATCH",
                "terminal declarations must exactly match node metadata",
                details={"node_id": node_id},
            )
    adjacency = {node_id: [] for node_id in node_ids}
    reverse = {node_id: [] for node_id in node_ids}
    ordinary = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        edge_class = str(edge["class"])
        if source in terminal_set:
            raise WorkflowCatalogError(
                "WORKFLOW_TERMINAL_OUTGOING",
                "terminal workflow nodes must not have outgoing edges",
                details={"edge_id": edge["id"], "source": source},
            )
        if edge_class == "block" and not bool(nodes[target]["waiting"]):
            raise WorkflowCatalogError(
                "WORKFLOW_EDGE_CLASS_INVALID",
                "block edges must target a declared waiting node",
                details={"edge_id": edge["id"], "target": target},
            )
        if edge_class == "resume" and not bool(nodes[source]["waiting"]):
            raise WorkflowCatalogError(
                "WORKFLOW_EDGE_CLASS_INVALID",
                "resume edges must originate at a declared waiting node",
                details={"edge_id": edge["id"], "source": source},
            )
        if edge_class == "cancel" and target not in terminal_set:
            raise WorkflowCatalogError(
                "WORKFLOW_EDGE_CLASS_INVALID",
                "cancel edges must target a declared terminal node",
                details={"edge_id": edge["id"], "target": target},
            )
        adjacency[source].append(target)
        reverse[target].append(source)
        if bool(edge["automatic"]) and target in terminal_set:
            raise WorkflowCatalogError(
                "WORKFLOW_TERMINAL_AUTOMATIC",
                "terminal edges can never be automatic",
                details={"edge_id": edge["id"], "target": target},
            )
        if edge_class not in {"rework", "retry", "resume"}:
            ordinary[source].append(target)
    reachable: set[str] = set()
    stack = list(reversed(entries))
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(reversed(adjacency[node_id]))
    unreachable = sorted(node_ids - reachable)
    if unreachable:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_UNREACHABLE",
            "workflow contains nodes unreachable from every entry",
            details={"nodes": unreachable},
        )
    exiting: set[str] = set()
    stack = list(reversed(terminals))
    while stack:
        node_id = stack.pop()
        if node_id in exiting:
            continue
        exiting.add(node_id)
        stack.extend(reversed(reverse[node_id]))
    no_exit = sorted(
        node_id
        for node_id in node_ids - exiting
        if not bool(nodes[node_id]["waiting"])
    )
    if no_exit:
        raise WorkflowCatalogError(
            "WORKFLOW_NO_TERMINAL_EXIT",
            "reachable non-waiting nodes must have a path to a terminal",
            details={"nodes": no_exit},
        )
    colors: dict[str, int] = {node_id: 0 for node_id in node_ids}
    path: list[str] = []

    def visit(node_id: str) -> None:
        colors[node_id] = 1
        path.append(node_id)
        for target in ordinary[node_id]:
            if colors[target] == 1:
                cycle_start = path.index(target)
                raise WorkflowCatalogError(
                    "WORKFLOW_IMPLICIT_CYCLE",
                    "workflow cycles must close through explicit retry, "
                    "rework, or resume edges",
                    details={"nodes": path[cycle_start:] + [target]},
                )
            if colors[target] == 0:
                visit(target)
        path.pop()
        colors[node_id] = 2

    for node_id in sorted(node_ids):
        if colors[node_id] == 0:
            visit(node_id)


def _workflow_catalog_expand_shared_actions(
    graph: Mapping[str, object],
    *,
    legacy_adapter: bool,
    workflow_version: int,
) -> tuple[list[dict[str, object]], dict[str, frozenset[str]]]:
    """Expand identity-covered action templates into explicit node actions."""

    node_values = _workflow_catalog_expect_list(
        graph["nodes"], "/nodes"
    )
    expanded: list[dict[str, object]] = []
    node_indexes: dict[str, int] = {}
    for index, node_value in enumerate(node_values):
        pointer = f"/nodes/{index}"
        node = dict(_workflow_catalog_expect_object(node_value, pointer))
        node_id = _workflow_catalog_stable_id(
            node.get("id"), f"{pointer}/id"
        )
        if node_id in node_indexes:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "workflow node IDs must be unique",
                details={"id": node_id},
            )
        actions = _workflow_catalog_expect_list(
            node.get("actions"), f"{pointer}/actions"
        )
        node["actions"] = list(actions)
        node_indexes[node_id] = index
        expanded.append(node)
    shared_values = _workflow_catalog_expect_list(
        graph.get("shared_actions", []), "/shared_actions"
    )
    injected_edge_ids: dict[str, set[str]] = {}
    if legacy_adapter and shared_values:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_POLICY_INVALID",
            "legacy workflow adapters cannot declare shared schema-v3 actions",
            details={"pointer": "/shared_actions"},
        )
    for family_index, family_value in enumerate(shared_values):
        family_pointer = f"/shared_actions/{family_index}"
        family = _workflow_catalog_expect_object(
            family_value, family_pointer
        )
        _workflow_catalog_expect_exact_fields(
            family,
            _workflow_catalog_shared_action_fields,
            family_pointer,
        )
        template = _workflow_catalog_expect_object(
            family["action"], f"{family_pointer}/action"
        )
        _workflow_catalog_expect_exact_fields(
            template,
            (
                _workflow_catalog_v4_action_fields
                if workflow_version >= 4
                else _workflow_catalog_action_fields
            )
            - {"edge_id"},
            f"{family_pointer}/action",
        )
        placements = _workflow_catalog_expect_list(
            family["placements"], f"{family_pointer}/placements"
        )
        if not placements:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_POLICY_INVALID",
                "shared actions require at least one explicit node placement",
                details={"pointer": f"{family_pointer}/placements"},
            )
        placed_nodes: set[str] = set()
        for placement_index, placement_value in enumerate(placements):
            placement_pointer = (
                f"{family_pointer}/placements/{placement_index}"
            )
            placement = _workflow_catalog_expect_object(
                placement_value, placement_pointer
            )
            _workflow_catalog_expect_exact_fields(
                placement,
                _workflow_catalog_shared_action_placement_fields,
                placement_pointer,
            )
            node_id = _workflow_catalog_stable_id(
                placement["node"], f"{placement_pointer}/node"
            )
            if node_id not in node_indexes:
                raise WorkflowCatalogError(
                    "WORKFLOW_REFERENCE_DANGLING",
                    "shared action placement names an unknown node",
                    details={
                        "pointer": f"{placement_pointer}/node",
                        "node_id": node_id,
                    },
                )
            if node_id in placed_nodes:
                raise WorkflowCatalogError(
                    "WORKFLOW_DUPLICATE_ID",
                    "one shared action can be placed only once per node",
                    details={
                        "pointer": placement_pointer,
                        "node_id": node_id,
                    },
                )
            placed_nodes.add(node_id)
            edge_id = _workflow_catalog_stable_id(
                placement["edge_id"], f"{placement_pointer}/edge_id"
            )
            if not _workflow_catalog_versioned_action_id_re.fullmatch(
                edge_id
            ):
                raise WorkflowCatalogError(
                    "WORKFLOW_ACTION_POLICY_INVALID",
                    "shared action-edge IDs must be explicitly versioned",
                    details={
                        "pointer": f"{placement_pointer}/edge_id",
                        "edge_id": edge_id,
                    },
                )
            action = dict(template)
            action["edge_id"] = edge_id
            expanded[node_indexes[node_id]]["actions"].append(action)
            injected_edge_ids.setdefault(node_id, set()).add(edge_id)
    return (
        expanded,
        {
            node_id: frozenset(edge_ids)
            for node_id, edge_ids in injected_edge_ids.items()
        },
    )


def _workflow_catalog_validate_tool_capabilities(
    graph: Mapping[str, object],
    action_edges: Sequence[Mapping[str, object]],
    *,
    legacy_adapter: bool,
) -> tuple[Mapping[str, object], ...]:
    """Validate the identity-covered external-tool declaration closure."""

    declarations = _workflow_catalog_expect_list(
        graph.get("tool_capabilities", []), "/tool_capabilities"
    )
    if legacy_adapter and declarations:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
            "legacy workflow adapters cannot expose external tools",
            details={"pointer": "/tool_capabilities"},
        )
    normalized: list[dict[str, object]] = []
    declared_ids: list[str] = []
    for index, supplied in enumerate(declarations):
        pointer = f"/tool_capabilities/{index}"
        declaration = _workflow_catalog_expect_object(supplied, pointer)
        _workflow_catalog_expect_exact_fields(
            declaration,
            _workflow_catalog_tool_capability_fields,
            pointer,
        )
        if (
            declaration["schema"]
            != _workflow_catalog_tool_capability_schema
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
                "external-tool capability schema is unsupported",
                details={"pointer": f"{pointer}/schema"},
            )
        capability_id = _workflow_catalog_versioned_operation_id(
            declaration["capability_id"],
            f"{pointer}/capability_id",
        )
        tool_id = _workflow_catalog_stable_id(
            declaration["tool_id"], f"{pointer}/tool_id"
        )
        operations = _workflow_catalog_validate_canonical_strings(
            declaration["operations"],
            f"{pointer}/operations",
            allowed=_workflow_catalog_tool_operations,
        )
        if not operations:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
                "external-tool capability operations cannot be empty",
                details={"pointer": f"{pointer}/operations"},
            )
        result_schema = _workflow_catalog_versioned_operation_id(
            declaration["result_schema"],
            f"{pointer}/result_schema",
        )
        scopes = _workflow_catalog_validate_canonical_strings(
            declaration["scopes"], f"{pointer}/scopes"
        )
        if not scopes:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
                "external-tool capability scopes cannot be empty",
                details={"pointer": f"{pointer}/scopes"},
            )
        for scope_index, scope in enumerate(scopes):
            _workflow_catalog_stable_id(
                scope, f"{pointer}/scopes/{scope_index}"
            )
        declared_ids.append(capability_id)
        normalized.append(
            {
                "schema": _workflow_catalog_tool_capability_schema,
                "capability_id": capability_id,
                "tool_id": tool_id,
                "operations": list(operations),
                "result_schema": result_schema,
                "scopes": list(scopes),
            }
        )
    if declared_ids != sorted(declared_ids) or len(
        declared_ids
    ) != len(set(declared_ids)):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
            "external-tool declarations must have unique UTF-8 ordered IDs",
            details={"pointer": "/tool_capabilities"},
        )
    used_ids: set[str] = set()
    declared_set = set(declared_ids)
    for edge in action_edges:
        policy = edge.get("tool_policy")
        edge_capabilities = (
            ()
            if policy is None
            else tuple(policy.get("capabilities", ()))
        )
        if tuple(edge.get("tool_capabilities", ())) != edge_capabilities:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
                "compiled action edge does not preserve exact tool IDs",
                details={"edge_id": edge.get("id")},
            )
        undeclared = sorted(set(edge_capabilities) - declared_set)
        if undeclared:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
                "action edge references an undeclared external tool",
                details={
                    "edge_id": edge.get("id"),
                    "capabilities": undeclared,
                },
            )
        used_ids.update(str(item) for item in edge_capabilities)
    unused = sorted(declared_set - used_ids)
    if unused:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
            "unused external tools cannot be exposed by the workflow",
            details={"capabilities": unused},
        )
    return tuple(
        _workflow_catalog_freeze(item) for item in normalized
    )


def _workflow_catalog_validate_workflow_graph(
    graph_value: object,
    *,
    expected_entry: Mapping[str, object],
    inventory: Mapping[str, str],
    bundle_root: Path,
    contract_resolver: object,
) -> tuple[
    Mapping[str, object],
    Mapping[str, Mapping[str, object]],
    tuple[Mapping[str, object], ...],
    tuple[ContractReference, ...],
    tuple[str, ...],
    tuple[Mapping[str, object], ...],
]:
    graph = _workflow_catalog_expect_object(graph_value, "/")
    _workflow_catalog_reject_executable_content(graph, "")
    _workflow_catalog_expect_allowed_fields(
        graph,
        _workflow_catalog_workflow_fields
        | _workflow_catalog_workflow_optional_fields,
        _workflow_catalog_workflow_fields,
        "/",
    )
    if graph["schema"] != WORKFLOW_SCHEMA:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_UNSUPPORTED",
            "workflow schema is unsupported",
            details={"schema": graph["schema"]},
        )
    if graph["identity_contract"] != BUNDLE_IDENTITY_CONTRACT:
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_CONTRACT_UNSUPPORTED",
            "workflow identity contract is unsupported",
        )
    bundle_schema_version = _workflow_catalog_expect_integer(
        graph["bundle_schema_version"], "/bundle_schema_version", minimum=1
    )
    if bundle_schema_version not in SUPPORTED_BUNDLE_SCHEMA_VERSIONS:
        raise WorkflowCatalogError(
            "WORKFLOW_BUNDLE_SCHEMA_UNSUPPORTED",
            "workflow bundle schema version is unsupported",
            details={"bundle_schema_version": bundle_schema_version},
        )
    workflow_id = _workflow_catalog_stable_id(
        graph["workflow_id"], "/workflow_id"
    )
    workflow_version = _workflow_catalog_expect_integer(
        graph["workflow_version"], "/workflow_version", minimum=1
    )
    for field, value in (
        ("workflow_id", workflow_id),
        ("workflow_version", workflow_version),
        ("bundle_schema_version", bundle_schema_version),
    ):
        if expected_entry[field] != value:
            raise WorkflowCatalogError(
                "WORKFLOW_CATALOG_GRAPH_MISMATCH",
                "catalog identity does not match the root graph",
                details={
                    "field": field,
                    "catalog": expected_entry[field],
                    "graph": value,
                },
            )
    if graph["flow"] not in {"full", "lite"}:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow flow must be full or lite",
            details={"pointer": "/flow"},
        )
    legacy_adapter = _workflow_catalog_expect_bool(
        graph["legacy_adapter"], "/legacy_adapter"
    )
    task_schema_versions = tuple(
        _workflow_catalog_expect_integer(
            item, f"/task_schema_versions/{index}", minimum=1
        )
        for index, item in enumerate(
            _workflow_catalog_expect_list(
                graph["task_schema_versions"], "/task_schema_versions"
            )
        )
    )
    if not task_schema_versions or len(task_schema_versions) != len(
        set(task_schema_versions)
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "task schema versions must be non-empty and unique",
            details={"pointer": "/task_schema_versions"},
        )
    expected_task_schemas = (1, 2) if legacy_adapter else (3,)
    if task_schema_versions != expected_task_schemas:
        raise WorkflowCatalogError(
            "WORKFLOW_NODE_CONTRACT_MISMATCH",
            "legacy adapters and schema-v3 workflows must be separated",
            details={
                "pointer": "/legacy_adapter",
                "legacy_adapter": legacy_adapter,
                "task_schema_versions": list(task_schema_versions),
                "expected": list(expected_task_schemas),
            },
        )
    profiles = _workflow_catalog_validate_unique_strings(
        graph["execution_profiles"],
        "/execution_profiles",
        allowed=SUPPORTED_EXECUTION_PROFILES,
    )
    if not profiles:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow must support at least one execution profile",
            details={"pointer": "/execution_profiles"},
        )
    if graph["flow"] == "lite" and "multi-repository" in profiles:
        raise WorkflowCatalogError(
            "WORKFLOW_ORCHESTRATION_FORBIDDEN",
            "lite workflows cannot declare multi-repository execution",
            details={"pointer": "/execution_profiles"},
        )
    _workflow_catalog_labels(graph["labels"], "/labels")
    projection = _workflow_catalog_expect_object(
        graph["projection"], "/projection"
    )
    _workflow_catalog_expect_exact_fields(
        projection, _workflow_catalog_projection_fields, "/projection"
    )
    if projection["profile"] != "agent-v1":
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "workflow projection profile must be agent-v1",
            details={"pointer": "/projection/profile"},
        )
    budgets = {
        field: _workflow_catalog_expect_integer(
            projection[field], f"/projection/{field}", minimum=1
        )
        for field in _workflow_catalog_projection_fields - {"profile"}
    }
    if budgets["node_result_summary_max_bytes"] > budgets["node_result_max_bytes"]:
        raise WorkflowCatalogError(
            "WORKFLOW_INVALID_FIELD",
            "node result summary budget cannot exceed result budget",
            details={"pointer": "/projection"},
        )
    schema_refs = _workflow_catalog_expect_object(
        graph["schemas"], "/schemas"
    )
    _workflow_catalog_expect_exact_fields(
        schema_refs, _workflow_catalog_schema_fields, "/schemas"
    )
    contract_schema_id = _workflow_catalog_expect_string(
        schema_refs["contracts"], "/schemas/contracts"
    )
    if not _workflow_catalog_schema_id_re.fullmatch(contract_schema_id):
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_REFERENCE_INVALID",
            "contract schema identity must be portable and versioned",
            details={
                "pointer": "/schemas/contracts",
                "schema": contract_schema_id,
            },
        )
    schema_documents: dict[str, str] = {}
    schema_paths: set[str] = set()
    for index, item_value in enumerate(
        _workflow_catalog_expect_list(
            schema_refs["documents"], "/schemas/documents"
        )
    ):
        item_pointer = f"/schemas/documents/{index}"
        item = _workflow_catalog_expect_object(item_value, item_pointer)
        _workflow_catalog_expect_exact_fields(
            item,
            _workflow_catalog_schema_document_reference_fields,
            item_pointer,
        )
        schema_id = _workflow_catalog_expect_string(
            item["id"], f"{item_pointer}/id"
        )
        if not _workflow_catalog_schema_id_re.fullmatch(schema_id):
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_REFERENCE_INVALID",
                "schema identities must be portable and versioned",
                details={"pointer": f"{item_pointer}/id", "schema": schema_id},
            )
        if schema_id in schema_documents:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "bundle schema identities must be unique",
                details={"pointer": item_pointer, "id": schema_id},
            )
        schema_kind = _workflow_catalog_expect_string(
            item["kind"], f"{item_pointer}/kind"
        )
        if schema_kind not in _workflow_catalog_schema_document_kinds:
            raise WorkflowCatalogError(
                "WORKFLOW_SCHEMA_ROLE_MISMATCH",
                "bundle schema document kind is unsupported",
                details={
                    "pointer": f"{item_pointer}/kind",
                    "kind": schema_kind,
                },
            )
        schema_path = _workflow_catalog_portable_relative_path(
            item["path"], f"{item_pointer}/path"
        )
        if schema_path in schema_paths:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "each bundle schema document must have one exact path",
                details={"pointer": item_pointer, "path": schema_path},
            )
        if inventory.get(schema_path) != "J":
            raise WorkflowCatalogError(
                "WORKFLOW_REFERENCE_DANGLING",
                "bundle schemas must be inventoried JSON files",
                details={"pointer": f"{item_pointer}/path", "path": schema_path},
            )
        schema_document = _workflow_catalog_parse_json_bytes(
            _workflow_catalog_resolve_regular_file(
                bundle_root,
                schema_path,
                pointer=f"{item_pointer}/path",
            ).read_bytes(),
            path=schema_path,
        )
        _workflow_catalog_validate_schema_document(
            schema_document,
            f"{item_pointer}/document",
            schema_id,
            schema_kind,
        )
        schema_documents[schema_id] = schema_kind
        schema_paths.add(schema_path)
    if not schema_documents:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_UNKNOWN",
            "workflow bundles must inventory typed schema documents",
            details={"pointer": "/schemas/documents"},
        )
    if contract_schema_id not in schema_documents:
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_UNKNOWN",
            "contract references require a bundle-local typed schema",
            details={"schema": contract_schema_id},
        )
    if schema_documents[contract_schema_id] != "contract-reference":
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_ROLE_MISMATCH",
            "workflow contract schema must use contract-reference kind",
            details={
                "schema": contract_schema_id,
                "actual_kind": schema_documents[contract_schema_id],
            },
        )
    if "node-input" not in set(schema_documents.values()) or (
        "node-output" not in set(schema_documents.values())
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_UNKNOWN",
            "workflow bundles require typed node input and output schemas",
            details={"pointer": "/schemas/documents"},
        )
    contract_items = _workflow_catalog_expect_list(
        graph["contracts"], "/contracts"
    )
    contracts = tuple(
        _workflow_catalog_contract_reference(
            item, f"/contracts/{index}"
        )
        for index, item in enumerate(contract_items)
    )
    if len(contracts) != len(set(contracts)):
        raise WorkflowCatalogError(
            "WORKFLOW_DUPLICATE_ID",
            "workflow contract references must be unique",
            details={"pointer": "/contracts"},
        )
    contract_set = frozenset(contracts)
    for contract in contracts:
        _workflow_catalog_resolve_contract(contract_resolver, contract)
    (
        expanded_node_values,
        shared_edge_ids_by_node,
    ) = _workflow_catalog_expand_shared_actions(
        graph,
        legacy_adapter=legacy_adapter,
        workflow_version=workflow_version,
    )
    nodes: dict[str, Mapping[str, object]] = {}
    action_edges: list[dict[str, object]] = []
    action_edge_ids: set[str] = set()
    action_semantics: dict[str, str] = {}
    used_contracts: set[ContractReference] = set()
    used_schemas = {contract_schema_id}
    referenced_files = {str(expected_entry["graph"]), *schema_paths}
    for index, node_value in enumerate(expanded_node_values):
        (
            node_id,
            node,
            references,
            node_schemas,
            playbook_path,
            node_action_edges,
            node_action_semantics,
        ) = (
            _workflow_catalog_validate_node(
                node_value,
                f"/nodes/{index}",
                contract_set,
                MappingProxyType(dict(schema_documents)),
                inventory,
                budgets["playbook_max_bytes"],
                bundle_root,
                legacy_adapter=legacy_adapter,
                flow=str(graph["flow"]),
                workflow_version=workflow_version,
            )
        )
        if node_id in nodes:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "workflow node IDs must be unique",
                details={"id": node_id},
            )
        shared_edge_ids = shared_edge_ids_by_node.get(
            node_id, frozenset()
        )
        if shared_edge_ids:
            node = {
                **node,
                "actions": [
                    action
                    for action in node["actions"]
                    if action.get("edge_id") not in shared_edge_ids
                ],
            }
        nodes[node_id] = node
        for action_edge in node_action_edges:
            edge_id = str(action_edge["id"])
            if edge_id in action_edge_ids:
                raise WorkflowCatalogError(
                    "WORKFLOW_DUPLICATE_ID",
                    "compiled action-edge IDs must be bundle-unique",
                    details={"id": edge_id},
                )
            action_edge_ids.add(edge_id)
            action_edges.append(action_edge)
        for action_id, fingerprint in node_action_semantics.items():
            previous = action_semantics.get(action_id)
            if previous is not None and previous != fingerprint:
                raise WorkflowCatalogError(
                    "WORKFLOW_ACTION_SEMANTIC_OVERLOAD",
                    "one action identity cannot name different validators, "
                    "events, writes, or effects",
                    details={"action_id": action_id, "node_id": node_id},
                )
            action_semantics[action_id] = fingerprint
        used_contracts.update(references)
        used_schemas.update(node_schemas)
    referenced_files.add(playbook_path)
    repository_orchestration = (
        _workflow_catalog_validate_repository_orchestration(
            graph.get("repository_orchestration"),
            profiles=profiles,
            legacy_adapter=legacy_adapter,
            nodes=nodes,
            action_edges=action_edges,
        )
    )
    policies: dict[str, Mapping[str, object]] = {}
    for index, policy_value in enumerate(
        _workflow_catalog_expect_list(
            graph["edge_policies"], "/edge_policies"
        )
    ):
        policy_id, policy, references = _workflow_catalog_validate_policy(
            policy_value,
            f"/edge_policies/{index}",
            contract_set,
            flow=str(graph["flow"]),
            legacy_adapter=legacy_adapter,
        )
        if policy_id in policies:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "workflow edge-policy IDs must be unique",
                details={"id": policy_id},
            )
        policies[policy_id] = policy
        used_contracts.update(references)
    if used_contracts != contract_set:
        unused = sorted(contract_set - used_contracts)
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNUSED",
            "every declared contract must be referenced by a node or edge",
            details={
                "contracts": [
                    {
                        "registry": item.registry,
                        "id": item.identifier,
                        "version": item.version,
                    }
                    for item in unused
                ]
            },
        )
    if used_schemas != set(schema_documents):
        unused_schemas = sorted(set(schema_documents) - used_schemas)
        raise WorkflowCatalogError(
            "WORKFLOW_SCHEMA_UNUSED",
            "every inventoried schema must be referenced by the workflow",
            details={"schemas": unused_schemas},
        )
    entries = _workflow_catalog_validate_unique_strings(
        graph["entry_nodes"], "/entry_nodes"
    )
    terminals = _workflow_catalog_validate_unique_strings(
        graph["terminal_nodes"], "/terminal_nodes"
    )
    ordered = _workflow_catalog_validate_unique_strings(
        graph["ordered_nodes"], "/ordered_nodes"
    )
    main_nodes = tuple(
        node_id
        for node_id in nodes
        if node_id not in {"BLOCKED", "CANCELLED"}
    )
    if set(ordered) != set(main_nodes) or tuple(ordered) != tuple(main_nodes):
        raise WorkflowCatalogError(
            "WORKFLOW_ORDER_MISMATCH",
            "ordered_nodes must list each non-blocked main node in node order",
            details={"ordered_nodes": list(ordered), "main_nodes": list(main_nodes)},
        )
    edges = _workflow_catalog_expanded_edges(graph, policies, nodes)
    movement_edge_ids = {str(edge["id"]) for edge in edges}
    duplicate_edge_ids = sorted(movement_edge_ids & action_edge_ids)
    if duplicate_edge_ids:
        raise WorkflowCatalogError(
            "WORKFLOW_DUPLICATE_ID",
            "movement and compiled action edges share an identity",
            details={"ids": duplicate_edge_ids},
        )
    _workflow_catalog_validate_graph_topology(
        nodes, edges, entries, terminals
    )
    tool_capabilities = _workflow_catalog_validate_tool_capabilities(
        graph,
        action_edges,
        legacy_adapter=legacy_adapter,
    )
    if set(inventory) != referenced_files:
        raise WorkflowCatalogError(
            "WORKFLOW_INVENTORY_MISMATCH",
            "bundle inventory must exactly match transitive graph references",
            details={
                "unreferenced": sorted(set(inventory) - referenced_files),
                "unlisted": sorted(referenced_files - set(inventory)),
            },
        )
    frozen_nodes = MappingProxyType(
        {
            node_id: _workflow_catalog_freeze(dict(node))
            for node_id, node in nodes.items()
        }
    )
    frozen_edges = tuple(
        _workflow_catalog_freeze(dict(edge)) for edge in edges
    )
    frozen_action_edges = tuple(
        _workflow_catalog_freeze(dict(edge))
        for edge in sorted(
            action_edges,
            key=lambda item: str(item["id"]).encode("utf-8"),
        )
    )
    normalized_graph = dict(graph)
    normalized_graph["tool_capabilities"] = list(tool_capabilities)
    if repository_orchestration is not None:
        normalized_graph["repository_orchestration"] = (
            repository_orchestration
        )
    return (
        _workflow_catalog_freeze(normalized_graph),
        frozen_nodes,
        frozen_edges,
        tuple(sorted(contracts)),
        profiles,
        frozen_action_edges,
    )


def _workflow_catalog_identity_result(
    identity_api: object,
    graph_source: bytes,
    file_sources: Sequence[tuple[str, str, bytes]],
    contracts: Sequence[ContractReference],
    contract_resolver: object,
) -> tuple[str, str]:
    try:
        bundle_file_type = getattr(identity_api, "BundleFile")
        compute = getattr(
            identity_api, "compute_workflow_bundle_identity"
        )
    except AttributeError as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_API_INVALID",
            "bundle identity API is missing required operations",
        ) from exc
    files = tuple(
        bundle_file_type(path, kind, source)
        for path, kind, source in file_sources
    )
    handlers: Sequence[object] = ()
    handler_resolver = getattr(contract_resolver, "identity_handlers", None)
    if callable(handler_resolver):
        handlers = tuple(handler_resolver(tuple(contracts)))
    try:
        result = compute(graph_source, files, handlers)
        graph_sha256 = str(result.graph_sha256)
        bundle_sha256 = str(result.bundle_sha256)
    except Exception as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_FAILED",
            "workflow bundle identity could not be computed",
            details={"error_type": type(exc).__name__},
        ) from exc
    if not _workflow_catalog_sha256_re.fullmatch(
        graph_sha256
    ) or not _workflow_catalog_sha256_re.fullmatch(bundle_sha256):
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_API_INVALID",
            "bundle identity API returned malformed digests",
        )
    return graph_sha256, bundle_sha256


def _workflow_catalog_load_validated(
    workflows_root: Path | str,
    *,
    contract_resolver: object,
    identity_api: object,
    verify_stored_digests: bool,
) -> WorkflowCatalog:
    """Validate one static catalog and optionally enforce its stored digests."""

    root = Path(workflows_root)
    catalog_path = _workflow_catalog_resolve_regular_file(
        root, "catalog.json", pointer="/catalog"
    )
    catalog = _workflow_catalog_expect_object(
        _workflow_catalog_parse_json_bytes(
            catalog_path.read_bytes(), path="catalog.json"
        ),
        "/",
    )
    _workflow_catalog_expect_exact_fields(
        catalog, _workflow_catalog_catalog_fields, "/"
    )
    if catalog["schema"] != CATALOG_SCHEMA:
        raise WorkflowCatalogError(
            "WORKFLOW_CATALOG_SCHEMA_UNSUPPORTED",
            "workflow catalog schema is unsupported",
        )
    if catalog["identity_contract"] != BUNDLE_IDENTITY_CONTRACT:
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_CONTRACT_UNSUPPORTED",
            "workflow catalog identity contract is unsupported",
        )
    activation_relative = _workflow_catalog_portable_relative_path(
        catalog["activation"], "/activation"
    )
    if activation_relative != "activation.json":
        raise WorkflowCatalogError(
            "WORKFLOW_STATIC_INVENTORY_INVALID",
            "workflow activation manifest must use the package-owned fixed path",
        )
    pending: list[
        tuple[
            Mapping[str, object],
            Path,
            bytes,
            tuple[tuple[str, str, bytes], ...],
            Mapping[str, object],
            Mapping[str, Mapping[str, object]],
            tuple[Mapping[str, object], ...],
            tuple[ContractReference, ...],
            tuple[str, ...],
        ]
    ] = []
    keys: set[tuple[str, int]] = set()
    catalog_entries: list[
        tuple[str, Mapping[str, object], str, int]
    ] = []
    for index, entry_value in enumerate(
        _workflow_catalog_expect_list(catalog["bundles"], "/bundles")
    ):
        pointer = f"/bundles/{index}"
        entry = _workflow_catalog_expect_object(entry_value, pointer)
        _workflow_catalog_expect_exact_fields(
            entry, _workflow_catalog_catalog_entry_fields, pointer
        )
        workflow_id = _workflow_catalog_stable_id(
            entry["workflow_id"], f"{pointer}/workflow_id"
        )
        workflow_version = _workflow_catalog_expect_integer(
            entry["workflow_version"],
            f"{pointer}/workflow_version",
            minimum=1,
        )
        key = (workflow_id, workflow_version)
        if key in keys:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_IDENTITY",
                "catalog binds a workflow identifier-version more than once",
                details={
                    "workflow_id": workflow_id,
                    "workflow_version": workflow_version,
                },
            )
        keys.add(key)
        catalog_entries.append(
            (pointer, entry, workflow_id, workflow_version)
        )
    identities: set[str] = set()
    roots: set[str] = set()
    for pointer, entry, workflow_id, workflow_version in catalog_entries:
        bundle_schema_version = _workflow_catalog_expect_integer(
            entry["bundle_schema_version"],
            f"{pointer}/bundle_schema_version",
            minimum=1,
        )
        graph_sha256 = _workflow_catalog_expect_string(
            entry["graph_sha256"], f"{pointer}/graph_sha256"
        )
        bundle_sha256 = _workflow_catalog_expect_string(
            entry["bundle_sha256"], f"{pointer}/bundle_sha256"
        )
        if not _workflow_catalog_sha256_re.fullmatch(
            graph_sha256
        ) or not _workflow_catalog_sha256_re.fullmatch(bundle_sha256):
            raise WorkflowCatalogError(
                "WORKFLOW_DIGEST_INVALID",
                "catalog digests must be lowercase SHA-256 values",
                details={"pointer": pointer},
            )
        key = (workflow_id, workflow_version)
        root_relative = _workflow_catalog_portable_relative_path(
            entry["root"], f"{pointer}/root"
        )
        if not root_relative.startswith("bundles/") or root_relative in roots:
            raise WorkflowCatalogError(
                "WORKFLOW_STATIC_INVENTORY_INVALID",
                "each bundle must have one unique package-owned bundles root",
                details={"root": root_relative},
            )
        bundle_root = root
        for part in root_relative.split("/"):
            bundle_root = bundle_root / part
            if bundle_root.is_symlink():
                raise WorkflowCatalogError(
                    "WORKFLOW_SYMLINK_FORBIDDEN",
                    "bundle roots must not traverse symlinks",
                    details={"root": root_relative},
                )
        try:
            bundle_root = bundle_root.resolve(strict=True)
            bundle_root.relative_to(root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_PATH_ESCAPE",
                "bundle root is missing or outside the package workflows root",
                details={"root": root_relative},
            ) from exc
        if not bundle_root.is_dir():
            raise WorkflowCatalogError(
                "WORKFLOW_REFERENCE_MISSING",
                "bundle root is not a directory",
                details={"root": root_relative},
            )
        graph_relative = _workflow_catalog_portable_relative_path(
            entry["graph"], f"{pointer}/graph"
        )
        file_items = _workflow_catalog_expect_list(
            entry["files"], f"{pointer}/files"
        )
        inventory: dict[str, str] = {}
        portable_paths: dict[str, str] = {}
        file_sources: list[tuple[str, str, bytes]] = []
        for file_index, file_value in enumerate(file_items):
            file_pointer = f"{pointer}/files/{file_index}"
            file_entry = _workflow_catalog_expect_object(
                file_value, file_pointer
            )
            _workflow_catalog_expect_exact_fields(
                file_entry, _workflow_catalog_file_fields, file_pointer
            )
            path = _workflow_catalog_portable_relative_path(
                file_entry["path"], f"{file_pointer}/path"
            )
            kind = _workflow_catalog_expect_string(
                file_entry["kind"], f"{file_pointer}/kind"
            )
            if kind not in {"B", "J", "T"}:
                raise WorkflowCatalogError(
                    "WORKFLOW_CONTENT_KIND_UNSUPPORTED",
                    "bundle file kind must be J, T, or B",
                    details={"pointer": f"{file_pointer}/kind"},
                )
            collision_key = unicodedata.normalize("NFC", path).casefold()
            if path in inventory or collision_key in portable_paths:
                raise WorkflowCatalogError(
                    "WORKFLOW_PATH_COLLISION",
                    "bundle inventory paths must be portable and unique",
                    details={
                        "path": path,
                        "other": portable_paths.get(collision_key),
                    },
                )
            source = _workflow_catalog_resolve_regular_file(
                bundle_root, path, pointer=file_pointer
            ).read_bytes()
            if kind == "J":
                _workflow_catalog_parse_json_bytes(source, path=path)
            elif kind == "T":
                try:
                    text = source.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise WorkflowCatalogError(
                        "WORKFLOW_TEXT_UTF8_INVALID",
                        "workflow text files must be valid UTF-8",
                        details={"path": path},
                    ) from exc
                if text.startswith("\ufeff") or unicodedata.normalize(
                    "NFC", text
                ) != text:
                    raise WorkflowCatalogError(
                        "WORKFLOW_TEXT_INVALID",
                        "workflow text files must be BOM-free NFC text",
                        details={"path": path},
                    )
            inventory[path] = kind
            portable_paths[collision_key] = path
            file_sources.append((path, kind, source))
        if inventory.get(graph_relative) != "J":
            raise WorkflowCatalogError(
                "WORKFLOW_REFERENCE_DANGLING",
                "bundle graph must resolve to one inventoried JSON file",
                details={"path": graph_relative},
            )
        actual_inventory = _workflow_catalog_inventory_regular_files(
            bundle_root
        )
        declared_inventory = tuple(
            sorted(inventory, key=lambda item: item.encode("utf-8"))
        )
        if actual_inventory != declared_inventory:
            raise WorkflowCatalogError(
                "WORKFLOW_INVENTORY_MISMATCH",
                "catalog inventory must exactly enumerate bundle regular files",
                details={
                    "declared": list(declared_inventory),
                    "actual": list(actual_inventory),
                },
            )
        graph_path = _workflow_catalog_resolve_regular_file(
            bundle_root, graph_relative, pointer=f"{pointer}/graph"
        )
        graph_source = graph_path.read_bytes()
        graph_value = _workflow_catalog_parse_json_bytes(
            graph_source, path=f"{root_relative}/{graph_relative}"
        )
        (
            frozen_graph,
            nodes,
            edges,
            contracts,
            profiles,
            action_edges,
        ) = _workflow_catalog_validate_workflow_graph(
            graph_value,
            expected_entry=entry,
            inventory=inventory,
            bundle_root=bundle_root,
            contract_resolver=contract_resolver,
        )
        actual_graph_sha256, actual_bundle_sha256 = (
            _workflow_catalog_identity_result(
                identity_api,
                graph_source,
                tuple(file_sources),
                contracts,
                contract_resolver,
            )
        )
        if actual_bundle_sha256 in identities:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_BUNDLE_DIGEST",
                "validated bundle identities must be unique",
                details={"bundle_sha256": actual_bundle_sha256},
            )
        if verify_stored_digests and (
            actual_graph_sha256 != graph_sha256
            or actual_bundle_sha256 != bundle_sha256
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_DIGEST_MISMATCH",
                "catalog digest does not match the exact bundle contents",
                details={
                    "workflow_id": workflow_id,
                    "workflow_version": workflow_version,
                    "expected_graph_sha256": graph_sha256,
                    "actual_graph_sha256": actual_graph_sha256,
                    "expected_bundle_sha256": bundle_sha256,
                    "actual_bundle_sha256": actual_bundle_sha256,
                },
            )
        validated_entry = dict(entry)
        validated_entry["graph_sha256"] = actual_graph_sha256
        validated_entry["bundle_sha256"] = actual_bundle_sha256
        identities.add(actual_bundle_sha256)
        roots.add(root_relative)
        pending.append(
            (
                validated_entry,
                bundle_root,
                graph_source,
                tuple(file_sources),
                frozen_graph,
                nodes,
                edges,
                contracts,
                profiles,
                action_edges,
            )
        )
    if not pending:
        raise WorkflowCatalogError(
            "WORKFLOW_CATALOG_EMPTY",
            "workflow catalog must contain at least one bundle",
        )
    actual_bundle_roots = _workflow_catalog_inventory_bundle_roots(root)
    declared_bundle_roots = tuple(
        sorted(roots, key=lambda item: item.encode("utf-8"))
    )
    if actual_bundle_roots != declared_bundle_roots:
        raise WorkflowCatalogError(
            "WORKFLOW_STATIC_INVENTORY_INVALID",
            "catalog roots must exactly enumerate packaged bundle roots",
            details={
                "declared": list(declared_bundle_roots),
                "actual": list(actual_bundle_roots),
            },
        )
    activation_path = _workflow_catalog_resolve_regular_file(
        root, activation_relative, pointer="/activation"
    )
    activation = _workflow_catalog_expect_object(
        _workflow_catalog_parse_json_bytes(
            activation_path.read_bytes(), path=activation_relative
        ),
        "/",
    )
    _workflow_catalog_expect_exact_fields(
        activation, _workflow_catalog_activation_fields, "/"
    )
    if activation["schema"] != ACTIVATION_SCHEMA:
        raise WorkflowCatalogError(
            "WORKFLOW_ACTIVATION_SCHEMA_UNSUPPORTED",
            "workflow activation schema is unsupported",
        )
    activation_items: list[Mapping[str, object]] = []
    activation_keys: set[tuple[str, int, str]] = set()
    active_by_bundle: dict[tuple[str, int], list[str]] = {}
    pending_by_key = {
        (
            str(item[0]["workflow_id"]),
            int(item[0]["workflow_version"]),
        ): item
        for item in pending
    }
    for index, value in enumerate(
        _workflow_catalog_expect_list(
            activation["profiles"], "/profiles"
        )
    ):
        pointer = f"/profiles/{index}"
        item = _workflow_catalog_expect_object(value, pointer)
        _workflow_catalog_expect_exact_fields(
            item, _workflow_catalog_activation_profile_fields, pointer
        )
        workflow_id = _workflow_catalog_stable_id(
            item["workflow_id"], f"{pointer}/workflow_id"
        )
        workflow_version = _workflow_catalog_expect_integer(
            item["workflow_version"],
            f"{pointer}/workflow_version",
            minimum=1,
        )
        profile = _workflow_catalog_expect_string(
            item["execution_profile"], f"{pointer}/execution_profile"
        )
        if profile not in SUPPORTED_EXECUTION_PROFILES:
            raise WorkflowCatalogError(
                "WORKFLOW_INVALID_FIELD",
                "activation profile is unsupported",
                details={"pointer": f"{pointer}/execution_profile"},
            )
        key = (workflow_id, workflow_version, profile)
        if key in activation_keys:
            raise WorkflowCatalogError(
                "WORKFLOW_DUPLICATE_ID",
                "activation profile entries must be unique",
                details={"key": list(key)},
            )
        try:
            bundle_pending = pending_by_key[(workflow_id, workflow_version)]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_REFERENCE_DANGLING",
                "activation refers to an unknown bundle",
                details={"key": list(key)},
            ) from exc
        supported_profiles = bundle_pending[8]
        if profile not in supported_profiles:
            raise WorkflowCatalogError(
                "WORKFLOW_REFERENCE_DANGLING",
                "activation refers to an unsupported bundle profile",
                details={"key": list(key)},
            )
        digest = _workflow_catalog_expect_string(
            item["bundle_sha256"], f"{pointer}/bundle_sha256"
        )
        if not _workflow_catalog_sha256_re.fullmatch(digest):
            raise WorkflowCatalogError(
                "WORKFLOW_DIGEST_INVALID",
                "activation digests must be lowercase SHA-256 values",
                details={"pointer": f"{pointer}/bundle_sha256"},
            )
        if (
            verify_stored_digests
            and digest != bundle_pending[0]["bundle_sha256"]
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_DIGEST_MISMATCH",
                "activation identity does not match the catalog bundle",
                details={"key": list(key)},
            )
        active = _workflow_catalog_expect_bool(
            item["active"], f"{pointer}/active"
        )
        suites = _workflow_catalog_validate_unique_strings(
            item["required_suites"], f"{pointer}/required_suites"
        )
        required_action_suites = {
            str(suite)
            for edge in bundle_pending[9]
            for suite in edge.get("required_suites", ())
            if isinstance(suite, str)
        }
        missing_action_suites = sorted(
            required_action_suites - set(suites)
        )
        if active and (not suites or missing_action_suites):
            raise WorkflowCatalogError(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "active profiles must name their completed movement and action "
                "closure suites",
                details={
                    "key": list(key),
                    "missing_action_suites": missing_action_suites,
                },
            )
        if active:
            active_by_bundle.setdefault(
                (workflow_id, workflow_version), []
            ).append(profile)
        activation_keys.add(key)
        activation_items.append(_workflow_catalog_freeze(dict(item)))
    allowed_activation_keys = {
        (
            str(item[0]["workflow_id"]),
            int(item[0]["workflow_version"]),
            profile,
        )
        for item in pending
        if not bool(item[4]["legacy_adapter"])
        and 3 in item[4]["task_schema_versions"]
        for profile in item[8]
    }
    required_activation_keys = {
        key for key in allowed_activation_keys if key[1] < 4
    }
    if (
        not required_activation_keys.issubset(activation_keys)
        or not activation_keys.issubset(allowed_activation_keys)
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "activation must preserve every historical schema-v3 profile and "
            "may omit inactive, unreserved V4 preview profiles",
            details={
                "missing": [
                    list(key)
                    for key in sorted(
                        required_activation_keys - activation_keys
                    )
                ],
                "unexpected": [
                    list(key)
                    for key in sorted(
                        activation_keys - allowed_activation_keys
                    )
                ],
            },
        )
    bundles: dict[tuple[str, int], WorkflowBundle] = {}
    by_identity: dict[str, WorkflowBundle] = {}
    for (
        entry,
        bundle_root,
        _graph_source,
        _file_sources,
        frozen_graph,
        nodes,
        edges,
        contracts,
        profiles,
        action_edges,
    ) in pending:
        key = (
            str(entry["workflow_id"]),
            int(entry["workflow_version"]),
        )
        bundle = WorkflowBundle(
            workflow_id=key[0],
            workflow_version=key[1],
            bundle_schema_version=int(entry["bundle_schema_version"]),
            graph_sha256=str(entry["graph_sha256"]),
            bundle_sha256=str(entry["bundle_sha256"]),
            root=bundle_root,
            graph=frozen_graph,
            resources=MappingProxyType(
                {
                    path: (kind, source)
                    for path, kind, source in _file_sources
                }
            ),
            nodes=nodes,
            edges=edges,
            action_edges=action_edges,
            contracts=contracts,
            execution_profiles=profiles,
            repository_orchestration=frozen_graph.get(
                "repository_orchestration"
            ),
            active_profiles=tuple(sorted(active_by_bundle.get(key, []))),
        )
        bundles[key] = bundle
        by_identity[bundle.bundle_sha256] = bundle
    return WorkflowCatalog(
        bundles=MappingProxyType(bundles),
        bundles_by_identity=MappingProxyType(by_identity),
        activations=tuple(activation_items),
    )


def expected_workflow_catalog_identities(
    workflows_root: Path | str,
    *,
    contract_resolver: object,
    identity_api: object,
) -> tuple[Mapping[str, object], ...]:
    """Return validated expected identities without trusting stored digests.

    This read-only operation follows the exact catalog loader path for static
    inventory, containment, graph, schema, playbook, topology, activation, and
    sealed executable-contract validation. It deliberately does not compare
    catalog or activation digest fields, so an explicit maintainer tool can
    report the expected replacement values after identity-covered bytes change.
    """

    loaded = _workflow_catalog_load_validated(
        workflows_root,
        contract_resolver=contract_resolver,
        identity_api=identity_api,
        verify_stored_digests=False,
    )
    return tuple(
        MappingProxyType(
            {
                "workflow_id": bundle.workflow_id,
                "workflow_version": bundle.workflow_version,
                "graph_sha256": bundle.graph_sha256,
                "bundle_sha256": bundle.bundle_sha256,
            }
        )
        for bundle in loaded.bundles.values()
    )


def load_workflow_catalog(
    workflows_root: Path | str,
    *,
    contract_resolver: object,
    identity_api: object,
) -> WorkflowCatalog:
    """Load, verify, and atomically seal the package's static workflow list."""

    return _workflow_catalog_load_validated(
        workflows_root,
        contract_resolver=contract_resolver,
        identity_api=identity_api,
        verify_stored_digests=True,
    )


__all__ = [
    "ACTIVATION_SCHEMA",
    "BUNDLE_IDENTITY_CONTRACT",
    "CATALOG_SCHEMA",
    "ContractReference",
    "SUPPORTED_BUNDLE_SCHEMA_VERSIONS",
    "StaticContractResolver",
    "WORKFLOW_SCHEMA",
    "WorkflowBundle",
    "WorkflowCatalog",
    "WorkflowCatalogError",
    "expected_workflow_catalog_identities",
    "load_workflow_catalog",
]
