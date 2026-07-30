# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Argument parser construction and the machine-protocol entrypoint.
from __future__ import annotations

def _parse_json_object(value: str | None, option: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise FlowError("INVALID_ARGUMENT", f"{option} is not valid JSON", details={"error": str(exc)}) from exc
    if not isinstance(parsed, dict):
        raise FlowError("INVALID_ARGUMENT", f"{option} must contain a JSON object")
    stack: list[tuple[str, Any]] = [("$", parsed)]
    while stack:
        location, candidate = stack.pop()
        if isinstance(candidate, dict):
            if "evidence_contract_version" in candidate:
                raise FlowError(
                    "RESERVED_METADATA_KEY",
                    (
                        f"{option} must not contain the controller-reserved "
                        "evidence_contract_version key"
                    ),
                    details={
                        "option": option,
                        "location": location,
                        "key": "evidence_contract_version",
                    },
                )
            stack.extend(
                (f"{location}.{key}", nested)
                for key, nested in candidate.items()
            )
        elif isinstance(candidate, list):
            stack.extend(
                (f"{location}[{index}]", nested)
                for index, nested in enumerate(candidate)
            )
    return parsed


def _task_arg(args: argparse.Namespace) -> str:
    task_id = getattr(args, "task_option", None) or getattr(args, "task_id", None)
    if not task_id:
        raise FlowError("INVALID_ARGUMENT", "task id is required (positional or --task)")
    return _validate_task_id(task_id)


def _add_data_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="state directory (overrides DEV_FLOW_DATA_DIR and PLUGIN_DATA)",
    )


