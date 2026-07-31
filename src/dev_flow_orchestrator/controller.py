"""The sole application boundary for current V4 task mutation."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping, Optional
import uuid

from .authority import AuthorityStore
from .engine import (
    apply_current_action,
    apply_preflight,
    plan_current_action,
    plan_preflight,
    validate_action_payload,
)
from .git_client import GitClient
from .journal import EffectJournal
from .model import (
    DevFlowError,
    MutationPlan,
    MutationReceipt,
    RepositoryRecord,
    TaskState,
    canonical_json_bytes,
    initial_state,
)
from .product import select_profile
from .repository_kernel import authority_evidence_ids
from .store import TaskStore
from .workflow import WORKFLOW_GRAPHS, agent_projection, required_grant


_RECOVERY_MODES = frozenset({"settle", "abandon", "reattach", "compensate"})


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _repository_id(path: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", path.name).strip("-") or "repo"
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return "{}-{}".format(slug[:40], digest)


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class Controller:
    """Coordinate product selection, effects and the private task store."""

    def __init__(
        self,
        data_dir: str,
        *,
        git_client: Optional[GitClient] = None,
    ) -> None:
        self.store = TaskStore(data_dir)
        self.git = git_client or GitClient()
        self.journal = EffectJournal(self.store.root)
        self.authorities = AuthorityStore(self.store.root)

    @staticmethod
    def _canonical_repositories(paths: Iterable[str]) -> tuple:
        repositories = []
        seen = set()
        for supplied in paths:
            path = Path(supplied).expanduser().resolve()
            if not path.is_dir():
                raise DevFlowError(
                    "REPOSITORY_INVALID",
                    "repository path is not a directory",
                    details={"path": str(path)},
                )
            identity = str(path)
            if identity in seen:
                continue
            seen.add(identity)
            repositories.append(
                RepositoryRecord(_repository_id(path), identity)
            )
        if not repositories:
            raise DevFlowError(
                "REPOSITORY_REQUIRED",
                "at least one distinct repository is required",
            )
        return tuple(repositories)

    def start(
        self,
        *,
        requirement: str,
        workflow: str,
        workspace_strategy: str,
        repositories: Iterable[str],
        task_id: Optional[str] = None,
    ) -> TaskState:
        clean_requirement = requirement.strip()
        repository_records = self._canonical_repositories(repositories)
        for repository in repository_records:
            root = Path(repository.path).resolve()
            if self.store.root == root or root in self.store.root.parents:
                raise DevFlowError(
                    "DATA_DIR_INSIDE_REPOSITORY",
                    "controller data directory must remain outside target repositories",
                    details={
                        "data_dir": str(self.store.root),
                        "repository": str(root),
                    },
                )
        try:
            profile = select_profile(
                workflow,
                len(repository_records),
                workspace_strategy,
            )
        except ValueError as exc:
            raise DevFlowError(
                "PRODUCT_SELECTION_INVALID",
                str(exc),
                details={
                    "workflow": workflow,
                    "workspace_strategy": workspace_strategy,
                    "repository_count": len(repository_records),
                },
            ) from exc
        effective_task_id = task_id or "task-{}".format(uuid.uuid4().hex[:16])
        state = initial_state(
            task_id=effective_task_id,
            requirement=clean_requirement,
            profile=profile,
            workspace_strategy=workspace_strategy,
            repositories=repository_records,
            timestamp=_utc_now(),
        )
        return self.store.create(state)

    def show(self, task_id: str) -> TaskState:
        return self.store.load(task_id)

    @staticmethod
    def _repository_context(state: TaskState) -> dict:
        repositories = []
        for repository in sorted(
            state.repositories,
            key=lambda item: item.repository_id.encode("utf-8"),
        ):
            workspace_path = None
            if (
                repository.workspace is not None
                and isinstance(repository.workspace.get("path"), str)
            ):
                workspace_path = str(
                    Path(repository.workspace["path"]).expanduser().resolve()
                )
            repositories.append(
                {
                    "repository_id": repository.repository_id,
                    "path": str(Path(repository.path).expanduser().resolve()),
                    "workspace_path": workspace_path,
                }
            )
        return {
            "topology": state.topology,
            "workspace_strategy": state.workspace_strategy,
            "repositories": repositories,
        }

    @staticmethod
    def _task_authority_ids(state: TaskState) -> set:
        """Read authority proof only from controller-owned state schemas."""

        found = set()
        for record in (*state.evidence, *state.approvals):
            if (
                isinstance(record, Mapping)
                and record.get("schema") == "dev-flow-v4-node-output/v1"
                and isinstance(record.get("authority_id"), str)
            ):
                found.add(record["authority_id"])
        for record in state.effects:
            if (
                isinstance(record, Mapping)
                and record.get("schema") == "dev-flow-v4-effect-summary/v1"
                and isinstance(record.get("authority_id"), str)
            ):
                found.add(record["authority_id"])
        orchestration = state.orchestration
        if (
            isinstance(orchestration, Mapping)
            and orchestration.get("schema")
            == "dev-flow-v4-repository-plan/v1"
        ):
            if isinstance(orchestration.get("authority_id"), str):
                found.add(orchestration["authority_id"])
            found.update(authority_evidence_ids(orchestration))
            cancellation = orchestration.get("cancellation")
            if (
                isinstance(cancellation, Mapping)
                and isinstance(cancellation.get("authority_id"), str)
            ):
                found.add(cancellation["authority_id"])
        return found

    def _workspace_requests(self, state: TaskState) -> dict:
        return {
            repository.repository_id: {
                "repository_path": repository.path,
                "strategy": state.workspace_strategy,
                "destination": str(
                    self.store.root
                    / "workspaces"
                    / state.task_id
                    / repository.repository_id
                ),
                "expected_head": (repository.preflight or {}).get("head"),
            }
            for repository in state.repositories
        }

    @staticmethod
    def _matching_effect_summary(
        state: TaskState,
        record: Mapping[str, object],
    ) -> Optional[Mapping[str, object]]:
        binding = record.get("plan_binding")
        action_id = record.get("action_id")
        authority_id = record.get("authority_id")
        receipt = record.get("receipt")
        for effect in state.effects:
            if (
                isinstance(effect, Mapping)
                and effect.get("schema")
                == "dev-flow-v4-effect-summary/v1"
                and effect.get("execution_id") == binding
                and effect.get("action_id") == action_id
                and effect.get("authority_id") == authority_id
                and effect.get("receipt") == receipt
            ):
                return effect
        return None

    @staticmethod
    def _confirmation_record(
        request_id: object,
        records: Iterable[Mapping[str, object]],
    ) -> Optional[Mapping[str, object]]:
        if not isinstance(request_id, str):
            return None
        for record in records:
            if record.get("request_id") == request_id:
                return record
        return None

    @staticmethod
    def _validate_terminal_tombstone(
        evidence: Mapping[str, object],
        *,
        request_id: str,
        binding_digest: str,
        task_id: str,
        action_id: str,
        grant: str,
        scope: Mapping[str, object],
        context: Mapping[str, object],
        repository_context: Mapping[str, object],
    ) -> None:
        """Validate historical proof without turning it into live authority."""

        locator = evidence.get("locator")
        if (
            evidence.get("schema")
            != "dev-flow-v4-confirmation-tombstone/v1"
            or evidence.get("request_id") != request_id
            or evidence.get("binding_digest") != binding_digest
            or evidence.get("status") != "CONSUMED"
            or evidence.get("task_id") != task_id
            or not isinstance(locator, Mapping)
            or locator.get("request_id") != request_id
            or locator.get("status") != "CONSUMED"
            or locator.get("action_id") != action_id
            or locator.get("grant") != grant
            or locator.get("scope_digest") != _canonical_digest(scope)
            or locator.get("context_digest") != _canonical_digest(context)
            or locator.get("repository_context_digest")
            != _canonical_digest(repository_context)
            or not isinstance(locator.get("session_id"), str)
            or not locator["session_id"]
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "terminal effect tombstone does not match its confirmation binding",
                details={"request_id": request_id},
            )

    def _validate_effect_record(
        self,
        *,
        state: TaskState,
        record: Mapping[str, object],
        binding: str,
        authority_records: Iterable[Mapping[str, object]],
    ) -> dict:
        """Validate journal schema, plan and both authority bindings centrally."""

        record = self.journal.validate_record(
            state.task_id,
            binding,
            record,
        )
        expected_revision = record["expected_revision"]
        action_id = record["action_id"]
        authority_id = record["authority_id"]
        actor_id = record["actor_id"]
        durable_summary = self._matching_effect_summary(state, record)
        authority_repository_context = self._repository_context(state)
        if durable_summary is not None:
            authority_repository_context = {
                **authority_repository_context,
                "repositories": [
                    {**repository, "workspace_path": None}
                    for repository in authority_repository_context[
                        "repositories"
                    ]
                ],
            }
        if state.revision == expected_revision:
            try:
                contract, plan = plan_current_action(
                    state,
                    action_id,
                    expected_revision,
                    authority_id=authority_id,
                    actor_id=actor_id,
                )
            except DevFlowError as exc:
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "effect journal no longer matches its task action",
                    details={"cause": exc.code},
                ) from exc
        elif (
            durable_summary is not None
            and state.revision >= expected_revision + 1
        ):
            graph = WORKFLOW_GRAPHS.get(state.workflow_id)
            candidates = (
                [
                    candidate
                    for candidate in graph.values()
                    if candidate.action_id == action_id
                    and candidate.effect_port == "git.prepare-workspace"
                ]
                if graph is not None
                else []
            )
            if len(candidates) != 1:
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "durable task evidence has no unique installed effect contract",
                )
            contract = candidates[0]
            plan = MutationPlan(
                action_id=contract.action_id,
                task_id=state.task_id,
                expected_revision=expected_revision,
                source_node=contract.node_id,
                target_node=contract.target_node,
                effect_kind=contract.effect_kind,
                allowed_writes=contract.allowed_state_writes,
                authority_id=authority_id,
                actor_id=actor_id,
            )
        else:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal is not bound to current action or durable task evidence",
            )
        try:
            validated_payload = dict(
                validate_action_payload(contract, record["payload"])
            )
        except DevFlowError as exc:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal payload is invalid",
                details={"cause": exc.code},
            ) from exc
        if (
            plan.binding != binding
            or contract.effect_port != "git.prepare-workspace"
            or record["effect_kind"] != plan.effect_kind
            or record["payload"] != validated_payload
            or record["requests"] != self._workspace_requests(state)
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal payload, request or plan binding is invalid",
            )

        phase = record["phase"]
        terminal = phase in {"ABANDONED", "COMMITTED"}
        grant = required_grant(contract)
        if not isinstance(grant, str):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal action has no exact authority grant",
            )
        original = self._confirmation_record(
            authority_id,
            authority_records,
        )
        if original is None:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal references unavailable confirmation evidence",
                details={"request_id": authority_id},
            )
        if (
            original.get("schema")
            == "dev-flow-v4-confirmation-tombstone/v1"
        ):
            if not terminal:
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "non-terminal effect cannot use compacted confirmation evidence",
                    details={"request_id": authority_id},
                )
            self._validate_terminal_tombstone(
                original,
                request_id=authority_id,
                binding_digest=record["authority_binding_digest"],
                task_id=state.task_id,
                action_id=action_id,
                grant=grant,
                scope={"effect_attempt": record["attempt"]},
                context=validated_payload,
                repository_context=authority_repository_context,
            )
        else:
            original_binding = original.get("binding")
            actor = (
                original_binding.get("actor")
                if isinstance(original_binding, Mapping)
                else None
            )
            allowed_statuses = (
                {"CONFIRMED", "CLAIMED", "CONSUMED"}
                if terminal
                else {"CONFIRMED", "CLAIMED"}
            )
            if (
                original.get("status") not in allowed_statuses
                or original.get("binding_digest")
                != record["authority_binding_digest"]
                or not isinstance(original_binding, Mapping)
                or original_binding.get("task_id") != state.task_id
                or original_binding.get("workflow_identity")
                != state.workflow_identity
                or original_binding.get("expected_revision")
                != expected_revision
                or original_binding.get("action_id") != action_id
                or original_binding.get("grant") != grant
                or original_binding.get("scope")
                != {"effect_attempt": record["attempt"]}
                or original_binding.get("context") != validated_payload
                or original_binding.get("repository_context")
                != authority_repository_context
                or not isinstance(actor, Mapping)
                or actor.get("id") != actor_id
                or actor.get("role")
                != self._actor_role_for_grant(grant or "")
            ):
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "effect journal does not match its original confirmation",
                )

        recovery = None
        recovery_claim = record.get("recovery_claim")
        if isinstance(recovery_claim, Mapping):
            expected_recovery_scope = {
                "execution_id": binding,
                "mode": recovery_claim["mode"],
                "effect_attempt": record["attempt"],
                "evidence_digest": recovery_claim["evidence_digest"],
            }
            recovery = self._confirmation_record(
                recovery_claim["request_id"],
                authority_records,
            )
            if recovery is None:
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "effect recovery references unavailable confirmation evidence",
                    details={
                        "request_id": recovery_claim["request_id"]
                    },
                )
            if (
                recovery.get("schema")
                == "dev-flow-v4-confirmation-tombstone/v1"
            ):
                if not terminal:
                    raise DevFlowError(
                        "EFFECT_JOURNAL_INVALID",
                        "non-terminal recovery cannot use compacted confirmation evidence",
                        details={
                            "request_id": recovery_claim["request_id"]
                        },
                    )
                self._validate_terminal_tombstone(
                    recovery,
                    request_id=recovery_claim["request_id"],
                    binding_digest=recovery_claim["binding_digest"],
                    task_id=state.task_id,
                    action_id="effect.recover." + recovery_claim["mode"],
                    grant="effect-recovery",
                    scope=expected_recovery_scope,
                    context=expected_recovery_scope,
                    repository_context=authority_repository_context,
                )
            else:
                recovery_binding = recovery.get("binding")
                recovery_actor = (
                    recovery_binding.get("actor")
                    if isinstance(recovery_binding, Mapping)
                    else None
                )
                stored_scope = (
                    recovery_binding.get("scope")
                    if isinstance(recovery_binding, Mapping)
                    else None
                )
                allowed_statuses = (
                    {"CONFIRMED", "CLAIMED", "CONSUMED"}
                    if terminal
                    else {"CONFIRMED", "CLAIMED"}
                )
                evidence_digest = (
                    stored_scope.get("evidence_digest")
                    if isinstance(stored_scope, Mapping)
                    else None
                )
                expected_recovery_actor = self.authorities.current_actor(
                    "operator"
                )
                if (
                    recovery.get("status") not in allowed_statuses
                    or recovery.get("binding_digest")
                    != recovery_claim["binding_digest"]
                    or not isinstance(recovery_binding, Mapping)
                    or not isinstance(stored_scope, Mapping)
                    or recovery_binding.get("task_id") != state.task_id
                    or recovery_binding.get("workflow_identity")
                    != state.workflow_identity
                    or recovery_binding.get("expected_revision")
                    != expected_revision
                    or recovery_binding.get("action_id")
                    != "effect.recover." + recovery_claim["mode"]
                    or recovery_binding.get("grant") != "effect-recovery"
                    or stored_scope != expected_recovery_scope
                    or recovery_binding.get("context")
                    != expected_recovery_scope
                    or recovery_binding.get("repository_context")
                    != authority_repository_context
                    or not isinstance(evidence_digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", evidence_digest)
                    is None
                    or evidence_digest
                    != recovery_claim["evidence_digest"]
                    or not isinstance(recovery_actor, Mapping)
                    or dict(recovery_actor) != expected_recovery_actor
                ):
                    raise DevFlowError(
                        "EFFECT_JOURNAL_INVALID",
                        "effect recovery claim does not match its confirmation",
                    )
        return {
            "record": record,
            "contract": contract,
            "plan": plan,
            "payload": validated_payload,
            "requests": record["requests"],
            "effect_attempt": record["attempt"],
            "durable_summary": durable_summary,
            "original_confirmation": original,
            "recovery_confirmation": recovery,
        }

    def _reconcile_confirmations(self, state: TaskState) -> None:
        """Reconcile private authority only from already-durable evidence."""

        authority_records = self.authorities.evidence_for_task(state.task_id)
        journal_records = self.journal.inspect(state.task_id)
        for record in journal_records:
            binding = record["plan_binding"]
            validated = self._validate_effect_record(
                state=state,
                record=record,
                binding=binding,
                authority_records=authority_records,
            )
            if (
                record["phase"] in {"RECEIPT", "QUARANTINED"}
                and validated["durable_summary"] is not None
            ):
                with self.journal.execution_fence(state.task_id, binding):
                    fresh_state = self.store.load(state.task_id)
                    fresh_record = self.journal.get(
                        state.task_id,
                        binding,
                    )
                    fresh = self._validate_effect_record(
                        state=fresh_state,
                        record=fresh_record,
                        binding=binding,
                        authority_records=authority_records,
                    )
                    durable_summary = fresh["durable_summary"]
                    if (
                        fresh_record["phase"]
                        in {"RECEIPT", "QUARANTINED"}
                        and durable_summary is not None
                    ):
                        fresh_record = self.journal.mark_receipt(
                            state.task_id,
                            binding,
                            durable_summary["receipt"],
                            _utc_now(),
                        )
                        self.journal.mark_committed(
                            state.task_id,
                            binding,
                            fresh_record["expected_revision"] + 1,
                            _utc_now(),
                        )

        journal_records = self.journal.inspect(state.task_id)
        validated_journal = [
            self._validate_effect_record(
                state=state,
                record=record,
                binding=record["plan_binding"],
                authority_records=authority_records,
            )
            for record in journal_records
        ]
        successful = self._task_authority_ids(state)
        claimed = set()
        journal_by_binding = {}
        journal_by_action_revision = {}
        for validated in validated_journal:
            record = validated["record"]
            binding = record["plan_binding"]
            journal_by_binding[binding] = record
            journal_by_action_revision[
                (record["action_id"], record["expected_revision"])
            ] = record
            phase = record["phase"]
            original = validated["original_confirmation"]
            if original is not None:
                request_id = original["request_id"]
                if phase in {"COMMITTED", "ABANDONED"}:
                    successful.add(request_id)
                else:
                    claimed.add(request_id)
            recovery = validated["recovery_confirmation"]
            if recovery is not None:
                request_id = recovery["request_id"]
                if phase in {"COMMITTED", "ABANDONED"}:
                    successful.add(request_id)
                else:
                    claimed.add(request_id)

        projection = agent_projection(state)
        action = projection.get("action")
        current_action_ids = set()
        if isinstance(action, Mapping) and isinstance(
            action.get("action_id"),
            str,
        ):
            current_action_ids.add(action["action_id"])
        additional = projection.get("additional_actions")
        if isinstance(additional, list):
            current_action_ids.update(
                item["action_id"]
                for item in additional
                if isinstance(item, Mapping)
                and isinstance(item.get("action_id"), str)
            )
        repository_context = self._repository_context(state)
        for record in self.authorities.records_for_task(state.task_id):
            request_id = record.get("request_id")
            status = record.get("status")
            binding = record.get("binding")
            if not isinstance(request_id, str) or not isinstance(binding, Mapping):
                continue
            if request_id in successful:
                self.authorities.consume(state.task_id, request_id)
                continue
            if request_id in claimed:
                self.authorities.mark_claimed(state.task_id, request_id)
                continue
            if status not in {"PENDING", "CONFIRMED"}:
                continue
            matches_task = (
                binding.get("workflow_identity") == state.workflow_identity
                and binding.get("expected_revision") == state.revision
                and binding.get("repository_context") == repository_context
            )
            bound_action = binding.get("action_id")
            if (
                isinstance(bound_action, str)
                and bound_action.startswith("effect.recover.")
            ):
                scope = binding.get("scope")
                execution_id = (
                    scope.get("execution_id")
                    if isinstance(scope, Mapping)
                    else None
                )
                effect = journal_by_binding.get(execution_id)
                action_matches = (
                    isinstance(effect, Mapping)
                    and effect.get("phase")
                    not in {"COMMITTED", "ABANDONED"}
                )
                if action_matches and isinstance(scope, Mapping):
                    action_matches = (
                        scope.get("effect_attempt") == effect.get("attempt")
                        and scope.get("mode")
                        == bound_action.removeprefix("effect.recover.")
                    )
                recovery_claim = (
                    effect.get("recovery_claim")
                    if isinstance(effect, Mapping)
                    else None
                )
                if (
                    action_matches
                    and isinstance(recovery_claim, Mapping)
                    and recovery_claim.get("request_id") != request_id
                ):
                    action_matches = False
            else:
                action_matches = bound_action in current_action_ids
                scope = binding.get("scope")
                bound_attempt = (
                    scope.get("effect_attempt")
                    if isinstance(scope, Mapping)
                    else None
                )
                if isinstance(bound_attempt, int) and not isinstance(
                    bound_attempt,
                    bool,
                ):
                    placement = journal_by_action_revision.get(
                        (
                            bound_action,
                            binding.get("expected_revision"),
                        )
                    )
                    if placement is None:
                        current_attempt = 1
                    elif placement.get("phase") == "ABANDONED":
                        current_attempt = int(placement.get("attempt", 0)) + 1
                    else:
                        current_attempt = None
                    action_matches = (
                        action_matches
                        and bound_attempt == current_attempt
                    )
            if not matches_task or not action_matches:
                self.authorities.mark_stale(state.task_id, request_id)

    def next(
        self,
        task_id: str,
        *,
        session_id: Optional[str] = None,
    ) -> dict:
        state = self.store.load(task_id)
        self._reconcile_confirmations(state)
        projection = agent_projection(state)
        action = projection.get("action")
        if session_id is not None and isinstance(action, Mapping):
            action_ids = [action["action_id"]]
            additional = projection.get("additional_actions")
            if isinstance(additional, list):
                action_ids.extend(
                    item["action_id"]
                    for item in additional
                    if isinstance(item, Mapping)
                    and isinstance(item.get("action_id"), str)
                )
            projection["confirmation"] = self.authorities.projection(
                task_id=state.task_id,
                workflow_identity=state.workflow_identity,
                expected_revision=state.revision,
                action_ids=action_ids,
                session_id=session_id,
                repository_context=self._repository_context(state),
            )
        return projection

    def observe_user_prompt(
        self,
        *,
        session_id: str,
        turn_id: str,
        cwd: str,
        prompt: str,
    ) -> dict:
        candidate = str(Path(cwd).expanduser().resolve())
        tasks = self.tasks_for_path(candidate)
        for state in tasks:
            self._reconcile_confirmations(state)
        return self.authorities.observe_user_prompt(
            session_id=session_id,
            turn_id=turn_id,
            cwd=candidate,
            prompt=prompt,
            eligible_task_ids=[state.task_id for state in tasks],
        )

    def tasks_for_path(self, path: str) -> tuple:
        candidate = Path(path).expanduser().resolve()
        matches = []
        for state in self.store.list_states():
            if state.status in {"DONE", "CANCELLED"}:
                continue
            roots = []
            for repository in state.repositories:
                roots.append(Path(repository.path).resolve())
                workspace = repository.workspace
                if workspace is not None and isinstance(workspace.get("path"), str):
                    roots.append(Path(workspace["path"]).resolve())
            if any(
                candidate == root or root in candidate.parents
                for root in roots
            ):
                matches.append(state)
        return tuple(
            sorted(
                matches,
                key=lambda state: state.task_id.encode("utf-8"),
            )
        )

    def preflight(
        self,
        task_id: str,
        expected_revision: int,
    ) -> MutationReceipt:
        observed = self.store.load(task_id)
        plan = plan_preflight(observed, expected_revision)
        evidence = {
            repository.repository_id: self.git.inspect(repository.path)
            for repository in observed.repositories
        }
        committed = self.store.update(
            task_id,
            expected_revision,
            lambda current: apply_preflight(
                current,
                plan,
                evidence,
                _utc_now(),
            ),
        )
        return MutationReceipt(
            task_id=committed.task_id,
            action_id=plan.action_id,
            committed_revision=committed.revision,
            status=committed.status,
            current_node=committed.current_node,
            changed_sections=(
                "current_node",
                "repositories",
                "status",
            ),
            plan_binding=plan.binding,
        )

    def _verified_authority(
        self,
        *,
        state: TaskState,
        task_id: str,
        expected_revision: int,
        action_id: str,
        contract,
        payload: Optional[dict],
        session_id: Optional[str],
        request_turn_id: Optional[str],
        allow_claimed_request_id: Optional[str] = None,
        grant_override: Optional[str] = None,
        actor_role_override: Optional[str] = None,
        scope_override: Optional[Mapping[str, object]] = None,
    ) -> tuple:
        grant = (
            grant_override
            if grant_override is not None
            else required_grant(contract)
        )
        if grant is None:
            return None, None, {}, None
        scope = dict(scope_override or {})
        actor_id = None
        actor_role = (
            actor_role_override
            if actor_role_override is not None
            else self._actor_role_for_grant(grant)
        )
        if grant == "lease-owner":
            repository_id = (payload or {}).get("repository_id")
            lease_id = (payload or {}).get("lease_id")
            leases = (
                state.orchestration.get("leases")
                if isinstance(state.orchestration, Mapping)
                else None
            )
            lease = (
                leases.get(lease_id)
                if isinstance(leases, Mapping)
                and isinstance(lease_id, str)
                else None
            )
            if (
                not isinstance(repository_id, str)
                or not isinstance(lease, Mapping)
                or lease.get("repository_id") != repository_id
                or lease.get("status") != "ACTIVE"
                or not isinstance(lease.get("owner_id"), str)
            ):
                raise DevFlowError(
                    "REPOSITORY_OWNER_MISMATCH",
                    "the current action does not identify an active lease owner",
                )
            scope = {
                "repository_id": repository_id,
                "lease_id": lease_id,
            }
            actor_id = lease["owner_id"]
        existing_ids = {
            item.get("request_id")
            for item in self.authorities.records_for_task(task_id)
        }
        record = self.authorities.resolve(
            task_id=task_id,
            workflow_identity=state.workflow_identity,
            expected_revision=expected_revision,
            action_id=action_id,
            grant=grant,
            actor_role=actor_role,
            actor_id=actor_id,
            scope=scope,
            context=payload,
            repository_context=self._repository_context(state),
            session_id=session_id,
            request_turn_id=request_turn_id,
        )
        request_id = record["request_id"]
        status = record.get("status")
        packet = self.authorities.public_packet(record)
        if status == "PENDING":
            raise DevFlowError(
                (
                    "CONFIRMATION_PENDING"
                    if request_id in existing_ids
                    else "CONFIRMATION_REQUIRED"
                ),
                "the exact operation is waiting for a later user reply",
                details={"confirmation": packet},
            )
        if status == "DENIED":
            raise DevFlowError(
                "CONFIRMATION_DENIED",
                "the exact confirmation binding was denied",
                details={"confirmation": packet},
            )
        if status == "CLAIMED":
            if request_id != allow_claimed_request_id:
                raise DevFlowError(
                    "CONFIRMATION_CLAIMED",
                    "the exact confirmation is already bound to an effect claim",
                    details={"confirmation": packet},
                )
        elif status == "CONSUMED":
            raise DevFlowError(
                "CONFIRMATION_CONSUMED",
                "the exact confirmation was already consumed",
                details={"confirmation": packet},
            )
        elif status == "STALE":
            raise DevFlowError(
                "CONFIRMATION_STALE",
                "the exact confirmation no longer matches current state",
                details={"confirmation": packet},
            )
        elif status != "CONFIRMED":
            raise DevFlowError(
                "CONFIRMATION_INVALID",
                "the confirmation lifecycle state is invalid",
                details={"confirmation": packet},
            )
        binding = record["binding"]
        actor = binding.get("actor")
        if (
            not isinstance(actor, Mapping)
            or not isinstance(actor.get("id"), str)
            or not isinstance(binding.get("scope"), Mapping)
        ):
            raise DevFlowError(
                "CONFIRMATION_BINDING_MISMATCH",
                "confirmation actor or scope is invalid",
                details={"request_id": request_id},
            )
        return request_id, actor["id"], dict(binding["scope"]), record

    @staticmethod
    def _actor_role_for_grant(grant: str) -> str:
        return {
            "implementer": "implementer",
            "independent-review": "reviewer",
            "manager": "manager",
            "lease-owner": "lease-owner",
        }.get(grant, "operator")

    def apply(
        self,
        task_id: str,
        expected_revision: int,
        action_id: str,
        payload: Optional[dict] = None,
        *,
        session_id: Optional[str] = None,
        request_turn_id: Optional[str] = None,
    ) -> MutationReceipt:
        if action_id == "task.preflight":
            if payload:
                raise DevFlowError(
                    "NODE_OUTPUT_INVALID",
                    "preflight does not accept an action payload",
                )
            return self.preflight(task_id, expected_revision)
        observed = self.store.load(task_id)
        self._reconcile_confirmations(observed)
        contract, plan = plan_current_action(
            observed,
            action_id,
            expected_revision,
        )
        validated_payload = dict(
            validate_action_payload(contract, payload)
        )
        authority_scope_override = None
        if contract.effect_port == "git.prepare-workspace":
            authority_records = self.authorities.evidence_for_task(task_id)
            with self.journal.execution_fence(task_id, plan.binding):
                effect_state = self.store.load(task_id)
                try:
                    prior_effect = self.journal.get(task_id, plan.binding)
                except DevFlowError as exc:
                    if exc.code != "EFFECT_NOT_FOUND":
                        raise
                    effect_attempt = 1
                else:
                    validated_prior = self._validate_effect_record(
                        state=effect_state,
                        record=prior_effect,
                        binding=plan.binding,
                        authority_records=authority_records,
                    )
                    prior_effect = validated_prior["record"]
                    prior_attempt = validated_prior["effect_attempt"]
                    if prior_effect["phase"] != "ABANDONED":
                        raise DevFlowError(
                            "EFFECT_ALREADY_CLAIMED",
                            "the exact operation already has a durable effect placement",
                            details={
                                "binding": plan.binding,
                                "phase": prior_effect.get("phase"),
                            },
                        )
                    effect_attempt = prior_attempt + 1
            authority_scope_override = {
                "effect_attempt": effect_attempt,
            }
        verified_id, actor_id, authority_scope, verified_authority = (
            self._verified_authority(
                state=observed,
                task_id=task_id,
                expected_revision=expected_revision,
                action_id=action_id,
                contract=contract,
                payload=validated_payload,
                session_id=session_id,
                request_turn_id=request_turn_id,
                scope_override=authority_scope_override,
            )
        )
        contract, plan = plan_current_action(
            observed,
            action_id,
            expected_revision,
            authority_id=verified_id,
            actor_id=actor_id,
        )
        effect_result = None
        committed = None
        if contract.effect_port == "git.prepare-workspace":
            if (
                not isinstance(verified_authority, Mapping)
                or not isinstance(
                    verified_authority.get("binding_digest"),
                    str,
                )
            ):
                raise DevFlowError(
                    "CONFIRMATION_BINDING_MISMATCH",
                    "workspace confirmation lacks its exact binding digest",
                )
            requests = self._workspace_requests(observed)
            uncertain = None
            settlement_error = None
            with self.journal.execution_fence(task_id, plan.binding):
                self.journal.claim(
                    task_id=task_id,
                    plan=plan,
                    payload=validated_payload,
                    requests=requests,
                    authority_binding_digest=verified_authority[
                        "binding_digest"
                    ],
                    expected_attempt=effect_attempt,
                    timestamp=_utc_now(),
                )
                try:
                    repositories = {
                        repository_id: self.git.prepare_workspace(
                            request["repository_path"],
                            request["strategy"],
                            Path(request["destination"]),
                            request["expected_head"],
                        )
                        for repository_id, request in requests.items()
                    }
                    effect_result = {
                        "execution_id": plan.binding,
                        "repositories": repositories,
                    }
                    self.journal.mark_receipt(
                        task_id,
                        plan.binding,
                        effect_result,
                        _utc_now(),
                    )
                except DevFlowError as exc:
                    self.journal.mark_quarantined(
                        task_id,
                        plan.binding,
                        exc.as_dict()["error"],
                        _utc_now(),
                    )
                    uncertain = exc
                if uncertain is None:
                    try:
                        committed = self.store.update(
                            task_id,
                            expected_revision,
                            lambda current: apply_current_action(
                                current,
                                contract,
                                plan,
                                payload=validated_payload,
                                effect_result=effect_result,
                                timestamp=_utc_now(),
                            ),
                        )
                    except DevFlowError as exc:
                        self.journal.mark_quarantined(
                            task_id,
                            plan.binding,
                            exc.as_dict()["error"],
                            _utc_now(),
                        )
                        settlement_error = exc
                    else:
                        try:
                            self.journal.mark_committed(
                                task_id,
                                plan.binding,
                                committed.revision,
                                _utc_now(),
                            )
                        except DevFlowError as exc:
                            settlement_error = exc
            if verified_id is not None:
                if uncertain is not None or settlement_error is not None:
                    try:
                        self.authorities.mark_claimed(task_id, verified_id)
                    except DevFlowError as exc:
                        if exc.code != "CONFIRMATION_CONSUMED":
                            raise
            if uncertain is not None:
                raise DevFlowError(
                    "EFFECT_UNCERTAIN",
                    "workspace effect requires explicit recovery",
                    details={
                        "execution_id": plan.binding,
                        "cause": uncertain.code,
                    },
                ) from uncertain
            if settlement_error is not None:
                raise settlement_error
        elif contract.effect_port == "git.inspect-result-head":
            repository_id = validated_payload.get("repository_id")
            lease_id = validated_payload.get("lease_id")
            if (
                authority_scope.get("repository_id") != repository_id
                or authority_scope.get("lease_id") != lease_id
            ):
                raise DevFlowError(
                    "AUTHORITY_SCOPE_MISMATCH",
                    "lease authority does not cover the submitted result",
                )
            repository = next(
                (
                    item
                    for item in observed.repositories
                    if item.repository_id == repository_id
                ),
                None,
            )
            if repository is None:
                raise DevFlowError(
                    "REPOSITORY_RESULT_INVALID",
                    "result repository is not part of the task",
                )
            workspace = repository.workspace
            observed_path = (
                workspace.get("path")
                if workspace is not None
                and isinstance(workspace.get("path"), str)
                else repository.path
            )
            effect_result = {
                "observed_head": self.git.inspect(observed_path)["head"],
            }
        elif contract.effect_port != "none":
            raise DevFlowError(
                "EFFECT_UNSUPPORTED",
                "node effect port is not implemented",
                details={"effect_port": contract.effect_port},
            )
        if contract.effect_port != "git.prepare-workspace":
            committed = self.store.update(
                task_id,
                expected_revision,
                lambda current: apply_current_action(
                    current,
                    contract,
                    plan,
                    payload=validated_payload,
                    effect_result=effect_result,
                    timestamp=_utc_now(),
                ),
            )
        if committed is None:
            raise AssertionError("action did not produce a committed task state")
        consumed_confirmation = None
        if verified_id is not None:
            consumed_confirmation = self.authorities.public_packet(
                self.authorities.consume(task_id, verified_id)
            )
        return MutationReceipt(
            task_id=committed.task_id,
            action_id=plan.action_id,
            committed_revision=committed.revision,
            status=committed.status,
            current_node=committed.current_node,
            changed_sections=tuple(
                sorted(
                    {
                        pointer.split("/")[1]
                        for pointer in plan.allowed_writes
                        if pointer.startswith("/")
                    }
                )
            ),
            plan_binding=plan.binding,
            confirmation=consumed_confirmation,
        )

    def effect_inspect(self, task_id: str) -> dict:
        self.store.load(task_id)
        return {
            "schema": "dev-flow-v4-effect-inspection/v1",
            "task_id": task_id,
            "executions": self.journal.inspect(task_id),
        }

    @staticmethod
    def _operator_intervention(
        task_id: str,
        binding: str,
        reason: str,
    ) -> dict:
        return {
            "schema": "dev-flow-v4-operator-intervention/v1",
            "task_id": task_id,
            "execution_id": binding,
            "required": True,
            "reason": reason,
            "automatic_redispatch": False,
            "automatic_compensation": False,
            "automatic_unblock": False,
            "caller_assertion_can_unblock": False,
        }

    def _effect_confirmation_record(
        self,
        task_id: str,
        request_id: object,
        records: Iterable[Mapping[str, object]],
    ) -> Mapping[str, object]:
        if not isinstance(request_id, str):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal does not identify its original confirmation",
            )
        for record in records:
            if record.get("request_id") == request_id:
                return record
        raise DevFlowError(
            "EFFECT_JOURNAL_INVALID",
            "effect journal references unavailable confirmation evidence",
            details={"request_id": request_id},
        )

    def _validate_recoverable_effect(
        self,
        *,
        state: TaskState,
        record: Mapping[str, object],
        binding: str,
        authority_records: Iterable[Mapping[str, object]],
    ) -> tuple:
        """Validate a journal record against current task and authority proof."""

        validated = self._validate_effect_record(
            state=state,
            record=record,
            binding=binding,
            authority_records=authority_records,
        )
        record = validated["record"]
        if record["phase"] not in {"CLAIMED", "RECEIPT", "QUARANTINED"}:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal phase is not recoverable",
            )
        if validated["original_confirmation"] is None:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "recoverable effect lacks original confirmation evidence",
            )
        return (
            validated["contract"],
            validated["plan"],
            validated["payload"],
            validated["requests"],
            validated["effect_attempt"],
        )

    def _recovery_proof(
        self,
        *,
        record: Mapping[str, object],
        binding: str,
        mode: str,
    ) -> tuple:
        requests = record["requests"]
        if mode == "settle":
            try:
                repositories = {
                    repository_id: self.git.observe_workspace(
                        requests[repository_id]
                    )
                    for repository_id in sorted(requests)
                }
            except DevFlowError:
                return None, None, "EFFECT_SETTLEMENT_UNPROVEN"
            effect_result = {
                "execution_id": binding,
                "repositories": repositories,
            }
            stored_receipt = record.get("receipt")
            if (
                stored_receipt is not None
                and stored_receipt != effect_result
            ):
                return None, None, "EFFECT_SETTLEMENT_UNPROVEN"
            proof = {"receipt": effect_result}
        elif mode == "abandon":
            try:
                absent = {
                    repository_id: bool(
                        self.git.workspace_effect_absent(
                            requests[repository_id]
                        )
                    )
                    for repository_id in sorted(requests)
                }
            except DevFlowError:
                return None, None, "EFFECT_ABSENCE_UNPROVEN"
            if not all(absent.values()):
                return None, None, "EFFECT_ABSENCE_UNPROVEN"
            proof = {"absence": absent}
        else:
            raise AssertionError("proof requested for unsupported recovery mode")
        proof_binding = {
            "execution_id": binding,
            "mode": mode,
            "effect_attempt": record["attempt"],
            "proof": proof,
        }
        digest = hashlib.sha256(
            b"dev-flow-v4-recovery-proof/v1\x00"
            + canonical_json_bytes(proof_binding)
        ).hexdigest()
        return proof, digest, None

    def recover_effect(
        self,
        task_id: str,
        binding: str,
        mode: str,
        *,
        session_id: Optional[str] = None,
        request_turn_id: Optional[str] = None,
    ) -> dict:
        if mode not in _RECOVERY_MODES:
            raise DevFlowError(
                "RECOVERY_MODE_INVALID",
                "recovery mode is not supported",
                details={"mode": mode},
            )
        authority_state = self.store.load(task_id)
        self._reconcile_confirmations(authority_state)
        record = self.journal.get(task_id, binding)
        authority_records = self.authorities.evidence_for_task(task_id)
        validated_record = self._validate_effect_record(
            state=authority_state,
            record=record,
            binding=binding,
            authority_records=authority_records,
        )
        record = validated_record["record"]
        if mode == "reattach":
            return self._operator_intervention(
                task_id,
                binding,
                "AUTHENTICATED_LIVE_RUNTIME_UNAVAILABLE",
            )
        if mode == "compensate":
            return self._operator_intervention(
                task_id,
                binding,
                "DUAL_BOUNDARY_COMPENSATION_AUTHORITY_UNAVAILABLE",
            )

        phase = record["phase"]
        if phase == "COMMITTED":
            return {
                "schema": "dev-flow-v4-effect-recovery-result/v1",
                "task_id": task_id,
                "execution_id": binding,
                "outcome": "SETTLED",
                "committed_revision": record.get("committed_revision"),
                "already_terminal": True,
            }
        if phase == "ABANDONED":
            return {
                "schema": "dev-flow-v4-effect-recovery-result/v1",
                "task_id": task_id,
                "execution_id": binding,
                "outcome": "ABANDONED",
                "already_terminal": True,
            }
        if phase not in {"CLAIMED", "RECEIPT", "QUARANTINED"}:
            raise DevFlowError(
                "EFFECT_PHASE_INVALID",
                "effect is not eligible for explicit recovery",
                details={"phase": phase},
            )

        (
            original_contract,
            original_plan,
            payload,
            requests,
            effect_attempt,
        ) = self._validate_recoverable_effect(
            state=authority_state,
            record=record,
            binding=binding,
            authority_records=authority_records,
        )
        prior_recovery_records = []
        for candidate in authority_records:
            candidate_binding = candidate.get("binding")
            candidate_scope = (
                candidate_binding.get("scope")
                if isinstance(candidate_binding, Mapping)
                else None
            )
            if (
                candidate.get("status")
                in {"PENDING", "CONFIRMED"}
                and isinstance(candidate_binding, Mapping)
                and isinstance(candidate_scope, Mapping)
                and candidate_binding.get("task_id") == task_id
                and candidate_binding.get("workflow_identity")
                == authority_state.workflow_identity
                and candidate_binding.get("expected_revision")
                == authority_state.revision
                and candidate_binding.get("action_id")
                == "effect.recover." + mode
                and candidate_binding.get("grant") == "effect-recovery"
                and candidate_binding.get("repository_context")
                == self._repository_context(authority_state)
                and candidate_scope.get("execution_id") == binding
                and candidate_scope.get("mode") == mode
                and candidate_scope.get("effect_attempt") == effect_attempt
            ):
                prior_recovery_records.append(candidate)
        proof, proof_digest, proof_failure = self._recovery_proof(
            record=record,
            binding=binding,
            mode=mode,
        )
        if proof_failure is not None:
            if prior_recovery_records:
                for candidate in prior_recovery_records:
                    self.authorities.mark_stale(
                        task_id,
                        candidate["request_id"],
                    )
                proof_failure = "EFFECT_RECOVERY_EVIDENCE_CHANGED"
            return self._operator_intervention(
                task_id,
                binding,
                proof_failure,
            )
        recovery_scope = {
            "execution_id": binding,
            "mode": mode,
            "effect_attempt": effect_attempt,
            "evidence_digest": proof_digest,
        }
        for candidate in prior_recovery_records:
            candidate_binding = candidate["binding"]
            candidate_scope = candidate_binding["scope"]
            if candidate_scope.get("evidence_digest") != proof_digest:
                self.authorities.mark_stale(
                    task_id,
                    candidate["request_id"],
                )
        recovery_claim = record.get("recovery_claim")
        if isinstance(recovery_claim, Mapping) and (
            recovery_claim.get("mode") != mode
            or recovery_claim.get("effect_attempt") != effect_attempt
            or not isinstance(recovery_claim.get("request_id"), str)
        ):
            raise DevFlowError(
                "EFFECT_RECOVERY_ALREADY_CLAIMED",
                "effect recovery already belongs to another exact request",
                details={
                    "request_id": recovery_claim.get("request_id"),
                    "mode": recovery_claim.get("mode"),
                    "effect_attempt": recovery_claim.get("effect_attempt"),
                },
            )
        if recovery_claim is not None and not isinstance(
            recovery_claim,
            Mapping,
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect recovery claim is malformed",
            )
        claimed_request_id = (
            recovery_claim.get("request_id")
            if isinstance(recovery_claim, Mapping)
            and recovery_claim.get("mode") == mode
            and isinstance(recovery_claim.get("request_id"), str)
            else None
        )
        if claimed_request_id is not None:
            claimed_record = self._effect_confirmation_record(
                task_id,
                claimed_request_id,
                authority_records,
            )
            claimed_binding = claimed_record.get("binding")
            claimed_actor = (
                claimed_binding.get("actor")
                if isinstance(claimed_binding, Mapping)
                else None
            )
            if (
                claimed_record.get("status")
                not in {"CONFIRMED", "CLAIMED"}
                or not isinstance(claimed_binding, Mapping)
                or claimed_binding.get("task_id") != task_id
                or claimed_binding.get("workflow_identity")
                != authority_state.workflow_identity
                or claimed_binding.get("expected_revision")
                != authority_state.revision
                or claimed_binding.get("action_id")
                != "effect.recover." + mode
                or claimed_binding.get("grant") != "effect-recovery"
                or not isinstance(claimed_actor, Mapping)
                or claimed_actor.get("role") != "operator"
                or claimed_binding.get("repository_context")
                != self._repository_context(authority_state)
            ):
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "effect recovery claim does not match its confirmation",
                )
            if claimed_binding.get("session_id") != session_id:
                raise DevFlowError(
                    "EFFECT_RECOVERY_ALREADY_CLAIMED",
                    "effect recovery already belongs to another exact request",
                    details={
                        "request_id": claimed_request_id,
                        "mode": mode,
                        "effect_attempt": effect_attempt,
                    },
                )
            if (
                claimed_binding.get("scope") != recovery_scope
                or claimed_binding.get("context") != recovery_scope
            ):
                return self._operator_intervention(
                    task_id,
                    binding,
                    "EFFECT_RECOVERY_EVIDENCE_CHANGED",
                )
        (
            recovery_id,
            _,
            verified_scope,
            verified_recovery,
        ) = self._verified_authority(
            state=authority_state,
            task_id=task_id,
            expected_revision=authority_state.revision,
            action_id="effect.recover." + mode,
            contract=original_contract,
            payload=recovery_scope,
            session_id=session_id,
            request_turn_id=request_turn_id,
            allow_claimed_request_id=claimed_request_id,
            grant_override="effect-recovery",
            actor_role_override="operator",
            scope_override=recovery_scope,
        )
        if verified_scope != recovery_scope or recovery_id is None:
            raise DevFlowError(
                "CONFIRMATION_BINDING_MISMATCH",
                "recovery confirmation does not cover this execution and mode",
            )
        if (
            not isinstance(verified_recovery, Mapping)
            or not isinstance(
                verified_recovery.get("binding_digest"),
                str,
            )
        ):
            raise DevFlowError(
                "CONFIRMATION_BINDING_MISMATCH",
                "recovery confirmation lacks its exact binding digest",
            )

        stale_confirmation = False
        conflict = None
        result = None
        with self.journal.execution_fence(task_id, binding):
            fresh_state = self.store.load(task_id)
            fresh_record = self.journal.get(task_id, binding)
            fresh_validated = self._validate_effect_record(
                state=fresh_state,
                record=fresh_record,
                binding=binding,
                authority_records=authority_records,
            )
            fresh_record = fresh_validated["record"]
            fresh_phase = fresh_record["phase"]
            if fresh_phase in {"COMMITTED", "ABANDONED"}:
                owner = fresh_record.get("recovery_claim")
                if (
                    not isinstance(owner, Mapping)
                    or owner.get("request_id") != recovery_id
                ):
                    stale_confirmation = True
                result = {
                    "schema": "dev-flow-v4-effect-recovery-result/v1",
                    "task_id": task_id,
                    "execution_id": binding,
                    "outcome": (
                        "SETTLED"
                        if fresh_phase == "COMMITTED"
                        else "ABANDONED"
                    ),
                    "already_terminal": True,
                }
                if fresh_phase == "COMMITTED":
                    result["committed_revision"] = fresh_record.get(
                        "committed_revision"
                    )
            else:
                (
                    fresh_contract,
                    fresh_plan,
                    fresh_payload,
                    _,
                    fresh_attempt,
                ) = self._validate_recoverable_effect(
                    state=fresh_state,
                    record=fresh_record,
                    binding=binding,
                    authority_records=authority_records,
                )
                fresh_proof, fresh_digest, fresh_failure = (
                    self._recovery_proof(
                        record=fresh_record,
                        binding=binding,
                        mode=mode,
                    )
                )
                if (
                    fresh_failure is not None
                    or fresh_digest != proof_digest
                    or fresh_attempt != effect_attempt
                ):
                    stale_confirmation = True
                    result = self._operator_intervention(
                        task_id,
                        binding,
                        (
                            fresh_failure
                            if fresh_failure is not None
                            else "EFFECT_RECOVERY_EVIDENCE_CHANGED"
                        ),
                    )
                else:
                    fresh_claim = fresh_record.get("recovery_claim")
                    if isinstance(fresh_claim, Mapping):
                        if (
                            fresh_claim.get("request_id") != recovery_id
                            or fresh_claim.get("mode") != mode
                            or fresh_claim.get("effect_attempt")
                            != effect_attempt
                        ):
                            conflict = DevFlowError(
                                "EFFECT_RECOVERY_ALREADY_CLAIMED",
                                "effect recovery already belongs to another exact request",
                                details={
                                    "request_id": fresh_claim.get("request_id"),
                                    "mode": fresh_claim.get("mode"),
                                    "effect_attempt": fresh_claim.get(
                                        "effect_attempt"
                                    ),
                                },
                            )
                            stale_confirmation = True
                    elif fresh_claim is not None:
                        conflict = DevFlowError(
                            "EFFECT_JOURNAL_INVALID",
                            "effect recovery claim is malformed",
                        )
                        stale_confirmation = True
                    else:
                        self.journal.claim_recovery(
                            task_id=task_id,
                            binding=binding,
                            request_id=recovery_id,
                            binding_digest=verified_recovery[
                                "binding_digest"
                            ],
                            mode=mode,
                            effect_attempt=effect_attempt,
                            evidence_digest=proof_digest,
                            timestamp=_utc_now(),
                        )
                    if conflict is None:
                        if mode == "settle":
                            effect_result = fresh_proof["receipt"]
                            self.journal.mark_receipt(
                                task_id,
                                binding,
                                effect_result,
                                _utc_now(),
                            )
                            try:
                                committed = self.store.update(
                                    task_id,
                                    fresh_record["expected_revision"],
                                    lambda current: apply_current_action(
                                        current,
                                        fresh_contract,
                                        fresh_plan,
                                        payload=fresh_payload,
                                        effect_result=effect_result,
                                        timestamp=_utc_now(),
                                    ),
                                )
                            except DevFlowError:
                                committed = self.store.load(task_id)
                                if (
                                    self._matching_effect_summary(
                                        committed,
                                        {
                                            **fresh_record,
                                            "receipt": effect_result,
                                        },
                                    )
                                    is None
                                ):
                                    raise
                            self.journal.mark_committed(
                                task_id,
                                binding,
                                fresh_record["expected_revision"] + 1,
                                _utc_now(),
                            )
                            result = {
                                "schema": "dev-flow-v4-effect-recovery-result/v1",
                                "task_id": task_id,
                                "execution_id": binding,
                                "outcome": "SETTLED",
                                "committed_revision": committed.revision,
                            }
                        elif mode == "abandon":
                            self.journal.mark_abandoned(
                                task_id,
                                binding,
                                _utc_now(),
                            )
                            result = {
                                "schema": "dev-flow-v4-effect-recovery-result/v1",
                                "task_id": task_id,
                                "execution_id": binding,
                                "outcome": "ABANDONED",
                            }
                        else:
                            raise AssertionError(
                                "validated recovery mode was not handled"
                            )

        if stale_confirmation:
            self.authorities.mark_stale(task_id, recovery_id)
        if conflict is not None:
            raise conflict
        if result is None:
            raise AssertionError("recovery did not produce a result")
        if not stale_confirmation:
            original = record.get("authority_id")
            if isinstance(original, str):
                self.authorities.consume(task_id, original)
            result["confirmation"] = self.authorities.public_packet(
                self.authorities.consume(task_id, recovery_id)
            )
        return result
