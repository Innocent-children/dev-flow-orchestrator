# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Configuration, scope evaluation, and repository ownership claims.
from __future__ import annotations

def config_path(data_dir: str | os.PathLike[str] | None = None) -> Path:
    return resolve_data_dir(data_dir) / "config.json"


def _default_config() -> dict[str, Any]:
    """The absent-configuration default keeps the plugin active everywhere."""

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "scope": {"mode": "all", "include": [], "exclude": []},
        "risk_policy": {
            "schema": "dev-flow-risk-policy/v1",
            "protected_paths": sorted(DEFAULT_PROTECTED_PATH_GLOBS),
        },
    }


def _normalize_scope_root(
    value: Any, option: str, *, code: str = "INVALID_ARGUMENT"
) -> str:
    text = str(value or "").strip()
    if not text:
        raise FlowError(code, f"{option} requires a non-empty directory path")
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise FlowError(
            code,
            f"{option} is not a usable directory path",
            details={"path": text, "error": str(exc)},
        ) from exc


def _normalize_scope(value: Any) -> dict[str, Any]:
    """Coerce a stored scope object into its canonical absolute-path form."""

    supplied = value if isinstance(value, dict) else {}
    mode = str(supplied.get("mode", "all")).strip().lower() or "all"
    if mode not in SCOPE_MODES:
        raise FlowError(
            "CONFIG_INVALID",
            f"scope.mode must be one of: {', '.join(SCOPE_MODES)}",
            details={"mode": mode},
        )
    scope: dict[str, Any] = {"mode": mode}
    for key in ("include", "exclude"):
        raw = supplied.get(key) or []
        if not isinstance(raw, list):
            raise FlowError(
                "CONFIG_INVALID",
                f"scope.{key} must be a list of directories",
                details={"key": key},
            )
        roots: list[str] = []
        for item in raw:
            root = _normalize_scope_root(
                item, f"scope.{key}", code="CONFIG_INVALID"
            )
            if not any(
                _same_path(Path(root), Path(existing))
                for existing in roots
            ):
                roots.append(root)
        scope[key] = sorted(roots)
    return scope


def _normalize_risk_glob(
    value: Any, option: str, *, code: str = "INVALID_ARGUMENT"
) -> str:
    if not isinstance(value, str):
        raise FlowError(
            code,
            f"{option} requires a repository-relative POSIX glob",
            details={"glob_type": type(value).__name__},
        )
    text = value.strip().replace("\\", "/")
    if (
        not text
        or "\x00" in text
        or text.startswith("/")
        or re.match(r"^[A-Za-z]:", text)
    ):
        raise FlowError(
            code,
            f"{option} requires a repository-relative POSIX glob",
            details={"glob": text},
        )
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise FlowError(
            code,
            f"{option} contains an invalid path segment",
            details={"glob": text},
        )
    if any(
        "[" in part
        or "]" in part
        or ("**" in part and part != "**")
        for part in parts
    ):
        raise FlowError(
            code,
            f"{option} supports literal characters, *, ?, and whole-segment **",
            details={"glob": text},
        )
    return text


def _normalize_risk_policy(value: Any) -> dict[str, Any]:
    supplied = value if isinstance(value, dict) else {}
    schema = supplied.get("schema", "dev-flow-risk-policy/v1")
    if schema != "dev-flow-risk-policy/v1":
        raise FlowError(
            "CONFIG_INVALID",
            "risk_policy.schema is unsupported",
            details={"schema": schema},
        )
    raw_patterns = supplied.get(
        "protected_paths", list(DEFAULT_PROTECTED_PATH_GLOBS)
    )
    if not isinstance(raw_patterns, list):
        raise FlowError(
            "CONFIG_INVALID",
            "risk_policy.protected_paths must be a list",
        )
    patterns = {
        _normalize_risk_glob(
            item, "risk_policy.protected_paths", code="CONFIG_INVALID"
        )
        for item in raw_patterns
    }
    return {
        "schema": "dev-flow-risk-policy/v1",
        "protected_paths": sorted(patterns),
    }