def _add_task(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id", nargs="?", help="task id")
    parser.add_argument("--task", dest="task_option", help="task id (alternative to positional form)")


def _add_mutation(parser: argparse.ArgumentParser) -> None:
    _add_task(parser)
    parser.add_argument(
        "--expected-revision",
        type=int,
        required=True,
        help="current state revision; stale writers fail with REVISION_CONFLICT",
    )
    _add_data_dir(parser)
    parser.set_defaults(_manager_mutation_command=True)


def _register_start_parser(subparsers, registration, handler) -> None:
    start = subparsers.add_parser(
        registration.command,
        help="create an INTAKE task for one or more repositories",
    )
    start.add_argument("requirement", nargs="?", help="requirement text")
    start.add_argument("--requirement", dest="requirement_option", help="requirement text (alternative to positional form)")
    start.add_argument("--repo", action="append", required=True, help="Git repository path; repeat for multiple repositories")
    start.add_argument("--task-id", help="stable task id (generated when omitted)")
    start.add_argument(
        "--workspace-strategy",
        choices=sorted(WORKSPACE_STRATEGIES),
        help=(
            "required work mode: in-place and branch infer the lite flow; "
            "worktree infers the full flow"
        ),
    )
    start.add_argument(
        "--protected-branch",
        action="append",
        help=(
            "additional protected branch name; repeat to extend, never "
            "replace, the default main/master/trunk set"
        ),
    )
    start.add_argument(
        "--change-category",
        action="append",
        help=(
            "declared change category; repeatable; known values are "
            + ", ".join(sorted(CHANGE_CATEGORIES))
        ),
    )
    start.add_argument(
        "--target-path",
        action="append",
        help=(
            "exact repository-relative path approved for a lite task; "
            "repeatable"
        ),
    )
    _add_data_dir(start)
    start.set_defaults(handler=handler)


def _register_show_parser(subparsers, registration, handler) -> None:
    show = subparsers.add_parser(
        registration.command,
        help="show a compact, sectioned, or full task snapshot",
    )
    _add_task(show)
    _add_data_dir(show)
    show_projection = show.add_mutually_exclusive_group()
    show_projection.add_argument(
        "--compact",
        action="store_true",
        help="return workflow progress and compact task counts without full state",
    )
    show_projection.add_argument(
        "--section",
        action="append",
        choices=sorted(SHOW_SECTION_FIELDS),
        help="return one named task section; repeat to select multiple sections",
    )
    show_projection.add_argument(
        "--next",
        action="store_true",
        help="return the bounded graph-derived agent-v1 frontier",
    )
    show_projection.add_argument(
        "--profile",
        choices=("agent-v1",),
        help="select a bounded machine response profile",
    )
    show.set_defaults(handler=handler)


def _register_recover_quarantine_parser(
    subparsers, registration, handler
) -> None:
    recover_quarantine = subparsers.add_parser(
        registration.command,
        help=(
            "prove an interrupted child is gone, validate partial "
            "postconditions, and archive its durable quarantine"
        ),
    )
    _add_mutation(recover_quarantine)
    recover_quarantine.set_defaults(handler=handler)


def _register_recover_atomic_write_parser(
    subparsers, registration, handler
) -> None:
    recover_atomic_write = subparsers.add_parser(
        registration.command,
        help=(
            "inspect and clear rollback evidence left behind by an "
            "interrupted atomic state write"
        ),
    )
    recover_atomic_write.add_argument(
        "--path",
        help=(
            "absolute blocked destination, or one of its rollback files as "
            "reported in details.rollback_candidates"
        ),
    )
    recover_atomic_write.add_argument(
        "--apply",
        action="store_true",
        help=(
            "remove rollback evidence that provably matches the committed "
            "destination; mismatches remain blocked"
        ),
    )
    recover_atomic_write.add_argument(
        "--resolve",
        choices=("keep-current", "restore-rollback"),
        help=(
            "resolve one mismatching candidate; requires --path and "
            "--rollback-sha256"
        ),
    )
    recover_atomic_write.add_argument(
        "--rollback-sha256",
        help="digest of the exact inspected rollback file",
    )
    _add_data_dir(recover_atomic_write)
    recover_atomic_write.set_defaults(
        handler=handler
    )


def _register_list_parser(subparsers, registration, handler) -> None:
    listing = subparsers.add_parser(
        registration.command, help="list task summaries"
    )
    listing.add_argument("--active-only", action="store_true", help="exclude DONE and CANCELLED tasks")
    listing.add_argument(
        "--status",
        action="append",
        choices=sorted(ALL_STATES),
        help=(
            "filter by stable status ID; repeat as needed; results also "
            "include display names"
        ),
    )
    _add_data_dir(listing)
    listing.set_defaults(handler=handler)


def _register_scope_parser(subparsers, registration, handler) -> None:
    scope = subparsers.add_parser(
        registration.command,
        help="show or change the directories where this plugin is active",
    )
    scope.add_argument(
        "--mode",
        choices=sorted(SCOPE_MODES),
        help="allowlist activates only inside included directories; all activates everywhere except excluded ones",
    )
    scope.add_argument(
        "--add",
        action="append",
        metavar="DIR",
        help="include a directory and its subdirectories; the first one switches to allowlist mode; repeatable",
    )
    scope.add_argument(
        "--remove", action="append", metavar="DIR", help="drop an included directory; repeatable"
    )
    scope.add_argument(
        "--add-exclude",
        action="append",
        metavar="DIR",
        help="exclude a directory and its subdirectories; repeatable",
    )
    scope.add_argument(
        "--remove-exclude",
        action="append",
        metavar="DIR",
        help="drop an excluded directory; repeatable",
    )
    scope.add_argument(
        "--clear",
        action="store_true",
        help="reset scope and protected paths to their defaults",
    )
    scope.add_argument(
        "--add-protected-path",
        action="append",
        metavar="GLOB",
        help=(
            "add a repository-relative POSIX glob that forces full flow; "
            "repeatable"
        ),
    )
    scope.add_argument(
        "--remove-protected-path",
        action="append",
        metavar="GLOB",
        help="remove an exact configured protected-path glob; repeatable",
    )
    scope.add_argument(
        "--reset-protected-paths",
        action="store_true",
        help="restore the built-in protected-path globs without changing scope",
    )
    scope.add_argument(
        "--check",
        nargs="?",
        const=".",
        metavar="DIR",
        help="report whether a directory is in scope; defaults to the current directory",
    )
    _add_data_dir(scope)
    scope.set_defaults(handler=handler)


def _register_preflight_parser(
    subparsers, registration, handler
) -> None:
    preflight = subparsers.add_parser(
        registration.command,
        help=(
            "preview one exact status decision, then capture and record "
            "complete Git/worktree evidence with the confirmed token"
        ),
    )
    _add_mutation(preflight)
    preflight.add_argument(
        "--repo",
        action="append",
        help=(
            "repository id or path; partial selections only record evidence, "
            "while status transitions require the default all-repository selection"
        ),
    )
    preflight.add_argument("--remote", help="override the parsed default remote")
    preflight.add_argument("--base", help="override the parsed default base branch")
    preflight.add_argument(
        "--preview",
        action="store_true",
        help=(
            "inspect lightweight preflight identity and status inputs without "
            "committing task state, then return the exact prospective edge and token"
        ),
    )
    preflight.add_argument(
        "--confirm-preview",
        metavar="TOKEN",
        help=(
            "apply an unchanged preflight status decision after the reported "
            "edge is confirmed, capturing complete evidence at confirmation time"
        ),
    )
    preflight.add_argument(
        "--accept-evidence-refresh",
        action="store_true",
        help=(
            "with --confirm-preview, explicitly accept the current lightweight "
            "worktree summary when it changed after preview"
        ),
    )
    preflight.set_defaults(handler=handler)


def _register_baseline_parser(
    subparsers, registration, handler
) -> None:
    baseline = subparsers.add_parser(
        registration.command,
        help="pin each repository's remote base commit after baseline-fetch approval",
    )
    _add_mutation(baseline)
    baseline.add_argument(
        "--fetch",
        action="store_true",
        help="fetch before pinning; approval must include --allow-fetch",
    )
    baseline.add_argument(
        "--materialize",
        action="store_true",
        help="create/reuse a detached analysis worktree at base_sha; requires baseline-fetch approval",
    )
    baseline.set_defaults(handler=handler)


def _register_record_index_parser(
    subparsers, registration, handler
) -> None:
    record_index = subparsers.add_parser(
        registration.command,
        help="record codebase-memory indexing provenance",
    )
    _add_mutation(record_index)
    record_index.add_argument(
        "--role",
        choices=["baseline", "workspace"],
        default="baseline",
        help="index role; baseline is the backward-compatible default",
    )
    record_index.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    record_index.add_argument(
        "--commit",
        help="indexed commit; defaults to pinned base for baseline or current HEAD for workspace",
    )
    record_index.add_argument(
        "--index-id",
        help="external index id; omission requires impact-degraded approval and failed metadata",
    )
    record_index.add_argument("--receipt", help="optional index receipt file to hash")
    record_index.add_argument(
        "--metadata-json",
        help="JSON provenance; workspace requires persistence:false; degraded baseline requires failure provenance",
    )
    record_index.set_defaults(handler=handler)


def _register_record_artifact_parser(
    subparsers, registration, handler
) -> None:
    artifact = subparsers.add_parser(
        registration.command,
        help="hash and record an immutable file or deterministic directory artifact",
    )
    _add_mutation(artifact)
    artifact.add_argument(
        "--path", "--artifact", dest="path", required=True, help="artifact file or directory"
    )
    artifact.add_argument("--kind", required=True, help="artifact kind, for example impact, openspec, plan or review")
    artifact.add_argument(
        "--verdict",
        choices=["PASS", "CONDITIONAL", "FAIL"],
        help="must match the review report's unique first non-empty Verdict: line",
    )
    artifact.add_argument("--metadata-json", help="optional JSON object")
    artifact.set_defaults(handler=handler)


def _register_set_route_parser(
    subparsers, registration, handler
) -> None:
    route = subparsers.add_parser(
        registration.command,
        help="bind direct or openspec to the current impact/index evidence",
    )
    _add_mutation(route)
    route.add_argument("route", nargs="?", choices=["direct", "openspec"], help="development route")
    route.add_argument("--route", dest="route_option", choices=["direct", "openspec"], help="development route")
    route.add_argument("--reason", required=True, help="why this route fits the impact")
    route.set_defaults(handler=handler)


def _register_approve_parser(
    subparsers, registration, handler
) -> None:
    approve = subparsers.add_parser(
        registration.command,
        help="approve a named gate with an auditable note",
    )
    _add_mutation(approve)
    approve.add_argument(
        "--gate",
        required=True,
        choices=APPROVAL_GATES,
        help="gate name; route approval advances to ROUTE_APPROVED",
    )
    approve.add_argument("--note", required=True, help="approval note")
    approve.add_argument("--artifact-sha256", help="artifact hash; required by evidence-bound gates")
    approve.add_argument(
        "--accept-conditional",
        action="store_true",
        help="explicitly accept a CONDITIONAL review verdict",
    )
    approve.add_argument(
        "--allow-fetch",
        action="store_true",
        help="authorize network fetches (only for --gate baseline-fetch)",
    )
    approve.add_argument(
        "--allow-dirty",
        action="store_true",
        help="approve the exact dirty preflight snapshot (only for baseline-fetch or lite)",
    )
    approve.set_defaults(handler=handler)


def _register_transition_parser(
    subparsers, registration, handler
) -> None:
    transition = subparsers.add_parser(
        registration.command,
        help="perform one guarded, separately confirmed state transition",
    )
    _add_mutation(transition)
    transition.add_argument(
        "to",
        nargs="?",
        choices=sorted(ALL_STATES),
        help="target state as a stable ID; responses also include a display name",
    )
    transition.add_argument(
        "--to",
        dest="to_option",
        choices=sorted(ALL_STATES),
        help="target state as a stable ID; responses also include a display name",
    )
    transition.add_argument("--note", help="transition note; required for BLOCKED or CANCELLED")
    transition_mode = transition.add_mutually_exclusive_group()
    transition_mode.add_argument(
        "--preview",
        action="store_true",
        help="validate the edge and return its confirmation intent without mutating",
    )
    transition_mode.add_argument(
        "--confirm-intent",
        help="apply the exact live intent returned by --preview",
    )
    transition.set_defaults(handler=handler)


def _register_prepare_workspace_parser(
    subparsers, registration, handler
) -> None:
    workspace = subparsers.add_parser(
        registration.command,
        help="record an approvable plan or create its exact isolated Git worktrees",
    )
    _add_mutation(workspace)
    workspace.add_argument("--repo", action="append", help="repository id or path; if supplied, must enumerate all task repositories")
    workspace.add_argument("--branch", help="workspace branch; defaults to codex/<task-id>")
    workspace.add_argument("--path", help="workspace path (only with one selected repository)")
    workspace.add_argument(
        "--workspace-path",
        action="append",
        help="per-repository absolute path override as REPOSITORY=PATH; repeatable",
    )
    workspace.add_argument(
        "--workspace-branch",
        action="append",
        help="per-repository branch override as REPOSITORY=BRANCH; repeatable",
    )
    mode = workspace.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="execute the latest workspace-gate-approved plan exactly",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="record/return a deterministic workspace-plan artifact (default)",
    )
    workspace.set_defaults(handler=handler)


