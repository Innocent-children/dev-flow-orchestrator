# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: manager-only secret transport and schema-v4 CLI authority.
from __future__ import annotations

import copy as _manager_copy
import hmac as _manager_hmac
import socket as _manager_socket
import struct as _manager_struct
from dataclasses import dataclass as _manager_dataclass


MANAGER_SECRET_CHANNEL_MAX_BYTES = 1024
MANAGER_SECRET_CHANNEL_MIN_BYTES = MIN_MANAGER_SECRET_BYTES
MANAGER_CAPABILITY_DEFAULT_TTL_SECONDS = 15 * 60
MANAGER_CAPABILITY_CLOCK_ID = "system-monotonic/v1"
MANAGER_CAPABILITY_AUTHORIZED_EVENT = (
    "manager_capability_request_consumed"
)
MANAGER_CAPABILITY_ISSUED_EVENT = "manager_capability_authorized"
MANAGER_CAPABILITY_REVOKED_EVENT = "manager_capability_revoked"
MANAGER_SECRET_CHANNEL_FD_ENV = "DEV_FLOW_MANAGER_SECRET_FD"
MANAGER_REGISTRY_AUTHORIZE_ACTION_ID = (
    "manager.capability.authorize.v1"
)
MANAGER_REGISTRY_REVOKE_ACTION_ID = "manager.capability.revoke.v1"
MANAGER_SECRET_PUBLICATION_PLAN_SCHEMA = (
    "dev-flow-manager-secret-publication-plan/v1"
)

_manager_mutation_seal_key = secrets.token_bytes(32)
_manager_preauthorization_seal_key = secrets.token_bytes(32)
_manager_registry_seal_key = secrets.token_bytes(32)
_manager_workflow_action_secret_domain = (
    b"dev-flow-manager-workflow-action-secret-v1\x00"
)
_manager_authority_context_var = contextvars.ContextVar(
    "dev_flow_manager_authority_context",
    default=None,
)
_manager_cli_effect_context_var = contextvars.ContextVar(
    "dev_flow_manager_cli_effect_context",
    default=None,
)

_MANAGER_REQUEST_TO_PACKAGE_ACTION = {
    "cancel": "task.cancel",
    "transition": "task.transition",
    "transition-cancel": "task.transition",
}
_MANAGER_PACKAGE_ACTION_EVENT_TYPES = {
    "evidence.artifact.record": frozenset({"artifact_recorded"}),
    "evidence.index.record": frozenset({"index_recorded"}),
    "evidence.review-snapshot.record": frozenset(
        {"review_snapshot_recorded"}
    ),
    "evidence.test.record": frozenset({"test_recorded"}),
    "gate.approve": frozenset({"gate_approved"}),
    "recovery.quarantine": frozenset(
        {
            "mutation_quarantine_archive_retried",
            "mutation_quarantine_recovered",
        }
    ),
    "task.baseline": frozenset({"baseline_recorded"}),
    "task.cancel": frozenset({"task_cancelled"}),
    "task.preflight": frozenset({"preflight_recorded"}),
    "task.route.set": frozenset({"route_set"}),
    "task.transition": frozenset(
        {"lite_risk_escalation_required", "state_transitioned"}
    ),
    "workspace.prepare": frozenset(
        {"workspace_plan_recorded", "workspace_prepared"}
    ),
    # Repository-orchestration mutations use their catalog operation
    # identity as the package action identity.  Keep the operation/event
    # relation explicit and exact: a manager proof for one operation must
    # never authorize another operation's canonical audit event.  Manager
    # capability authorize/revoke are intentionally absent because those
    # registry actions are operator-authorized and do not consume a manager
    # capability request nonce.
    "orchestration.artifact.record/v1": frozenset(
        {"orchestration.artifact.record.event.v1"}
    ),
    "orchestration.assignment.issue/v1": frozenset(
        {"orchestration.assignment.issue.event.v1"}
    ),
    "orchestration.attempt.abandon/v1": frozenset(
        {"orchestration.attempt.abandon.event.v1"}
    ),
    "orchestration.barrier.close/v1": frozenset(
        {"orchestration.barrier.close.event.v1"}
    ),
    "orchestration.barrier.reopen/v1": frozenset(
        {"orchestration.barrier.reopen.event.v1"}
    ),
    "orchestration.cancellation.request/v1": frozenset(
        {"orchestration.cancellation.request.event.v1"}
    ),
    "orchestration.dispatch.handoff/v1": frozenset(
        {"orchestration.dispatch.handoff.event.v1"}
    ),
    "orchestration.finalization.commit/v1": frozenset(
        {"orchestration.finalization.commit.event.v1"}
    ),
    "orchestration.frontier.advance/v1": frozenset(
        {"orchestration.frontier.advance.event.v1"}
    ),
    "orchestration.integration.capture/v1": frozenset(
        {"orchestration.integration.capture.event.v1"}
    ),
    "orchestration.integration.verify/v1": frozenset(
        {"orchestration.integration.verify.event.v1"}
    ),
    "orchestration.lease.expire/v1": frozenset(
        {"orchestration.lease.expire.event.v1"}
    ),
    "orchestration.lease.issue/v1": frozenset(
        {"orchestration.lease.issue.event.v1"}
    ),
    "orchestration.lease.revoke/v1": frozenset(
        {"orchestration.lease.revoke.event.v1"}
    ),
    "orchestration.map.expand/v1": frozenset(
        {"orchestration.map.expand.event.v1"}
    ),
    "orchestration.map.invalidate/v1": frozenset(
        {"orchestration.map.invalidate.event.v1"}
    ),
    "orchestration.plan.approve/v1": frozenset(
        {"orchestration.plan.approve.event.v1"}
    ),
    "orchestration.plan.record/v1": frozenset(
        {"orchestration.plan.record.event.v1"}
    ),
    "orchestration.reconciliation.begin/v1": frozenset(
        {"orchestration.reconciliation.begin.event.v1"}
    ),
    "orchestration.reconciliation.complete/v1": frozenset(
        {"orchestration.reconciliation.complete.event.v1"}
    ),
    "orchestration.result.accept/v1": frozenset(
        {"orchestration.result.accept.event.v1"}
    ),
    "orchestration.result.invalidate/v1": frozenset(
        {"orchestration.result.invalidate.event.v1"}
    ),
    "orchestration.retry.request/v1": frozenset(
        {"orchestration.retry.request.event.v1"}
    ),
    "orchestration.review.record/v1": frozenset(
        {"orchestration.review.record.event.v1"}
    ),
    "orchestration.runtime-stop.record/v1": frozenset(
        {"orchestration.runtime-stop.record.event.v1"}
    ),
    "orchestration.runtime.recovery.observe/v1": frozenset(
        {"orchestration.runtime.recovery.observe.event.v1"}
    ),
    "orchestration.timeout.record/v1": frozenset(
        {"orchestration.timeout.record.event.v1"}
    ),
}


def _manager_package_action_event_types(
    package_action_id: object,
) -> frozenset[str] | None:
    if package_action_id == "control.reconcile/v1":
        return frozenset().union(
            *_MANAGER_PACKAGE_ACTION_EVENT_TYPES.values()
        )
    if not isinstance(package_action_id, str):
        return None
    return _MANAGER_PACKAGE_ACTION_EVENT_TYPES.get(package_action_id)


def _manager_system_monotonic_ns() -> int:
    """Return one monotonic epoch that is comparable across processes."""

    clock_gettime_ns = getattr(time, "clock_gettime_ns", None)
    clock_monotonic = getattr(time, "CLOCK_MONOTONIC", None)
    if callable(clock_gettime_ns) and clock_monotonic is not None:
        return int(clock_gettime_ns(clock_monotonic))
    # macOS exposes a process-independent monotonic epoch.
    return int(time.monotonic_ns())


def _manager_zeroize(value: bytearray | None) -> None:
    if value is None:
        return
    for index in range(len(value)):
        value[index] = 0


def _manager_json_clone(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _manager_canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@_manager_dataclass(frozen=True)
class ManagerSecretChannelConfig:
    """Non-sensitive configuration for one inherited local descriptor."""

    fd: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.fd, bool)
            or not isinstance(self.fd, int)
            or self.fd <= 2
        ):
            raise FlowError(
                "MANAGER_SECRET_CHANNEL_INVALID",
                "manager secret channel must be an inherited descriptor above 2",
            )


class _EnvironmentManagerSecretChannel:
    """Trusted local MCP adapter over one inherited secret descriptor."""

    __slots__ = ("_config",)

    def __init__(self, config: ManagerSecretChannelConfig) -> None:
        if not isinstance(config, ManagerSecretChannelConfig):
            raise FlowError(
                "MANAGER_SECRET_CHANNEL_INVALID",
                "manager secret channel configuration is invalid",
            )
        self._config = config

    def resolve_secret(self, capability_id: str) -> bytearray:
        if not isinstance(capability_id, str) or not capability_id:
            raise FlowError(
                "MANAGER_CAPABILITY_UNKNOWN",
                "manager secret resolution requires a capability identity",
            )
        return resolve_manager_secret(self._config)

    def principal_for(
        self, request_identity: object
    ) -> AgentPrincipal:
        try:
            request = validate_manager_capability_request(
                request_identity
            )
        except OrchestrationAuthorityError as exc:
            raise FlowError(
                exc.code, exc.message, details=exc.details
            ) from exc
        # Only the schema-validated session binding crosses MCP. Role and
        # user/host identities are always observed from this local process.
        return _manager_local_principal(
            request.manager_session_id
        )


def manager_secret_channel_from_environment(
) -> _EnvironmentManagerSecretChannel:
    """Resolve only non-secret inherited-FD configuration from the process."""

    raw = os.environ.get(MANAGER_SECRET_CHANNEL_FD_ENV)
    if raw is None:
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
            "manager secret channel descriptor is not configured",
            details={"environment": MANAGER_SECRET_CHANNEL_FD_ENV},
        )
    try:
        fd = int(raw, 10)
    except (TypeError, ValueError) as exc:
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_INVALID",
            "manager secret channel descriptor must be a decimal integer",
            details={"environment": MANAGER_SECRET_CHANNEL_FD_ENV},
        ) from exc
    return _EnvironmentManagerSecretChannel(
        ManagerSecretChannelConfig(fd)
    )


def _manager_channel_descriptor(config: ManagerSecretChannelConfig) -> int:
    if not isinstance(config, ManagerSecretChannelConfig):
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_INVALID",
            "manager secret channel configuration is invalid",
        )
    duplicate: int | None = None
    try:
        duplicate = os.dup(config.fd)
        mode = os.fstat(duplicate).st_mode
        is_socket = bool(
            getattr(stat, "S_ISSOCK", lambda _mode: False)(mode)
        )
        if not stat.S_ISFIFO(mode) and not is_socket:
            raise FlowError(
                "MANAGER_SECRET_CHANNEL_FORBIDDEN",
                "manager secret channel must be an inherited pipe or local socket",
            )
        if is_socket:
            channel_socket = _manager_socket.socket(fileno=duplicate)
            try:
                if channel_socket.family != _manager_socket.AF_UNIX:
                    raise FlowError(
                        "MANAGER_SECRET_CHANNEL_FORBIDDEN",
                        "manager secret socket must use the local AF_UNIX family",
                    )
                try:
                    channel_socket.getpeername()
                except OSError as exc:
                    raise FlowError(
                        "MANAGER_SECRET_CHANNEL_FORBIDDEN",
                        "manager secret socket must be connected",
                    ) from exc
            finally:
                duplicate = channel_socket.detach()
        result = duplicate
        duplicate = None
        return result
    except FlowError:
        raise
    except OSError as exc:
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
            "manager secret channel is unavailable",
        ) from exc
    finally:
        if duplicate is not None:
            try:
                os.close(duplicate)
            except OSError:
                pass


def _manager_read_exact(fd: int, size: int) -> bytearray:
    result = bytearray()
    try:
        while len(result) < size:
            chunk = os.read(fd, size - len(result))
            if not chunk:
                raise FlowError(
                    "MANAGER_SECRET_CHANNEL_TRUNCATED",
                    "manager secret channel closed before its bounded frame completed",
                )
            result.extend(chunk)
        return result
    except BaseException:
        _manager_zeroize(result)
        raise


def resolve_manager_secret(
    config: ManagerSecretChannelConfig,
) -> bytearray:
    """Read one bounded length-prefixed proof from an inherited descriptor."""

    fd = _manager_channel_descriptor(config)
    header = None
    secret = None
    try:
        header = _manager_read_exact(fd, 4)
        (length,) = _manager_struct.unpack(">I", bytes(header))
        if not (
            MANAGER_SECRET_CHANNEL_MIN_BYTES
            <= length
            <= MANAGER_SECRET_CHANNEL_MAX_BYTES
        ):
            raise FlowError(
                "MANAGER_SECRET_CHANNEL_FRAME_INVALID",
                "manager secret channel frame length is outside its fixed bounds",
            )
        secret = _manager_read_exact(fd, length)
        return secret
    except OSError as exc:
        _manager_zeroize(secret)
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
            "manager secret channel could not be read",
        ) from exc
    finally:
        _manager_zeroize(header)
        os.close(fd)


def publish_manager_secret(
    config: ManagerSecretChannelConfig,
    manager_secret: bytes | bytearray,
) -> None:
    """Publish one proof without ever routing it through process text."""

    if not isinstance(manager_secret, (bytes, bytearray)):
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_FRAME_INVALID",
            "manager secret channel accepts only secret bytes",
        )
    length = len(manager_secret)
    if not (
        MANAGER_SECRET_CHANNEL_MIN_BYTES
        <= length
        <= MANAGER_SECRET_CHANNEL_MAX_BYTES
    ):
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_FRAME_INVALID",
            "manager secret channel frame length is outside its fixed bounds",
        )
    fd = _manager_channel_descriptor(config)
    frame = bytearray(_manager_struct.pack(">I", length))
    frame.extend(manager_secret)
    try:
        offset = 0
        while offset < len(frame):
            written = os.write(fd, frame[offset:])
            if written <= 0:
                raise FlowError(
                    "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
                    "manager secret channel closed before publication completed",
                )
            offset += written
    except OSError as exc:
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
            "manager secret channel could not publish the capability proof",
        ) from exc
    finally:
        _manager_zeroize(frame)
        os.close(fd)