def _risk_glob_regex(pattern: str) -> re.Pattern[str]:
    segments = pattern.split("/")
    expression = "^"
    for index, segment in enumerate(segments):
        if segment == "**":
            if index == len(segments) - 1:
                expression += ".*"
            else:
                expression += "(?:[^/]+/)*"
            continue
        translated = ""
        cursor = 0
        while cursor < len(segment):
            char = segment[cursor]
            if char == "*":
                if cursor + 1 < len(segment) and segment[cursor + 1] == "*":
                    translated += ".*"
                    cursor += 2
                    continue
                translated += "[^/]*"
            elif char == "?":
                translated += "[^/]"
            else:
                translated += re.escape(char)
            cursor += 1
        expression += translated
        if index < len(segments) - 1:
            expression += "/"
    return re.compile(expression + "$")


def _normalize_repo_relative_path(
    value: Any, option: str, *, code: str = "INVALID_ARGUMENT"
) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if (
        not text
        or "\x00" in text
        or text.startswith("/")
        or re.match(r"^[A-Za-z]:", text)
    ):
        raise FlowError(
            code,
            f"{option} requires a repository-relative path",
            details={"path": text},
        )
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise FlowError(
            code,
            f"{option} contains an invalid path segment",
            details={"path": text},
        )
    return "/".join(parts)


def _normalize_git_evidence_path(
    value: Any, option: str, *, code: str = "RISK_EVIDENCE_INVALID"
) -> str:
    """Preserve Git path identity and reject cross-platform ambiguities."""

    if (
        not isinstance(value, str)
        or value != value.strip()
        or "\\" in value
    ):
        raise FlowError(
            code,
            f"{option} is ambiguous across supported filesystems",
            details={
                "path": value if isinstance(value, str) else None,
                "path_type": type(value).__name__,
            },
        )
    return _normalize_repo_relative_path(value, option, code=code)


def _protected_path_match(
    relative_path: str, risk_policy: dict[str, Any]
) -> str | None:
    normalized = _normalize_repo_relative_path(
        relative_path, "changed path", code="RISK_EVIDENCE_INVALID"
    )
    for pattern in risk_policy.get("protected_paths", []):
        if _risk_glob_regex(pattern).fullmatch(normalized):
            return pattern
    return None