def _register_record_test_parser(
    subparsers, registration, handler
) -> None:
    tests = subparsers.add_parser(
        registration.command,
        help="record a named command identity against exact repository fingerprints",
    )
    _add_mutation(tests)
    tests.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    tests.add_argument("--name", required=True, help="test suite name")
    tests.add_argument("--command", dest="test_command", required=True, help="command that was run (recorded, never executed)")
    tests.add_argument("--exit-code", type=int, required=True, help="observed process exit code")
    tests.add_argument("--output", help="optional captured test output file to hash")
    tests.set_defaults(handler=handler)


def _register_review_snapshot_parser(
    subparsers, registration, handler
) -> None:
    review = subparsers.add_parser(
        registration.command,
        help="capture base...HEAD, cached, unstaged and untracked review inputs",
    )
    _add_mutation(review)
    review.add_argument("--repo", action="append", help="repository id or path; must cover all repositories")
    review.set_defaults(handler=handler)


def _register_cancel_parser(
    subparsers, registration, handler
) -> None:
    cancel = subparsers.add_parser(
        registration.command,
        help="cancel a non-terminal task with a reason",
    )
    _add_mutation(cancel)
    cancel.add_argument("--reason", required=True, help="cancellation reason")
    cancel_mode = cancel.add_mutually_exclusive_group()
    cancel_mode.add_argument(
        "--preview",
        action="store_true",
        help="return a cancellation intent without mutating",
    )
    cancel_mode.add_argument(
        "--confirm-intent",
        help="cancel using the exact live intent returned by --preview",
    )
    cancel.set_defaults(handler=handler)