def _manager_local_principal(
    manager_session_id: str,
    *,
    role: str = "manager",
) -> AgentPrincipal:
    user_identity = f"uid:{os.getuid()}"
    host_identity = "host:" + os.uname().nodename
    return validate_agent_principal(
        {
            "schema": AGENT_PRINCIPAL_SCHEMA,
            "role": role,
            "session_id": manager_session_id,
            "os_user_identity_sha256": hashlib.sha256(
                user_identity.encode("utf-8")
            ).hexdigest(),
            "host_identity_sha256": hashlib.sha256(
                host_identity.encode("utf-8")
            ).hexdigest(),
        }
    )


class _ManagerAuthorityInvocation:
    __slots__ = (
        "request",
        "action_id",
        "package_action_id",
        "principal",
        "operation_fingerprint_sha256",
        "_secret_resolver",
        "_secret",
        "_resolved",
        "_preauthorization",
        "_wall_time_ns",
        "_monotonic_time_ns",
        "_clock_id",
    )

    def __init__(
        self,
        *,
        request: ManagerCapabilityRequest,
        action_id: str,
        principal: AgentPrincipal,
        secret_resolver: Any,
        operation_fingerprint_sha256: str | None,
        wall_time_ns: Any,
        monotonic_time_ns: Any,
        clock_id: str,
    ) -> None:
        self.request = request
        self.action_id = action_id
        self.package_action_id = _MANAGER_REQUEST_TO_PACKAGE_ACTION.get(
            action_id, action_id
        )
        self.principal = principal
        self.operation_fingerprint_sha256 = (
            operation_fingerprint_sha256
        )
        self._secret_resolver = secret_resolver
        self._secret: bytearray | None = None
        self._resolved = False
        self._preauthorization: object | None = None
        self._wall_time_ns = wall_time_ns
        self._monotonic_time_ns = monotonic_time_ns
        self._clock_id = clock_id

    def clock_context(self) -> tuple[int, int, str]:
        return (
            int(self._wall_time_ns()),
            int(self._monotonic_time_ns()),
            self._clock_id,
        )

    def take_secret(self) -> bytearray:
        if self._resolved:
            raise FlowError(
                "MANAGER_CAPABILITY_PROOF_UNAVAILABLE",
                "manager proof has already been resolved for this invocation",
            )
        self._resolved = True
        try:
            resolved = self._secret_resolver()
        except FlowError:
            raise
        except Exception as exc:
            raise FlowError(
                "MANAGER_CAPABILITY_PROOF_UNAVAILABLE",
                "manager proof could not be resolved",
            ) from exc
        if not isinstance(resolved, bytearray):
            raise FlowError(
                "MANAGER_CAPABILITY_PROOF_INVALID",
                "manager secret channel must return mutable proof bytes",
            )
        self._secret = resolved
        if len(self._secret) < MIN_MANAGER_SECRET_BYTES:
            self.clear_secret()
            raise FlowError(
                "MANAGER_CAPABILITY_PROOF_INVALID",
                "manager proof is invalid",
            )
        return self._secret

    def clear_secret(self) -> None:
        _manager_zeroize(self._secret)
        self._secret = None

    def derive_workflow_action_secret(
        self, binding: dict[str, Any]
    ) -> str:
        """Derive one restart-stable journal key without exposing raw proof."""

        if self._secret is None:
            raise FlowError(
                "MANAGER_CAPABILITY_PROOF_UNAVAILABLE",
                "manager workflow action has no live proof material",
            )
        payload = _json_bytes(binding)
        return _manager_hmac.new(
            self._secret,
            _manager_workflow_action_secret_domain
            + len(payload).to_bytes(8, "big")
            + payload,
            hashlib.sha256,
        ).hexdigest()

    def current_secret(self) -> bytearray:
        if self._secret is None:
            raise FlowError(
                "MANAGER_CAPABILITY_PROOF_UNAVAILABLE",
                "manager workflow action has no live proof material",
            )
        return self._secret

    def install_preauthorization(self, value: object) -> None:
        if self._preauthorization is not None:
            raise FlowError(
                "MANAGER_PREAUTHORIZATION_CONFLICT",
                "manager invocation already owns a sealed preauthorization",
            )
        self._preauthorization = value

    def preauthorization(self) -> object | None:
        return self._preauthorization

    def replace_preauthorization(
        self, expected: object, value: object
    ) -> None:
        if self._preauthorization is not expected:
            raise FlowError(
                "MANAGER_PREAUTHORIZATION_CONFLICT",
                "manager preauthorization changed before scoped rebase",
            )
        self._preauthorization = value

    def effect_authorization_live(self) -> bool:
        return (
            self._secret is not None
            or self._preauthorization is not None
        )

    def clear_effect_authorization(self) -> None:
        self.clear_secret()
        self._preauthorization = None


@contextlib.contextmanager
def _manager_authority_context(
    *,
    request: ManagerCapabilityRequest | dict[str, Any],
    action_id: str,
    secret_resolver: Any,
    principal: AgentPrincipal | dict[str, Any] | None = None,
    operation_fingerprint_sha256: str | None = None,
    wall_time_ns: Any = time.time_ns,
    monotonic_time_ns: Any = _manager_system_monotonic_ns,
    clock_id: str = MANAGER_CAPABILITY_CLOCK_ID,
) -> Iterator[None]:
    """Install one request-scoped authority source for CLI or future MCP."""

    if _manager_authority_context_var.get() is not None:
        raise FlowError(
            "MANAGER_AUTHORITY_CONTEXT_CONFLICT",
            "manager authority contexts cannot be nested or replaced",
        )
    try:
        parsed_request = validate_manager_capability_request(request)
        parsed_principal = validate_agent_principal(
            principal
            if principal is not None
            else _manager_local_principal(
                parsed_request.manager_session_id
            )
        )
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if (
        not isinstance(action_id, str)
        or not action_id
        or action_id != parsed_request.action_id
    ):
        raise FlowError(
            "MANAGER_CAPABILITY_ACTION_MISMATCH",
            "manager request action does not match the sealed runtime operation",
        )
    if not callable(secret_resolver):
        raise FlowError(
            "MANAGER_CAPABILITY_PROOF_UNAVAILABLE",
            "manager proof resolver is unavailable",
        )
    if (
        not callable(wall_time_ns)
        or not callable(monotonic_time_ns)
        or not isinstance(clock_id, str)
        or not clock_id
    ):
        raise FlowError(
            "MANAGER_CAPABILITY_CLOCK_CONTEXT_INVALID",
            "manager authority clock context is unavailable",
        )
    if (
        operation_fingerprint_sha256 is not None
        and (
            not isinstance(operation_fingerprint_sha256, str)
            or len(operation_fingerprint_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in operation_fingerprint_sha256
            )
        )
    ):
        raise FlowError(
            "MANAGER_CAPABILITY_REQUEST_INVALID",
            "manager operation fingerprint must be a SHA-256 digest",
        )
    invocation = _ManagerAuthorityInvocation(
        request=parsed_request,
        action_id=action_id,
        principal=parsed_principal,
        secret_resolver=secret_resolver,
        operation_fingerprint_sha256=(
            operation_fingerprint_sha256
        ),
        wall_time_ns=wall_time_ns,
        monotonic_time_ns=monotonic_time_ns,
        clock_id=clock_id,
    )
    token = _manager_authority_context_var.set(invocation)
    try:
        yield
    finally:
        if invocation.effect_authorization_live():
            invocation.clear_effect_authorization()
        _manager_authority_context_var.reset(token)


def _manager_cli_candidate_intent_sha256(
    args: argparse.Namespace,
) -> str:
    """Bind one parsed CLI candidate without retaining proof transport."""

    excluded = {
        "handler",
        "manager_request_json",
        "manager_secret_fd",
        "_manager_action_id",
        "_manager_mutation_command",
    }
    arguments = {
        name: value
        for name, value in sorted(vars(args).items())
        if name not in excluded
        and not name.startswith("_")
        and not callable(value)
    }
    document = {
        "schema": "dev-flow-manager-cli-candidate-intent/v1",
        "command": getattr(args, "command", None),
        "action_id": getattr(args, "_manager_action_id", None),
        "arguments": arguments,
    }
    try:
        encoded = _json_bytes(document)
    except (TypeError, ValueError) as exc:
        raise FlowError(
            "MANAGER_CANDIDATE_INTENT_INVALID",
            "manager CLI candidate cannot be canonically bound",
        ) from exc
    return hashlib.sha256(
        b"dev-flow-manager-cli-candidate-intent-v1\x00" + encoded
    ).hexdigest()


@contextlib.contextmanager
def _manager_cli_authority_context(
    args: argparse.Namespace,
) -> Iterator[None]:
    """Resolve only public request identity at parse time; proof stays lazy."""

    if not bool(
        getattr(args, "_manager_mutation_command", False)
    ):
        yield
        return
    request_json = getattr(args, "manager_request_json", None)
    channel_fd = getattr(args, "manager_secret_fd", None)
    effect_kind = (
        "preview"
        if bool(getattr(args, "preview", False))
        else "mutation"
    )
    effect_token = _manager_cli_effect_context_var.set(effect_kind)
    try:
        if effect_kind == "preview":
            if request_json is not None or channel_fd is not None:
                raise FlowError(
                    "MANAGER_CAPABILITY_PREVIEW_FORBIDDEN",
                    "read-only preview does not accept manager capability proof",
                )
            yield
            return
        if request_json is None:
            if channel_fd is not None:
                raise FlowError(
                    "MANAGER_CAPABILITY_REQUEST_REQUIRED",
                    "--manager-secret-fd requires --manager-request-json",
                )
            yield
            return
        try:
            request_value = json.loads(request_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FlowError(
                "MANAGER_CAPABILITY_REQUEST_INVALID",
                "--manager-request-json is not valid JSON",
            ) from exc
        if not isinstance(request_value, dict):
            raise FlowError(
                "MANAGER_CAPABILITY_REQUEST_INVALID",
                "--manager-request-json must contain one public request object",
            )
        config = (
            None
            if channel_fd is None
            else ManagerSecretChannelConfig(channel_fd)
        )

        def resolver() -> bytearray:
            if config is None:
                raise FlowError(
                    "MANAGER_SECRET_CHANNEL_REQUIRED",
                    "schema-v4 mutation requires --manager-secret-fd",
                )
            return resolve_manager_secret(config)

        with _manager_authority_context(
            request=request_value,
            action_id=getattr(args, "_manager_action_id", ""),
            secret_resolver=resolver,
            operation_fingerprint_sha256=(
                _manager_cli_candidate_intent_sha256(args)
            ),
        ):
            yield
    finally:
        _manager_cli_effect_context_var.reset(effect_token)


def _manager_state_digest(state_value: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(state_value)).hexdigest()


def _manager_seal(key: bytes, payload: dict[str, Any]) -> str:
    return _manager_hmac.new(
        key, _json_bytes(payload), hashlib.sha256
    ).hexdigest()


def _manager_pre_effect_state_digest(
    state_value: dict[str, Any],
) -> str:
    """Hash the logical locked snapshot, excluding outbox delivery state."""

    logical = _manager_json_clone(state_value)
    logical.pop("pending_event", None)
    logical.pop("pending_events", None)
    logical = _redact_sensitive_value(logical)
    if not isinstance(logical, dict):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_INVALID",
            "manager preauthorization state projection is invalid",
        )
    return _manager_state_digest(logical)


@_manager_dataclass(frozen=True)
class _PreauthorizedManagerMutation:
    authorization: ManagerAuthorization
    task_id: str
    input_revision: int
    authorized_state_revision: int
    action_id: str
    package_action_id: str
    capability_id: str
    request_fingerprint_sha256: str
    request_nonce_sha256: str
    manager_session_id: str
    principal_sha256: str
    operation_fingerprint_sha256: str
    pre_effect_state_sha256: str
    verifier_state_sha256: str
    seal: str

    def seal_payload(self) -> dict[str, Any]:
        return {
            "authorization": self.authorization.as_dict(),
            "task_id": self.task_id,
            "input_revision": self.input_revision,
            "authorized_state_revision": (
                self.authorized_state_revision
            ),
            "action_id": self.action_id,
            "package_action_id": self.package_action_id,
            "capability_id": self.capability_id,
            "request_fingerprint_sha256": (
                self.request_fingerprint_sha256
            ),
            "request_nonce_sha256": self.request_nonce_sha256,
            "manager_session_id": self.manager_session_id,
            "principal_sha256": self.principal_sha256,
            "operation_fingerprint_sha256": (
                self.operation_fingerprint_sha256
            ),
            "pre_effect_state_sha256": (
                self.pre_effect_state_sha256
            ),
            "verifier_state_sha256": self.verifier_state_sha256,
        }


