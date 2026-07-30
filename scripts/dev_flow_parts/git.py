# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Git evidence, repository selection, artifacts, fingerprints, and flow helpers.
from __future__ import annotations

def _git(repo: Path, *arguments: str, check: bool = True, text: bool = True) -> Any:
    result = _run(["git", "-C", str(repo), *arguments], check=check, text=text)
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_mutating(
    repo: Path, *arguments: str, text: bool = True
) -> Any:
    result = _run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        text=text,
        mutation=True,
    )
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_optional(repo: Path, *arguments: str) -> str | None:
    result = _run(["git", "-C", str(repo), *arguments], check=False, text=True)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_config_value(repo: Path, key: str) -> str | None:
    result = _run(
        ["git", "-C", str(repo), "config", "--get", key],
        check=False,
        text=True,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise FlowError(
            "GIT_CAPABILITY_UNAVAILABLE",
            f"could not read effective Git setting {key}",
            details={
                "repository": str(repo),
                "key": key,
                "stderr": result.stderr.strip(),
            },
        )
    return result.stdout.strip()


def _git_bool_config(repo: Path, key: str, default: bool) -> bool:
    value = _git_config_value(repo, key)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on", "1"}:
        return True
    if lowered in {"false", "no", "off", "0"}:
        return False
    raise FlowError(
        "GIT_CAPABILITY_CONTRADICTION",
        f"effective Git setting {key} is not boolean",
        details={"repository": str(repo), "key": key, "value": value},
    )


def _probe_worktree_capabilities(repo: Path) -> dict[str, Any]:
    probe_root: Path | None = None
    try:
        probe_root = Path(
            tempfile.mkdtemp(prefix=".dev-flow-capability-", dir=str(repo))
        )
        regular = probe_root / "mode-probe"
        regular.write_bytes(b"mode")
        before = stat.S_IMODE(regular.stat().st_mode)
        file_mode = False
        regular.chmod(before ^ stat.S_IXUSR)
        after = stat.S_IMODE(regular.stat().st_mode)
        file_mode = bool((before ^ after) & stat.S_IXUSR)
        target = probe_root / "symlink-target"
        link = probe_root / "symlink-probe"
        target.write_bytes(b"target")
        try:
            os.symlink(target.name, link)
            symlinks = link.is_symlink()
        except (OSError, NotImplementedError):
            symlinks = False
        unicode_normalization_distinct = (
            _probe_filesystem_unicode_distinct(probe_root)
        )
        case_sensitive = _probe_filesystem_case_sensitive(probe_root)
        return {
            "case_sensitive": case_sensitive,
            "file_mode": file_mode,
            "symlinks": symlinks,
            "unicode_normalization_distinct": unicode_normalization_distinct,
        }
    except FlowError:
        raise
    except OSError as exc:
        raise FlowError(
            "GIT_CAPABILITY_UNAVAILABLE",
            "could not probe worktree filesystem capabilities",
            details={"repository": str(repo), "error": str(exc)},
        ) from exc
    finally:
        if probe_root is not None:
            try:
                shutil.rmtree(probe_root)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FlowError(
                    "GIT_CAPABILITY_UNAVAILABLE",
                    "worktree capability probe could not be cleaned up",
                    details={"repository": str(repo), "path": str(probe_root), "error": str(exc)},
                ) from exc


def _git_capability_profile(
    repo: Path,
    filesystem_path: Path | None = None,
    *,
    filesystem_capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = repo.resolve(strict=True)
    profile_path = filesystem_path or resolved
    probe_target = resolved
    if filesystem_path is not None:
        probe_target, _ = _nearest_existing_path(filesystem_path)
        if not probe_target.is_dir():
            probe_target = probe_target.parent
    filesystem = (
        dict(filesystem_capabilities)
        if filesystem_capabilities is not None
        else _probe_worktree_capabilities(probe_target)
    )
    core_file_mode = _git_bool_config(
        resolved, "core.fileMode", filesystem["file_mode"]
    )
    core_symlinks = _git_bool_config(
        resolved, "core.symlinks", filesystem["symlinks"]
    )
    core_ignore_case = _git_bool_config(
        resolved, "core.ignoreCase", not filesystem["case_sensitive"]
    )
    contradictions: list[str] = []
    if core_file_mode and not filesystem["file_mode"]:
        contradictions.append("core.fileMode=true but executable mode changes are unavailable")
    if core_symlinks and not filesystem["symlinks"]:
        contradictions.append("core.symlinks=true but native symlink creation is unavailable")
    if not core_ignore_case and not filesystem["case_sensitive"]:
        contradictions.append("core.ignoreCase=false on a case-insensitive filesystem")
    if contradictions:
        raise FlowError(
            "GIT_CAPABILITY_CONTRADICTION",
            "effective Git settings contradict verified worktree capabilities",
            details={
                "repository": str(resolved),
                "contradictions": contradictions,
                "filesystem": filesystem,
            },
        )
    autocrlf = (_git_config_value(resolved, "core.autocrlf") or "false").lower()
    eol = (_git_config_value(resolved, "core.eol") or "native").lower()
    if autocrlf not in {"true", "false", "input"} or eol not in {
        "native",
        "lf",
        "crlf",
    }:
        raise FlowError(
            "GIT_CAPABILITY_CONTRADICTION",
            "effective line-ending settings are not recognized",
            details={
                "repository": str(resolved),
                "core.autocrlf": autocrlf,
                "core.eol": eol,
            },
        )
    profile: dict[str, Any] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "platform": "macos",
        "core_file_mode": core_file_mode,
        "core_symlinks": core_symlinks,
        "core_ignore_case": core_ignore_case,
        "core_autocrlf": autocrlf,
        "core_eol": eol,
        "filesystem": filesystem,
        "filesystem_identity": _capability_path_identity(profile_path),
        "git_version": _run(["git", "--version"]).stdout.strip(),
    }
    profile["sha256"] = _sha256_bytes(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode(
            "utf-8", "backslashreplace"
        )
    )
    return profile


def _evidence_git_command(repo: Path, *arguments: str) -> list[str]:
    return [
        "git",
        "-c",
        "color.ui=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.ignoreStat=false",
        "-c",
        "core.trustctime=true",
        "-c",
        "core.checkStat=default",
        "-c",
        "core.quotePath=true",
        "-c",
        "diff.external=",
        "-c",
        "diff.mnemonicPrefix=false",
        "-c",
        "diff.noprefix=false",
        "-c",
        "diff.srcPrefix=a/",
        "-c",
        "diff.dstPrefix=b/",
        "-c",
        "diff.ignoreSubmodules=none",
        "-c",
        "diff.submodule=short",
        "-C",
        str(repo),
        *arguments,
    ]


def _git_evidence(
    repo: Path, *arguments: str, check: bool = True, text: bool = True
) -> Any:
    result = _run(
        _evidence_git_command(repo, *arguments),
        check=check,
        text=text,
        evidence_git=True,
    )
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_evidence_optional(repo: Path, *arguments: str) -> str | None:
    result = _run(
        _evidence_git_command(repo, *arguments),
        check=False,
        text=True,
        evidence_git=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_diff(repo: Path, *arguments: str, text: bool = True) -> Any:
    return _git_evidence(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        "--submodule=short",
        "--no-renames",
        "--no-color",
        "--no-indent-heuristic",
        "--diff-algorithm=myers",
        "--unified=3",
        "--inter-hunk-context=0",
        *arguments,
        text=text,
    )


def _git_evidence_path(repo: Path, option: str) -> Path:
    raw = Path(_git_evidence(repo, "rev-parse", option))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _dirty_initialized_submodules(repo: Path) -> list[dict[str, str]]:
    """Return initialized submodules with unbound inner worktree content.

    A parent diff records a dirty submodule only as ``<gitlink>-dirty``.  It
    therefore cannot distinguish two different inner worktree states.  Clean
    submodule HEAD changes are safe because the changed gitlink commit remains
    part of the parent diff; tracked or untracked content below that HEAD is
    not safe evidence and must be rejected.
    """

    output = _git_evidence(
        repo,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
        "--no-renames",
        text=False,
    )
    dirty: list[dict[str, str]] = []
    records = output.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or record[:2] not in {b"1 ", b"2 ", b"u "}:
            continue
        kind = record[:1]
        path_field = {b"1": 8, b"2": 9, b"u": 10}[kind]
        fields = record.split(b" ", path_field)
        if len(fields) <= path_field or len(fields) < 3:
            continue
        submodule = fields[2]
        # Porcelain v2 uses S<c><m><u>: c is a clean pointer/HEAD change,
        # while m/u mean modified/untracked content inside the submodule.
        if (
            len(submodule) == 4
            and submodule.startswith(b"S")
            and (submodule[2:3] != b"." or submodule[3:4] != b".")
        ):
            dirty.append(
                {
                    "path": fields[path_field].decode("utf-8", "replace"),
                    "submodule_status": submodule.decode("ascii", "replace"),
                }
            )
        if kind == b"2" and index < len(records):
            # A rename/copy record is followed by its original path.
            index += 1
    return dirty


def _initialized_submodule_worktrees(repo: Path) -> list[tuple[str, Path]]:
    output = _git_evidence(
        repo, "ls-files", "--stage", "-z", "--cached", "--", text=False
    )
    initialized: list[tuple[str, Path]] = []
    for record in output.split(b"\0"):
        metadata, separator, path_bytes = record.partition(b"\t")
        if not separator or not metadata.startswith(b"160000 "):
            continue
        relative = os.fsdecode(path_bytes)
        target = (repo / relative).resolve(strict=False)
        root = _git_evidence_optional(target, "rev-parse", "--show-toplevel")
        if root and Path(root).resolve(strict=False) == target:
            initialized.append((relative, target))
    return initialized


def _hidden_index_entries(repo: Path) -> list[dict[str, str]]:
    """Return tracked paths hidden from ordinary status/diff inspection."""

    output = _git_evidence(repo, "ls-files", "-v", "-z", "--cached", "--", text=False)
    hidden: list[dict[str, str]] = []
    for record in output.split(b"\0"):
        if len(record) < 3 or record[1:2] != b" ":
            continue
        tag = record[:1]
        assume_unchanged = tag.isalpha() and tag == tag.lower()
        skip_worktree = tag.upper() == b"S"
        if assume_unchanged or skip_worktree:
            flags: list[str] = []
            if assume_unchanged:
                flags.append("assume-unchanged")
            if skip_worktree:
                flags.append("skip-worktree")
            hidden.append(
                {
                    "path": record[2:].decode("utf-8", "replace"),
                    "flags": ",".join(flags),
                    "tag": tag.decode("ascii", "replace"),
                }
            )
    return hidden


def _content_filter_entries(
    repo: Path, source: str | None = None
) -> list[dict[str, str]]:
    """Return tracked paths whose Git attributes select a content filter."""

    if source:
        tracked_raw = _git_evidence(
            repo, "ls-tree", "-r", "-z", "--name-only", source, text=False
        )
    else:
        tracked_raw = _git_evidence(
            repo, "ls-files", "-z", "--cached", "--", text=False
        )
    tracked = [os.fsdecode(item) for item in tracked_raw.split(b"\0") if item]
    filtered: list[dict[str, str]] = []
    for offset in range(0, len(tracked), 128):
        batch = tracked[offset : offset + 128]
        source_arguments = ["--source", source] if source else []
        output = _git_evidence(
            repo,
            "check-attr",
            "-z",
            *source_arguments,
            "filter",
            "--",
            *batch,
            text=False,
        )
        fields = output.split(b"\0")
        for index in range(0, len(fields) - 2, 3):
            path_bytes, attribute, value = fields[index : index + 3]
            if attribute != b"filter" or value in {b"unspecified", b"unset"}:
                continue
            filtered.append(
                {
                    "path": path_bytes.decode("utf-8", "replace"),
                    "filter": value.decode("utf-8", "replace"),
                }
            )
    return filtered


def _assert_tree_checkout_supported(repo: Path, source: str) -> None:
    filtered = _content_filter_entries(repo, source)
    if filtered:
        raise FlowError(
            "CONTENT_FILTER_UNSUPPORTED",
            "target tree uses Git content filters that can execute during checkout",
            details={
                "repository": str(repo.resolve(strict=False)),
                "source": source,
                "entries": filtered,
                "hint": "remove filter attributes before materializing a worktree",
            },
        )


def _assert_no_hidden_index_entries(repo: Path) -> None:
    hidden = _hidden_index_entries(repo)
    if hidden:
        raise FlowError(
            "HIDDEN_INDEX_FLAGS",
            "tracked paths hidden by index flags cannot be used as complete evidence",
            details={
                "repository": str(repo.resolve(strict=False)),
                "entries": hidden,
                "hint": (
                    "clear assume-unchanged/skip-worktree flags and use a full "
                    "non-sparse checkout before continuing"
                ),
            },
        )


def _prefixed_evidence_path(prefix: str, path: str) -> str:
    return f"{prefix}/{path}" if prefix else path


def _assert_evidence_supported(repo: Path) -> None:
    evidence_root = repo.resolve(strict=True)
    visited: set[Path] = set()

    def visit(current: Path, prefix: str) -> None:
        resolved = current.resolve(strict=True)
        if resolved in visited:
            return
        visited.add(resolved)
        hidden = _hidden_index_entries(resolved)
        if hidden:
            for entry in hidden:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "HIDDEN_INDEX_FLAGS",
                "tracked paths hidden by index flags cannot be used as complete evidence",
                details={
                    "repository": str(evidence_root),
                    "entries": hidden,
                    "hint": (
                        "clear assume-unchanged/skip-worktree flags in every "
                        "initialized submodule and use a full non-sparse checkout"
                    ),
                },
            )
        filtered = _content_filter_entries(resolved)
        if filtered:
            for entry in filtered:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "CONTENT_FILTER_UNSUPPORTED",
                "Git clean/process filters cannot be used as complete byte evidence",
                details={
                    "repository": str(evidence_root),
                    "entries": filtered,
                    "hint": "remove filter attributes before continuing",
                },
            )
        children = _initialized_submodule_worktrees(resolved)
        for relative, child in children:
            visit(child, _prefixed_evidence_path(prefix, relative))
        dirty = _dirty_initialized_submodules(resolved)
        if dirty:
            for entry in dirty:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "DIRTY_SUBMODULE_UNSUPPORTED",
                "dirty initialized submodules cannot be represented by complete review evidence",
                details={
                    "repository": str(evidence_root),
                    "submodules": dirty,
                    "hint": (
                        "commit each submodule change and update its parent gitlink, "
                        "or configure the submodule as a separate task repository"
                    ),
                },
            )

    visit(evidence_root, "")