def _register_manager_authorize_parser(
    subparsers, registration, handler
) -> None:
    authorize = subparsers.add_parser(
        registration.command,
        help=(
            "preview or issue one verifier-only schema-v4 manager capability"
        ),
    )
    _add_task(authorize)
    authorize.add_argument(
        "--expected-revision",
        type=int,
        required=True,
        help="current task revision",
    )
    authorize.add_argument(
        "--manager-session-id",
        required=True,
        help="exact manager session that will own the capability",
    )
    authorize.add_argument(
        "--ttl-seconds",
        type=int,
        default=MANAGER_CAPABILITY_DEFAULT_TTL_SECONDS,
        help="capability lifetime from 1 through 900 seconds",
    )
    authorize_mode = authorize.add_mutually_exclusive_group(
        required=True
    )
    authorize_mode.add_argument(
        "--preview",
        action="store_true",
        help="return the exact read-only operator confirmation intent",
    )
    authorize_mode.add_argument(
        "--confirm-intent",
        help="issue only when the exact current preview intent still matches",
    )
    authorize.add_argument(
        "--manager-secret-fd",
        type=int,
        help=(
            "inherited manager-only descriptor that receives the secret; "
            "required only with --confirm-intent"
        ),
    )
    _add_data_dir(authorize)
    authorize.set_defaults(handler=handler)