def _manager_preauthorize_locked_state(
    state_value: dict[str, Any],
    *,
    effect_policy: str,
    package_action_id: str | None,
) -> None:
    """Authenticate one v4 mutation before any protected effect can begin."""

    if effect_policy not in {"formal", "generic", "preview", "registry"}:
        raise FlowError(
            "MANAGER_EFFECT_POLICY_INVALID",
            "locked state requires one sealed manager effect policy",
        )
    if state_value.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        return
    if effect_policy in {"formal", "preview", "registry"}:
        return
    if (
        not isinstance(package_action_id, str)
        or _manager_package_action_event_types(package_action_id)
        is None
    ):
        raise FlowError(
            "MANAGER_HANDLER_ACTION_INVALID",
            "generic schema-v4 mutation has no sealed package action",
        )
    invocation = _manager_authority_context_var.get()
    if not isinstance(invocation, _ManagerAuthorityInvocation):
        raise FlowError(
            "MANAGER_CAPABILITY_REQUIRED",
            "schema-v4 agent-plane mutation requires manager capability proof",
            details={"task_id": state_value.get("task_id")},
        )
    if invocation.preauthorization() is not None:
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_CONFLICT",
            "manager invocation cannot authorize more than one effect window",
        )
    if invocation.package_action_id != package_action_id:
        raise FlowError(
            "MANAGER_HANDLER_ACTION_MISMATCH",
            "manager proof is bound to a different package handler action",
            details={
                "authorized_package_action_id": (
                    invocation.package_action_id
                ),
                "actual_package_action_id": package_action_id,
            },
        )
    request = invocation.request
    actual_revision = int(state_value.get("revision", 0))
    checks = (
        (
            request.task_id,
            state_value.get("task_id"),
            "MANAGER_CAPABILITY_TASK_MISMATCH",
        ),
        (
            request.expected_revision,
            actual_revision,
            "MANAGER_CAPABILITY_REVISION_MISMATCH",
        ),
        (
            request.action_id,
            invocation.action_id,
            "MANAGER_CAPABILITY_ACTION_MISMATCH",
        ),
    )
    for supplied, actual, code in checks:
        if supplied != actual:
            raise FlowError(
                code,
                "manager request is outside the exact mutation scope",
                details={
                    "task_id": state_value.get("task_id"),
                    "actual_revision": actual_revision,
                },
            )
    operation_fingerprint = invocation.operation_fingerprint_sha256
    if operation_fingerprint is None:
        raise FlowError(
            "MANAGER_CANDIDATE_INTENT_REQUIRED",
            "manager mutation requires a canonical candidate intent",
        )
    orchestration = _manager_orchestration_mapping(state_value)
    capabilities = orchestration["manager_capabilities"]
    verifier = capabilities.get(request.capability_id)
    if verifier is None:
        raise FlowError(
            "MANAGER_CAPABILITY_UNKNOWN",
            "manager capability verifier is unknown",
            details={"task_id": state_value.get("task_id")},
        )
    try:
        verifier_state_sha256 = hashlib.sha256(
            _json_bytes(
                validate_manager_capability_verifier(
                    verifier
                ).as_persistent_dict()
            )
        ).hexdigest()
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    pre_effect_state_sha256 = _manager_pre_effect_state_digest(
        state_value
    )
    principal_sha256 = hashlib.sha256(
        _json_bytes(invocation.principal.as_dict())
    ).hexdigest()
    secret = invocation.take_secret()
    try:
        try:
            wall_time_ns, monotonic_time_ns, clock_id = (
                invocation.clock_context()
            )
            authorization = consume_manager_capability_request(
                verifier,
                request,
                invocation.principal,
                manager_secret=secret,
                wall_time_ns=wall_time_ns,
                monotonic_time_ns=monotonic_time_ns,
                clock_id=clock_id,
            )
        except OrchestrationAuthorityError as exc:
            raise FlowError(
                exc.code, exc.message, details=exc.details
            ) from exc
        values = {
            "task_id": request.task_id,
            "input_revision": request.expected_revision,
            "authorized_state_revision": request.expected_revision,
            "action_id": request.action_id,
            "package_action_id": package_action_id,
            "capability_id": request.capability_id,
            "request_fingerprint_sha256": (
                authorization.request_fingerprint_sha256
            ),
            "request_nonce_sha256": (
                manager_request_nonce_digest(request)
            ),
            "manager_session_id": request.manager_session_id,
            "principal_sha256": principal_sha256,
            "operation_fingerprint_sha256": operation_fingerprint,
            "pre_effect_state_sha256": pre_effect_state_sha256,
            "verifier_state_sha256": verifier_state_sha256,
        }
        preauthorization = _PreauthorizedManagerMutation(
            authorization=authorization,
            **values,
            seal=_manager_seal(
                _manager_preauthorization_seal_key,
                {
                    "authorization": authorization.as_dict(),
                    **values,
                },
            ),
        )
        invocation.install_preauthorization(preauthorization)
    except FlowError:
        invocation.clear_effect_authorization()
        raise
    except BaseException:
        invocation.clear_effect_authorization()
        raise


def _manager_clear_effect_authorization() -> None:
    invocation = _manager_authority_context_var.get()
    if (
        isinstance(invocation, _ManagerAuthorityInvocation)
        and invocation.effect_authorization_live()
    ):
        invocation.clear_effect_authorization()


@_manager_dataclass(frozen=True)
class _AuthorizedManagerMutation:
    task_id: str
    expected_revision: int
    action_id: str
    package_action_id: str
    event_type: str
    capability_id: str
    authorization_id: str
    request_fingerprint_sha256: str
    request_nonce_sha256: str
    manager_session_id: str
    operation_fingerprint_sha256: str | None
    old_state_sha256: str
    candidate_state_sha256: str
    seal: str

    def seal_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "expected_revision": self.expected_revision,
            "action_id": self.action_id,
            "package_action_id": self.package_action_id,
            "event_type": self.event_type,
            "capability_id": self.capability_id,
            "authorization_id": self.authorization_id,
            "request_fingerprint_sha256": (
                self.request_fingerprint_sha256
            ),
            "request_nonce_sha256": self.request_nonce_sha256,
            "manager_session_id": self.manager_session_id,
            "operation_fingerprint_sha256": (
                self.operation_fingerprint_sha256
            ),
            "old_state_sha256": self.old_state_sha256,
            "candidate_state_sha256": self.candidate_state_sha256,
        }


def _manager_orchestration_mapping(
    state_value: dict[str, Any],
) -> dict[str, Any]:
    value = state_value.get("orchestration")
    if not isinstance(value, dict):
        raise FlowError(
            "MANAGER_CAPABILITY_REGISTRY_UNAVAILABLE",
            "schema-v4 task has no manager capability registry",
            details={"task_id": state_value.get("task_id")},
        )
    if value.get("schema") != "dev-flow-orchestration-state/v1":
        raise FlowError(
            "MANAGER_CAPABILITY_REGISTRY_INVALID",
            "schema-v4 orchestration registry has an unsupported schema",
            details={"task_id": state_value.get("task_id")},
        )
    capabilities = value.get("manager_capabilities")
    if not isinstance(capabilities, dict):
        raise FlowError(
            "MANAGER_CAPABILITY_REGISTRY_UNAVAILABLE",
            "schema-v4 task has no manager capability registry",
            details={"task_id": state_value.get("task_id")},
        )
    return value


def _manager_validate_nonce_delta(
    old_state: dict[str, Any],
    new_state: dict[str, Any],
    *,
    capability_id: str,
    nonce_sha256: str,
    allow_additional_nonces: bool = False,
) -> None:
    old_orchestration = _manager_orchestration_mapping(old_state)
    new_orchestration = _manager_orchestration_mapping(new_state)
    old_capabilities = old_orchestration["manager_capabilities"]
    new_capabilities = new_orchestration["manager_capabilities"]
    if set(old_capabilities) != set(new_capabilities):
        raise FlowError(
            "MANAGER_AUTHORIZATION_DELTA_INVALID",
            "manager authorization cannot add or remove capability verifiers",
        )
    modified = [
        identifier
        for identifier in sorted(old_capabilities)
        if old_capabilities[identifier] != new_capabilities[identifier]
    ]
    if modified != [capability_id]:
        raise FlowError(
            "MANAGER_AUTHORIZATION_DELTA_INVALID",
            "manager authorization must consume exactly its target verifier",
        )
    try:
        old_verifier = validate_manager_capability_verifier(
            old_capabilities[capability_id]
        )
        new_verifier = validate_manager_capability_verifier(
            new_capabilities[capability_id]
        )
    except (KeyError, OrchestrationAuthorityError) as exc:
        if isinstance(exc, OrchestrationAuthorityError):
            raise FlowError(
                exc.code, exc.message, details=exc.details
            ) from exc
        raise FlowError(
            "MANAGER_CAPABILITY_UNKNOWN",
            "manager capability verifier is unknown",
        ) from exc
    old_record = old_verifier.as_persistent_dict()
    new_record = new_verifier.as_persistent_dict()
    old_nonces = list(old_record.pop("used_request_nonce_sha256s"))
    new_nonces = list(new_record.pop("used_request_nonce_sha256s"))
    expected_nonces = sorted([*old_nonces, nonce_sha256])
    if allow_additional_nonces:
        valid_nonce_delta = (
            nonce_sha256 not in old_nonces
            and nonce_sha256 in new_nonces
            and set(old_nonces).issubset(new_nonces)
        )
    else:
        valid_nonce_delta = (
            new_nonces == expected_nonces
            and len(new_nonces) == len(old_nonces) + 1
        )
    if old_record != new_record or not valid_nonce_delta:
        raise FlowError(
            "MANAGER_AUTHORIZATION_DELTA_INVALID",
            "manager authorization must append one exact nonce digest",
        )


def _manager_validated_preauthorization_v1(
    old_state: dict[str, Any],
    *,
    event_type: str,
) -> tuple[
    _ManagerAuthorityInvocation,
    ManagerCapabilityRequest,
    _PreauthorizedManagerMutation,
]:
    invocation = _manager_authority_context_var.get()
    if not isinstance(invocation, _ManagerAuthorityInvocation):
        raise FlowError(
            "MANAGER_CAPABILITY_REQUIRED",
            "schema-v4 agent-plane mutation requires manager capability proof",
            details={"task_id": old_state.get("task_id")},
        )
    request = invocation.request
    actual_revision = int(old_state.get("revision", 0))
    preauthorization = invocation.preauthorization()
    if not isinstance(
        preauthorization, _PreauthorizedManagerMutation
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_REQUIRED",
            "schema-v4 mutation has no sealed pre-effect authorization",
            details={"task_id": old_state.get("task_id")},
        )
    expected_preauthorization_seal = _manager_seal(
        _manager_preauthorization_seal_key,
        preauthorization.seal_payload(),
    )
    if not _manager_hmac.compare_digest(
        preauthorization.seal,
        expected_preauthorization_seal,
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_INVALID",
            "manager preauthorization seal is invalid",
        )
    allowed_event_types = _manager_package_action_event_types(
        preauthorization.package_action_id
    )
    if (
        allowed_event_types is None
        or event_type not in allowed_event_types
    ):
        raise FlowError(
            "MANAGER_HANDLER_EVENT_MISMATCH",
            "manager proof does not authorize this handler event type",
            details={
                "package_action_id": (
                    preauthorization.package_action_id
                ),
                "event_type": event_type,
            },
        )
    old_orchestration = _manager_orchestration_mapping(old_state)
    old_capabilities = old_orchestration["manager_capabilities"]
    verifier = old_capabilities.get(request.capability_id)
    if verifier is None:
        raise FlowError(
            "MANAGER_CAPABILITY_UNKNOWN",
            "manager capability verifier is unknown",
            details={"task_id": old_state.get("task_id")},
        )
    try:
        verifier_state_sha256 = hashlib.sha256(
            _json_bytes(
                validate_manager_capability_verifier(
                    verifier
                ).as_persistent_dict()
            )
        ).hexdigest()
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    operation_fingerprint = invocation.operation_fingerprint_sha256
    principal_sha256 = hashlib.sha256(
        _json_bytes(invocation.principal.as_dict())
    ).hexdigest()
    expected_bindings = (
        (
            preauthorization.task_id,
            old_state.get("task_id"),
        ),
        (
            preauthorization.authorized_state_revision,
            actual_revision,
        ),
        (
            preauthorization.input_revision,
            request.expected_revision,
        ),
        (
            preauthorization.action_id,
            invocation.action_id,
        ),
        (
            preauthorization.package_action_id,
            invocation.package_action_id,
        ),
        (
            preauthorization.capability_id,
            request.capability_id,
        ),
        (
            preauthorization.request_fingerprint_sha256,
            manager_request_fingerprint(request),
        ),
        (
            preauthorization.request_nonce_sha256,
            manager_request_nonce_digest(request),
        ),
        (
            preauthorization.manager_session_id,
            request.manager_session_id,
        ),
        (
            preauthorization.principal_sha256,
            principal_sha256,
        ),
        (
            preauthorization.operation_fingerprint_sha256,
            operation_fingerprint,
        ),
        (
            preauthorization.pre_effect_state_sha256,
            _manager_pre_effect_state_digest(old_state),
        ),
        (
            preauthorization.verifier_state_sha256,
            verifier_state_sha256,
        ),
    )
    if any(
        supplied != actual
        for supplied, actual in expected_bindings
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_STALE",
            "manager preauthorization does not bind this locked candidate",
            details={
                "task_id": old_state.get("task_id"),
                "actual_revision": actual_revision,
            },
        )
    authorization = preauthorization.authorization
    authorization_bindings = (
        (authorization.task_id, request.task_id),
        (
            authorization.expected_revision,
            request.expected_revision,
        ),
        (authorization.action_id, request.action_id),
        (authorization.capability_id, request.capability_id),
        (
            authorization.request_fingerprint_sha256,
            preauthorization.request_fingerprint_sha256,
        ),
    )
    if any(
        supplied != actual
        for supplied, actual in authorization_bindings
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_INVALID",
            "manager authorization does not match its sealed request",
        )
    return invocation, request, preauthorization