def _assert_no_dirty_submodules(repo: Path) -> None:
    dirty = _dirty_initialized_submodules(repo)
    if dirty:
        raise FlowError(
            "DIRTY_SUBMODULE_UNSUPPORTED",
            "dirty initialized submodules cannot be represented by complete review evidence",
            details={
                "repository": str(repo.resolve(strict=False)),
                "submodules": dirty,
                "hint": (
                    "commit each submodule change and update its parent gitlink, "
                    "or configure the submodule as a separate task repository"
                ),
            },
        )


def _tracked_worktree_manifest(
    repo: Path, capability_profile: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Bind raw tracked filesystem bytes/types/modes, including submodules."""

    manifest: list[dict[str, Any]] = []
    visited: set[Path] = set()
    profile = capability_profile or _git_capability_profile(repo)
    case_aliases: dict[str, str] = {}

    def visit(current: Path, prefix: bytes) -> None:
        resolved = current.resolve(strict=True)
        if resolved in visited:
            return
        visited.add(resolved)
        output = _git_evidence(
            resolved, "ls-files", "--stage", "-z", "--cached", "--", text=False
        )
        for record in output.split(b"\0"):
            if not record:
                continue
            metadata, separator, path_bytes = record.partition(b"\t")
            fields = metadata.split(b" ")
            if not separator or len(fields) != 3:
                raise FlowError(
                    "GIT_EVIDENCE_MALFORMED",
                    "git ls-files returned a malformed tracked-entry record",
                    details={
                        "repository": str(resolved),
                        "record_hex": record.hex(),
                    },
                )
            index_mode, index_oid, stage = fields
            full_path = prefix + (b"/" if prefix else b"") + path_bytes
            display_path = os.fsdecode(full_path)
            filesystem = profile.get("filesystem") or {}
            case_aliasing = bool(
                profile.get("core_ignore_case")
                or not filesystem.get("case_sensitive", True)
            )
            unicode_aliasing = not filesystem.get(
                "unicode_normalization_distinct", True
            )
            if case_aliasing or unicode_aliasing:
                alias = (
                    unicodedata.normalize("NFC", display_path)
                    if unicode_aliasing
                    else display_path
                )
                if case_aliasing:
                    alias = alias.casefold()
                previous = case_aliases.get(alias)
                if previous is not None and previous != full_path.hex():
                    raise FlowError(
                        "CASE_COLLISION_UNSUPPORTED",
                        "tracked paths collide on the verified worktree filesystem",
                        details={
                            "repository": str(repo),
                            "first_path_bytes_hex": previous,
                            "second_path_bytes_hex": full_path.hex(),
                            "case_aliasing": case_aliasing,
                            "unicode_aliasing": unicode_aliasing,
                        },
                    )
                case_aliases[alias] = full_path.hex()
            target = resolved / os.fsdecode(path_bytes)
            item: dict[str, Any] = {
                "path": full_path.decode("utf-8", "replace"),
                "path_bytes_hex": full_path.hex(),
                "index_mode": index_mode.decode("ascii", "replace"),
                "index_oid": index_oid.decode("ascii", "replace"),
                "index_stage": stage.decode("ascii", "replace"),
            }
            try:
                metadata_value = target.lstat()
            except FileNotFoundError:
                item["worktree_type"] = "missing"
            else:
                item["worktree_mode"] = format(metadata_value.st_mode & 0o177777, "06o")
                item["size"] = metadata_value.st_size
                if stat.S_ISLNK(metadata_value.st_mode):
                    target_bytes = os.fsencode(os.readlink(target))
                    item["worktree_type"] = "symlink"
                    item["sha256"] = _sha256_bytes(target_bytes)
                elif stat.S_ISREG(metadata_value.st_mode):
                    item["worktree_type"] = "file"
                    item["sha256"] = _sha256_worktree_file(target)
                elif stat.S_ISDIR(metadata_value.st_mode):
                    item["worktree_type"] = "directory"
                else:
                    item["worktree_type"] = "other"
            manifest.append(item)
        for relative, child in _initialized_submodule_worktrees(resolved):
            relative_bytes = os.fsencode(relative)
            child_prefix = prefix + (b"/" if prefix else b"") + relative_bytes
            visit(child, child_prefix)

    visit(repo, b"")
    manifest.sort(
        key=lambda item: (item["path_bytes_hex"], item["index_stage"], item["index_oid"])
    )
    return manifest


def _canonical_repo(path_value: str) -> Path:
    supplied = Path(path_value).expanduser().resolve(strict=False)
    root = _git_optional(supplied, "rev-parse", "--show-toplevel")
    if not root:
        raise FlowError(
            "NOT_A_GIT_REPOSITORY",
            f"not a Git repository: {supplied}",
            details={"path": str(supplied)},
        )
    return Path(root).resolve(strict=True)


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return result or "repo"


def _repo_id(root: Path, existing: set[str]) -> str:
    base = _slug(root.name)[:40]
    candidate = base
    if candidate in existing:
        digest = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:8]
        candidate = f"{base}-{digest}"
    return candidate


def _split_lines(value: str | None) -> list[str]:
    if not value:
        return []
    return [line for line in value.splitlines() if line]


def _selector_is_path_like(selector: str) -> bool:
    return bool(
        "/" in selector
        or "\\" in selector
        or selector.startswith((".", "~"))
        or re.match(r"^[A-Za-z]:", selector)
        or selector.startswith(("//", "\\\\"))
    )


def _selector_path(selector: str) -> Path | None:
    try:
        return Path(selector).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "repository selector path could not be normalized",
            details={"selector": selector, "error": str(exc)},
        ) from exc


def _repo_by_selector(state_value: dict[str, Any], selectors: Sequence[str] | None) -> list[dict[str, Any]]:
    repositories = state_value.get("repositories", [])
    if not selectors:
        return repositories
    selected: list[dict[str, Any]] = []
    for selector in selectors:
        if _selector_is_path_like(selector):
            normalized_path = _selector_path(selector)
            matches = []
            if normalized_path is not None:
                for repo in repositories:
                    recorded_paths = {
                        str(value)
                        for value in (
                            repo.get("path"),
                            repo.get("canonical_path"),
                        )
                        if value
                    }
                    if any(
                        _same_path(normalized_path, Path(value))
                        for value in recorded_paths
                    ):
                        matches.append(repo)
        else:
            matches = [
                repo
                for repo in repositories
                if selector == repo.get("id")
                or selector == Path(str(repo.get("path", ""))).name
            ]
        matches = list(
            {
                str(repo.get("id")): repo
                for repo in matches
            }.values()
        )
        if len(matches) != 1:
            raise FlowError(
                "REPOSITORY_NOT_FOUND" if not matches else "AMBIGUOUS_REPOSITORY",
                f"repository selector must match exactly one configured repository: {selector}",
                details={"selector": selector, "matches": [repo.get("id") for repo in matches]},
            )
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def _assert_status(state_value: dict[str, Any], allowed: set[str], command: str) -> None:
    current = state_value.get("status")
    if current not in allowed:
        raise FlowError(
            "INVALID_STATE",
            f"{command} is not allowed while task is {current}",
            details={"status": current, "allowed": sorted(allowed), "command": command},
        )


def _flow(state_value: dict[str, Any]) -> str:
    value = state_value.get("flow")
    return value if value in FLOW_MODES else DEFAULT_FLOW


def _workspace_strategy(state_value: dict[str, Any]) -> str:
    workspace = state_value.get("workspace")
    value = workspace.get("strategy") if isinstance(workspace, dict) else None
    if value in WORKSPACE_STRATEGIES:
        return value
    return "in-place" if _flow(state_value) == "lite" else "worktree"


def _workflow_progress(state_value: dict[str, Any]) -> dict[str, Any]:
    flow = _flow(state_value)
    ordered = LITE_ORDERED_STATES if flow == "lite" else ORDERED_STATES
    status = str(state_value.get("status") or "INTAKE")
    progress_status = status
    resume_state: dict[str, str] | None = None
    if status == "BLOCKED":
        blocked = state_value.get("blocked")
        candidate = (
            blocked.get("from_status")
            if isinstance(blocked, dict)
            else None
        )
        if candidate in ordered:
            progress_status = candidate
            resume_state = {
                "id": candidate,
                "name": STATE_NAMES_ZH[candidate],
            }
    if progress_status in ordered:
        index = ordered.index(progress_status)
        remaining_ids = ordered[index + 1 :]
    else:
        remaining_ids = []
    strategy = _workspace_strategy(state_value)
    return {
        "flow": {
            "id": flow,
            "name": FLOW_NAMES_ZH[flow],
        },
        "workspace_strategy": {
            "id": strategy,
            "name": WORKSPACE_STRATEGY_NAMES_ZH[strategy],
        },
        "current": {
            "id": status,
            "name": STATE_NAMES_ZH.get(status, status),
        },
        "resume_state": resume_state,
        "remaining": [
            {"id": state, "name": STATE_NAMES_ZH[state]}
            for state in remaining_ids
        ],
    }


def _assert_flow(state_value: dict[str, Any], required: str, command: str) -> None:
    actual = _flow(state_value)
    if actual != required:
        raise FlowError(
            "FLOW_MISMATCH",
            f"{command} is not part of the {actual} flow",
            details={"flow": actual, "required_flow": required, "command": command},
        )


def _operation_state(repo: Path) -> dict[str, bool]:
    git_dir_text = _git(repo, "rev-parse", "--absolute-git-dir")
    git_dir = Path(git_dir_text)
    return {
        "merge": (git_dir / "MERGE_HEAD").exists(),
        "rebase": (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists(),
        "cherry_pick": (git_dir / "CHERRY_PICK_HEAD").exists(),
        "revert": (git_dir / "REVERT_HEAD").exists(),
        "bisect": (git_dir / "BISECT_LOG").exists(),
        "sequencer": (git_dir / "sequencer").exists(),
    }


def _ref_exists(repo: Path, ref: str) -> bool:
    result = _run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", ref], check=False)
    return result.returncode == 0


def _default_remote(repo: Path, branch: str | None) -> str | None:
    if branch:
        configured = _git_optional(repo, "config", "--get", f"branch.{branch}.remote")
        if configured and configured != ".":
            return configured
    for key in ("remote.pushDefault", "checkout.defaultRemote"):
        configured = _git_optional(repo, "config", "--get", key)
        if configured:
            return configured
    remotes = _split_lines(_git_optional(repo, "remote"))
    if "origin" in remotes:
        return "origin"
    return remotes[0] if len(remotes) == 1 else None


def _default_base(repo: Path, remote: str | None, branch: str | None, protected: Sequence[str]) -> str | None:
    if remote:
        symbolic = _git_optional(repo, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
        if symbolic and symbolic.startswith(f"{remote}/"):
            return symbolic[len(remote) + 1 :]
    for candidate in protected:
        if remote and _ref_exists(repo, f"refs/remotes/{remote}/{candidate}"):
            return candidate
        if _ref_exists(repo, f"refs/heads/{candidate}"):
            return candidate
    # A feature branch is not a safe implicit baseline.  Repositories with a
    # non-standard default branch must expose remote/HEAD or pass --base.
    return branch if branch in protected else None


def _remote_url(repo: Path, remote: str | None) -> str | None:
    if not remote:
        return None
    return _git_optional(repo, "remote", "get-url", "--", remote)


def _remote_url_evidence(value: str | None) -> dict[str, str | None]:
    return {
        "remote_url": _redact_sensitive_text(value) if value else None,
        "remote_url_sha256": _sensitive_value_sha256(value),
    }


def _live_approved_remote_url(
    repo: Path, repo_id: str, preflight: dict[str, Any]
) -> str | None:
    remote = preflight.get("remote")
    actual_url = _remote_url(repo, remote)
    recorded_digest = preflight.get("remote_url_sha256")
    actual_digest = _sensitive_value_sha256(actual_url)
    if actual_digest != recorded_digest:
        raise FlowError(
            "REMOTE_URL_CHANGED",
            f"remote URL changed after preflight approval: {repo_id}",
            details={
                "repository_id": repo_id,
                "remote": remote,
                "recorded_url": preflight.get("remote_url"),
                "actual_url": (
                    _redact_sensitive_text(actual_url)
                    if actual_url
                    else None
                ),
                "recorded_url_sha256": recorded_digest,
                "actual_url_sha256": actual_digest,
            },
        )
    return actual_url


def _approved_fetch_refspec(remote: str | None, base_branch: str | None) -> str | None:
    if not remote or not base_branch:
        return None
    return f"+refs/heads/{base_branch}:refs/remotes/{remote}/{base_branch}"


def _baseline_source_ref(remote: str | None, base_branch: str | None) -> str | None:
    if not base_branch:
        return None
    return (
        f"refs/remotes/{remote}/{base_branch}"
        if remote
        else f"refs/heads/{base_branch}"
    )


def _preflight_repo(
    repo_record: dict[str, Any],
    remote_override: str | None,
    base_override: str | None,
    *,
    capture_fingerprint: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_record["path"])
    _assert_evidence_supported(repo)
    repository_root = Path(
        _git_evidence(repo, "rev-parse", "--show-toplevel")
    ).resolve(strict=True)
    git_dir = _git_evidence_path(repo, "--git-dir")
    git_common_dir = _git_evidence_path(repo, "--git-common-dir")
    branch = _git_optional(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    head_sha = _git(repo, "rev-parse", "HEAD")
    remote = remote_override or _default_remote(repo, branch)
    base_branch = base_override or _default_base(
        repo, remote, branch, repo_record.get("protected_branches", DEFAULT_PROTECTED_BRANCHES)
    )
    if remote and (
        remote.startswith("-")
        or _run(
            ["git", "check-ref-format", f"refs/remotes/{remote}/base"],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "INVALID_REMOTE",
            "remote name is not safe for deterministic fetch operations",
            details={"repository": str(repo), "remote": remote},
        )
    if base_branch and (
        _run(
            ["git", "check-ref-format", "--branch", base_branch],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "INVALID_BASE_BRANCH",
            "base branch name is invalid",
            details={"repository": str(repo), "base_branch": base_branch},
        )
    base_candidate_ref = _baseline_source_ref(remote, base_branch)
    base_candidate_sha = (
        _git_optional(
            repo, "rev-parse", "--verify", f"{base_candidate_ref}^{{commit}}"
        )
        if base_candidate_ref
        else None
    )
    staged_raw = _git_diff(
        repo,
        "--cached",
        "--name-only",
        "-z",
        "--",
        text=False,
    )
    unstaged_raw = _git_diff(
        repo,
        "--name-only",
        "-z",
        "--",
        text=False,
    )
    untracked_raw = _git_evidence(
        repo,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        text=False,
    )
    conflicts_raw = _git_diff(
        repo,
        "--name-only",
        "--diff-filter=U",
        "-z",
        "--",
        text=False,
    )
    staged = [
        os.fsdecode(item) for item in staged_raw.split(b"\0") if item
    ]
    unstaged = [
        os.fsdecode(item) for item in unstaged_raw.split(b"\0") if item
    ]
    untracked = [
        os.fsdecode(item) for item in untracked_raw.split(b"\0") if item
    ]
    conflicts = [
        os.fsdecode(item) for item in conflicts_raw.split(b"\0") if item
    ]
    operations = _operation_state(repo)
    blockers: list[str] = []
    if branch is None:
        blockers.append("detached_head")
    if conflicts:
        blockers.append("unmerged_conflicts")
    blockers.extend(f"operation_in_progress:{name}" for name, active in operations.items() if active)
    if not base_branch:
        blockers.append("base_branch_unresolved")
    if remote and remote not in _split_lines(_git_optional(repo, "remote")):
        blockers.append("remote_not_found")
    remote_url = _remote_url(repo, remote)
    evidence: dict[str, Any] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "checked_at": utc_now(),
        "repository_root": str(repository_root),
        "repository_path_identity": _serializable_path_identity(repo),
        "repository_root_identity": _serializable_path_identity(
            repository_root
        ),
        "git_dir": str(git_dir),
        "git_dir_identity": _serializable_path_identity(git_dir),
        "git_common_dir": str(git_common_dir),
        "git_common_dir_identity": _serializable_path_identity(
            git_common_dir
        ),
        "branch": branch,
        "head_sha": head_sha,
        "remote": remote,
        **_remote_url_evidence(remote_url),
        "base_branch": base_branch,
        "base_candidate_ref": base_candidate_ref,
        "base_candidate_sha": base_candidate_sha,
        "fetch_refspec": _approved_fetch_refspec(remote, base_branch),
        "staged": staged,
        "staged_paths_sha256": _sha256_bytes(staged_raw),
        "unstaged": unstaged,
        "unstaged_paths_sha256": _sha256_bytes(unstaged_raw),
        "untracked": untracked,
        "untracked_paths_sha256": _sha256_bytes(untracked_raw),
        "conflicts": conflicts,
        "conflict_paths_sha256": _sha256_bytes(conflicts_raw),
        "operations": operations,
        "dirty": bool(staged or unstaged or untracked or conflicts),
        "blockers": blockers,
        "ready": not blockers,
        "evidence_complete": capture_fingerprint,
        "capture_phase": (
            "confirm" if capture_fingerprint else "preview"
        ),
    }
    if capture_fingerprint:
        fingerprint = _fingerprint_repo(repo)
        evidence.update(
            {
                "worktree_fingerprint_sha256": fingerprint["sha256"],
                "capability_profile": fingerprint["capability_profile"],
                "capability_profile_sha256": fingerprint[
                    "capability_profile_sha256"
                ],
                "tracked_worktree_manifest_sha256": fingerprint[
                    "tracked_worktree_manifest_sha256"
                ],
            }
        )
    return evidence


def _baseline_ref(repo: Path, remote: str | None, base_branch: str) -> tuple[str, str]:
    if remote:
        # Never label a local branch as a remote baseline.  If the tracking
        # ref is absent, the caller must explicitly fetch (behind its gate) or
        # fix the remote rather than silently pinning stale local state.
        candidates = [f"refs/remotes/{remote}/{base_branch}"]
    else:
        candidates = [f"refs/heads/{base_branch}", base_branch]
    for candidate in candidates:
        sha = _git_optional(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}")
        if sha:
            return candidate, sha
    raise FlowError(
        "BASE_REF_NOT_FOUND",
        f"could not resolve base branch {base_branch}",
        details={
            "repository": str(repo),
            "remote": remote,
            "base_branch": base_branch,
            "required_ref": f"refs/remotes/{remote}/{base_branch}" if remote else f"refs/heads/{base_branch}",
            "hint": "approve baseline-fetch and rerun baseline --fetch" if remote else "pass --base during preflight",
        },
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_worktree_file(path: Path) -> str:
    """Hash one regular worktree file without following an identity race."""

    try:
        before = path.lstat()
    except OSError as exc:
        raise FlowError(
            "WORKTREE_CHANGED",
            "worktree file disappeared before byte evidence was captured",
            details={"path": str(path)},
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise FlowError(
            "WORKTREE_CHANGED",
            "worktree evidence path is no longer a regular file",
            details={
                "path": str(path),
                "mode": format(before.st_mode & 0o177777, "06o"),
            },
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FlowError(
            "WORKTREE_CHANGED",
            "worktree file identity changed before it was opened",
            details={"path": str(path)},
        ) from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise FlowError(
                "WORKTREE_CHANGED",
                "opened worktree file does not match its observed identity",
                details={"path": str(path)},
            )
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after_open = os.fstat(descriptor)
        try:
            after_path = path.lstat()
        except OSError as exc:
            raise FlowError(
                "WORKTREE_CHANGED",
                "worktree file disappeared while bytes were captured",
                details={"path": str(path)},
            ) from exc
        signatures = {
            (
                item.st_dev,
                item.st_ino,
                item.st_mode,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )
            for item in (before, opened, after_open, after_path)
        }
        if len(signatures) != 1:
            raise FlowError(
                "WORKTREE_CHANGED",
                "worktree file identity or metadata changed during capture",
                details={"path": str(path)},
            )
    except FlowError:
        raise
    except OSError as exc:
        raise FlowError(
            "WORKTREE_CHANGED",
            "worktree file could not be read as stable byte evidence",
            details={"path": str(path)},
        ) from exc
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _hash_artifact(path: Path) -> dict[str, Any]:
    """Hash a file or a directory without following directory symlinks.

    Directory hashes are a canonical JSONL manifest over sorted relative
    paths.  Entries bind path, type, file content, or symlink target; empty
    directories therefore remain significant too.
    """

    if path.is_file():
        size = path.stat().st_size
        return {
            "artifact_type": "file",
            "sha256": _sha256_file(path),
            "size": size,
            "file_count": 1,
            "total_size": size,
        }
    if not path.is_dir():
        raise FlowError("INVALID_ARTIFACT", f"artifact must be a regular file or directory: {path}")

    entries: list[dict[str, Any]] = [{"path": ".", "type": "directory"}]
    file_count = 0
    total_size = 0

    def visit(directory: Path, relative_directory: Path) -> None:
        nonlocal file_count, total_size
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise FlowError(
                "ARTIFACT_READ_FAILED",
                f"could not enumerate artifact directory: {directory}",
                details={"path": str(directory), "error": str(exc)},
            ) from exc
        for child in children:
            relative = (relative_directory / child.name).as_posix()
            try:
                if child.is_symlink():
                    target = os.readlink(child.path)
                    entries.append({"path": relative, "type": "symlink", "target": target})
                    file_count += 1
                elif child.is_dir(follow_symlinks=False):
                    entries.append({"path": relative, "type": "directory"})
                    visit(Path(child.path), relative_directory / child.name)
                elif child.is_file(follow_symlinks=False):
                    child_path = Path(child.path)
                    size = child.stat(follow_symlinks=False).st_size
                    entries.append(
                        {
                            "path": relative,
                            "type": "file",
                            "size": size,
                            "sha256": _sha256_file(child_path),
                        }
                    )
                    file_count += 1
                    total_size += size
                else:
                    entries.append({"path": relative, "type": "other"})
                    file_count += 1
            except OSError as exc:
                raise FlowError(
                    "ARTIFACT_READ_FAILED",
                    f"could not read artifact entry: {child.path}",
                    details={"path": child.path, "error": str(exc)},
                ) from exc

    visit(path, Path())
    manifest = b"".join(
        (
            json.dumps(
                entry,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8", "backslashreplace")
        for entry in entries
    )
    return {
        "artifact_type": "directory",
        "sha256": _sha256_bytes(manifest),
        "size": total_size,
        "file_count": file_count,
        "total_size": total_size,
        "manifest_entry_count": len(entries),
    }


def _parse_review_report_verdict(path: Path) -> str:
    if not path.is_file():
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "review-report must be a UTF-8 text file containing one 'Verdict: VALUE' line",
            details={"path": str(path)},
        )
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "review-report must be readable UTF-8 text",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    nonempty_lines = [line for line in body.splitlines() if line.strip()]
    first_match = (
        REVIEW_VERDICT_RE.fullmatch(nonempty_lines[0]) if nonempty_lines else None
    )
    verdict_lines = [
        line for line in body.splitlines() if line.lstrip().startswith("Verdict:")
    ]
    if first_match is None or len(verdict_lines) != 1:
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "the first non-empty review-report line must be exactly 'Verdict: PASS|CONDITIONAL|FAIL', with no second Verdict line",
            details={
                "path": str(path),
                "verdict_field_count": len(verdict_lines),
                "first_nonempty_line": nonempty_lines[0] if nonempty_lines else None,
            },
        )
    return first_match.group(1)


def _latest_artifact(state_value: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next(
        (artifact for artifact in reversed(state_value.get("artifacts", [])) if artifact.get("kind") == kind),
        None,
    )


def _assert_artifact_unchanged(artifact: dict[str, Any]) -> None:
    _require_current_evidence(artifact, "artifact")
    path_value = artifact.get("path")
    if not path_value:
        raise FlowError(
            "ARTIFACT_CHANGED",
            "recorded artifact has no verifiable path",
            details={"artifact_id": artifact.get("artifact_id")},
        )
    path = Path(path_value)
    if not _recorded_path_matches(
        artifact.get("path_identity"), path_value, path
    ):
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact path identity changed: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
            },
        )
    try:
        current = _hash_artifact(path)
    except (FlowError, OSError) as exc:
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact is missing or unreadable: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
                "recorded_sha256": artifact.get("sha256"),
                "error": str(exc),
            },
        ) from exc
    if current.get("sha256") != artifact.get("sha256"):
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact changed on disk: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
                "recorded_sha256": artifact.get("sha256"),
                "current_sha256": current.get("sha256"),
            },
        )


def _require_gate(state_value: dict[str, Any], gate: str) -> dict[str, Any]:
    approval = state_value.get("approvals", {}).get(gate)
    if not approval:
        raise FlowError(
            "APPROVAL_REQUIRED",
            f"the {gate} gate must be approved first",
            details={"gate": gate},
        )
    return approval


def _require_gate_for_latest_artifact(
    state_value: dict[str, Any], gate: str, artifact_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = _latest_artifact(state_value, artifact_kind)
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            f"the {gate} gate requires a recorded {artifact_kind} artifact",
            details={"gate": gate, "artifact_kind": artifact_kind},
        )
    _assert_artifact_unchanged(artifact)
    approval = _require_gate(state_value, gate)
    if approval.get("artifact_sha256") != artifact.get("sha256"):
        raise FlowError(
            "STALE_APPROVAL",
            f"the {gate} approval must bind the latest {artifact_kind} artifact",
            details={
                "gate": gate,
                "artifact_kind": artifact_kind,
                "expected_sha256": artifact.get("sha256"),
                "approved_sha256": approval.get("artifact_sha256"),
            },
        )
    return approval, artifact


def _require_current_impact(state_value: dict[str, Any]) -> dict[str, Any]:
    artifact = _latest_artifact(state_value, "impact")
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            "route selection requires a current impact artifact",
            details={"artifact_kind": "impact"},
        )
    _assert_artifact_unchanged(artifact)
    metadata = artifact.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise FlowError(
            "IMPACT_ANALYSIS_INVALID",
            "latest impact artifact metadata must be an object",
            details={"artifact_id": artifact.get("artifact_id")},
        )
    if _uses_confirmation_contract(state_value):
        contract_version = metadata.get(
            "impact_analysis_contract_version"
        )
        if contract_version != IMPACT_ANALYSIS_CONTRACT_VERSION:
            raise FlowError(
                "IMPACT_ANALYSIS_INVALID",
                "latest impact artifact has no supported controller contract",
                details={
                    "artifact_id": artifact.get("artifact_id"),
                    "expected_contract_version": (
                        IMPACT_ANALYSIS_CONTRACT_VERSION
                    ),
                    "recorded_contract_version": contract_version,
                },
            )
        canonical = _impact_analysis_canonical_projection(
            metadata,
            allow_controller_fields=True,
        )
        validated = _validate_impact_analysis_contract(
            state_value,
            canonical,
        )
        recorded_digest = metadata.get("impact_analysis_sha256")
        current_digest = validated["impact_analysis_sha256"]
        if recorded_digest != current_digest:
            raise FlowError(
                "STALE_IMPACT",
                "latest impact analysis metadata digest is stale",
                details={
                    "artifact_id": artifact.get("artifact_id"),
                    "recorded_impact_analysis_sha256": recorded_digest,
                    "current_impact_analysis_sha256": current_digest,
                },
            )
    expected = _index_provenance_sha256(state_value)
    recorded = metadata.get("index_provenance_sha256")
    expected_generation = int(state_value.get("impact_generation", 0))
    recorded_generation = metadata.get("impact_generation")
    if recorded != expected or recorded_generation != expected_generation:
        raise FlowError(
            "STALE_IMPACT",
            "latest impact artifact does not describe the current impact epoch and all-repository index provenance",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "expected_index_provenance_sha256": expected,
                "recorded_index_provenance_sha256": recorded,
                "expected_impact_generation": expected_generation,
                "recorded_impact_generation": recorded_generation,
            },
        )
    return artifact


def _require_current_route_selection(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    impact = _require_current_impact(state_value)
    route = state_value.get("route")
    if not isinstance(route, dict) or route.get("value") not in {"direct", "openspec"}:
        raise FlowError("ROUTE_REQUIRED", "a route must be selected for the current impact")
    impact_contract_matches = (
        not _uses_confirmation_contract(state_value)
        or route.get("impact_analysis_sha256")
        == (impact.get("metadata") or {}).get("impact_analysis_sha256")
    )
    if (
        route.get("impact_artifact_id") != impact.get("artifact_id")
        or route.get("impact_sha256") != impact.get("sha256")
        or route.get("index_provenance_sha256")
        != (impact.get("metadata") or {}).get("index_provenance_sha256")
        or route.get("impact_generation")
        != (impact.get("metadata") or {}).get("impact_generation")
        or not impact_contract_matches
    ):
        raise FlowError(
            "STALE_ROUTE_SELECTION",
            "route selection is not bound to the latest current impact artifact",
        )
    return route, impact


def _require_route_gate(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, impact = _require_current_route_selection(state_value)
    approval, approved_impact = _require_gate_for_latest_artifact(
        state_value, "route", "impact"
    )
    impact_contract_matches = (
        not _uses_confirmation_contract(state_value)
        or approval.get("impact_analysis_sha256")
        == (impact.get("metadata") or {}).get("impact_analysis_sha256")
    )
    if (
        approval.get("artifact_id") != impact.get("artifact_id")
        or approval.get("index_provenance_sha256")
        != (impact.get("metadata") or {}).get("index_provenance_sha256")
        or approval.get("impact_generation")
        != (impact.get("metadata") or {}).get("impact_generation")
        or not impact_contract_matches
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "route approval is not bound to the current impact record and index provenance",
        )
    return approval, approved_impact


def _latest_review_snapshot(state_value: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = state_value.get("review_snapshots", [])
    return snapshots[-1] if snapshots else None


def _require_review_report_for_latest_snapshot(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _latest_review_snapshot(state_value)
    if not snapshot:
        raise FlowError("CURRENT_REVIEW_REQUIRED", "a review snapshot is required")
    report = _latest_artifact(state_value, "review-report")
    if not report:
        raise FlowError("ARTIFACT_REQUIRED", "the review gate requires a review-report artifact")
    _assert_artifact_unchanged(report)
    body_verdict = _parse_review_report_verdict(Path(report["path"]))
    metadata_verdict = (report.get("metadata") or {}).get("verdict")
    if body_verdict != metadata_verdict:
        raise FlowError(
            "REVIEW_VERDICT_MISMATCH",
            "review report Verdict field no longer matches its recorded metadata",
            details={
                "body_verdict": body_verdict,
                "metadata_verdict": metadata_verdict,
                "path": report.get("path"),
            },
        )
    bound_snapshot = (report.get("metadata") or {}).get("review_snapshot_sha256")
    if bound_snapshot != snapshot.get("sha256"):
        raise FlowError(
            "STALE_REVIEW_REPORT",
            "the latest review report is not bound to the latest review snapshot",
            details={
                "report_sha256": report.get("sha256"),
                "expected_review_snapshot_sha256": snapshot.get("sha256"),
                "bound_review_snapshot_sha256": bound_snapshot,
            },
        )
    return report, snapshot


def _require_review_gate(state_value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    report, snapshot = _require_review_report_for_latest_snapshot(state_value)
    verdict = (report.get("metadata") or {}).get("verdict")
    if verdict not in {"PASS", "CONDITIONAL", "FAIL"}:
        raise FlowError(
            "INVALID_REVIEW_VERDICT",
            "latest review report has no valid structured verdict",
            details={"verdict": verdict},
        )
    if verdict == "FAIL":
        raise FlowError(
            "REVIEW_VERDICT_FAILED",
            "a FAIL review report cannot pass the final review gate",
        )
    approval = _require_gate(state_value, "review")
    if (
        approval.get("artifact_sha256") != report.get("sha256")
        or approval.get("review_snapshot_sha256") != snapshot.get("sha256")
        or approval.get("review_verdict") != verdict
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "the review approval must bind the latest report and review snapshot",
            details={
                "expected_report_sha256": report.get("sha256"),
                "approved_report_sha256": approval.get("artifact_sha256"),
                "expected_review_snapshot_sha256": snapshot.get("sha256"),
                "approved_review_snapshot_sha256": approval.get("review_snapshot_sha256"),
                "expected_verdict": verdict,
                "approved_verdict": approval.get("review_verdict"),
            },
        )
    if verdict == "CONDITIONAL" and approval.get("conditional_accepted") is not True:
        raise FlowError(
            "CONDITIONAL_ACCEPTANCE_REQUIRED",
            "the CONDITIONAL review verdict lacks explicit acceptance",
        )
    return approval, report


def _fingerprint_repo_once(
    repo: Path,
    *,
    filesystem_capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_repo = repo.resolve(strict=True)
    capability_profile = _git_capability_profile(
        repo,
        filesystem_capabilities=filesystem_capabilities,
    )
    _assert_evidence_supported(repo)
    head = _git_evidence(repo, "rev-parse", "HEAD")
    cached = _git_diff(
        repo, "--binary", "--full-index", "--cached", "--", text=False
    )
    unstaged = _git_diff(repo, "--binary", "--full-index", "--", text=False)
    untracked_output = _git_evidence(
        repo,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        text=False,
    )
    untracked_paths = [item for item in untracked_output.split(b"\0") if item]
    untracked: list[dict[str, Any]] = []
    for relative_bytes in sorted(untracked_paths):
        relative = relative_bytes.decode("utf-8", "replace")
        target = repo / os.fsdecode(relative_bytes)
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            raise FlowError(
                "WORKTREE_CHANGED",
                f"untracked path disappeared while creating a snapshot: {relative}",
                details={"repository": str(repo), "path": relative},
            )
        if stat.S_ISLNK(metadata.st_mode):
            content_hash = _sha256_bytes(os.readlink(target).encode("utf-8", "surrogateescape"))
            item_type = "symlink"
        elif stat.S_ISREG(metadata.st_mode):
            content_hash = _sha256_worktree_file(target)
            item_type = "file"
        else:
            raise FlowError(
                "UNTRACKED_TYPE_UNSUPPORTED",
                "untracked review evidence supports only regular files and symlinks",
                details={
                    "repository": str(repo),
                    "path": relative,
                    "mode": format(metadata.st_mode & 0o177777, "06o"),
                },
            )
        untracked.append(
            {
                "path": relative,
                "path_bytes_hex": relative_bytes.hex(),
                "type": item_type,
                "size": metadata.st_size,
                "sha256": content_hash,
            }
        )
    tracked_worktree = _tracked_worktree_manifest(repo, capability_profile)
    payload = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(resolved_repo),
        "root": _git_evidence(repo, "rev-parse", "--show-toplevel"),
        "branch": _git_evidence_optional(
            repo, "symbolic-ref", "--quiet", "--short", "HEAD"
        ),
        "git_dir": str(_git_evidence_path(repo, "--git-dir")),
        "git_common_dir": str(_git_evidence_path(repo, "--git-common-dir")),
        "linked_worktree": _git_evidence_path(
            repo, "--git-dir"
        )
        != _git_evidence_path(repo, "--git-common-dir"),
        "head_sha": head,
        "cached_sha256": _sha256_bytes(cached),
        "unstaged_sha256": _sha256_bytes(unstaged),
        "capability_profile": capability_profile,
        "capability_profile_sha256": capability_profile["sha256"],
        "tracked_worktree": tracked_worktree,
        "tracked_worktree_manifest_sha256": _sha256_bytes(
            json.dumps(
                tracked_worktree, sort_keys=True, separators=(",", ":")
            ).encode("utf-8", "backslashreplace")
        ),
        "untracked": untracked,
    }
    payload["sha256"] = _fingerprint_payload_sha256(payload)
    return payload


def _fingerprint_payload_sha256(fingerprint: dict[str, Any]) -> str:
    payload = dict(fingerprint)
    payload.pop("sha256", None)
    return _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8", "backslashreplace"
        )
    )


def _fingerprint_repo(repo: Path) -> dict[str, Any]:
    """Return a complete fingerprint only after two identical observations."""

    # Filesystem capabilities are stable for the duration of one capture.
    # Probe them once, while still rebuilding the effective Git profile and
    # all repository byte evidence independently in both observations.
    filesystem_capabilities = _probe_worktree_capabilities(
        repo.resolve(strict=True)
    )
    first = _fingerprint_repo_once(
        repo,
        filesystem_capabilities=filesystem_capabilities,
    )
    second = _fingerprint_repo_once(
        repo,
        filesystem_capabilities=filesystem_capabilities,
    )
    if first.get("sha256") != second.get("sha256"):
        raise FlowError(
            "WORKTREE_CHANGED",
            "repository changed while complete byte evidence was being captured",
            details={
                "repository": str(repo.resolve(strict=False)),
                "first_sha256": first.get("sha256"),
                "second_sha256": second.get("sha256"),
            },
        )
    return second


def _decode_risk_paths(raw: bytes, *, source: str) -> list[str]:
    paths: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            decoded = item.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise FlowError(
                "RISK_EVIDENCE_INVALID",
                "a changed Git path is not valid UTF-8",
                details={"source": source, "path_bytes_hex": item.hex()},
            ) from exc
        paths.append(
            _normalize_git_evidence_path(
                decoded, f"{source} changed path", code="RISK_EVIDENCE_INVALID"
            )
        )
    return paths


def _decode_gitlink_paths(raw: bytes, *, source: str) -> set[str]:
    paths: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, separator, path_bytes = record.partition(b"\t")
        if not separator or not header.startswith(b"160000 "):
            continue
        try:
            decoded = path_bytes.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise FlowError(
                "RISK_EVIDENCE_INVALID",
                "a Git link path is not valid UTF-8",
                details={
                    "source": source,
                    "path_bytes_hex": path_bytes.hex(),
                },
            ) from exc
        paths.add(
            _normalize_git_evidence_path(
                decoded,
                f"{source} Git link path",
                code="RISK_EVIDENCE_INVALID",
            )
        )
    return paths


def _capture_lite_change_assessment(
    state_value: dict[str, Any],
    data_dir: str | os.PathLike[str] | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Classify the live lite diff against its immutable start declaration."""

    evaluated_at = utc_now()
    reasons: list[dict[str, Any]] = []
    changed_paths: list[str] = []
    fingerprint_sha256: str | None = None
    current_head_sha: str | None = None
    preflight_head_sha: str | None = None
    current_policy: dict[str, Any] | None = None
    captured_fingerprints: dict[str, dict[str, Any]] = {}
    risk = state_value.get("risk_assessment")
    repositories = state_value.get("repositories")
    try:
        if (
            state_value.get("schema_version") != V4_TASK_SCHEMA_VERSION
            or not isinstance(risk, dict)
        ):
            raise FlowError(
                "RISK_CONTRACT_MISSING",
                "lite task does not contain its current V4 risk contract",
            )
        if not isinstance(repositories, list) or len(repositories) != 1:
            raise FlowError(
                "RISK_EVIDENCE_INVALID",
                "lite risk assessment requires exactly one repository",
            )
        repo_record = repositories[0]
        preflight = repo_record.get("preflight")
        if not isinstance(preflight, dict):
            raise FlowError(
                "RISK_EVIDENCE_INVALID",
                "lite risk assessment requires current preflight evidence",
            )
        _require_current_evidence(
            preflight, f"preflight:{repo_record.get('id')}"
        )
        preflight_head_sha = preflight.get("head_sha")
        if not isinstance(preflight_head_sha, str):
            raise FlowError(
                "RISK_EVIDENCE_INVALID",
                "preflight evidence has no HEAD anchor",
            )
        repo = Path(repo_record["path"])
        filesystem_capabilities = _probe_worktree_capabilities(
            repo.resolve(strict=True)
        )
        first = _fingerprint_repo_once(
            repo,
            filesystem_capabilities=filesystem_capabilities,
        )
        committed_raw = _git_diff(
            repo,
            "--no-renames",
            "--name-only",
            "-z",
            preflight_head_sha,
            "HEAD",
            "--",
            text=False,
        )
        staged_raw = _git_diff(
            repo,
            "--cached",
            "--no-renames",
            "--name-only",
            "-z",
            "--",
            text=False,
        )
        unstaged_raw = _git_diff(
            repo, "--no-renames", "--name-only", "-z", "--", text=False
        )
        untracked_raw = _git_evidence(
            repo,
            "ls-files",
            "-z",
            "--others",
            "--exclude-standard",
            "--",
            text=False,
        )
        provisional_paths = sorted(
            {
                *(_decode_risk_paths(committed_raw, source="committed")),
                *(_decode_risk_paths(staged_raw, source="staged")),
                *(_decode_risk_paths(unstaged_raw, source="unstaged")),
                *(_decode_risk_paths(untracked_raw, source="untracked")),
            }
        )
        current_gitlinks_raw = (
            _git_evidence(
                repo,
                "ls-files",
                "--stage",
                "-z",
                "--",
                *provisional_paths,
                text=False,
            )
            if provisional_paths
            else b""
        )
        baseline_gitlinks_raw = (
            _git_evidence(
                repo,
                "ls-tree",
                "-z",
                preflight_head_sha,
                "--",
                *provisional_paths,
                text=False,
            )
            if provisional_paths
            else b""
        )
        second = _fingerprint_repo_once(
            repo,
            filesystem_capabilities=filesystem_capabilities,
        )
        if first.get("sha256") != second.get("sha256"):
            raise FlowError(
                "WORKTREE_CHANGED",
                "repository changed while lite risk evidence was captured",
                details={
                    "first_sha256": first.get("sha256"),
                    "second_sha256": second.get("sha256"),
                },
            )
        fingerprint_sha256 = second.get("sha256")
        captured_fingerprints[repo_record["id"]] = second
        current_head_sha = second.get("head_sha")
        changed_paths = provisional_paths
        gitlink_paths = (
            _decode_gitlink_paths(
                current_gitlinks_raw, source="current-index"
            )
            | _decode_gitlink_paths(
                baseline_gitlinks_raw, source="preflight-tree"
            )
        )
        stored_policy = _normalize_risk_policy(risk.get("policy"))
        live_policy = load_config(data_dir)["risk_policy"]
        current_policy = _normalize_risk_policy(
            {
                "schema": "dev-flow-risk-policy/v1",
                "protected_paths": [
                    *stored_policy["protected_paths"],
                    *live_policy["protected_paths"],
                ],
            }
        )
        declared = set(risk.get("target_paths") or [])
        for relative_path in changed_paths:
            if relative_path in gitlink_paths:
                reasons.append(
                    {
                        "code": "gitlink_or_submodule",
                        "path": relative_path,
                    }
                )
            pattern = _protected_path_match(relative_path, current_policy)
            if pattern is not None:
                reasons.append(
                    {
                        "code": "protected_path",
                        "path": relative_path,
                        "pattern": pattern,
                    }
                )
            if relative_path not in declared:
                reasons.append(
                    {
                        "code": "undeclared_changed_path",
                        "path": relative_path,
                    }
                )
    except (FlowError, OSError, UnicodeError, ValueError) as exc:
        code = exc.code if isinstance(exc, FlowError) else type(exc).__name__
        safe_message = _redact_sensitive_value(str(exc))
        reasons.append(
            {
                "code": "risk_evidence_unknown",
                "cause": code,
                "message": (
                    safe_message
                    if isinstance(safe_message, str)
                    else "risk evidence unavailable"
                ),
            }
        )
    decision = "requires_full" if reasons else "safe"
    assessment = {
        "schema": "dev-flow-live-risk-assessment/v1",
        "decision": decision,
        "repository_id": (
            repositories[0].get("id")
            if isinstance(repositories, list)
            and len(repositories) == 1
            and isinstance(repositories[0], dict)
            else None
        ),
        "preflight_head_sha": preflight_head_sha,
        "current_head_sha": current_head_sha,
        "fingerprint_sha256": fingerprint_sha256,
        "changed_paths": changed_paths,
        "changed_paths_sha256": _sha256_bytes(_json_bytes(changed_paths)),
        "policy_sha256": (
            _sha256_bytes(_json_bytes(current_policy))
            if current_policy is not None
            else None
        ),
        "reasons": reasons,
        "evaluated_at": evaluated_at,
    }
    stable_assessment = dict(assessment)
    stable_assessment.pop("evaluated_at", None)
    assessment["sha256"] = _sha256_bytes(
        _json_bytes(stable_assessment)
    )
    return assessment, captured_fingerprints


def _lite_change_assessment(
    state_value: dict[str, Any],
    data_dir: str | os.PathLike[str] | None,
) -> dict[str, Any]:
    assessment, _ = _capture_lite_change_assessment(
        state_value, data_dir
    )
    return assessment


_FINGERPRINT_STORAGE_KIND = "task-local-json-v1"


def _fingerprint_blob_error(
    code: str,
    message: str,
    *,
    label: str,
    path: Path | None = None,
    **details: Any,
) -> FlowError:
    payload = {"label": label, **details}
    if path is not None:
        payload["path"] = str(path)
    return FlowError(code, message, details=payload)


def _load_recorded_fingerprint(
    recorded: Any,
    label: str,
) -> dict[str, Any]:
    """Resolve an inline v2 fingerprint or a validated task-local blob ref."""

    if not isinstance(recorded, dict):
        raise _fingerprint_blob_error(
            "FINGERPRINT_EVIDENCE_INVALID",
            "recorded repository fingerprint is missing or malformed",
            label=label,
        )
    storage = recorded.get("storage")
    if storage is None:
        _require_current_evidence(recorded, label)
        return recorded
    if storage != _FINGERPRINT_STORAGE_KIND:
        raise _fingerprint_blob_error(
            "FINGERPRINT_STORAGE_UNSUPPORTED",
            "recorded repository fingerprint uses an unsupported storage format",
            label=label,
            storage=storage,
        )

    fingerprint_sha256 = recorded.get("sha256")
    blob_sha256 = recorded.get("blob_sha256")
    size = recorded.get("size")
    path_value = recorded.get("path")
    path_identity = recorded.get("path_identity")
    task_root_value = recorded.get("task_root")
    task_root_identity = recorded.get("task_root_identity")
    if (
        not isinstance(fingerprint_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fingerprint_sha256)
        or not isinstance(blob_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", blob_sha256)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(path_value, str)
        or not path_value
        or not isinstance(path_identity, dict)
        or not isinstance(task_root_value, str)
        or not task_root_value
        or not isinstance(task_root_identity, dict)
    ):
        raise _fingerprint_blob_error(
            "FINGERPRINT_EVIDENCE_INVALID",
            "external repository fingerprint has incomplete integrity metadata",
            label=label,
        )
    path = Path(path_value)
    task_root = Path(task_root_value)
    expected_path = (
        task_root
        / "artifacts"
        / "fingerprints"
        / f"{fingerprint_sha256}.json"
    )
    if (
        not path.is_absolute()
        or not task_root.is_absolute()
        or path != expected_path
        or not _recorded_path_matches(
            task_root_identity,
            task_root_value,
            task_root,
        )
    ):
        raise _fingerprint_blob_error(
            "FINGERPRINT_EVIDENCE_INVALID",
            "external repository fingerprint is outside its recorded task store",
            label=label,
            path=path,
            task_root=task_root_value,
            expected_path=str(expected_path),
        )
    if not _recorded_path_matches(
        path_identity,
        path_value,
        path,
    ):
        raise _fingerprint_blob_error(
            "FINGERPRINT_BLOB_CHANGED",
            "external repository fingerprint path identity changed",
            label=label,
            path=path,
        )
    unresolved = _rollback_evidence_for(path)
    if unresolved:
        raise FlowError(
            "ATOMIC_RECOVERY_REQUIRED",
            "external repository fingerprint has unresolved rollback evidence",
            details={
                "label": label,
                "path": str(path),
                "rollback_candidates": [
                    str(candidate) for candidate in unresolved
                ],
                "recovery_command": _ROLLBACK_RECOVERY_COMMAND,
            },
        )
    try:
        if not path.is_file():
            raise FileNotFoundError(path)
        raw_payload = path.read_bytes()
        current_size = len(raw_payload)
        current_blob_sha256 = _sha256_bytes(raw_payload)
        payload = json.loads(raw_payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fingerprint_blob_error(
            "FINGERPRINT_BLOB_UNREADABLE",
            "external repository fingerprint is missing or unreadable",
            label=label,
            path=path,
            error=str(exc),
        ) from exc
    if current_size != size or current_blob_sha256 != blob_sha256:
        raise _fingerprint_blob_error(
            "FINGERPRINT_BLOB_CHANGED",
            "external repository fingerprint file changed",
            label=label,
            path=path,
            expected_size=size,
            actual_size=current_size,
            expected_blob_sha256=blob_sha256,
            actual_blob_sha256=current_blob_sha256,
        )
    if not isinstance(payload, dict):
        raise _fingerprint_blob_error(
            "FINGERPRINT_EVIDENCE_INVALID",
            "external repository fingerprint payload is not an object",
            label=label,
            path=path,
        )
    _require_current_evidence(payload, label)
    actual_fingerprint_sha256 = _fingerprint_payload_sha256(payload)
    if (
        payload.get("sha256") != actual_fingerprint_sha256
        or fingerprint_sha256 != actual_fingerprint_sha256
        or recorded.get("capability_profile_sha256")
        != payload.get("capability_profile_sha256")
        or recorded.get("tracked_worktree_manifest_sha256")
        != payload.get("tracked_worktree_manifest_sha256")
    ):
        raise _fingerprint_blob_error(
            "FINGERPRINT_EVIDENCE_INVALID",
            "external repository fingerprint payload does not match its reference",
            label=label,
            path=path,
            expected_fingerprint_sha256=fingerprint_sha256,
            actual_fingerprint_sha256=actual_fingerprint_sha256,
        )
    return payload


def _store_fingerprint(
    task_dir: Path,
    fingerprint: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    """Persist one immutable task-local fingerprint before state references it."""

    _require_current_evidence(fingerprint, label)
    fingerprint_sha256 = fingerprint.get("sha256")
    actual_fingerprint_sha256 = _fingerprint_payload_sha256(fingerprint)
    if (
        not isinstance(fingerprint_sha256, str)
        or fingerprint_sha256 != actual_fingerprint_sha256
    ):
        raise _fingerprint_blob_error(
            "FINGERPRINT_EVIDENCE_INVALID",
            "repository fingerprint payload hash is invalid",
            label=label,
            expected_fingerprint_sha256=fingerprint_sha256,
            actual_fingerprint_sha256=actual_fingerprint_sha256,
        )

    task_root = task_dir.resolve(strict=True)
    path = (
        task_root
        / "artifacts"
        / "fingerprints"
        / f"{fingerprint_sha256}.json"
    )
    if path.exists():
        unresolved = _rollback_evidence_for(path)
        if unresolved:
            raise FlowError(
                "ATOMIC_RECOVERY_REQUIRED",
                "task-local fingerprint has unresolved rollback evidence",
                details={
                    "label": label,
                    "path": str(path),
                    "rollback_candidates": [
                        str(candidate) for candidate in unresolved
                    ],
                    "recovery_command": _ROLLBACK_RECOVERY_COMMAND,
                },
            )
        try:
            existing_raw = path.read_bytes()
            existing = json.loads(existing_raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _fingerprint_blob_error(
                "FINGERPRINT_BLOB_UNREADABLE",
                "existing task-local fingerprint blob is unreadable",
                label=label,
                path=path,
                error=str(exc),
            ) from exc
        if (
            not isinstance(existing, dict)
            or existing.get("sha256") != fingerprint_sha256
            or _fingerprint_payload_sha256(existing) != fingerprint_sha256
            or existing != fingerprint
        ):
            raise _fingerprint_blob_error(
                "FINGERPRINT_BLOB_COLLISION",
                "task-local fingerprint path contains different evidence",
                label=label,
                path=path,
                fingerprint_sha256=fingerprint_sha256,
            )
    else:
        _atomic_write_json(path, fingerprint)

    try:
        blob_bytes = path.read_bytes()
    except OSError as exc:
        raise _fingerprint_blob_error(
            "FINGERPRINT_BLOB_UNREADABLE",
            "task-local fingerprint blob could not be re-read",
            label=label,
            path=path,
            error=str(exc),
        ) from exc
    reference = {
        "storage": _FINGERPRINT_STORAGE_KIND,
        "task_root": str(task_root),
        "task_root_identity": _serializable_path_identity(task_root),
        "path": str(path),
        "path_identity": _serializable_path_identity(path),
        "blob_sha256": _sha256_bytes(blob_bytes),
        "size": len(blob_bytes),
        "sha256": fingerprint_sha256,
        "capability_profile_sha256": fingerprint.get(
            "capability_profile_sha256"
        ),
        "tracked_worktree_manifest_sha256": fingerprint.get(
            "tracked_worktree_manifest_sha256"
        ),
    }
    _load_recorded_fingerprint(reference, label)
    return reference


def _untracked_filesystem_path(item: dict[str, Any]) -> str:
    raw_hex = item.get("path_bytes_hex")
    if isinstance(raw_hex, str):
        try:
            return os.fsdecode(bytes.fromhex(raw_hex))
        except ValueError as exc:
            raise FlowError(
                "REVIEW_SNAPSHOT_INVALID",
                "untracked evidence contains an invalid raw path encoding",
                details={"path": item.get("path"), "path_bytes_hex": raw_hex},
            ) from exc
    # Compatibility for evidence recorded before raw path bytes were bound.
    return str(item.get("path", ""))


def _validate_untracked_archive(
    archive_path: Path, manifest: Sequence[dict[str, Any]]
) -> None:
    """Prove that archived untracked entries match their byte manifest."""

    try:
        with tarfile.open(archive_path, mode="r") as archive:
            members = {
                member.name.rstrip("/"): member
                for member in archive.getmembers()
            }
            for item in manifest:
                relative = _untracked_filesystem_path(item).replace(
                    os.sep, "/"
                )
                member = members.get(relative.rstrip("/"))
                if member is None:
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CHANGED",
                        "untracked archive is missing a manifest entry",
                        details={
                            "archive": str(archive_path),
                            "path": item.get("path"),
                        },
                    )
                item_type = item.get("type")
                type_matches = (
                    (item_type == "file" and member.isfile())
                    or (item_type == "symlink" and member.issym())
                    or (
                        item_type == "other"
                        and not member.isfile()
                        and not member.issym()
                    )
                )
                if item_type == "file":
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise FlowError(
                            "REVIEW_SNAPSHOT_CHANGED",
                            "untracked regular file has no archived bytes",
                            details={
                                "archive": str(archive_path),
                                "path": item.get("path"),
                            },
                        )
                    digest = hashlib.sha256()
                    with extracted:
                        for chunk in iter(
                            lambda: extracted.read(1024 * 1024), b""
                        ):
                            digest.update(chunk)
                    actual_sha = digest.hexdigest()
                elif item_type == "symlink":
                    actual_sha = (
                        _sha256_bytes(os.fsencode(member.linkname))
                        if member.issym()
                        else None
                    )
                else:
                    actual_sha = None
                if (
                    not type_matches
                    or actual_sha != item.get("sha256")
                    or (
                        item_type == "file"
                        and member.size != item.get("size")
                    )
                ):
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CHANGED",
                        "untracked archive bytes differ from the manifest",
                        details={
                            "archive": str(archive_path),
                            "path": item.get("path"),
                            "expected_sha256": item.get("sha256"),
                            "actual_sha256": actual_sha,
                        },
                    )
    except FlowError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise FlowError(
            "REVIEW_SNAPSHOT_INVALID",
            "untracked review archive could not be verified",
            details={"archive": str(archive_path), "error": str(exc)},
        ) from exc


def _working_path(repo: dict[str, Any]) -> Path:
    workspace = repo.get("workspace")
    if isinstance(workspace, dict) and workspace.get("ready") and workspace.get("path"):
        return Path(workspace["path"])
    return Path(repo["path"])


def _copy_state(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _recommended_index_name(
    state_value: dict[str, Any], repo: dict[str, Any], role: str
) -> str:
    prefix = f"devflow-{state_value['task_id']}-{repo['id']}"
    if role == "baseline":
        return f"{prefix}-baseline"
    if role == "workspace":
        generation = int(
            (state_value.get("workspace") or {}).get("generation", 0)
        )
        return f"{prefix}-workspace-r{generation}"
    raise ValueError(f"unknown index role: {role}")


def _index_role_for_status(state_value: dict[str, Any]) -> str | None:
    if _flow(state_value) == "lite":
        # Lite tasks record no controller-bound indexes; ad-hoc codebase-memory
        # use stays outside the evidence chain.
        return None
    status = state_value.get("status")
    if status == "BLOCKED":
        status = (state_value.get("blocked") or {}).get("from_status")
    if status in BASELINE_INDEX_STATES:
        return "baseline"
    if status in WORKSPACE_INDEX_STATES:
        return "workspace"
    return None


def _index_role_summary(
    state_value: dict[str, Any], repo: dict[str, Any], role: str
) -> dict[str, Any]:
    record = repo.get("index" if role == "baseline" else "workspace_index")
    record = record if isinstance(record, dict) else {}
    receipt = record.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    degraded = bool(record) and (
        not record.get("index_id")
        or metadata.get("status") == "failed"
    )
    summary: dict[str, Any] = {
        "role": role,
        "index_record_id": record.get("index_record_id"),
        "recorded_project": record.get("index_id"),
        "recommended_project": _recommended_index_name(
            state_value, repo, role
        ),
        "recorded": bool(record),
        "repo_path": record.get("repo_path"),
        "mode": receipt.get("mode") or metadata.get("mode"),
        "persistence": (
            receipt.get("persistence")
            if "persistence" in receipt
            else metadata.get("persistence")
        ),
        "usable": bool(record.get("index_id")) and not degraded,
        "degraded": degraded,
    }
    if role == "workspace":
        summary["workspace_generation"] = record.get(
            "workspace_generation"
        )
    return summary


def _index_selection(state_value: dict[str, Any]) -> dict[str, Any]:
    """Describe the exact phase-selected project without selecting it for callers."""

    selected_role = _index_role_for_status(state_value)
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        baseline = _index_role_summary(state_value, repo, "baseline")
        workspace = _index_role_summary(state_value, repo, "workspace")
        selected = (
            baseline
            if selected_role == "baseline"
            else workspace
            if selected_role == "workspace"
            else None
        )
        repositories.append(
            {
                "repository_id": repo.get("id"),
                "selected_role": selected_role,
                "role": selected_role,
                "recorded_project": (
                    selected.get("recorded_project") if selected else None
                ),
                "recommended_project": (
                    selected.get("recommended_project") if selected else None
                ),
                "index_record_id": (
                    selected.get("index_record_id") if selected else None
                ),
                "mode": selected.get("mode") if selected else None,
                "persistence": (
                    selected.get("persistence") if selected else None
                ),
                "usable": selected.get("usable") if selected else False,
                "degraded": (
                    selected.get("degraded") if selected else False
                ),
                "baseline": baseline,
                "workspace": workspace,
            }
        )
    return {
        "automatic": False,
        "selected_role": selected_role,
        # ``role`` is retained as a compact compatibility alias.  Consumers
        # should use selected_role and pass recorded_project explicitly.
        "role": selected_role,
        "repositories": repositories,
    }