def _register_manager_revoke_parser(
    subparsers, registration, handler
) -> None:
    revoke = subparsers.add_parser(
        registration.command,
        help="preview or revoke one persisted schema-v4 manager verifier",
    )
    _add_task(revoke)
    revoke.add_argument(
        "--expected-revision",
        type=int,
        required=True,
        help="current task revision",
    )
    revoke.add_argument(
        "--capability-id",
        required=True,
        help="exact persisted capability verifier identity",
    )
    revoke.add_argument(
        "--reason",
        required=True,
        help="stable audit reason identifier",
    )
    revoke_mode = revoke.add_mutually_exclusive_group(required=True)
    revoke_mode.add_argument(
        "--preview",
        action="store_true",
        help="return the exact read-only operator confirmation intent",
    )
    revoke_mode.add_argument(
        "--confirm-intent",
        help="revoke only when the exact current preview intent still matches",
    )
    _add_data_dir(revoke)
    revoke.set_defaults(handler=handler)


def _register_action_recovery_inspect_parser(
    subparsers, registration, handler
) -> None:
    inspect = subparsers.add_parser(
        registration.command,
        help=(
            "inspect one schema-v4 action execution without granting "
            "reconciliation authority"
        ),
    )
    _add_task(inspect)
    inspect.add_argument(
        "--execution-id",
        required=True,
        help="exact active or archived action execution identity",
    )
    _add_data_dir(inspect)
    inspect.set_defaults(handler=handler)


def _register_action_recovery_preview_parser(
    subparsers, registration, handler
) -> None:
    preview = subparsers.add_parser(
        registration.command,
        help=(
            "preview one exact quarantined action reconciliation using "
            "discovery-only journal facts"
        ),
    )
    _add_task(preview)
    preview.add_argument(
        "--execution-id",
        required=True,
        help="exact quarantined action execution identity",
    )
    preview.add_argument(
        "--attempt-id",
        required=True,
        help="fresh portable reconciliation attempt identity",
    )
    preview.add_argument(
        "--outcome",
        required=True,
        choices=("ACCEPTED", "ABANDONED", "COMPENSATED"),
        help="explicit terminal reconciliation decision",
    )
    preview.add_argument(
        "--expected-revision",
        required=True,
        type=int,
        help="current task revision bound by the preview",
    )
    preview.add_argument(
        "--evidence-json",
        required=True,
        help="strict decision-specific reconciliation evidence object",
    )
    _add_data_dir(preview)
    preview.set_defaults(handler=handler)