def manager_rebase_preauthorization_v1(
    current_state: dict[str, Any],
    *,
    event_type: str,
) -> None:
    """Rebind one still-unconsumed request to a later disjoint revision.

    This is a proof-only operation.  It neither persists the verifier nor
    dispatches an effect; the generic transaction must still revalidate its
    durable semantic facts and commit the rebased nonce with the business
    mutation under the current task CAS.
    """

    invocation = _manager_authority_context_var.get()
    if not isinstance(invocation, _ManagerAuthorityInvocation):
        raise FlowError(
            "MANAGER_CAPABILITY_REQUIRED",
            "scoped manager rebase requires live request authority",
        )
    request = invocation.request
    original = invocation.preauthorization()
    if not isinstance(original, _PreauthorizedManagerMutation):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_REQUIRED",
            "scoped manager rebase requires sealed preauthorization",
        )
    expected_seal = _manager_seal(
        _manager_preauthorization_seal_key,
        original.seal_payload(),
    )
    if not _manager_hmac.compare_digest(
        original.seal, expected_seal
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_INVALID",
            "manager preauthorization seal is invalid",
        )
    actual_revision = int(current_state.get("revision", 0))
    if actual_revision == original.authorized_state_revision:
        return
    if actual_revision < original.authorized_state_revision:
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_STALE",
            "manager rebase cannot move to an earlier task revision",
        )
    allowed_event_types = _manager_package_action_event_types(
        original.package_action_id
    )
    principal_sha256 = hashlib.sha256(
        _json_bytes(invocation.principal.as_dict())
    ).hexdigest()
    static_bindings = (
        (original.task_id, current_state.get("task_id")),
        (original.input_revision, request.expected_revision),
        (original.action_id, invocation.action_id),
        (original.package_action_id, invocation.package_action_id),
        (original.capability_id, request.capability_id),
        (
            original.request_fingerprint_sha256,
            manager_request_fingerprint(request),
        ),
        (
            original.request_nonce_sha256,
            manager_request_nonce_digest(request),
        ),
        (original.manager_session_id, request.manager_session_id),
        (original.principal_sha256, principal_sha256),
        (
            original.operation_fingerprint_sha256,
            invocation.operation_fingerprint_sha256,
        ),
    )
    if (
        allowed_event_types is None
        or event_type not in allowed_event_types
        or any(left != right for left, right in static_bindings)
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_STALE",
            "manager rebase changed a sealed request or handler binding",
        )
    current_orchestration = _manager_orchestration_mapping(
        current_state
    )
    current_value = current_orchestration[
        "manager_capabilities"
    ].get(request.capability_id)
    if current_value is None:
        raise FlowError(
            "MANAGER_CAPABILITY_UNKNOWN",
            "manager capability verifier is unknown",
        )
    try:
        current_verifier = validate_manager_capability_verifier(
            current_value
        )
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    current_record = current_verifier.as_persistent_dict()
    authorized_record = (
        original.authorization.verifier_state.as_persistent_dict()
    )
    current_nonces = set(
        current_record.pop("used_request_nonce_sha256s")
    )
    authorized_nonces = set(
        authorized_record.pop("used_request_nonce_sha256s")
    )
    request_nonce = original.request_nonce_sha256
    prior_nonces = authorized_nonces - {request_nonce}
    if (
        current_record != authorized_record
        or request_nonce not in authorized_nonces
        or request_nonce in current_nonces
        or not prior_nonces.issubset(current_nonces)
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_STALE",
            "manager verifier drift is not an unrelated committed nonce",
        )
    try:
        wall_time_ns, monotonic_time_ns, clock_id = (
            invocation.clock_context()
        )
        authorization = consume_manager_capability_request(
            current_verifier,
            request,
            invocation.principal,
            manager_secret=invocation.current_secret(),
            wall_time_ns=wall_time_ns,
            monotonic_time_ns=monotonic_time_ns,
            clock_id=clock_id,
        )
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if (
        authorization.authorization_id
        != original.authorization.authorization_id
        or authorization.request_fingerprint_sha256
        != original.request_fingerprint_sha256
    ):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_INVALID",
            "rebased manager authorization changed request identity",
        )
    verifier_state_sha256 = hashlib.sha256(
        _json_bytes(current_verifier.as_persistent_dict())
    ).hexdigest()
    values = {
        "task_id": request.task_id,
        "input_revision": request.expected_revision,
        "authorized_state_revision": actual_revision,
        "action_id": request.action_id,
        "package_action_id": original.package_action_id,
        "capability_id": request.capability_id,
        "request_fingerprint_sha256": (
            authorization.request_fingerprint_sha256
        ),
        "request_nonce_sha256": request_nonce,
        "manager_session_id": request.manager_session_id,
        "principal_sha256": principal_sha256,
        "operation_fingerprint_sha256": (
            original.operation_fingerprint_sha256
        ),
        "pre_effect_state_sha256": (
            _manager_pre_effect_state_digest(current_state)
        ),
        "verifier_state_sha256": verifier_state_sha256,
    }
    rebased = _PreauthorizedManagerMutation(
        authorization=authorization,
        **values,
        seal=_manager_seal(
            _manager_preauthorization_seal_key,
            {
                "authorization": authorization.as_dict(),
                **values,
            },
        ),
    )
    invocation.replace_preauthorization(original, rebased)


def _manager_engine_evaluation_state_v1(
    old_state: dict[str, Any],
    *,
    event_type: str,
) -> dict[str, Any] | None:
    """Return the nonce-consumed base that the engine must evaluate.

    No durable or caller-owned value is mutated.  Absence of a generic
    manager preauthorization returns ``None`` so preview and formal paths can
    retain their existing evaluation order; a present but invalid
    preauthorization always fails closed.
    """

    invocation = _manager_authority_context_var.get()
    if not isinstance(invocation, _ManagerAuthorityInvocation):
        return None
    if not isinstance(
        invocation.preauthorization(),
        _PreauthorizedManagerMutation,
    ):
        return None
    (
        _validated_invocation,
        request,
        preauthorization,
    ) = _manager_validated_preauthorization_v1(
        old_state, event_type=event_type
    )
    old_orchestration = _manager_orchestration_mapping(old_state)
    old_capabilities = old_orchestration["manager_capabilities"]
    authorization = preauthorization.authorization
    next_orchestration = _manager_json_clone(old_orchestration)
    next_capabilities = _manager_json_clone(old_capabilities)
    next_capabilities[request.capability_id] = (
        authorization.verifier_state.as_persistent_dict()
    )
    next_orchestration["manager_capabilities"] = next_capabilities
    evaluation_state = _manager_json_clone(old_state)
    evaluation_state["orchestration"] = next_orchestration
    nonce_sha256 = manager_request_nonce_digest(request)
    _manager_validate_nonce_delta(
        old_state,
        evaluation_state,
        capability_id=request.capability_id,
        nonce_sha256=nonce_sha256,
    )
    return evaluation_state


def _manager_workflow_action_authorization_v1(
    old_state: dict[str, Any],
    *,
    event_type: str,
) -> WorkflowActionAuthorization:
    """Project current manager proof into the digest-only action contract."""

    invocation, request, preauthorization = (
        _manager_validated_preauthorization_v1(
            old_state, event_type=event_type
        )
    )
    authorization = preauthorization.authorization
    authorization_binding = authorization.as_dict()
    reauthentication_secret = (
        _manager_workflow_action_journal_secret_v1()
    )
    old_snapshot = _manager_json_clone(old_state)
    nonce_sha256 = manager_request_nonce_digest(request)
    expected_event_payload = {
        "authorization_id": authorization.authorization_id,
        "capability_id": request.capability_id,
        "manager_session_id": request.manager_session_id,
        "action_id": request.action_id,
        "package_action_id": preauthorization.package_action_id,
        "request_fingerprint_sha256": (
            authorization.request_fingerprint_sha256
        ),
        "request_nonce_sha256": nonce_sha256,
        "operation_fingerprint_sha256": (
            preauthorization.operation_fingerprint_sha256
        ),
    }

    def nonce_consumed_verifier(
        state_value: Mapping[str, object],
        events: tuple[Mapping[str, object], ...],
    ) -> bool:
        candidate = _manager_json_clone(state_value)
        if not isinstance(candidate, dict):
            return False
        try:
            _manager_validate_nonce_delta(
                old_snapshot,
                candidate,
                capability_id=request.capability_id,
                nonce_sha256=nonce_sha256,
                allow_additional_nonces=True,
            )
        except FlowError:
            return False
        matches = []
        for event in events:
            payload = event.get("payload")
            if (
                event.get("type")
                == MANAGER_CAPABILITY_AUTHORIZED_EVENT
                and isinstance(payload, Mapping)
                and all(
                    payload.get(key) == value
                    for key, value in expected_event_payload.items()
                )
            ):
                matches.append(event)
        return len(matches) == 1

    orchestration = _manager_orchestration_mapping(old_state)
    principal = invocation.principal.as_dict()
    return WorkflowActionAuthorization(
        kind="manager",
        authorization_sha256=hashlib.sha256(
            _json_bytes(authorization_binding)
        ).hexdigest(),
        capability_sha256=preauthorization.verifier_state_sha256,
        request_nonce_sha256=nonce_sha256,
        principal=(
            "manager:"
            + request.manager_session_id
            + ":"
            + preauthorization.principal_sha256
        ),
        ownership_sha256=hashlib.sha256(
            _json_bytes(
                {
                    "task_id": request.task_id,
                    "manager_session_id": request.manager_session_id,
                    "principal": principal,
                }
            )
        ).hexdigest(),
        registry_state_sha256=hashlib.sha256(
            _json_bytes(orchestration["manager_capabilities"])
        ).hexdigest(),
        reauthenticate=lambda: reauthentication_secret,
        nonce_consumed_verifier=nonce_consumed_verifier,
    )


def _manager_workflow_action_journal_secret_v1() -> str:
    """Derive the stable per-capability secret used by action journals.

    Journal HMAC keys are already domain-separated again by task and
    execution identity in ``derive_execution_key``.  Keeping this outer
    derivation independent of a particular request nonce is what allows a
    fresh, still-authorized reconciliation request from the same local
    manager session to authenticate an older quarantined execution after a
    process restart.  The raw manager proof never leaves the process-local
    invocation.
    """

    invocation = _manager_authority_context_var.get()
    if not isinstance(invocation, _ManagerAuthorityInvocation):
        raise FlowError(
            "MANAGER_CAPABILITY_REQUIRED",
            "manager journal reauthentication requires live capability proof",
        )
    request = invocation.request
    return invocation.derive_workflow_action_secret(
        {
            "contract": (
                "dev-flow-manager-workflow-action-journal-secret/v1"
            ),
            "task_id": request.task_id,
            "capability_id": request.capability_id,
            "manager_session_id": request.manager_session_id,
        }
    )


def _evaluate_v4_manager_mutation(
    old_state: dict[str, Any],
    new_state: dict[str, Any],
    *,
    event_type: str,
) -> _AuthorizedManagerMutation:
    (
        _invocation,
        request,
        preauthorization,
    ) = _manager_validated_preauthorization_v1(
        old_state, event_type=event_type
    )
    evaluation_state = _manager_engine_evaluation_state_v1(
        old_state, event_type=event_type
    )
    if not isinstance(evaluation_state, dict):
        raise FlowError(
            "MANAGER_PREAUTHORIZATION_REQUIRED",
            "schema-v4 mutation has no manager engine input",
            details={"task_id": old_state.get("task_id")},
        )
    new_orchestration = _manager_orchestration_mapping(new_state)
    evaluation_orchestration = _manager_orchestration_mapping(
        evaluation_state
    )
    if (
        new_orchestration.get("manager_capabilities")
        != evaluation_orchestration.get("manager_capabilities")
    ):
        raise FlowError(
            "MANAGER_AUTHORIZATION_DELTA_INVALID",
            "engine candidate lacks the exact pre-evaluated manager nonce",
            details={"task_id": old_state.get("task_id")},
        )
    authorization = preauthorization.authorization
    nonce_sha256 = manager_request_nonce_digest(request)
    _manager_validate_nonce_delta(
        old_state,
        new_state,
        capability_id=request.capability_id,
        nonce_sha256=nonce_sha256,
    )
    values = {
        "task_id": request.task_id,
        "expected_revision": (
            preauthorization.authorized_state_revision
        ),
        "action_id": request.action_id,
        "package_action_id": preauthorization.package_action_id,
        "event_type": event_type,
        "capability_id": request.capability_id,
        "authorization_id": authorization.authorization_id,
        "request_fingerprint_sha256": (
            authorization.request_fingerprint_sha256
        ),
        "request_nonce_sha256": nonce_sha256,
        "manager_session_id": request.manager_session_id,
        "operation_fingerprint_sha256": (
            preauthorization.operation_fingerprint_sha256
        ),
        "old_state_sha256": _manager_state_digest(old_state),
        "candidate_state_sha256": _manager_state_digest(new_state),
    }
    return _AuthorizedManagerMutation(
        **values,
        seal=_manager_seal(_manager_mutation_seal_key, values),
    )


def _manager_authorized_event(
    authorization: _AuthorizedManagerMutation,
    old_state: dict[str, Any],
    new_state: dict[str, Any],
    event_type: str,
) -> tuple[str, dict[str, Any]]:
    if not isinstance(authorization, _AuthorizedManagerMutation):
        raise FlowError(
            "MANAGER_AUTHORIZATION_INVALID",
            "manager mutation requires package-issued typed authorization",
        )
    expected_seal = _manager_seal(
        _manager_mutation_seal_key,
        authorization.seal_payload(),
    )
    if not _manager_hmac.compare_digest(
        authorization.seal, expected_seal
    ):
        raise FlowError(
            "MANAGER_AUTHORIZATION_INVALID",
            "manager mutation authorization seal is invalid",
        )
    expected = {
        "task_id": old_state.get("task_id"),
        "expected_revision": int(old_state.get("revision", 0)),
        "event_type": event_type,
        "old_state_sha256": _manager_state_digest(old_state),
        "candidate_state_sha256": _manager_state_digest(new_state),
    }
    mismatches = sorted(
        field
        for field, value in expected.items()
        if getattr(authorization, field) != value
    )
    if mismatches:
        raise FlowError(
            "MANAGER_AUTHORIZATION_STALE",
            "manager mutation authorization does not bind this candidate: "
            + ", ".join(mismatches),
            details={"fields": mismatches},
        )
    _manager_validate_nonce_delta(
        old_state,
        new_state,
        capability_id=authorization.capability_id,
        nonce_sha256=authorization.request_nonce_sha256,
    )
    payload = {
            "authorization_id": authorization.authorization_id,
            "capability_id": authorization.capability_id,
            "manager_session_id": authorization.manager_session_id,
            "action_id": authorization.action_id,
            "package_action_id": authorization.package_action_id,
            "request_fingerprint_sha256": (
                authorization.request_fingerprint_sha256
            ),
            "request_nonce_sha256": (
                authorization.request_nonce_sha256
            ),
        }
    if authorization.operation_fingerprint_sha256 is not None:
        payload["operation_fingerprint_sha256"] = (
            authorization.operation_fingerprint_sha256
        )
    return (MANAGER_CAPABILITY_AUTHORIZED_EVENT, payload)


