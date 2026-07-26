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


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="dev_flow.py",
        description="Deterministic Codex + OpenSpec + codebase-memory development-flow control plane.",
    )
    parser.add_argument("--data-dir", help="state directory (may also follow a subcommand)")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    start = subparsers.add_parser(
        "start",
        help="create an INTAKE task for one or more repositories",
    )
    start.add_argument("requirement", nargs="?", help="requirement text")
    start.add_argument("--requirement", dest="requirement_option", help="requirement text (alternative to positional form)")
    start.add_argument("--repo", action="append", required=True, help="Git repository path; repeat for multiple repositories")
    start.add_argument("--task-id", help="stable task id (generated when omitted)")
    start.add_argument(
        "--flow",
        choices=sorted(FLOW_MODES),
        help=(
            "optional compatibility assertion; the flow is inferred from "
            "--workspace-strategy"
        ),
    )
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
    _add_data_dir(start)
    start.set_defaults(handler=command_start)

    show = subparsers.add_parser("show", help="show one full task snapshot")
    _add_task(show)
    _add_data_dir(show)
    show.set_defaults(handler=command_show)

    recover_quarantine = subparsers.add_parser(
        "recover-quarantine",
        help=(
            "prove an interrupted child is gone, validate partial "
            "postconditions, and archive its durable quarantine"
        ),
    )
    _add_mutation(recover_quarantine)
    recover_quarantine.set_defaults(handler=command_recover_quarantine)

    recover_atomic_write = subparsers.add_parser(
        "recover-atomic-write",
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
        handler=command_recover_atomic_write
    )

    listing = subparsers.add_parser("list", help="list task summaries")
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
    listing.set_defaults(handler=command_list)

    scope = subparsers.add_parser(
        "scope",
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
        help="reset to the default scope: active in every directory",
    )
    scope.add_argument(
        "--check",
        nargs="?",
        const=".",
        metavar="DIR",
        help="report whether a directory is in scope; defaults to the current directory",
    )
    _add_data_dir(scope)
    scope.set_defaults(handler=command_scope)

    preflight = subparsers.add_parser(
        "preflight",
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
    preflight.set_defaults(handler=command_preflight)

    baseline = subparsers.add_parser(
        "baseline",
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
    baseline.set_defaults(handler=command_baseline)

    record_index = subparsers.add_parser("record-index", help="record codebase-memory indexing provenance")
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
    record_index.set_defaults(handler=command_record_index)

    artifact = subparsers.add_parser(
        "record-artifact",
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
    artifact.set_defaults(handler=command_record_artifact)

    route = subparsers.add_parser("set-route", help="bind direct or openspec to the current impact/index evidence")
    _add_mutation(route)
    route.add_argument("route", nargs="?", choices=["direct", "openspec"], help="development route")
    route.add_argument("--route", dest="route_option", choices=["direct", "openspec"], help="development route")
    route.add_argument("--reason", required=True, help="why this route fits the impact")
    route.set_defaults(handler=command_set_route)

    approve = subparsers.add_parser("approve", help="approve a named gate with an auditable note")
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
    approve.set_defaults(handler=command_approve)

    transition = subparsers.add_parser(
        "transition",
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
    transition.set_defaults(handler=command_transition)

    workspace = subparsers.add_parser(
        "prepare-workspace",
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
    workspace.set_defaults(handler=command_prepare_workspace)

    tests = subparsers.add_parser("record-test", help="record a named command identity against exact repository fingerprints")
    _add_mutation(tests)
    tests.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    tests.add_argument("--name", required=True, help="test suite name")
    tests.add_argument("--command", dest="test_command", required=True, help="command that was run (recorded, never executed)")
    tests.add_argument("--exit-code", type=int, required=True, help="observed process exit code")
    tests.add_argument("--output", help="optional captured test output file to hash")
    tests.set_defaults(handler=command_record_test)

    review = subparsers.add_parser("review-snapshot", help="capture base...HEAD, cached, unstaged and untracked review inputs")
    _add_mutation(review)
    review.add_argument("--repo", action="append", help="repository id or path; must cover all repositories")
    review.set_defaults(handler=command_review_snapshot)

    cancel = subparsers.add_parser("cancel", help="cancel a non-terminal task with a reason")
    _add_mutation(cancel)
    cancel.add_argument("--reason", required=True, help="cancellation reason")
    cancel.set_defaults(handler=command_cancel)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = build_parser()
        args, unknown = parser.parse_known_args(argv)
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