def _register_action_recovery_apply_parser(
    subparsers, registration, handler
) -> None:
    apply = subparsers.add_parser(
        registration.command,
        help=(
            "apply or recover one manager-authorized schema-v4 action "
            "reconciliation"
        ),
    )
    _add_mutation(apply)
    apply.add_argument(
        "--execution-id",
        required=True,
        help="exact quarantined action execution identity",
    )
    apply.add_argument(
        "--attempt-id",
        required=True,
        help="fresh or replayed portable reconciliation attempt identity",
    )
    apply.add_argument(
        "--outcome",
        required=True,
        choices=("ACCEPTED", "ABANDONED", "COMPENSATED"),
        help="explicit terminal reconciliation decision",
    )
    apply.add_argument(
        "--confirm-preview",
        required=True,
        help="exact token returned by action-recovery-preview",
    )
    apply.add_argument(
        "--evidence-json",
        required=True,
        help="strict decision-specific reconciliation evidence object",
    )
    apply.set_defaults(handler=handler)


def _build_parser_from_command_registry(
    command_registry,
) -> argparse.ArgumentParser:
    if not bool(getattr(command_registry, "sealed", False)):
        raise WorkflowRegistryError(
            "REGISTRY_UNSEALED",
            "CLI parser construction requires the sealed command registry",
            details={"registry": "commands"},
        )
    registrations = sorted(
        command_registry.entries.values(),
        key=lambda item: item.parser_order,
    )
    expected_orders = list(range(len(registrations)))
    observed_orders = [
        registration.parser_order for registration in registrations
    ]
    if observed_orders != expected_orders:
        raise WorkflowRegistryError(
            "REGISTRY_PARSER_ORDER_INVALID",
            "sealed command parser orders must be unique and contiguous",
            details={
                "expected": expected_orders,
                "observed": observed_orders,
            },
        )

    parser = JsonArgumentParser(
        prog="dev_flow.py",
        description="Deterministic Codex + OpenSpec + codebase-memory development-flow control plane.",
    )
    parser.add_argument("--data-dir", help="state directory (may also follow a subcommand)")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=JsonArgumentParser,
    )
    for registration in registrations:
        parser_factory = command_registry.resolve_callable(
            registration.identifier,
            registration.contract_version,
            "parser_factory",
        )
        handler = command_registry.resolve_callable(
            registration.identifier,
            registration.contract_version,
            "handler",
        )
        existing = frozenset(subparsers.choices)
        parser_factory(subparsers, registration, handler)
        added = frozenset(subparsers.choices) - existing
        if added != {registration.command}:
            raise WorkflowRegistryError(
                "REGISTRY_PARSER_FACTORY_INVALID",
                "command parser factory must add exactly its registered spelling",
                details={
                    "identifier": registration.identifier,
                    "command": registration.command,
                    "added": sorted(added),
                },
            )
        configured = subparsers.choices[registration.command]
        if bool(
            configured._defaults.get(
                "_manager_mutation_command", False
            )
        ):
            configured.set_defaults(
                _manager_action_id=registration.action_id
            )
        if configured._defaults.get("handler") is not handler:
            raise WorkflowRegistryError(
                "REGISTRY_PARSER_HANDLER_MISMATCH",
                "command parser factory must bind its frozen registered handler",
                details={
                    "identifier": registration.identifier,
                    "command": registration.command,
                },
            )
    return parser


def build_parser() -> argparse.ArgumentParser:
    services = workflow_runtime_services()
    return _build_parser_from_command_registry(
        services.registries.commands
    )