def _manager_default_actions(
    state_value: dict[str, Any],
) -> tuple[str, ...]:
    if state_value.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise FlowError(
            "MANAGER_CAPABILITY_SCHEMA_REQUIRED",
            "manager capabilities are available only for schema-v4 tasks",
            details={"task_id": state_value.get("task_id")},
        )
    workflow_ref = state_value.get("workflow_ref")
    if not isinstance(workflow_ref, dict):
        raise FlowError(
            "MANAGER_CAPABILITY_WORKFLOW_INVALID",
            "schema-v4 task has no pinned workflow identity",
        )
    flow = state_value.get("flow")
    if flow not in {"full", "lite"}:
        raise FlowError(
            "MANAGER_CAPABILITY_WORKFLOW_INVALID",
            "manager capability actions require a supported pinned flow",
        )
    graph_path = (
        Path(_json_bytes.__code__.co_filename).resolve().parents[2]
        / "workflows"
        / "bundles"
        / f"{flow}-v4"
        / "workflow.json"
    )
    try:
        graph_source = graph_path.read_bytes()
        graph = json.loads(graph_source)
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowError(
            "MANAGER_CAPABILITY_WORKFLOW_INVALID",
            "pinned workflow action contract is unavailable",
        ) from exc
    if not isinstance(graph, dict):
        raise FlowError(
            "MANAGER_CAPABILITY_WORKFLOW_INVALID",
            "pinned workflow action contract is invalid",
        )
    canonical_graph = json.dumps(
        graph,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    graph_sha256 = hashlib.sha256(
        b"dev-flow-graph-v1\x00"
        + _manager_struct.pack(">Q", len(canonical_graph))
        + canonical_graph
    ).hexdigest()
    if graph_sha256 != workflow_ref.get("graph_sha256"):
        raise FlowError(
            "MANAGER_CAPABILITY_WORKFLOW_INVALID",
            "manager capability actions differ from the pinned workflow graph",
        )
    actions = {
        action["id"]
        for node in graph.get("nodes", ())
        for action in node.get("actions", ())
        if isinstance(action, Mapping)
        and isinstance(action.get("id"), str)
    }
    actions.update(
        trigger["id"]
        for edge in graph.get("edge_policies", ())
        if isinstance(edge, Mapping)
        for trigger in (edge.get("trigger"),)
        if isinstance(trigger, Mapping)
        and isinstance(trigger.get("id"), str)
    )
    orchestration = graph.get("repository_orchestration")
    if isinstance(orchestration, Mapping):
        actions.update(
            item
            for item in orchestration.get("operation_ids", ())
            if isinstance(item, str)
        )
        for field in ("map", "join"):
            operation = orchestration.get(field)
            if (
                isinstance(operation, Mapping)
                and isinstance(operation.get("operation_id"), str)
            ):
                actions.add(operation["operation_id"])
    actions.update(manager_command_action_ids_v1())
    return tuple(sorted(actions, key=lambda item: item.encode("utf-8")))


CONTROLLER_ACTION_TRANSITION_INPUT_SCHEMA = (
    "dev-flow-action-transition-input/v1"
)
CONTROLLER_ACTION_CANCEL_INPUT_SCHEMA = (
    "dev-flow-action-cancel-input/v1"
)
CONTROLLER_ACTION_PREVIEW_RESULT_SCHEMA = (
    "dev-flow-mcp-action-preview-result/v1"
)
CONTROLLER_ACTION_PREVIEW_INTENT_SCHEMA = (
    "dev-flow-controller-action-preview-intent/v1"
)
CONTROLLER_ACTION_REPLAY_FINGERPRINT_SCHEMA = (
    "dev-flow-controller-action-replay-fingerprint/v1"
)
CONTROLLER_ACTION_REPLAY_MAX_LINE_BYTES = 512 * 1024
CONTROLLER_ACTION_REPLAY_MAX_LOG_BYTES = 16 * 1024 * 1024
CONTROLLER_ACTION_REPLAY_MAX_EVENTS = 100_000


def _controller_action_trigger_ids(
    state_value: dict[str, Any],
) -> tuple[str, ...]:
    try:
        bundle = _workflow_transition_bundle(state_value)
    except TransitionEngineError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    graph = getattr(bundle, "graph", None)
    if not isinstance(graph, Mapping):
        raise FlowError(
            "WORKFLOW_GRAPH_INVALID",
            "pinned workflow graph is unavailable",
        )
    identifiers = {
        trigger["id"]
        for edge in graph.get("edge_policies", ())
        if isinstance(edge, Mapping)
        for trigger in (edge.get("trigger"),)
        if isinstance(trigger, Mapping)
        and isinstance(trigger.get("id"), str)
    }
    return tuple(
        sorted(identifiers, key=lambda item: item.encode("utf-8"))
    )


def _controller_action_bounded_text(
    value: object, maximum: int, *, nonempty: bool = False
) -> bool:
    if not isinstance(value, str) or (nonempty and not value):
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= maximum
    except UnicodeEncodeError:
        return False


def _controller_action_input(
    action_id: str,
    input_value: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(input_value, dict):
        raise FlowError(
            "CONTROLLER_ACTION_INPUT_INVALID",
            "controller action input must be an object",
        )
    if action_id == "transition":
        expected = {"contract", "to", "note"}
        schema = CONTROLLER_ACTION_TRANSITION_INPUT_SCHEMA
        if (
            set(input_value) != expected
            or input_value.get("contract") != schema
            or not _controller_action_bounded_text(
                input_value.get("to"), 256, nonempty=True
            )
            or (
                input_value.get("note") is not None
                and not _controller_action_bounded_text(
                    input_value.get("note"), 2048
                )
            )
        ):
            raise FlowError(
                "CONTROLLER_ACTION_INPUT_INVALID",
                "transition input must be exact (contract, to, note)",
                details={"schema": schema},
            )
    elif action_id == "cancel":
        expected = {"contract", "reason"}
        schema = CONTROLLER_ACTION_CANCEL_INPUT_SCHEMA
        if (
            set(input_value) != expected
            or input_value.get("contract") != schema
            or not _controller_action_bounded_text(
                input_value.get("reason"), 2048, nonempty=True
            )
        ):
            raise FlowError(
                "CONTROLLER_ACTION_INPUT_INVALID",
                "cancel input must be exact (contract, reason)",
                details={"schema": schema},
            )
    elif action_id == "transition-cancel":
        expected = {"contract", "reason"}
        schema = CONTROLLER_ACTION_CANCEL_INPUT_SCHEMA
        reason = input_value.get("reason")
        if (
            set(input_value) != expected
            or input_value.get("contract") != schema
            or not _controller_action_bounded_text(
                reason, 2048, nonempty=True
            )
        ):
            raise FlowError(
                "CONTROLLER_ACTION_INPUT_INVALID",
                "transition-cancel input requires one exact cancellation reason",
                details={"schema": schema},
            )
    return _manager_json_clone(input_value)


def _controller_action_namespace(
    task_id: str,
    *,
    expected_revision: int,
    action_id: str,
    input_value: dict[str, Any],
    data_dir: Any,
    preview: bool,
    confirm_intent: str | None,
) -> argparse.Namespace:
    common = {
        "task": task_id,
        "task_id": task_id,
        "data_dir": data_dir,
        "expected_revision": expected_revision,
        "preview": preview,
        "confirm_intent": confirm_intent,
    }
    if action_id == "cancel":
        return argparse.Namespace(
            **common,
            reason=input_value["reason"],
        )
    return argparse.Namespace(
        **common,
        to=None,
        to_option=(
            "CANCELLED"
            if action_id == "transition-cancel"
            else input_value["to"]
        ),
        note=(
            input_value["reason"]
            if action_id == "transition-cancel"
            else input_value["note"]
        ),
    )


def _controller_action_preview_core(
    state_value: dict[str, Any],
    *,
    action_id: str,
    input_value: dict[str, Any],
    applicable: bool,
    blockers: list[str],
    command_intent: str | None,
) -> dict[str, Any]:
    input_sha256 = hashlib.sha256(
        _manager_canonical_json_bytes(input_value)
    ).hexdigest()
    workflow_ref = state_value.get("workflow_ref")
    return {
        "schema": CONTROLLER_ACTION_PREVIEW_INTENT_SCHEMA,
        "task_id": state_value.get("task_id"),
        "revision": state_value.get("revision"),
        "workflow_ref": _manager_json_clone(workflow_ref),
        "current_status": state_value.get("status"),
        "current_state_sha256": _manager_state_digest(state_value),
        "action_id": action_id,
        "input_sha256": input_sha256,
        "applicable": applicable,
        "blockers": list(blockers),
        "command_intent": command_intent,
    }


def _controller_action_cli_fallback(
    task_id: str,
    *,
    expected_revision: int,
    action_id: str,
    data_dir: Any,
) -> dict[str, Any]:
    registry = workflow_runtime_services().registries.commands
    if not bool(getattr(registry, "sealed", False)):
        raise FlowError(
            "REGISTRY_UNSEALED",
            "controller CLI fallback requires the sealed command registry",
        )
    commands = {
        entry.command
        for entry in registry.entries.values()
        if isinstance(getattr(entry, "command", None), str)
    }
    if "show" not in commands:
        raise FlowError(
            "REGISTRY_COMMAND_UNKNOWN",
            "controller CLI fallback requires the sealed show command",
        )
    # An undecoded trigger cannot safely synthesize mutation arguments.
    # Resume from the exact bounded next-step projection instead.
    arguments = ["show", "--task", task_id, "--next"]
    controller = (
        Path(_json_bytes.__code__.co_filename).resolve().parents[1]
        / "dev_flow.py"
    )
    return {
        "schema": "dev-flow-cli-fallback/v1",
        "controller": str(controller),
        "data_dir": (
            None
            if data_dir is None
            else str(resolve_data_dir(data_dir))
        ),
        "arguments": arguments,
    }


def controller_action_preview(
    task_id: str,
    *,
    expected_revision: int,
    action_id: str,
    input_value: dict[str, Any],
    data_dir: Any = None,
) -> dict[str, Any]:
    """Preview one pinned graph trigger without mutation."""

    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        raise FlowError(
            "INVALID_REVISION",
            "controller action preview requires a non-negative revision",
        )
    state_value = load_state(task_id, data_dir)
    _check_revision(state_value, expected_revision)
    triggers = _controller_action_trigger_ids(state_value)
    if action_id not in triggers:
        raise FlowError(
            "CONTROLLER_ACTION_UNKNOWN",
            "action ID is not a trigger in the task-pinned graph",
            details={"action_id": action_id, "supported": list(triggers)},
        )
    decoded = action_id in {
        "transition",
        "cancel",
        "transition-cancel",
    }
    normalized_input = _controller_action_input(
        action_id, input_value
    )
    input_sha256 = hashlib.sha256(
        _manager_canonical_json_bytes(normalized_input)
    ).hexdigest()
    if not decoded:
        blockers = ["CLI_REQUIRED"]
        core = _controller_action_preview_core(
            state_value,
            action_id=action_id,
            input_value=normalized_input,
            applicable=False,
            blockers=blockers,
            command_intent=None,
        )
        return {
            "contract": CONTROLLER_ACTION_PREVIEW_RESULT_SCHEMA,
            "task_id": task_id,
            "revision": expected_revision,
            "action_id": action_id,
            "input_sha256": input_sha256,
            "preview_intent": (
                "controller-action-preview:"
                + hashlib.sha256(
                    b"dev-flow-controller-action-preview-v1\x00"
                    + _json_bytes(core)
                ).hexdigest()
            ),
            "applicable": False,
            "blockers": blockers,
            "fallback": _controller_action_cli_fallback(
                task_id,
                expected_revision=expected_revision,
                action_id=action_id,
                data_dir=data_dir,
            ),
        }
    namespace = _controller_action_namespace(
        task_id,
        expected_revision=expected_revision,
        action_id=action_id,
        input_value=normalized_input,
        data_dir=data_dir,
        preview=True,
        confirm_intent=None,
    )
    command_intent = None
    blockers: list[str] = []
    applicable = True
    try:
        result = (
            command_cancel(namespace)
            if action_id == "cancel"
            else command_transition(namespace)
        )
        preview = result.get("preview")
        if isinstance(preview, dict):
            value = preview.get("intent_id")
            command_intent = value if isinstance(value, str) else None
        if command_intent is None:
            applicable = False
            blockers.append(
                "ACTION_NO_CHANGE"
                if result.get("unchanged") is True
                else "ACTION_PREVIEW_UNAVAILABLE"
            )
    except FlowError as exc:
        applicable = False
        blockers.append(exc.code)
    core = _controller_action_preview_core(
        state_value,
        action_id=action_id,
        input_value=normalized_input,
        applicable=applicable,
        blockers=blockers,
        command_intent=command_intent,
    )
    return {
        "contract": CONTROLLER_ACTION_PREVIEW_RESULT_SCHEMA,
        "task_id": task_id,
        "revision": expected_revision,
        "action_id": action_id,
        "input_sha256": input_sha256,
        "preview_intent": (
            "controller-action-preview:"
            + hashlib.sha256(
                b"dev-flow-controller-action-preview-v1\x00"
                + _json_bytes(core)
            ).hexdigest()
        ),
        "applicable": applicable,
        "blockers": blockers,
    }


def _controller_action_event_stream(
    task_id: str,
    *,
    data_dir: Any,
) -> Iterator[dict[str, Any]]:
    """Stream one bounded task log without retaining unrelated events."""

    event_path = _task_dir(task_id, data_dir) / "events.jsonl"
    total_bytes = 0
    event_count = 0
    try:
        with event_path.open("rb") as handle:
            while True:
                line = handle.readline(
                    CONTROLLER_ACTION_REPLAY_MAX_LINE_BYTES + 1
                )
                if not line:
                    break
                if (
                    len(line)
                    > CONTROLLER_ACTION_REPLAY_MAX_LINE_BYTES
                ):
                    raise FlowError(
                        "CONTROLLER_ACTION_REPLAY_LOG_BOUNDED",
                        "controller event record exceeds its recovery bound",
                    )
                total_bytes += len(line)
                event_count += 1
                if (
                    total_bytes
                    > CONTROLLER_ACTION_REPLAY_MAX_LOG_BYTES
                    or event_count
                    > CONTROLLER_ACTION_REPLAY_MAX_EVENTS
                ):
                    raise FlowError(
                        "CONTROLLER_ACTION_REPLAY_LOG_BOUNDED",
                        "controller event log exceeds its recovery bound",
                    )
                try:
                    event = json.loads(line)
                except (
                    TypeError,
                    ValueError,
                    UnicodeError,
                ) as exc:
                    raise FlowError(
                        "CONTROLLER_ACTION_REPLAY_LOG_INVALID",
                        "controller event log contains an invalid record",
                    ) from exc
                if not isinstance(event, dict):
                    raise FlowError(
                        "CONTROLLER_ACTION_REPLAY_LOG_INVALID",
                        "controller event log contains a non-object record",
                    )
                yield event
    except FlowError:
        raise
    except OSError as exc:
        raise FlowError(
            "CONTROLLER_ACTION_RECEIPT_MISSING",
            "committed controller action event is unavailable",
        ) from exc


def _controller_action_operation_fingerprint(
    request: ManagerCapabilityRequest,
    *,
    input_value: dict[str, Any],
    preview_intent: str,
) -> str:
    preview_prefix = "controller-action-preview:"
    if (
        not isinstance(preview_intent, str)
        or not preview_intent.startswith(preview_prefix)
        or len(preview_intent) != len(preview_prefix) + 64
        or any(
            character not in "0123456789abcdef"
            for character in preview_intent[len(preview_prefix) :]
        )
    ):
        raise FlowError(
            "INTENT_STALE",
            "controller action requires its preview intent",
        )
    document = {
        "schema": CONTROLLER_ACTION_REPLAY_FINGERPRINT_SCHEMA,
        "manager_request_fingerprint_sha256": (
            manager_request_fingerprint(request)
        ),
        "task_id": request.task_id,
        "expected_revision": request.expected_revision,
        "action_id": request.action_id,
        "input": _manager_json_clone(input_value),
        "preview_intent": preview_intent,
    }
    return hashlib.sha256(
        b"dev-flow-controller-action-replay-fingerprint-v1\x00"
        + _json_bytes(document)
    ).hexdigest()


def _controller_action_channel_principal(
    manager_channel: object,
    request: ManagerCapabilityRequest,
    principal: object,
) -> AgentPrincipal:
    secret_resolver = getattr(
        manager_channel, "resolve_secret", None
    )
    principal_resolver = getattr(
        manager_channel, "principal_for", None
    )
    if not callable(secret_resolver) or not callable(
        principal_resolver
    ):
        raise FlowError(
            "MANAGER_SECRET_CHANNEL_INVALID",
            "controller action requires one manager channel for principal and proof",
        )
    try:
        channel_principal = validate_agent_principal(
            principal_resolver(request.as_dict())
        )
        supplied_principal = validate_agent_principal(principal)
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if (
        channel_principal.as_dict()
        != supplied_principal.as_dict()
    ):
        raise FlowError(
            "MANAGER_CAPABILITY_PRINCIPAL_MISMATCH",
            "controller principal does not match its manager channel",
        )
    return channel_principal


def _controller_action_replay_authorization(
    state_value: dict[str, Any],
    request: ManagerCapabilityRequest,
    principal: AgentPrincipal,
    *,
    manager_channel: object,
) -> ManagerAuthorization | None:
    orchestration = _manager_orchestration_mapping(state_value)
    capabilities = orchestration["manager_capabilities"]
    verifier_value = capabilities.get(request.capability_id)
    if verifier_value is None:
        return None
    try:
        verifier = validate_manager_capability_verifier(
            verifier_value
        )
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    nonce_sha256 = manager_request_nonce_digest(request)
    if nonce_sha256 not in verifier.used_request_nonce_sha256s:
        return None
    resolver = getattr(manager_channel, "resolve_secret", None)
    assert callable(resolver)
    try:
        secret = resolver(request.capability_id)
    except FlowError:
        raise
    except Exception as exc:
        raise FlowError(
            "MANAGER_CAPABILITY_PROOF_UNAVAILABLE",
            "manager proof could not be resolved",
        ) from exc
    if not isinstance(secret, bytearray):
        raise FlowError(
            "MANAGER_CAPABILITY_PROOF_INVALID",
            "manager secret channel must return mutable proof bytes",
        )
    try:
        try:
            return verify_manager_capability_replay_request(
                verifier,
                request,
                principal,
                manager_secret=secret,
            )
        except OrchestrationAuthorityError as exc:
            raise FlowError(
                exc.code, exc.message, details=exc.details
            ) from exc
    finally:
        _manager_zeroize(secret)


def _controller_action_replay_receipt(
    task_id: str,
    *,
    expected_revision: int,
    action_id: str,
    input_value: dict[str, Any],
    request: ManagerCapabilityRequest,
    authorization: ManagerAuthorization,
    operation_fingerprint_sha256: str,
    data_dir: Any,
) -> dict[str, Any]:
    nonce_sha256 = manager_request_nonce_digest(request)
    request_fingerprint_sha256 = manager_request_fingerprint(
        request
    )
    target_revision = expected_revision + 1
    revision_events: list[dict[str, Any]] = []
    matching_consumptions: list[dict[str, Any]] = []
    for event in _controller_action_event_stream(
        task_id, data_dir=data_dir
    ):
        if event.get("revision") == target_revision:
            revision_events.append(event)
        payload = event.get("payload")
        if (
            event.get("type")
            == MANAGER_CAPABILITY_AUTHORIZED_EVENT
            and isinstance(payload, dict)
            and payload.get("capability_id")
            == request.capability_id
            and payload.get("request_nonce_sha256")
            == nonce_sha256
        ):
            matching_consumptions.append(event)
    if len(matching_consumptions) != 1:
        raise FlowError(
            "CONTROLLER_ACTION_REPLAY_RECEIPT_INVALID",
            "consumed manager nonce has no unique durable receipt",
            details={"matches": len(matching_consumptions)},
        )
    consumption = matching_consumptions[0]
    payload = consumption.get("payload")
    assert isinstance(payload, dict)
    expected_payload_fields = {
        "authorization_id",
        "capability_id",
        "manager_session_id",
        "action_id",
        "package_action_id",
        "request_fingerprint_sha256",
        "request_nonce_sha256",
        "operation_fingerprint_sha256",
    }
    fingerprints_match = (
        set(payload) == expected_payload_fields
        and payload.get("request_fingerprint_sha256")
        == request_fingerprint_sha256
        and payload.get("operation_fingerprint_sha256")
        == operation_fingerprint_sha256
        and payload.get("action_id") == action_id
        and payload.get("package_action_id")
        == _MANAGER_REQUEST_TO_PACKAGE_ACTION.get(
            action_id, action_id
        )
        and payload.get("manager_session_id")
        == request.manager_session_id
    )
    if not fingerprints_match:
        raise FlowError(
            "MANAGER_CAPABILITY_REQUEST_REPLAY_CONFLICT",
            "manager nonce was committed for a different canonical action request",
        )
    transaction_id = consumption.get("transaction_id")
    if (
        consumption.get("task_id") != task_id
        or consumption.get("previous_revision")
        != expected_revision
        or consumption.get("revision") != target_revision
        or not isinstance(consumption.get("event_id"), str)
        or not isinstance(transaction_id, str)
        or not transaction_id
        or payload.get("authorization_id")
        != authorization.authorization_id
    ):
        raise FlowError(
            "CONTROLLER_ACTION_REPLAY_RECEIPT_INVALID",
            "manager receipt does not bind the original atomic transaction",
        )
    transaction_events = [
        event
        for event in revision_events
        if event.get("transaction_id") == transaction_id
    ]
    event_ids = [
        event.get("event_id") for event in transaction_events
    ]
    if (
        consumption not in transaction_events
        or len(event_ids) != len(set(event_ids))
        or any(
            event.get("task_id") != task_id
            or event.get("previous_revision") != expected_revision
            or event.get("revision") != target_revision
            for event in transaction_events
        )
    ):
        raise FlowError(
            "CONTROLLER_ACTION_REPLAY_RECEIPT_INVALID",
            "manager receipt transaction is incomplete or inconsistent",
        )
    expected_type = (
        "task_cancelled"
        if action_id == "cancel"
        else "state_transitioned"
    )
    primary_events = [
        event
        for event in transaction_events
        if event.get("type") == expected_type
        and isinstance(event.get("event_id"), str)
    ]
    manager_events = [
        event
        for event in transaction_events
        if event.get("type")
        == MANAGER_CAPABILITY_AUTHORIZED_EVENT
    ]
    if len(primary_events) != 1 or manager_events != [consumption]:
        raise FlowError(
            "CONTROLLER_ACTION_REPLAY_RECEIPT_INVALID",
            "manager receipt transaction lacks one exact action and consumption event",
        )
    primary = primary_events[0]
    primary_payload = primary.get("payload")
    if not isinstance(primary_payload, dict):
        raise FlowError(
            "CONTROLLER_ACTION_REPLAY_RECEIPT_INVALID",
            "controller action event has no canonical payload",
        )
    if action_id == "cancel":
        payload_matches = (
            primary_payload.get("reason")
            == input_value["reason"]
            and primary.get("status") == "CANCELLED"
        )
    else:
        expected_target = (
            "CANCELLED"
            if action_id == "transition-cancel"
            else input_value["to"]
        )
        expected_note = (
            input_value["reason"]
            if action_id == "transition-cancel"
            else input_value["note"]
        )
        payload_matches = (
            primary_payload.get("to") == expected_target
            and primary_payload.get("note") == expected_note
            and primary.get("status") == expected_target
        )
    if not payload_matches:
        raise FlowError(
            "CONTROLLER_ACTION_REPLAY_RECEIPT_INVALID",
            "controller action event differs from its canonical request",
        )
    return {
        "revision": target_revision,
        "event_id": primary["event_id"],
        "event_type": primary["type"],
        "authorization_id": authorization.authorization_id,
    }


def _controller_action_committed_receipt(
    task_id: str,
    *,
    revision: int,
    action_id: str,
    data_dir: Any,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for event in _controller_action_event_stream(
        task_id, data_dir=data_dir
    ):
        if event.get("revision") == revision:
            events.append(event)
    expected_type = (
        "task_cancelled"
        if action_id == "cancel"
        else "state_transitioned"
    )
    primary_events = [
            event
            for event in events
            if event.get("type") == expected_type
            and isinstance(event.get("event_id"), str)
    ]
    consumption_events = [
            event
            for event in events
            if event.get("type")
            == MANAGER_CAPABILITY_AUTHORIZED_EVENT
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("action_id") == action_id
    ]
    primary = (
        primary_events[0] if len(primary_events) == 1 else None
    )
    consumption = (
        consumption_events[0]
        if len(consumption_events) == 1
        else None
    )
    authorization_id = (
        consumption.get("payload", {}).get("authorization_id")
        if isinstance(consumption, dict)
        else None
    )
    if (
        not isinstance(primary, dict)
        or not isinstance(authorization_id, str)
        or primary.get("transaction_id")
        != consumption.get("transaction_id")
    ):
        raise FlowError(
            "CONTROLLER_ACTION_RECEIPT_MISSING",
            "controller action lacks its atomic mutation receipt",
        )
    return {
        "revision": revision,
        "event_id": primary["event_id"],
        "event_type": primary["type"],
        "authorization_id": authorization_id,
    }


def controller_action_apply(
    task_id: str,
    *,
    expected_revision: int,
    action_id: str,
    input_value: dict[str, Any],
    preview_intent: str,
    request: object,
    principal: object,
    manager_channel: object,
    data_dir: Any = None,
) -> dict[str, Any]:
    """Apply one decoded graph trigger under exact manager authority."""

    try:
        parsed_request = validate_manager_capability_request(request)
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if (
        parsed_request.task_id != task_id
        or parsed_request.expected_revision != expected_revision
        or parsed_request.action_id != action_id
    ):
        raise FlowError(
            "MANAGER_CAPABILITY_ACTION_MISMATCH",
            "manager request does not bind the previewed graph trigger",
        )
    normalized_input = _controller_action_input(
        action_id, input_value
    )
    channel_principal = _controller_action_channel_principal(
        manager_channel, parsed_request, principal
    )
    operation_fingerprint_sha256 = (
        _controller_action_operation_fingerprint(
            parsed_request,
            input_value=normalized_input,
            preview_intent=preview_intent,
        )
    )
    # Lost-response recovery precedes revision and live preview checks. A
    # consumed nonce can return only its already committed atomic receipt.
    state_value = load_state(task_id, data_dir)
    replay_authorization = (
        _controller_action_replay_authorization(
            state_value,
            parsed_request,
            channel_principal,
            manager_channel=manager_channel,
        )
    )
    if replay_authorization is not None:
        return _controller_action_replay_receipt(
            task_id,
            expected_revision=expected_revision,
            action_id=action_id,
            input_value=normalized_input,
            request=parsed_request,
            authorization=replay_authorization,
            operation_fingerprint_sha256=(
                operation_fingerprint_sha256
            ),
            data_dir=data_dir,
        )
    preview = controller_action_preview(
        task_id,
        expected_revision=expected_revision,
        action_id=action_id,
        input_value=normalized_input,
        data_dir=data_dir,
    )
    if (
        not isinstance(preview_intent, str)
        or not secrets.compare_digest(
            preview_intent, str(preview["preview_intent"])
        )
    ):
        raise FlowError(
            "INTENT_STALE",
            "controller action preview intent no longer matches live state",
        )
    if preview["applicable"] is not True:
        raise FlowError(
            "CONTROLLER_ACTION_NOT_APPLICABLE",
            "controller action cannot be applied by the typed service",
            details={"blockers": preview["blockers"]},
        )
    namespace = _controller_action_namespace(
        task_id,
        expected_revision=expected_revision,
        action_id=action_id,
        input_value=normalized_input,
        data_dir=data_dir,
        preview=False,
        confirm_intent=None,
    )
    # Command handlers require their native confirmation intent, not the MCP
    # wrapper intent. Recompute it under the same state immediately before
    # entering the mutation authority context.
    native_preview = (
        command_cancel(
            _controller_action_namespace(
                task_id,
                expected_revision=expected_revision,
                action_id=action_id,
                input_value=normalized_input,
                data_dir=data_dir,
                preview=True,
                confirm_intent=None,
            )
        )
        if action_id == "cancel"
        else command_transition(
            _controller_action_namespace(
                task_id,
                expected_revision=expected_revision,
                action_id=action_id,
                input_value=normalized_input,
                data_dir=data_dir,
                preview=True,
                confirm_intent=None,
            )
        )
    )
    native = native_preview.get("preview")
    if not isinstance(native, dict) or not isinstance(
        native.get("intent_id"), str
    ):
        raise FlowError(
            "CONTROLLER_ACTION_NOT_APPLICABLE",
            "native command preview is unavailable",
        )
    namespace.confirm_intent = native["intent_id"]

    def resolve_secret() -> bytearray:
        resolver = getattr(manager_channel, "resolve_secret")
        return resolver(parsed_request.capability_id)

    with _manager_authority_context(
        request=parsed_request,
        action_id=action_id,
        secret_resolver=resolve_secret,
        principal=channel_principal,
        operation_fingerprint_sha256=(
            operation_fingerprint_sha256
        ),
    ):
        if action_id == "cancel":
            result = command_cancel(namespace)
        else:
            result = command_transition(namespace)
    revision = result.get("revision")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision != expected_revision + 1
    ):
        raise FlowError(
            "CONTROLLER_ACTION_RECEIPT_MISSING",
            "controller action returned no committed revision",
        )
    return _controller_action_committed_receipt(
        task_id,
        revision=revision,
        action_id=action_id,
        data_dir=data_dir,
    )


def _manager_registry_action_guard_v1(projection, _capabilities):
    """Pure registry guard over an immutable engine projection."""

    parameters = projection.get("action_parameters")
    if not hasattr(parameters, "get"):
        return (False, "MANAGER_REGISTRY_PARAMETERS_REQUIRED")
    if (
        parameters.get("authority") != "operator"
        or parameters.get("principal_role") != "operator"
    ):
        return (False, "MANAGER_REGISTRY_OPERATOR_REQUIRED")
    operation = parameters.get("operation")
    if operation not in {"authorize", "revoke"}:
        return (False, "MANAGER_REGISTRY_OPERATION_INVALID")
    verifier = parameters.get("verifier")
    if not hasattr(verifier, "get"):
        return (False, "MANAGER_CAPABILITY_VERIFIER_INVALID")
    capability_id = parameters.get("capability_id")
    if (
        not isinstance(capability_id, str)
        or not capability_id
        or verifier.get("capability_id") != capability_id
        or verifier.get("task_id") != projection.get("task_id")
    ):
        return (False, "MANAGER_CAPABILITY_BINDING_MISMATCH")
    orchestration = projection.get("orchestration")
    if orchestration is None:
        capabilities = {}
    elif hasattr(orchestration, "get"):
        if (
            orchestration.get("schema")
            != "dev-flow-orchestration-state/v1"
        ):
            return (False, "MANAGER_CAPABILITY_REGISTRY_INVALID")
        capabilities = orchestration.get("manager_capabilities", {})
        if not hasattr(capabilities, "get"):
            return (False, "MANAGER_CAPABILITY_REGISTRY_INVALID")
    else:
        return (False, "MANAGER_CAPABILITY_REGISTRY_INVALID")
    publication = parameters.get("secret_publication")
    if operation == "authorize":
        if capabilities.get(capability_id) is not None:
            return (False, "MANAGER_CAPABILITY_EXISTS")
        if (
            verifier.get("issued_for_task_revision")
            != projection.get("revision")
            or verifier.get("revoked_at_wall_ns") is not None
            or tuple(verifier.get("used_request_nonce_sha256s", ()))
        ):
            return (False, "MANAGER_CAPABILITY_VERIFIER_INVALID")
        if not hasattr(publication, "get") or set(publication) != {
            "channel_binding_sha256",
            "effect",
            "publication_required",
            "schema",
            "transport",
        }:
            return (False, "MANAGER_SECRET_PUBLICATION_PLAN_REQUIRED")
        channel_sha256 = publication.get("channel_binding_sha256")
        if (
            publication.get("schema")
            != "dev-flow-manager-secret-publication-plan/v1"
            or publication.get("effect") != "secret-publication"
            or publication.get("publication_required") is not True
            or publication.get("transport")
            != verifier.get("secret_transport")
            or not isinstance(channel_sha256, str)
            or len(channel_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in channel_sha256
            )
        ):
            return (False, "MANAGER_SECRET_PUBLICATION_PLAN_INVALID")
        return True
    if publication is not None:
        return (False, "MANAGER_SECRET_PUBLICATION_FORBIDDEN")
    current = capabilities.get(capability_id)
    if not hasattr(current, "get"):
        return (False, "MANAGER_CAPABILITY_UNKNOWN")
    if (
        current.get("revoked_at_wall_ns") is not None
        or verifier.get("revoked_at_wall_ns") is None
    ):
        return (False, "MANAGER_CAPABILITY_REVOCATION_INVALID")
    ignored = {
        "revocation_audit_sha256",
        "revocation_reason",
        "revoked_at_wall_ns",
    }
    old_core = {
        key: value for key, value in current.items() if key not in ignored
    }
    new_core = {
        key: value for key, value in verifier.items() if key not in ignored
    }
    if old_core != new_core:
        return (False, "MANAGER_CAPABILITY_REVOCATION_INVALID")
    return True


def _manager_registry_action_reducer_v1(projection, _capabilities):
    """Pure reducer deriving only the bounded orchestration registry write."""

    def thaw(value):
        if hasattr(value, "items"):
            return {
                str(key): thaw(item) for key, item in value.items()
            }
        if isinstance(value, tuple):
            return [thaw(item) for item in value]
        return value

    candidate_delta = projection.get("candidate_delta")
    if hasattr(candidate_delta, "get"):
        supplied_set = candidate_delta.get("set")
        supplied_remove = candidate_delta.get("remove")
        supplied_operations = candidate_delta.get("operations")
        if (
            hasattr(supplied_set, "items")
            and isinstance(supplied_remove, tuple)
            and isinstance(supplied_operations, tuple)
            and not supplied_operations
        ):
            normalized_set = {
                str(pointer): thaw(item)
                for pointer, item in supplied_set.items()
            }
            normalized_remove = [
                str(pointer) for pointer in supplied_remove
            ]
            changed = (*normalized_set, *normalized_remove)
            if changed and all(
                pointer.startswith(
                    "/orchestration/manager_capabilities/"
                )
                for pointer in changed
            ):
                return {
                    "set": normalized_set,
                    "remove": normalized_remove,
                    "operations": [],
                }

    parameters = projection.get("action_parameters")
    if not hasattr(parameters, "get"):
        return {"set": {}, "remove": [], "operations": []}
    verifier = parameters.get("verifier")
    capability_id = parameters.get("capability_id")
    if (
        parameters.get("operation") not in {"authorize", "revoke"}
        or not hasattr(verifier, "items")
        or not isinstance(capability_id, str)
        or not capability_id
    ):
        return {"set": {}, "remove": [], "operations": []}
    current = projection.get("orchestration")
    if current is None:
        orchestration = {
            "schema": "dev-flow-orchestration-state/v1",
            "manager_capabilities": {},
        }
    else:
        orchestration = thaw(current)
    capabilities = orchestration.get("manager_capabilities")
    if not isinstance(capabilities, dict):
        return {"set": {}, "remove": [], "operations": []}
    updated_capabilities = {
        **capabilities,
        capability_id: thaw(verifier),
    }
    updated_orchestration = {
        **orchestration,
        "manager_capabilities": updated_capabilities,
    }
    return {
        "set": {"/orchestration": updated_orchestration},
        "remove": [],
        "operations": [],
    }


def _manager_registry_action_flow_error(
    exc: OrchestrationAuthorityError,
) -> FlowError:
    return FlowError(exc.code, exc.message, details=exc.details)


def manager_registry_action_parameters_v1(
    state: Mapping[str, object],
    *,
    operation: str,
    verifier: object,
    principal: object,
    secret_publication: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build secret-free parameters for the future transaction coordinator."""

    if state.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise FlowError(
            "MANAGER_CAPABILITY_SCHEMA_REQUIRED",
            "manager registry actions require a schema-v4 task",
        )
    revision = state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise FlowError(
            "TASK_STATE_INVALID",
            "manager registry actions require an integer task revision",
        )
    if operation not in {"authorize", "revoke"}:
        raise FlowError(
            "MANAGER_REGISTRY_OPERATION_INVALID",
            "manager registry action is unsupported",
        )
    try:
        parsed_principal = validate_agent_principal(principal)
        parsed_verifier = validate_manager_capability_verifier(verifier)
    except OrchestrationAuthorityError as exc:
        raise _manager_registry_action_flow_error(exc) from exc
    if parsed_principal.role != "operator":
        raise FlowError(
            "MANAGER_REGISTRY_OPERATOR_REQUIRED",
            "manager registry actions require the current operator principal",
        )
    if (
        parsed_verifier.task_id != state.get("task_id")
    ):
        raise FlowError(
            "MANAGER_CAPABILITY_BINDING_MISMATCH",
            "manager verifier does not bind the current task",
            details={"capability_id": parsed_verifier.capability_id},
        )
    orchestration = state.get("orchestration")
    if orchestration is None:
        capabilities: Mapping[str, object] = {}
    elif isinstance(orchestration, Mapping):
        if (
            orchestration.get("schema")
            != "dev-flow-orchestration-state/v1"
            or not isinstance(
                orchestration.get("manager_capabilities"), Mapping
            )
        ):
            raise FlowError(
                "MANAGER_CAPABILITY_REGISTRY_INVALID",
                "schema-v4 manager capability registry is invalid",
            )
        capabilities = orchestration["manager_capabilities"]
    else:
        raise FlowError(
            "MANAGER_CAPABILITY_REGISTRY_INVALID",
            "schema-v4 orchestration registry must be an object",
        )
    capability_id = parsed_verifier.capability_id
    publication: dict[str, object] | None
    if operation == "authorize":
        if parsed_verifier.issued_for_task_revision != revision:
            raise FlowError(
                "MANAGER_CAPABILITY_BINDING_MISMATCH",
                "new manager verifier does not bind the current task revision",
                details={"capability_id": capability_id},
            )
        if capability_id in capabilities:
            raise FlowError(
                "MANAGER_CAPABILITY_EXISTS",
                "manager capability verifier already exists",
                details={"capability_id": capability_id},
            )
        if (
            parsed_verifier.revoked_at_wall_ns is not None
            or parsed_verifier.used_request_nonce_sha256s
        ):
            raise FlowError(
                "MANAGER_CAPABILITY_VERIFIER_INVALID",
                "new manager verifier must be active and unused",
            )
        if not isinstance(secret_publication, Mapping):
            raise FlowError(
                "MANAGER_SECRET_PUBLICATION_PLAN_REQUIRED",
                "manager authorization requires a secret-publication plan",
            )
        publication = _manager_json_clone(dict(secret_publication))
        if set(publication) != {
            "channel_binding_sha256",
            "effect",
            "publication_required",
            "schema",
            "transport",
        }:
            raise FlowError(
                "MANAGER_SECRET_PUBLICATION_PLAN_INVALID",
                "secret-publication plan has an unsupported shape",
            )
        if (
            publication.get("schema")
            != MANAGER_SECRET_PUBLICATION_PLAN_SCHEMA
            or publication.get("effect") != "secret-publication"
            or publication.get("publication_required") is not True
            or publication.get("transport")
            != parsed_verifier.secret_transport
            or not isinstance(
                publication.get("channel_binding_sha256"), str
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(publication.get("channel_binding_sha256")),
            )
        ):
            raise FlowError(
                "MANAGER_SECRET_PUBLICATION_PLAN_INVALID",
                "secret-publication plan does not bind the verifier channel",
            )
    else:
        if secret_publication is not None:
            raise FlowError(
                "MANAGER_SECRET_PUBLICATION_FORBIDDEN",
                "manager revocation has no secret-publication side effect",
            )
        current_value = capabilities.get(capability_id)
        if current_value is None:
            raise FlowError(
                "MANAGER_CAPABILITY_UNKNOWN",
                "manager capability verifier is unknown",
                details={"capability_id": capability_id},
            )
        try:
            current = validate_manager_capability_verifier(
                current_value
            )
        except OrchestrationAuthorityError as exc:
            raise _manager_registry_action_flow_error(exc) from exc
        old_record = current.as_persistent_dict()
        new_record = parsed_verifier.as_persistent_dict()
        for field in (
            "revoked_at_wall_ns",
            "revocation_reason",
            "revocation_audit_sha256",
        ):
            old_record.pop(field)
            new_record.pop(field)
        if (
            old_record != new_record
            or current.revoked_at_wall_ns is not None
            or parsed_verifier.revoked_at_wall_ns is None
        ):
            raise FlowError(
                "MANAGER_CAPABILITY_REVOCATION_INVALID",
                "manager revocation may change only fixed revocation facts",
            )
        publication = None
    persistent_verifier = parsed_verifier.as_persistent_dict()
    parameters = {
        "operation": operation,
        "authority": "operator",
        "principal_role": parsed_principal.role,
        "principal_sha256": _manager_state_digest(
            parsed_principal.as_dict()
        ),
        "capability_id": capability_id,
        "verifier": persistent_verifier,
        "verifier_sha256": _manager_state_digest(
            persistent_verifier
        ),
        "secret_publication": publication,
    }
    projection = _manager_json_clone(dict(state))
    projection["action_parameters"] = parameters
    guarded = _manager_registry_action_guard_v1(projection, None)
    passed = guarded if isinstance(guarded, bool) else guarded[0]
    if passed is not True:
        reason = (
            guarded[1]
            if isinstance(guarded, tuple) and len(guarded) > 1
            else "MANAGER_REGISTRY_GUARD_REJECTED"
        )
        raise FlowError(
            str(reason),
            "manager registry action guard rejected current parameters",
        )
    return parameters


def build_manager_registry_action_outcome_v1(
    state: Mapping[str, object],
    edge: Mapping[str, object],
    *,
    operation: str,
    verifier: object,
    principal: object,
    secret_publication: Mapping[str, object] | None = None,
) -> ActionOutcome:
    """Produce one strict outcome without persistence or secret publication."""

    expected = {
        "authorize": {
            "action_id": MANAGER_REGISTRY_AUTHORIZE_ACTION_ID,
            "command": "manager-authorize",
            "event": MANAGER_CAPABILITY_ISSUED_EVENT,
            "side_effects": {"secret-publication", "task-state"},
            "dispatch": "single-dispatch",
        },
        "revoke": {
            "action_id": MANAGER_REGISTRY_REVOKE_ACTION_ID,
            "command": "manager-revoke",
            "event": MANAGER_CAPABILITY_REVOKED_EVENT,
            "side_effects": {"task-state"},
            "dispatch": "none",
        },
    }.get(operation)
    trigger = edge.get("trigger")
    public_command = edge.get("public_command")
    effects = edge.get("effects")
    dispatches = {
        item.get("dispatch")
        for item in effects
        if isinstance(item, Mapping)
    } if isinstance(effects, (list, tuple)) else set()
    if (
        expected is None
        or edge.get("class") != "action"
        or edge.get("source") != state.get("status")
        or edge.get("target") != state.get("status")
        or not isinstance(trigger, Mapping)
        or trigger.get("id") != expected["action_id"]
        or not isinstance(public_command, Mapping)
        or public_command.get("id") != expected["command"]
        or public_command.get("selector") != "authority"
        or tuple(public_command.get("values", ())) != ("operator",)
        or edge.get("canonical_event") != expected["event"]
        or set(edge.get("side_effects", ()))
        != expected["side_effects"]
        or dispatches != {expected["dispatch"]}
        or "/orchestration"
        not in set(edge.get("kernel_state_writes", ()))
    ):
        raise FlowError(
            "MANAGER_REGISTRY_ACTION_EDGE_MISMATCH",
            "manager registry adapter requires the exact catalog-sealed edge",
            details={"operation": operation, "edge_id": edge.get("id")},
        )
    parameters = manager_registry_action_parameters_v1(
        state,
        operation=operation,
        verifier=verifier,
        principal=principal,
        secret_publication=secret_publication,
    )
    projection = _manager_json_clone(dict(state))
    projection["action_parameters"] = parameters
    delta = _manager_registry_action_reducer_v1(projection, None)
    publication = parameters["secret_publication"]
    return ActionOutcome(
        str(expected["action_id"]),
        str(edge["id"]),
        evidence_records=(
            {
                "operation": operation,
                "capability_id": parameters["capability_id"],
                "principal_sha256": parameters["principal_sha256"],
                "verifier_sha256": parameters["verifier_sha256"],
                "secret_publication_required": publication is not None,
            },
        ),
        proposed_state_delta=delta,
        audit_facts=(
            AuditFact(
                "manager-registry-action-prepared",
                {
                    "operation": operation,
                    "edge_id": edge["id"],
                    "capability_id": parameters["capability_id"],
                    "verifier_sha256": parameters["verifier_sha256"],
                    "secret_publication_required": (
                        publication is not None
                    ),
                },
            ),
        ),
        external_postconditions=(
            (_manager_copy.deepcopy(publication),)
            if isinstance(publication, dict)
            else ()
        ),
    )


def _manager_intent(
    *,
    operation: str,
    facts: dict[str, Any],
) -> dict[str, Any]:
    document = {
        "schema": "dev-flow-manager-capability-intent/v1",
        "operation": operation,
        **facts,
    }
    digest = hashlib.sha256(
        b"dev-flow-manager-capability-intent-v1\x00"
        + _json_bytes(document)
    ).hexdigest()
    return {
        "facts": document,
        "intent_id": f"manager-capability-intent:{digest}",
        "confirmation_sha256": hashlib.sha256(
            _json_bytes(document)
        ).hexdigest(),
    }


@_manager_dataclass(frozen=True)
class _ManagerRegistryOperation:
    operation: str
    task_id: str
    expected_revision: int
    capability_id: str
    old_state_sha256: str
    candidate_state_sha256: str
    seal: str

    def seal_payload(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "task_id": self.task_id,
            "expected_revision": self.expected_revision,
            "capability_id": self.capability_id,
            "old_state_sha256": self.old_state_sha256,
            "candidate_state_sha256": self.candidate_state_sha256,
        }


def _manager_registry_candidate(
    old_state: dict[str, Any],
    *,
    operation: str,
    verifier: ManagerCapabilityVerifier,
) -> tuple[dict[str, Any], _ManagerRegistryOperation]:
    if old_state.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise FlowError(
            "MANAGER_CAPABILITY_SCHEMA_REQUIRED",
            "manager capability registry requires a schema-v4 task",
            details={"task_id": old_state.get("task_id")},
        )
    candidate = _manager_json_clone(old_state)
    old_orchestration = old_state.get("orchestration")
    if old_orchestration is None:
        orchestration = {
            "schema": "dev-flow-orchestration-state/v1",
            "manager_capabilities": {},
        }
    elif isinstance(old_orchestration, dict):
        orchestration = _manager_json_clone(old_orchestration)
        if (
            orchestration.get("schema")
            != "dev-flow-orchestration-state/v1"
        ):
            raise FlowError(
                "MANAGER_CAPABILITY_REGISTRY_INVALID",
                "schema-v4 orchestration registry has an unsupported schema",
            )
        orchestration.setdefault("manager_capabilities", {})
    else:
        raise FlowError(
            "MANAGER_CAPABILITY_REGISTRY_INVALID",
            "schema-v4 orchestration registry must be an object",
        )
    capabilities = orchestration.get("manager_capabilities")
    if not isinstance(capabilities, dict):
        raise FlowError(
            "MANAGER_CAPABILITY_REGISTRY_INVALID",
            "manager capability registry must be an object",
        )
    capability_id = verifier.capability_id
    if operation == "authorize":
        if capability_id in capabilities:
            raise FlowError(
                "MANAGER_CAPABILITY_EXISTS",
                "manager capability verifier already exists",
                details={"capability_id": capability_id},
            )
    elif operation == "revoke":
        if capability_id not in capabilities:
            raise FlowError(
                "MANAGER_CAPABILITY_UNKNOWN",
                "manager capability verifier is unknown",
                details={"capability_id": capability_id},
            )
    else:
        raise FlowError(
            "MANAGER_REGISTRY_OPERATION_INVALID",
            "manager registry operation is unsupported",
        )
    capabilities[capability_id] = verifier.as_persistent_dict()
    orchestration["manager_capabilities"] = capabilities
    candidate["orchestration"] = orchestration
    values = {
        "operation": operation,
        "task_id": str(old_state.get("task_id")),
        "expected_revision": int(old_state.get("revision", 0)),
        "capability_id": capability_id,
        "old_state_sha256": _manager_state_digest(old_state),
        "candidate_state_sha256": _manager_state_digest(candidate),
    }
    return candidate, _ManagerRegistryOperation(
        **values,
        seal=_manager_seal(_manager_registry_seal_key, values),
    )


def _manager_validate_registry_delta(
    operation: _ManagerRegistryOperation,
    old_state: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    if {
        key: value
        for key, value in old_state.items()
        if key != "orchestration"
    } != {
        key: value
        for key, value in candidate.items()
        if key != "orchestration"
    }:
        raise FlowError(
            "MANAGER_REGISTRY_DELTA_INVALID",
            "manager registry operation cannot rewrite task state",
        )
    old_orchestration = old_state.get("orchestration")
    new_orchestration = candidate.get("orchestration")
    if not isinstance(new_orchestration, dict):
        raise FlowError(
            "MANAGER_REGISTRY_DELTA_INVALID",
            "manager registry operation requires orchestration state",
        )
    if old_orchestration is None:
        if set(new_orchestration) != {
            "schema",
            "manager_capabilities",
        }:
            raise FlowError(
                "MANAGER_REGISTRY_DELTA_INVALID",
                "manager registry initialization contains unrelated fields",
            )
        old_capabilities: dict[str, Any] = {}
    elif isinstance(old_orchestration, dict):
        if {
            key: value
            for key, value in old_orchestration.items()
            if key != "manager_capabilities"
        } != {
            key: value
            for key, value in new_orchestration.items()
            if key != "manager_capabilities"
        }:
            raise FlowError(
                "MANAGER_REGISTRY_DELTA_INVALID",
                "manager registry operation cannot rewrite orchestration state",
            )
        old_capabilities_value = old_orchestration.get(
            "manager_capabilities", {}
        )
        if not isinstance(old_capabilities_value, dict):
            raise FlowError(
                "MANAGER_REGISTRY_DELTA_INVALID",
                "manager capability registry is invalid",
            )
        old_capabilities = old_capabilities_value
    else:
        raise FlowError(
            "MANAGER_REGISTRY_DELTA_INVALID",
            "manager orchestration state is invalid",
        )
    new_capabilities = new_orchestration.get("manager_capabilities")
    if not isinstance(new_capabilities, dict):
        raise FlowError(
            "MANAGER_REGISTRY_DELTA_INVALID",
            "manager capability registry is invalid",
        )
    added = sorted(set(new_capabilities) - set(old_capabilities))
    removed = sorted(set(old_capabilities) - set(new_capabilities))
    modified = sorted(
        key
        for key in set(old_capabilities) & set(new_capabilities)
        if old_capabilities[key] != new_capabilities[key]
    )
    if operation.operation == "authorize":
        valid_shape = (
            added == [operation.capability_id]
            and not removed
            and not modified
        )
    else:
        valid_shape = (
            not added
            and not removed
            and modified == [operation.capability_id]
        )
    if not valid_shape:
        raise FlowError(
            "MANAGER_REGISTRY_DELTA_INVALID",
            "manager registry operation exceeds its fixed atomic boundary",
        )
    try:
        new_verifier = validate_manager_capability_verifier(
            new_capabilities[operation.capability_id]
        )
    except OrchestrationAuthorityError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if operation.operation == "authorize":
        if (
            new_verifier.task_id != old_state.get("task_id")
            or new_verifier.issued_for_task_revision
            != int(old_state.get("revision", 0))
            or new_verifier.revoked_at_wall_ns is not None
            or new_verifier.used_request_nonce_sha256s
        ):
            raise FlowError(
                "MANAGER_REGISTRY_DELTA_INVALID",
                "issued manager verifier is outside the exact task revision",
            )
    else:
        try:
            old_verifier = validate_manager_capability_verifier(
                old_capabilities[operation.capability_id]
            )
        except OrchestrationAuthorityError as exc:
            raise FlowError(
                exc.code, exc.message, details=exc.details
            ) from exc
        old_record = old_verifier.as_persistent_dict()
        new_record = new_verifier.as_persistent_dict()
        for field in (
            "revoked_at_wall_ns",
            "revocation_reason",
            "revocation_audit_sha256",
        ):
            old_record.pop(field)
            new_record.pop(field)
        if (
            old_record != new_record
            or old_verifier.revoked_at_wall_ns is not None
            or new_verifier.revoked_at_wall_ns is None
        ):
            raise FlowError(
                "MANAGER_REGISTRY_DELTA_INVALID",
                "revocation may change only the fixed revocation facts",
            )


def _manager_validate_registry_commit(
    operation: _ManagerRegistryOperation,
    old_state: dict[str, Any],
    candidate: dict[str, Any],
    *,
    event_type: str,
) -> None:
    if not isinstance(operation, _ManagerRegistryOperation):
        raise FlowError(
            "MANAGER_REGISTRY_AUTHORIZATION_INVALID",
            "manager registry mutation requires a package-issued operation",
        )
    expected_seal = _manager_seal(
        _manager_registry_seal_key, operation.seal_payload()
    )
    if not _manager_hmac.compare_digest(operation.seal, expected_seal):
        raise FlowError(
            "MANAGER_REGISTRY_AUTHORIZATION_INVALID",
            "manager registry operation seal is invalid",
        )
    expected_event = (
        MANAGER_CAPABILITY_ISSUED_EVENT
        if operation.operation == "authorize"
        else MANAGER_CAPABILITY_REVOKED_EVENT
    )
    if (
        event_type != expected_event
        or operation.task_id != old_state.get("task_id")
        or operation.expected_revision
        != int(old_state.get("revision", 0))
        or operation.old_state_sha256
        != _manager_state_digest(old_state)
        or operation.candidate_state_sha256
        != _manager_state_digest(candidate)
    ):
        raise FlowError(
            "MANAGER_REGISTRY_AUTHORIZATION_STALE",
            "manager registry operation does not bind this candidate",
        )
    _manager_validate_registry_delta(operation, old_state, candidate)


def manager_process_commit_gate_v1(
    old_state: dict[str, Any],
    candidate: dict[str, Any],
    event_type: str,
    registry_operation: object = None,
    *,
    _effect_lifecycle: tuple[str, str] | None = None,
    _effect_package_action_id: str | None = None,
    formal_operation: object = None,
    formal_event_payload: Mapping[str, object] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Single process.py membrane for both package-owned authority forms."""

    if _effect_lifecycle is not None:
        if (
            not isinstance(_effect_lifecycle, tuple)
            or len(_effect_lifecycle) != 2
        ):
            raise FlowError(
                "MANAGER_EFFECT_LIFECYCLE_INVALID",
                "manager effect lifecycle is invalid",
            )
        phase, policy = _effect_lifecycle
        if phase == "preauthorize":
            _manager_preauthorize_locked_state(
                old_state,
                effect_policy=policy,
                package_action_id=_effect_package_action_id,
            )
            return None
        if phase == "clear":
            _manager_clear_effect_authorization()
            return None
        raise FlowError(
            "MANAGER_EFFECT_LIFECYCLE_INVALID",
            "manager effect lifecycle phase is invalid",
        )
    if formal_operation is not None:
        if registry_operation is not None:
            raise FlowError(
                "MANAGER_AUTHORIZATION_MODE_CONFLICT",
                "formal node authority cannot share a registry operation",
            )
        try:
            return validate_v4_formal_manager_operation(
                formal_operation,
                old_state,
                candidate,
                event_type=event_type,
                event_payload=dict(formal_event_payload or {}),
            )
        except TransitionEngineError as exc:
            raise FlowError(
                exc.code, exc.message, details=exc.details
            ) from exc
    if registry_operation is not None:
        if not isinstance(
            registry_operation, _ManagerRegistryOperation
        ):
            raise FlowError(
                "MANAGER_REGISTRY_AUTHORIZATION_INVALID",
                "manager registry mutation requires a package-issued operation",
            )
        _manager_validate_registry_commit(
            registry_operation,
            old_state,
            candidate,
            event_type=event_type,
        )
        return None
    authorization = _evaluate_v4_manager_mutation(
        old_state,
        candidate,
        event_type=event_type,
    )
    return _manager_authorized_event(
        authorization,
        old_state,
        candidate,
        event_type,
    )


def _commit_manager_registry_operation(
    operation: _ManagerRegistryOperation,
    old_state: dict[str, Any],
    candidate: dict[str, Any],
    task_dir: Path,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Route a sealed fixed registry operation through the generic gate."""

    return _commit_state(
        old_state,
        candidate,
        task_dir,
        event_type,
        payload,
        _manager_registry_operation=operation,
    )