def load_config(data_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return the stored plugin configuration, or the defaults when absent."""

    path = config_path(data_dir)
    if not path.exists():
        return _default_config()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "CONFIG_INVALID",
            "plugin configuration is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    schema_version = value.get("schema_version") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in SUPPORTED_CONFIG_SCHEMA_VERSIONS
    ):
        raise FlowError(
            "CONFIG_INVALID",
            "plugin configuration has an unsupported structure",
            details={
                "path": str(path),
                "schema_version": value.get("schema_version")
                if isinstance(value, dict)
                else None,
            },
        )
    raw_risk_policy = value.get("risk_policy")
    if schema_version == CONFIG_SCHEMA_VERSION and (
        not isinstance(raw_risk_policy, dict)
        or raw_risk_policy.get("schema") != "dev-flow-risk-policy/v1"
        or not isinstance(raw_risk_policy.get("protected_paths"), list)
    ):
        raise FlowError(
            "CONFIG_INVALID",
            "schema-v2 configuration requires a complete risk_policy",
            details={"path": str(path)},
        )
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "scope": _normalize_scope(value.get("scope")),
        "risk_policy": _normalize_risk_policy(raw_risk_policy),
    }


def _scope_env_roots(environ: Any, name: str) -> list[str] | None:
    """Parse one ``os.pathsep`` separated override, or None when unset."""

    raw = environ.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return None
    roots: list[str] = []
    for item in raw.split(os.pathsep):
        if not item.strip():
            continue
        root = _normalize_scope_root(item, name)
        if not any(
            _same_path(Path(root), Path(existing)) for existing in roots
        ):
            roots.append(root)
    return sorted(roots) or None


def resolve_scope(
    data_dir: str | os.PathLike[str] | None = None,
    environ: Any = None,
) -> dict[str, Any]:
    """Return the stored scope after applying the environment overrides.

    ``DEV_FLOW_SCOPE`` replaces the included directories and forces allowlist
    mode; ``DEV_FLOW_SCOPE_EXCLUDE`` replaces the excluded directories in
    either mode.  ``overrides`` records which list the environment supplied.
    """

    values = os.environ if environ is None else environ
    scope = load_config(data_dir)["scope"]
    overrides: dict[str, str] = {}
    include = _scope_env_roots(values, SCOPE_INCLUDE_ENV)
    if include is not None:
        scope.update({"mode": "allowlist", "include": include})
        overrides["include"] = SCOPE_INCLUDE_ENV
    exclude = _scope_env_roots(values, SCOPE_EXCLUDE_ENV)
    if exclude is not None:
        scope["exclude"] = exclude
        overrides["exclude"] = SCOPE_EXCLUDE_ENV
    scope["overrides"] = overrides
    return scope


def evaluate_scope(path: str | os.PathLike[str], scope: dict[str, Any]) -> dict[str, Any]:
    """Decide whether one directory is in scope; the deepest root wins.

    A directory nested under both an included and an excluded root follows the
    more specific one, so an allowlist can carve exceptions back out of an
    exclusion.  An exactly equal pair resolves to the exclusion.
    """

    current = Path(path).expanduser().resolve(strict=False)
    matched: str | None = None
    rule = "default"
    depth = -1
    for candidate_rule in ("include", "exclude"):
        for root in scope.get(candidate_rule) or []:
            candidate = Path(root)
            if not _is_within(current, candidate):
                continue
            candidate_depth = len(
                _filesystem_identity(candidate)["parts"]
            )
            if candidate_depth > depth or (
                candidate_depth == depth and candidate_rule == "exclude"
            ):
                matched, rule, depth = root, candidate_rule, candidate_depth
    if rule == "default":
        in_scope = str(scope.get("mode", "all")) != "allowlist"
    else:
        in_scope = rule == "include"
    return {
        "path": str(current),
        "in_scope": in_scope,
        "rule": rule,
        "matched": matched,
        "mode": str(scope.get("mode", "all")),
    }


def evaluate_scope_for_path(
    path: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
    environ: Any = None,
) -> dict[str, Any]:
    """Resolve the effective scope and evaluate one directory against it."""

    return evaluate_scope(path, resolve_scope(data_dir, environ))


def _scope_summary(scope: dict[str, Any]) -> str:
    if str(scope.get("mode", "all")) == "allowlist":
        if not scope.get("include"):
            return "inactive in every directory"
        if scope.get("exclude"):
            return "active only inside the included directories, minus the excluded ones"
        return "active only inside the included directories"
    if scope.get("exclude"):
        return "active in every directory except the excluded ones"
    return "active in every directory"


def _assert_path_in_scope(
    path: Path, label: str, data_dir: str | os.PathLike[str] | None
) -> None:
    decision = evaluate_scope_for_path(path, data_dir)
    if decision["in_scope"]:
        return
    raise FlowError(
        "OUT_OF_SCOPE",
        f"{label} is outside the configured Dev Flow scope",
        details={
            "path": decision["path"],
            "matched": decision["matched"],
            "rule": decision["rule"],
            "mode": decision["mode"],
            "config_path": str(config_path(data_dir)),
            "remedy": "add the directory with the scope command, or widen the scope",
        },
    )


def _load_workspace_registry(
    data_root: Path, *, allow_legacy_container: bool = False
) -> dict[str, Any]:
    path = data_root / "workspace-registry.json"
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "claims": [],
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCHEMA_VERSION
        or not isinstance(value.get("claims"), list)
    ):
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry has an unsupported structure",
            details={"path": str(path)},
        )
    _assert_supported_evidence_versions(value)
    if (
        value.get("evidence_contract_version")
        != EVIDENCE_CONTRACT_VERSION
        and not allow_legacy_container
    ):
        raise FlowError(
            "EVIDENCE_REGENERATION_REQUIRED",
            (
                "legacy workspace registry evidence must be regenerated from "
                "a current approved workspace plan"
            ),
            details={
                "path": str(path),
                "required_version": EVIDENCE_CONTRACT_VERSION,
                "encountered_version": value.get(
                    "evidence_contract_version"
                ),
            },
        )
    return value


def _source_common_dir_for_claim(source_path: Any) -> str:
    source = Path(str(source_path)).expanduser().resolve(strict=False)
    try:
        return str(_git_evidence_path(source, "--git-common-dir"))
    except (FlowError, OSError):
        return f"unavailable:{source}"


def _state_workspace_claims(data_root: Path) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    tasks_dir = data_root / "tasks"
    if not tasks_dir.is_dir():
        return claims
    for state_path in tasks_dir.glob("*/state.json"):
        try:
            state_value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(state_value, dict) or not state_value.get("task_id"):
            continue
        task_id = state_value["task_id"]
        for repo in state_value.get("repositories", []):
            common_dir = _source_common_dir_for_claim(repo.get("path"))
            for workspace in [repo.get("workspace"), *repo.get("workspace_history", [])]:
                if not isinstance(workspace, dict) or not workspace.get("path"):
                    continue
                workspace_path = Path(workspace["path"]).resolve(strict=False)
                source_path = Path(repo.get("path", "")).resolve(strict=False)
                common_path = (
                    Path(common_dir)
                    if not common_dir.startswith("unavailable:")
                    else None
                )
                claims.append(
                    {
                        "evidence_contract_version": workspace.get(
                            "evidence_contract_version"
                        ),
                        "task_id": task_id,
                        "repository_id": repo.get("id"),
                        "source_path": str(source_path),
                        "source_identity": _serializable_path_identity(source_path),
                        "path": str(workspace_path),
                        "path_identity": _serializable_path_identity(workspace_path),
                        "branch": workspace.get("branch"),
                        "branch_ref": workspace.get("branch_ref"),
                        "planned_ref_oid": workspace.get(
                            "planned_ref_oid"
                        ),
                        "ref_case_sensitive": workspace.get(
                            "ref_case_sensitive"
                        ),
                        "ref_unicode_normalization_distinct": workspace.get(
                            "ref_unicode_normalization_distinct"
                        ),
                        "source_common_dir": common_dir,
                        "source_common_dir_identity": (
                            _serializable_path_identity(common_path)
                            if common_path is not None
                            else None
                        ),
                        "workspace_generation": workspace.get(
                            "workspace_generation"
                        ),
                        "plan_sha256": (
                            workspace.get("workspace_claim") or {}
                        ).get("plan_sha256"),
                        "origin": "task-state",
                    }
                )
        controller_plan = (state_value.get("workspace") or {}).get("plan") or {}
        plan_path = controller_plan.get("path")
        if plan_path:
            try:
                evidence = json.loads(Path(plan_path).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            for planned in evidence.get("repositories", []):
                if not planned.get("path"):
                    continue
                planned_path = Path(planned["path"]).resolve(strict=False)
                source_path = Path(
                    planned.get("source_path", "")
                ).resolve(strict=False)
                common_dir = _source_common_dir_for_claim(source_path)
                common_path = (
                    Path(common_dir)
                    if not common_dir.startswith("unavailable:")
                    else None
                )
                claims.append(
                    {
                        "evidence_contract_version": evidence.get(
                            "evidence_contract_version"
                        ),
                        "task_id": task_id,
                        "repository_id": planned.get("repository_id"),
                        "source_path": str(source_path),
                        "source_identity": planned.get("source_identity")
                        or _serializable_path_identity(source_path),
                        "path": str(planned_path),
                        "path_identity": planned.get("path_identity")
                        or _serializable_path_identity(planned_path),
                        "branch": planned.get("branch"),
                        "branch_ref": planned.get("branch_ref"),
                        "planned_ref_oid": planned.get(
                            "planned_ref_oid"
                        ),
                        "ref_case_sensitive": planned.get(
                            "ref_case_sensitive"
                        ),
                        "ref_unicode_normalization_distinct": planned.get(
                            "ref_unicode_normalization_distinct"
                        ),
                        "source_common_dir": common_dir,
                        "source_common_dir_identity": planned.get(
                            "source_common_dir_identity"
                        )
                        or (
                            _serializable_path_identity(common_path)
                            if common_path is not None
                            else None
                        ),
                        "workspace_generation": controller_plan.get(
                            "workspace_generation"
                        ),
                        "plan_sha256": controller_plan.get("sha256"),
                        "origin": "task-plan",
                    }
                )
    return claims


def _repository_claim(root: Path, git_common_dir: Path) -> dict[str, Any]:
    """Build the durable exclusive-ownership key for one source checkout."""

    canonical_root = root.resolve(strict=False)
    canonical_common_dir = git_common_dir.resolve(strict=False)
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "canonical_path": str(canonical_root),
        "canonical_path_identity": _serializable_path_identity(
            canonical_root
        ),
        "git_common_dir": str(canonical_common_dir),
        "git_common_dir_identity": _serializable_path_identity(
            canonical_common_dir
        ),
    }


def _recorded_repository_claim(repo: dict[str, Any]) -> dict[str, Any]:
    """Load a durable repository claim, deriving a safe legacy equivalent."""

    stored = repo.get("repository_claim")
    if stored is not None and not isinstance(stored, dict):
        raise FlowError(
            "REPOSITORY_CLAIM_UNAVAILABLE",
            "repository ownership claim has an invalid structure",
            details={"repository_id": repo.get("id")},
        )
    stored = stored or {}
    root_value = (
        stored.get("canonical_path")
        or repo.get("canonical_path")
        or repo.get("path")
    )
    if not isinstance(root_value, str) or not root_value:
        raise FlowError(
            "REPOSITORY_CLAIM_UNAVAILABLE",
            "active repository has no canonical source path for ownership verification",
            details={"repository_id": repo.get("id")},
        )
    root = Path(root_value).expanduser().resolve(strict=False)
    common_value = stored.get("git_common_dir")
    if isinstance(common_value, str) and common_value:
        common_dir = Path(common_value).expanduser().resolve(strict=False)
    else:
        try:
            common_dir = _git_evidence_path(root, "--git-common-dir")
        except (FlowError, OSError, ValueError) as exc:
            raise FlowError(
                "REPOSITORY_CLAIM_UNAVAILABLE",
                "active repository Git common directory cannot be verified",
                details={
                    "repository_id": repo.get("id"),
                    "repository": str(root),
                    "error": str(exc),
                },
            ) from exc
    claim = _repository_claim(root, common_dir)
    for key in ("canonical_path_identity", "git_common_dir_identity"):
        candidate = stored.get(key)
        if isinstance(candidate, dict):
            claim[key] = candidate
    return claim


def _repository_claim_path_matches(
    left: dict[str, Any], right: dict[str, Any], path_key: str, identity_key: str
) -> bool:
    left_identity = left.get(identity_key)
    right_identity = right.get(identity_key)
    if isinstance(left_identity, dict) and isinstance(right_identity, dict):
        if _path_identity_equal(left_identity, right_identity):
            return True
    left_path = left.get(path_key)
    right_path = right.get(path_key)
    if not isinstance(left_path, str) or not isinstance(right_path, str):
        return False
    return _same_path(
        Path(left_path).expanduser().resolve(strict=False),
        Path(right_path).expanduser().resolve(strict=False),
    )


def _repository_claim_conflict(
    proposed: dict[str, Any], existing: dict[str, Any]
) -> str | None:
    """Return the exclusive resource shared by two active task claims."""

    if _repository_claim_path_matches(
        proposed,
        existing,
        "canonical_path",
        "canonical_path_identity",
    ):
        return "canonical_path"
    if _repository_claim_path_matches(
        proposed,
        existing,
        "git_common_dir",
        "git_common_dir_identity",
    ):
        return "git_common_dir"
    return None


def _active_repository_claims(data_root: Path) -> list[dict[str, Any]]:
    """Return every non-terminal task's source checkout ownership claim.

    Claims are intentionally exclusive across tasks.  A separate task cannot
    safely share either the same canonical checkout or a sibling worktree that
    resolves to the same Git common directory: both can mutate shared Git
    metadata and invalidate each other's observations.
    """

    tasks_dir = data_root / "tasks"
    if not tasks_dir.is_dir():
        return []
    claims: list[dict[str, Any]] = []
    for state_path in tasks_dir.glob("*/state.json"):
        try:
            state_value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FlowError(
                "REPOSITORY_CLAIM_UNAVAILABLE",
                "an existing task state cannot be read for ownership verification",
                details={"path": str(state_path), "error": str(exc)},
            ) from exc
        if not isinstance(state_value, dict):
            raise FlowError(
                "REPOSITORY_CLAIM_UNAVAILABLE",
                "an existing task state is invalid for ownership verification",
                details={"path": str(state_path)},
            )
        try:
            _validate_task_state_snapshot(state_path, state_value)
        except FlowError as exc:
            raise FlowError(
                "REPOSITORY_CLAIM_UNAVAILABLE",
                "an existing task state failed ownership contract validation",
                details={
                    "path": str(state_path),
                    "cause": exc.code,
                },
            ) from exc
        task_id = state_value.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise FlowError(
                "REPOSITORY_CLAIM_UNAVAILABLE",
                "an existing task has no valid identity for ownership verification",
                details={"path": str(state_path)},
            )
        if state_value.get("status") in TERMINAL_STATES:
            continue
        repositories = state_value.get("repositories")
        if not isinstance(repositories, list):
            raise FlowError(
                "REPOSITORY_CLAIM_UNAVAILABLE",
                "an active task has invalid repository ownership metadata",
                details={"task_id": task_id, "path": str(state_path)},
            )
        for repo in repositories:
            if not isinstance(repo, dict):
                raise FlowError(
                    "REPOSITORY_CLAIM_UNAVAILABLE",
                    "an active task contains an invalid repository record",
                    details={"task_id": task_id, "path": str(state_path)},
                )
            repository_id = repo.get("id")
            if not isinstance(repository_id, str) or not repository_id:
                raise FlowError(
                    "REPOSITORY_CLAIM_UNAVAILABLE",
                    "an active task repository has no valid identity",
                    details={"task_id": task_id, "path": str(state_path)},
                )
            claims.append(
                {
                    **_recorded_repository_claim(repo),
                    "task_id": task_id,
                    "repository_id": repository_id,
                    "state_path": str(state_path),
                }
            )
    return claims


def _claim_workspace_plan(
    data_root: Path,
    state_value: dict[str, Any],
    plan_sha256: str,
    plans: Sequence[dict[str, Any]],
    *,
    registry_locked: bool = False,
) -> dict[str, dict[str, Any]]:
    lock_context = (
        contextlib.nullcontext()
        if registry_locked
        else _workspace_registry_lock(data_root)
    )
    with lock_context:
        registry = _load_workspace_registry(
            data_root, allow_legacy_container=True
        )
        existing_claims = [*registry["claims"], *_state_workspace_claims(data_root)]
        proposed: list[dict[str, Any]] = []
        for plan in plans:
            source_path = Path(plan["source_path"]).resolve(strict=False)
            workspace_path = Path(plan["path"]).resolve(strict=False)
            source_common_dir = _source_common_dir_for_claim(source_path)
            source_common_path = (
                Path(source_common_dir)
                if not source_common_dir.startswith("unavailable:")
                else None
            )
            proposed.append(
                {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "claim_id": str(uuid.uuid4()),
                    "task_id": state_value["task_id"],
                    "repository_id": plan["repository_id"],
                    "source_path": str(source_path),
                    "source_identity": _serializable_path_identity(source_path),
                    "source_common_dir": source_common_dir,
                    "source_common_dir_identity": (
                        _serializable_path_identity(source_common_path)
                        if source_common_path is not None
                        else None
                    ),
                    "path": str(workspace_path),
                    "path_identity": _serializable_path_identity(workspace_path),
                    "branch": plan["branch"],
                    "branch_ref": plan.get("branch_ref"),
                    "planned_ref_oid": plan.get("planned_ref_oid"),
                    "ref_case_sensitive": plan.get("ref_case_sensitive"),
                    "ref_unicode_normalization_distinct": plan.get(
                        "ref_unicode_normalization_distinct"
                    ),
                    "workspace_generation": int(
                        (state_value.get("workspace") or {}).get("generation", 0)
                    ),
                    "plan_sha256": plan_sha256,
                    "claimed_at": utc_now(),
                }
            )
        for candidate_index, candidate in enumerate(proposed):
            candidate_path = Path(candidate["path"])
            for claimed in [*existing_claims, *proposed[:candidate_index]]:
                exact_retry = (
                    claimed.get("task_id") == candidate["task_id"]
                    and claimed.get("repository_id")
                    == candidate["repository_id"]
                    and _recorded_path_matches(
                        claimed.get("path_identity"),
                        claimed.get("path"),
                        candidate_path,
                    )
                    and claimed.get("branch") == candidate["branch"]
                    and claimed.get("branch_ref")
                    == candidate.get("branch_ref")
                    and claimed.get("planned_ref_oid")
                    == candidate.get("planned_ref_oid")
                    and claimed.get(
                        "ref_unicode_normalization_distinct"
                    )
                    == candidate.get(
                        "ref_unicode_normalization_distinct"
                    )
                    and (
                        _path_identity_equal(
                            claimed.get("source_common_dir_identity"),
                            candidate.get("source_common_dir_identity"),
                        )
                        if candidate.get("source_common_dir_identity")
                        else claimed.get("source_common_dir")
                        == candidate["source_common_dir"]
                    )
                    and claimed.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and claimed.get("plan_sha256") == candidate["plan_sha256"]
                )
                if exact_retry:
                    continue
                regenerating_same_legacy_claim = (
                    claimed.get("evidence_contract_version")
                    != EVIDENCE_CONTRACT_VERSION
                    and claimed.get("task_id") == candidate["task_id"]
                    and claimed.get("repository_id")
                    == candidate["repository_id"]
                    and claimed.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and _recorded_path_matches(
                        claimed.get("path_identity"),
                        claimed.get("path"),
                        candidate_path,
                    )
                    and claimed.get("branch") == candidate["branch"]
                )
                if regenerating_same_legacy_claim:
                    continue
                claimed_path_value = claimed.get("path")
                claimed_path = (
                    Path(claimed_path_value).resolve(strict=False)
                    if claimed_path_value
                    else None
                )
                path_conflict = bool(
                    claimed_path
                    and (
                        _is_within(candidate_path, claimed_path)
                        or _is_within(claimed_path, candidate_path)
                    )
                )
                candidate_ref = candidate.get("branch_ref") or (
                    f"refs/heads/{candidate['branch']}"
                    if candidate.get("branch")
                    else None
                )
                claimed_ref = claimed.get("branch_ref") or (
                    f"refs/heads/{claimed['branch']}"
                    if claimed.get("branch")
                    else None
                )
                ref_case_sensitive = bool(
                    candidate.get("ref_case_sensitive", True)
                    and claimed.get("ref_case_sensitive", True)
                )
                ref_unicode_distinct = bool(
                    candidate.get(
                        "ref_unicode_normalization_distinct", True
                    )
                    and claimed.get(
                        "ref_unicode_normalization_distinct", True
                    )
                )
                candidate_ref_identity = (
                    (
                        str(candidate_ref)
                        if ref_unicode_distinct
                        else unicodedata.normalize(
                            "NFC", str(candidate_ref)
                        )
                    )
                    if candidate_ref
                    else None
                )
                claimed_ref_identity = (
                    (
                        str(claimed_ref)
                        if ref_unicode_distinct
                        else unicodedata.normalize(
                            "NFC", str(claimed_ref)
                        )
                    )
                    if claimed_ref
                    else None
                )
                if not ref_case_sensitive:
                    candidate_ref_identity = (
                        candidate_ref_identity.casefold()
                        if candidate_ref_identity
                        else None
                    )
                    claimed_ref_identity = (
                        claimed_ref_identity.casefold()
                        if claimed_ref_identity
                        else None
                    )
                branch_conflict = bool(
                    candidate_ref_identity
                    and claimed_ref_identity
                    and (
                        candidate_ref_identity == claimed_ref_identity
                        or candidate_ref_identity.startswith(
                            f"{claimed_ref_identity}/"
                        )
                        or claimed_ref_identity.startswith(
                            f"{candidate_ref_identity}/"
                        )
                    )
                    and candidate.get("source_common_dir")
                    and (
                        _path_identity_equal(
                            candidate.get("source_common_dir_identity"),
                            claimed.get("source_common_dir_identity"),
                        )
                        if candidate.get("source_common_dir_identity")
                        and claimed.get("source_common_dir_identity")
                        else _same_path(
                            Path(candidate["source_common_dir"]),
                            Path(str(claimed.get("source_common_dir"))),
                        )
                        if claimed.get("source_common_dir")
                        and not str(claimed.get("source_common_dir")).startswith(
                            "unavailable:"
                        )
                        else candidate.get("source_common_dir")
                        == claimed.get("source_common_dir")
                    )
                )
                if path_conflict or branch_conflict:
                    raise FlowError(
                        "WORKSPACE_OWNERSHIP_CONFLICT",
                        "workspace path or repository branch is already claimed by another task or repository plan",
                        details={
                            "task_id": state_value["task_id"],
                            "repository_id": candidate["repository_id"],
                            "path": candidate["path"],
                            "branch": candidate["branch"],
                            "owner_task_id": claimed.get("task_id"),
                            "owner_path": claimed.get("path"),
                            "owner_branch": claimed.get("branch"),
                            "conflict": "path" if path_conflict else "branch",
                        },
                    )
        selected_claims: dict[str, dict[str, Any]] = {}
        for candidate in proposed:
            existing = next(
                (
                    claim
                    for claim in registry["claims"]
                    if claim.get("evidence_contract_version")
                    == EVIDENCE_CONTRACT_VERSION
                    and claim.get("task_id") == candidate["task_id"]
                    and claim.get("repository_id") == candidate["repository_id"]
                    and claim.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and claim.get("plan_sha256") == candidate["plan_sha256"]
                    and _recorded_path_matches(
                        claim.get("path_identity"),
                        claim.get("path"),
                        Path(candidate["path"]),
                    )
                    and claim.get("branch") == candidate["branch"]
                    and claim.get("branch_ref")
                    == candidate.get("branch_ref")
                    and claim.get("planned_ref_oid")
                    == candidate.get("planned_ref_oid")
                    and claim.get(
                        "ref_unicode_normalization_distinct"
                    )
                    == candidate.get(
                        "ref_unicode_normalization_distinct"
                    )
                ),
                None,
            )
            if existing is None:
                registry["claims"].append(candidate)
                existing = candidate
            selected_claims[candidate["repository_id"]] = existing
        registry["evidence_contract_version"] = (
            EVIDENCE_CONTRACT_VERSION
        )
        _atomic_write_json(data_root / "workspace-registry.json", registry)
        for plan in plans:
            claim = selected_claims[plan["repository_id"]]
            plan["workspace_claim"] = {
                "claim_id": claim["claim_id"],
                "registry_path": str(data_root / "workspace-registry.json"),
                "registry_identity": _serializable_path_identity(
                    data_root / "workspace-registry.json"
                ),
                "plan_sha256": plan_sha256,
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "path_identity": claim.get("path_identity"),
                "source_identity": claim.get("source_identity"),
                "source_common_dir_identity": claim.get(
                    "source_common_dir_identity"
                ),
            }
        return selected_claims