def _extract_manager_cli_authority_options(
    arguments: Sequence[str],
) -> tuple[list[str], str | None, int | None]:
    """Parse the V4 proof transport used by current commands."""

    remaining: list[str] = []
    request_json: str | None = None
    secret_fd: int | None = None
    index = 0
    values = list(arguments)
    while index < len(values):
        token = values[index]
        option = None
        inline_value = None
        if token == "--manager-request-json":
            option = token
        elif token.startswith("--manager-request-json="):
            option = "--manager-request-json"
            inline_value = token.split("=", 1)[1]
        elif token == "--manager-secret-fd":
            option = token
        elif token.startswith("--manager-secret-fd="):
            option = "--manager-secret-fd"
            inline_value = token.split("=", 1)[1]
        if option is None:
            remaining.append(token)
            index += 1
            continue
        if inline_value is None:
            index += 1
            if index >= len(values):
                raise FlowError(
                    "INVALID_ARGUMENT",
                    f"{option} requires one value",
                )
            inline_value = values[index]
        if option == "--manager-request-json":
            if request_json is not None:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--manager-request-json may be supplied only once",
                )
            request_json = inline_value
        else:
            if secret_fd is not None:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--manager-secret-fd may be supplied only once",
                )
            try:
                secret_fd = int(inline_value, 10)
            except (TypeError, ValueError) as exc:
                raise FlowError(
                    "MANAGER_SECRET_CHANNEL_INVALID",
                    "--manager-secret-fd must be a decimal integer",
                ) from exc
        index += 1
    return remaining, request_json, secret_fd


def _cli_command_hint(arguments: Sequence[str]) -> str | None:
    """Locate the subcommand while honoring the sole root option."""

    values = list(arguments)
    index = 0
    while index < len(values):
        token = values[index]
        if token == "--data-dir":
            index += 2
            continue
        if token.startswith("--data-dir="):
            index += 1
            continue
        if token.startswith("-"):
            return None
        return token
    return None


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = build_parser()
        supplied_arguments = list(
            argv if argv is not None else sys.argv[1:]
        )
        manager_request_json = None
        manager_secret_fd = None
        if _cli_command_hint(supplied_arguments) != (
            "manager-authorize"
        ):
            (
                supplied_arguments,
                manager_request_json,
                manager_secret_fd,
            ) = _extract_manager_cli_authority_options(
                supplied_arguments
            )
        args, unknown = parser.parse_known_args(supplied_arguments)
        if (
            manager_request_json is not None
            or manager_secret_fd is not None
        ) and not bool(
            getattr(args, "_manager_mutation_command", False)
        ):
            parser.error(
                "manager authority options are valid only for mutating commands"
            )
        if bool(
            getattr(args, "_manager_mutation_command", False)
        ):
            args.manager_request_json = manager_request_json
            args.manager_secret_fd = manager_secret_fd
        else:
            if not hasattr(args, "manager_request_json"):
                args.manager_request_json = None
            if not hasattr(args, "manager_secret_fd"):
                args.manager_secret_fd = None
        # argparse cannot intermix optional arguments between two optional
        # positionals.  Accept the natural `TASK --expected-revision N TARGET`
        # spelling for these two commands without weakening typo detection.
        if unknown:
            if (
                args.command == "set-route"
                and len(unknown) == 1
                and args.route is None
                and unknown[0] in {"direct", "openspec"}
            ):
                args.route = unknown[0]
            elif (
                args.command == "transition"
                and len(unknown) == 1
                and args.to is None
                and unknown[0] in ALL_STATES
            ):
                args.to = unknown[0]
            else:
                parser.error(f"unrecognized arguments: {' '.join(unknown)}")
        if not hasattr(args, "data_dir"):
            args.data_dir = None
        with _manager_cli_authority_context(args):
            response = args.handler(args)
        _write_protocol_response(response)
        return 0
    except FlowError as exc:
        response = {
            "ok": False,
            "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        }
        _write_protocol_response(response)
        return exc.exit_code
    except KeyboardInterrupt:
        _write_protocol_response(
            {
                "ok": False,
                "error": {
                    "code": "INTERRUPTED",
                    "message": "operation interrupted",
                    "details": {},
                },
            }
        )
        return 130
    except Exception as exc:  # Keep the machine contract even for unexpected failures.
        _write_protocol_response(
            {
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "details": {"type": type(exc).__name__},
                },
            }
        )
        return 1
