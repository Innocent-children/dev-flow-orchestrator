#!/bin/sh
set -eu

REPOSITORY_URL="${DEV_FLOW_REPOSITORY_URL:-https://github.com/Innocent-children/dev-flow-orchestrator.git}"
REPOSITORY_REF="main"
SOURCE_ROOT="${DEV_FLOW_SOURCE_ROOT:-$HOME/plugins/dev-flow-orchestrator}"
MARKETPLACE_FILE="${DEV_FLOW_MARKETPLACE_FILE:-$HOME/.agents/plugins/marketplace.json}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
RUNTIME_ROOT="${DEV_FLOW_RUNTIME_HOME:-$HOME/.local/share/dev-flow-orchestrator/runtime}"
DATA_ROOT="$CODEX_ROOT/plugins/data/dev-flow-orchestrator-personal/0.4.0"
select_path_bin_dir() {
  if [ -n "${DEV_FLOW_BIN_DIR:-}" ]; then
    printf '%s\n' "$DEV_FLOW_BIN_DIR"
    return
  fi
  original_ifs="$IFS"
  IFS=:
  for candidate in $PATH; do
    case "$candidate" in
      /*)
        if [ -d "$candidate" ] && [ ! -L "$candidate" ] \
          && [ -w "$candidate" ] && [ -x "$candidate" ]; then
          IFS="$original_ifs"
          printf '%s\n' "$candidate"
          return
        fi
        ;;
    esac
  done
  IFS="$original_ifs"
  return 1
}

BIN_DIR="$(select_path_bin_dir)" || {
  printf 'Dev Flow installation failed: PATH has no writable absolute directory; set DEV_FLOW_BIN_DIR explicitly.\n' >&2
  exit 1
}
LAUNCHER_PATH="$BIN_DIR/dev-flow"
MCP_LAUNCHER_PATH="$BIN_DIR/dev-flow-mcp"
PLUGIN_ID="dev-flow-orchestrator@personal"
LAUNCHER_MARKER="# dev-flow-orchestrator managed launcher"
MCP_LAUNCHER_MARKER="# dev-flow-orchestrator managed MCP launcher"

NEON_CYAN=""
NEON_BLUE=""
NEON_PURPLE=""
NEON_GREEN=""
BRIGHT_WHITE=""
TEXT_DIM=""
TEXT_BOLD=""
COLOR_RESET=""
if [ -z "${NO_COLOR:-}" ] && {
  [ "${DEV_FLOW_FORCE_COLOR:-0}" = "1" ] \
    || { [ -t 1 ] && [ "${TERM:-}" != "dumb" ]; }
}; then
  COLOR_ESCAPE="$(printf '\033')"
  NEON_CYAN="${COLOR_ESCAPE}[38;5;51m"
  NEON_BLUE="${COLOR_ESCAPE}[38;5;39m"
  NEON_PURPLE="${COLOR_ESCAPE}[38;5;213m"
  NEON_GREEN="${COLOR_ESCAPE}[38;5;82m"
  BRIGHT_WHITE="${COLOR_ESCAPE}[38;5;255m"
  TEXT_DIM="${COLOR_ESCAPE}[2m"
  TEXT_BOLD="${COLOR_ESCAPE}[1m"
  COLOR_RESET="${COLOR_ESCAPE}[0m"
fi

fail() {
  if [ "${ROLLBACK_READY:-0}" = "1" ]; then
    rollback_activation "$1"
  fi
  printf 'Dev Flow installation failed: %s\n' "$1" >&2
  exit 1
}

maybe_fail_at() {
  [ "${DEV_FLOW_INSTALL_FAIL_AT:-}" != "$1" ] \
    || fail "Injected installer failure at $1."
}

inject_test_source_drift_at() {
  drift_point="$1"
  [ "${DEV_FLOW_INSTALL_TEST_SOURCE_DRIFT_AT:-}" = "$drift_point" ] || return 0
  drift_target="$SOURCE_ROOT/README.md"
  if [ -L "$drift_target" ] || [ ! -f "$drift_target" ]; then
    fail "The bounded source-drift test target is not a regular file."
  fi
  printf '\nDEV_FLOW_INSTALL_TEST_SOURCE_DRIFT:%s\n' "$drift_point" >>"$drift_target" \
    || fail "Cannot apply the bounded source-drift test marker."
}

capture_source_inventory() {
  inventory_root="$1"
  mkdir -p "$inventory_root" || return 1
  git -C "$SOURCE_ROOT" rev-parse --verify 'HEAD^{commit}' >"$inventory_root/head" \
    && git -C "$SOURCE_ROOT" rev-parse --verify 'HEAD^{tree}' >"$inventory_root/tree" \
    && git -C "$SOURCE_ROOT" status --porcelain -z --untracked-files=no >"$inventory_root/tracked" \
    && git -C "$SOURCE_ROOT" ls-files --others --exclude-standard -z >"$inventory_root/untracked" \
    && git -C "$SOURCE_ROOT" ls-files --others --ignored --exclude-standard -z >"$inventory_root/ignored" \
    && source_path_digest "$inventory_root/untracked" >"$inventory_root/untracked-digest" \
    && source_path_digest "$inventory_root/ignored" >"$inventory_root/ignored-digest"
}

source_path_digest() {
  path_list="$1"
  DEV_FLOW_INVENTORY_SOURCE="$SOURCE_ROOT" \
  DEV_FLOW_INVENTORY_PATHS="$path_list" \
  python_no_bytecode -I -S -c '
import hashlib
import os
from pathlib import Path
import stat

root = Path(os.environ["DEV_FLOW_INVENTORY_SOURCE"])
names = Path(os.environ["DEV_FLOW_INVENTORY_PATHS"]).read_bytes().split(b"\0")
digest = hashlib.sha256()
for encoded in sorted(name for name in names if name):
    relative = os.fsdecode(encoded)
    path = root / relative
    value = path.lstat()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    digest.update(stat.S_IFMT(value.st_mode).to_bytes(8, "big"))
    if stat.S_ISREG(value.st_mode):
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(128 * 1024), b""):
                digest.update(chunk)
    elif stat.S_ISLNK(value.st_mode):
        digest.update(os.fsencode(os.readlink(path)))
    else:
        digest.update(str(value.st_size).encode("ascii"))
print(digest.hexdigest())
'
}

source_inventory_matches_baseline() {
  current_inventory="$ROLLBACK_ROOT/source-current"
  rm -rf "$current_inventory" || return 1
  capture_source_inventory "$current_inventory" || return 1
  cmp -s "$ROLLBACK_ROOT/source-baseline/head" "$current_inventory/head" \
    && cmp -s "$ROLLBACK_ROOT/source-baseline/tree" "$current_inventory/tree" \
    && cmp -s "$ROLLBACK_ROOT/source-baseline/tracked" "$current_inventory/tracked" \
    && cmp -s "$ROLLBACK_ROOT/source-baseline/untracked" "$current_inventory/untracked" \
    && cmp -s "$ROLLBACK_ROOT/source-baseline/ignored" "$current_inventory/ignored" \
    && cmp -s "$ROLLBACK_ROOT/source-baseline/untracked-digest" "$current_inventory/untracked-digest" \
    && cmp -s "$ROLLBACK_ROOT/source-baseline/ignored-digest" "$current_inventory/ignored-digest"
}

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) fail "$BIN_DIR is not on PATH; set DEV_FLOW_BIN_DIR to a writable PATH directory." ;;
esac

if [ -L "$BIN_DIR" ] || { [ -e "$BIN_DIR" ] && [ ! -d "$BIN_DIR" ]; }; then
  fail "$BIN_DIR must be a regular directory, not a symbolic link or special file."
fi
if [ -e "$LAUNCHER_PATH" ] || [ -L "$LAUNCHER_PATH" ]; then
  [ ! -L "$LAUNCHER_PATH" ] && [ -f "$LAUNCHER_PATH" ] \
    || fail "$LAUNCHER_PATH is not a regular installer-managed launcher."
  grep -Fqx "$LAUNCHER_MARKER" "$LAUNCHER_PATH" \
    || fail "$LAUNCHER_PATH already exists and is not owned by Dev Flow."
fi
if [ -e "$MCP_LAUNCHER_PATH" ] || [ -L "$MCP_LAUNCHER_PATH" ]; then
  [ ! -L "$MCP_LAUNCHER_PATH" ] && [ -f "$MCP_LAUNCHER_PATH" ] \
    || fail "$MCP_LAUNCHER_PATH is not a regular installer-managed launcher."
  grep -Fqx "$MCP_LAUNCHER_MARKER" "$MCP_LAUNCHER_PATH" \
    || fail "$MCP_LAUNCHER_PATH already exists and is not owned by Dev Flow."
fi

verify_and_update_source() {
  EXISTING_REMOTE="$(git -C "$SOURCE_ROOT" remote get-url origin 2>/dev/null || true)"
  if [ "$EXISTING_REMOTE" != "$REPOSITORY_URL" ]; then
    fail "$SOURCE_ROOT origin is '$EXISTING_REMOTE', expected '$REPOSITORY_URL'."
  fi

  CURRENT_BRANCH="$(git -C "$SOURCE_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  if [ "$CURRENT_BRANCH" != "$REPOSITORY_REF" ]; then
    fail "$SOURCE_ROOT is on '${CURRENT_BRANCH:-a detached HEAD}', expected branch '$REPOSITORY_REF'."
  fi

  SOURCE_STATUS="$(git -C "$SOURCE_ROOT" status --porcelain 2>/dev/null)" \
    || fail "Cannot inspect the working tree at $SOURCE_ROOT."
  if [ -n "$SOURCE_STATUS" ]; then
    fail "$SOURCE_ROOT has local changes; preserve or commit them before reinstalling."
  fi

  printf 'Fetching the authoritative %s branch...\n' "$REPOSITORY_REF"
  if ! git -C "$SOURCE_ROOT" fetch --no-tags origin "refs/heads/$REPOSITORY_REF"; then
    fail "Cannot fetch authoritative ref 'refs/heads/$REPOSITORY_REF' from '$REPOSITORY_URL'."
  fi

  APPROVED_HEAD="$(git -C "$SOURCE_ROOT" rev-parse --verify 'FETCH_HEAD^{commit}' 2>/dev/null)" \
    || fail "The fetched authoritative ref does not resolve to a commit."
  CURRENT_HEAD="$(git -C "$SOURCE_ROOT" rev-parse --verify 'HEAD^{commit}' 2>/dev/null)" \
    || fail "$SOURCE_ROOT HEAD does not resolve to a commit."

  SEAL_HELPER="$ROLLBACK_ROOT/runtime_integrity.py"
  git -C "$SOURCE_ROOT" show "$APPROVED_HEAD:scripts/runtime_integrity.py" >"$SEAL_HELPER" \
    || fail "The authoritative release is missing its runtime integrity helper."

  if [ "$CURRENT_HEAD" != "$APPROVED_HEAD" ]; then
    if git -C "$SOURCE_ROOT" merge-base --is-ancestor "$CURRENT_HEAD" "$APPROVED_HEAD"; then
      PREVIOUS_SOURCE_TREE="$(
        git -C "$SOURCE_ROOT" rev-parse --verify "$CURRENT_HEAD^{tree}" 2>/dev/null
      )" || fail "The previous source commit has no readable tree identity."
      PREVIOUS_SEAL_JSON="$(
        seal_git_commit "$CURRENT_HEAD" "$PREVIOUS_SOURCE_TREE" previous
      )" || fail "Cannot seal the previous source release before fast-forwarding."
      printf 'Fast-forwarding the existing source checkout...\n'
      git -C "$SOURCE_ROOT" merge --ff-only --no-overwrite-ignore "$APPROVED_HEAD" \
        || fail "Could not fast-forward $SOURCE_ROOT to authoritative $REPOSITORY_REF without overwriting local work."
    elif git -C "$SOURCE_ROOT" merge-base --is-ancestor "$APPROVED_HEAD" "$CURRENT_HEAD"; then
      fail "$SOURCE_ROOT has local commits beyond authoritative origin/$REPOSITORY_REF; preserve them and restore a clean authoritative checkout manually."
    else
      fail "$SOURCE_ROOT has diverged from authoritative origin/$REPOSITORY_REF; reconcile it manually before reinstalling."
    fi
  fi

  VERIFIED_HEAD="$(git -C "$SOURCE_ROOT" rev-parse --verify 'HEAD^{commit}' 2>/dev/null)" \
    || fail "$SOURCE_ROOT HEAD does not resolve to a commit after update."
  if [ "$VERIFIED_HEAD" != "$APPROVED_HEAD" ]; then
    fail "$SOURCE_ROOT HEAD does not match the fetched authoritative origin/$REPOSITORY_REF commit."
  fi
  SOURCE_STATUS="$(git -C "$SOURCE_ROOT" status --porcelain 2>/dev/null)" \
    || fail "Cannot inspect the working tree at $SOURCE_ROOT after update."
  if [ -n "$SOURCE_STATUS" ]; then
    fail "$SOURCE_ROOT changed during update; refusing to validate or activate it."
  fi
}

command -v git >/dev/null 2>&1 || fail "Git is required."
command -v codex >/dev/null 2>&1 || fail "Codex with plugin support is required."
command -v uv >/dev/null 2>&1 || fail "uv is required to build the exact locked MCP runtime."

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  fail "Python 3.10-3.14 is required."
fi

python_no_bytecode() {
  PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -B "$@"
}

python_no_bytecode -c 'import struct,sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) and struct.calcsize("P") == 8 else 1)' \
  || fail "64-bit Python 3.10-3.14 is required."

if [ "$(uname -s)" != "Darwin" ]; then
  fail "This Dev Flow installer supports macOS; use the documented PowerShell installer on Windows."
fi

ROLLBACK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dev-flow-install-rollback.XXXXXX")" \
  || fail "Cannot create the bounded installation rollback directory."
INSTALL_COMMITTED=0
ROLLBACK_READY=0
SOURCE_BASELINE_CAPTURED=0
PREVIOUS_SEAL_JSON=""
PREVIOUS_SOURCE_TREE=""
MCP_LAUNCHER_PREEXISTED=0
MARKETPLACE_PREEXISTED=0
LAUNCHER_PREEXISTED=0

cleanup_rollback() {
  exit_status="$?"
  trap - 0 HUP INT TERM
  if [ "$ROLLBACK_READY" = "1" ] && [ "$INSTALL_COMMITTED" != "1" ]; then
    ROLLBACK_READY=0
    rollback_activation "Installation stopped before the candidate was committed." || true
  fi
  if [ "$SOURCE_BASELINE_CAPTURED" = "1" ] \
    && ! source_inventory_matches_baseline; then
    printf '%s\n' \
      'Authoritative source changed after candidate sealing; no post-seal activation input was read from that checkout.' \
      >&2
  fi
  rm -rf "$ROLLBACK_ROOT" || true
  exit "$exit_status"
}
trap cleanup_rollback 0 HUP INT TERM

seal_git_commit() {
  seal_commit="$1"
  seal_tree="$2"
  seal_name="$3"
  seal_archive="$ROLLBACK_ROOT/$seal_name.tar"
  seal_destination="$ROLLBACK_ROOT/sealed-$seal_name"
  git -C "$SOURCE_ROOT" archive --format=tar --output="$seal_archive" "$seal_commit" \
    || return 1
  python_no_bytecode -I -S "$SEAL_HELPER" seal \
    --archive "$seal_archive" \
    --destination "$seal_destination" \
    --source-commit "$seal_commit" \
    --source-tree "$seal_tree"
}

if [ ! -e "$SOURCE_ROOT" ]; then
  mkdir -p "$(dirname "$SOURCE_ROOT")"
  printf 'Cloning Dev Flow Orchestrator from authoritative branch %s...\n' "$REPOSITORY_REF"
  if ! git clone --depth 1 --branch "$REPOSITORY_REF" --single-branch "$REPOSITORY_URL" "$SOURCE_ROOT"; then
    fail "Cannot clone authoritative branch '$REPOSITORY_REF' from '$REPOSITORY_URL'."
  fi
elif [ -d "$SOURCE_ROOT/.git" ]; then
  printf 'Checking the existing source checkout...\n'
else
  fail "$SOURCE_ROOT already exists and is not a Git checkout."
fi

verify_and_update_source

VERIFIED_TREE="$(git -C "$SOURCE_ROOT" rev-parse --verify "$VERIFIED_HEAD^{tree}" 2>/dev/null)" \
  || fail "The verified source commit has no readable tree identity."
capture_source_inventory "$ROLLBACK_ROOT/source-baseline" \
  || fail "Cannot capture the verified source inventory."
SOURCE_BASELINE_CAPTURED=1
maybe_fail_at candidate-staging
CANDIDATE_SEAL_JSON="$(seal_git_commit "$VERIFIED_HEAD" "$VERIFIED_TREE" candidate)" \
  || fail "Cannot seal the verified Git commit into a candidate release."
SEALED_SOURCE_ROOT="$(
  printf '%s' "$CANDIDATE_SEAL_JSON" | python_no_bytecode -I -S -c '
import json
import sys
value = json.load(sys.stdin)
if value.get("ok") is not True or not isinstance(value.get("plugin_root"), str):
    raise SystemExit("invalid sealed release result")
print(value["plugin_root"])
'
)" || fail "Cannot interpret the sealed candidate result."
CANDIDATE_RELEASE_ID="$(
  printf '%s' "$CANDIDATE_SEAL_JSON" | python_no_bytecode -I -S -c '
import json
import sys
value = json.load(sys.stdin)
release_id = value.get("release_id")
if not isinstance(release_id, str) or not release_id:
    raise SystemExit("invalid sealed release identity")
print(release_id)
'
)" || fail "Cannot interpret the sealed candidate identity."

printf 'Validating the package...\n'
python_no_bytecode -I -S "$SEALED_SOURCE_ROOT/scripts/validate_package.py"
PLUGIN_VERSION="$(
  python_no_bytecode -I -S -c '
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = manifest.get("version")
if not isinstance(version, str) or not version:
    raise SystemExit("plugin manifest must contain a non-empty version")
print(version)
' "$SEALED_SOURCE_ROOT/.codex-plugin/plugin.json"
)" || fail "Cannot read the validated plugin version."

printf 'Inspecting the installed Codex plugin...\n'
PLUGIN_LIST_JSON="$(codex plugin list --marketplace personal --json)" \
  || fail "Cannot inspect the installed Codex plugins."
PLUGIN_STATE="$(
  printf '%s' "$PLUGIN_LIST_JSON" | python_no_bytecode -I -S -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError) as error:
    raise SystemExit(f"invalid plugin list JSON: {error}")
installed = payload.get("installed") if isinstance(payload, dict) else None
if not isinstance(installed, list):
    raise SystemExit("plugin list JSON must contain an installed array")
matches = [
    item
    for item in installed
    if isinstance(item, dict)
    and item.get("pluginId") == "dev-flow-orchestrator@personal"
]
if len(matches) > 1:
    raise SystemExit("plugin list contains duplicate installed entries")
if not matches or matches[0].get("installed") is not True:
    print("not-installed")
else:
    version = matches[0].get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit("installed plugin entry must contain a version")
    state = "active" if matches[0].get("enabled") is True else "inactive"
    print(f"installed-{state}:{version}")
'
)" || fail "Cannot interpret the installed Codex plugin state."

INSTALL_ACTION="installed"
PREVIOUS_VERSION=""
PLUGIN_BUNDLED_ACTIVE=0
case "$PLUGIN_STATE" in
  not-installed)
    ;;
  installed-active:*|installed-inactive:*)
    PREVIOUS_VERSION="${PLUGIN_STATE#*:}"
    if [ "${PLUGIN_STATE%%:*}" = "installed-active" ]; then
      PLUGIN_BUNDLED_ACTIVE=1
    fi
    if [ "$PREVIOUS_VERSION" = "$PLUGIN_VERSION" ]; then
      INSTALL_ACTION="repaired"
      printf 'Repairing Dev Flow Orchestrator %s...\n' "$PLUGIN_VERSION"
    else
      INSTALL_ACTION="upgraded"
      printf 'Upgrading Dev Flow Orchestrator from %s to %s...\n' \
        "$PREVIOUS_VERSION" "$PLUGIN_VERSION"
    fi
    ;;
  *)
    fail "Codex returned an unrecognized plugin state."
    ;;
esac

check_mcp_registration_state() {
  require_bundled="$1"
  DEV_FLOW_BUNDLED_ACTIVE="$PLUGIN_BUNDLED_ACTIVE" \
  DEV_FLOW_CODEX_CONFIG="$CODEX_ROOT/config.toml" \
  DEV_FLOW_MCP_LAUNCHER="$MCP_LAUNCHER_PATH" \
  DEV_FLOW_REQUIRE_BUNDLED="$require_bundled" \
  python_no_bytecode -I -S -c '
import json
import os
import re
import sys
from pathlib import Path

payload = json.load(sys.stdin)
if not isinstance(payload, list):
    raise SystemExit("MCP list must be an array")

owned = Path(os.environ["DEV_FLOW_MCP_LAUNCHER"]).expanduser().resolve()

def commands(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in {"command", "executable", "program"} and isinstance(item, str):
                yield item
            yield from commands(item)
    elif isinstance(value, list):
        for item in value:
            yield from commands(item)

def owned_command(command):
    path = Path(command).expanduser()
    if path.name.casefold() in {"dev-flow-mcp", "dev-flow-mcp.cmd"}:
        return True
    try:
        return path.resolve() == owned
    except OSError:
        return False

def is_owned(item):
    return any(owned_command(command) for command in commands(item))

def is_canonical(item):
    if not isinstance(item, dict) or item.get("name") != "dev-flow" or item.get("enabled") is not True:
        return False
    transport = item.get("transport")
    return (
        isinstance(transport, dict)
        and transport.get("type") == "stdio"
        and transport.get("command") == "dev-flow-mcp"
        and transport.get("args") == ["--stdio"]
    )

def fallback_explicit_owned(text):
    names = []
    current = None
    apostrophe = chr(39)
    name = rf"(?:\"([^\"]+)\"|{apostrophe}([^{apostrophe}]+){apostrophe}|([A-Za-z0-9_-]+))"
    value = rf"(?:\"([^\"]+)\"|{apostrophe}([^{apostrophe}]+){apostrophe})"
    header = re.compile(r"^\s*\[\s*mcp_servers\s*\.\s*" + name + r"\s*\]\s*$")
    assignment = re.compile(r"^\s*command\s*=\s*" + value)
    dotted = re.compile(
        r"^\s*mcp_servers\s*\.\s*" + name + r"\s*\.\s*command\s*=\s*" + value
    )
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = header.match(line)
        if match:
            current = next(value for value in match.groups() if value is not None)
            continue
        if line.startswith("["):
            current = None
            continue
        match = dotted.match(line)
        if match:
            values = match.groups()
            name = next(value for value in values[:3] if value is not None)
            command = next(value for value in values[3:] if value is not None)
            if owned_command(command):
                names.append(name)
            continue
        if current is not None:
            match = assignment.match(line)
            if match:
                command = next(value for value in match.groups() if value is not None)
                if owned_command(command):
                    names.append(current)
    return names

config_path = Path(os.environ["DEV_FLOW_CODEX_CONFIG"])
explicit_owned = []
if config_path.exists():
    if not config_path.is_file():
        raise SystemExit(f"{config_path} must be a regular config.toml file")
    text = config_path.read_text(encoding="utf-8")
    try:
        import tomllib
    except ImportError:
        explicit_owned = fallback_explicit_owned(text)
    else:
        try:
            config = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            raise SystemExit(f"cannot parse {config_path}: {error}")
        servers = config.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise SystemExit(f"{config_path} mcp_servers must be a table")
        explicit_owned = [
            str(name)
            for name, registration in servers.items()
            if isinstance(registration, dict) and is_owned(registration)
        ]
if explicit_owned:
    raise SystemExit(
        "explicit standalone Dev Flow MCP registration(s) {} are present in {}; "
        "remove them before enabling bundled mode".format(
            ", ".join(sorted(explicit_owned)), config_path
        )
    )

owned_rows = [item for item in payload if isinstance(item, dict) and is_owned(item)]
enabled_owned = [item for item in owned_rows if item.get("enabled") is True]
canonical = [item for item in payload if is_canonical(item)]
if os.environ["DEV_FLOW_REQUIRE_BUNDLED"] == "1":
    if len(canonical) != 1 or len(owned_rows) != 1:
        raise SystemExit(
            "activated plugin must expose exactly one enabled canonical dev-flow STDIO registration "
            "and no additional owned-launcher registrations"
        )
elif os.environ["DEV_FLOW_BUNDLED_ACTIVE"] == "1" and len(canonical) == 1:
    conflicts = [item for item in enabled_owned if not is_canonical(item)]
else:
    conflicts = owned_rows
if os.environ["DEV_FLOW_REQUIRE_BUNDLED"] != "1" and conflicts:
    names = sorted(str(item.get("name", "<unnamed>")) for item in conflicts)
    raise SystemExit(
        "standalone Dev Flow MCP registration(s) {} target the owned launcher; "
        "disable or remove them with codex mcp before enabling bundled mode".format(
            ", ".join(names)
        )
    )
'
}

MCP_LIST_JSON="$(codex mcp list --json)" \
  || fail "Cannot inspect standalone MCP registrations."
printf '%s' "$MCP_LIST_JSON" | check_mcp_registration_state 0 \
  || fail "Standalone Dev Flow MCP registration conflicts with bundled plugin mode."

json_required_string() {
  json_key="$1"
  python_no_bytecode -I -S -c '
import json
import sys
key = sys.argv[1]
value = json.load(sys.stdin)
item = value.get(key) if isinstance(value, dict) else None
if value.get("ok") is not True or not isinstance(item, str) or not item:
    raise SystemExit(f"managed runtime result has no valid {key}")
print(item)
' "$json_key"
}

manage_sealed_release() {
  managed_source_root="$1"
  managed_source_commit="$2"
  managed_source_tree="$3"
  managed_release_id="$4"
  python_no_bytecode -I -S "$SEALED_SOURCE_ROOT/scripts/manage_runtime.py" \
    --source-root "$managed_source_root" \
    --runtime-root "$RUNTIME_ROOT" \
    --source-commit "$managed_source_commit" \
    --source-tree "$managed_source_tree" \
    --release-id "$managed_release_id" \
    --data-root "$DATA_ROOT"
}

printf 'Building the isolated locked MCP runtime...\n'
maybe_fail_at runtime-build
inject_test_source_drift_at runtime-build-before
CANDIDATE_RUNTIME_JSON="$(
  manage_sealed_release \
    "$SEALED_SOURCE_ROOT" "$VERIFIED_HEAD" "$VERIFIED_TREE" "$CANDIDATE_RELEASE_ID"
)" || fail "Cannot build and validate the managed MCP runtime."
inject_test_source_drift_at runtime-build-after
CANDIDATE_RUNTIME_DIR="$(
  printf '%s' "$CANDIDATE_RUNTIME_JSON" | json_required_string runtime_dir
)" || fail "Cannot interpret the managed runtime directory."
CANDIDATE_PLUGIN_ROOT="$(
  printf '%s' "$CANDIDATE_RUNTIME_JSON" | json_required_string plugin_root
)" || fail "Cannot interpret the managed plugin release directory."
CANDIDATE_MCP_LAUNCHER="$(
  printf '%s' "$CANDIDATE_RUNTIME_JSON" | json_required_string launcher_path
)" || fail "Cannot interpret the managed MCP launcher."
RUNTIME_RECEIPT_PATH="$(
  printf '%s' "$CANDIDATE_RUNTIME_JSON" | json_required_string receipt_path
)" || fail "Cannot interpret the managed runtime receipt."
RUNTIME_PYTHON="$(
  DEV_FLOW_RUNTIME_DIR="$CANDIDATE_RUNTIME_DIR" python_no_bytecode -I -S -c '
import os
from pathlib import Path
runtime = Path(os.environ["DEV_FLOW_RUNTIME_DIR"])
python = runtime / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.is_file():
    raise SystemExit("managed runtime result is invalid")
print(python)
'
)" || fail "Cannot interpret the managed MCP runtime result."

PREVIOUS_RELEASE_ID=""
PREVIOUS_PLUGIN_ROOT=""
PREVIOUS_RUNTIME_DIR=""
PREVIOUS_RUNTIME_PYTHON=""
PREVIOUS_MCP_LAUNCHER=""
if [ -n "$PREVIOUS_VERSION" ]; then
  if [ -z "$PREVIOUS_SEAL_JSON" ]; then
    PREVIOUS_SEAL_JSON="$CANDIDATE_SEAL_JSON"
    PREVIOUS_SOURCE_TREE="$VERIFIED_TREE"
    PREVIOUS_SOURCE_COMMIT="$VERIFIED_HEAD"
  else
    PREVIOUS_SOURCE_COMMIT="$CURRENT_HEAD"
  fi
  PREVIOUS_STAGED_ROOT="$(
    printf '%s' "$PREVIOUS_SEAL_JSON" | json_required_string plugin_root
  )" || fail "Cannot interpret the sealed previous release directory."
  PREVIOUS_RELEASE_ID="$(
    printf '%s' "$PREVIOUS_SEAL_JSON" | json_required_string release_id
  )" || fail "Cannot interpret the sealed previous release identity."
  if [ "$PREVIOUS_RELEASE_ID" = "$CANDIDATE_RELEASE_ID" ]; then
    PREVIOUS_RUNTIME_JSON="$CANDIDATE_RUNTIME_JSON"
  else
    printf 'Staging the previous release for bounded rollback...\n'
    PREVIOUS_RUNTIME_JSON="$(
      manage_sealed_release \
        "$PREVIOUS_STAGED_ROOT" "$PREVIOUS_SOURCE_COMMIT" \
        "$PREVIOUS_SOURCE_TREE" "$PREVIOUS_RELEASE_ID"
    )" || fail "Cannot stage a runnable previous release for rollback."
  fi
  PREVIOUS_RUNTIME_DIR="$(
    printf '%s' "$PREVIOUS_RUNTIME_JSON" | json_required_string runtime_dir
  )" || fail "Cannot interpret the previous runtime directory."
  PREVIOUS_PLUGIN_ROOT="$(
    printf '%s' "$PREVIOUS_RUNTIME_JSON" | json_required_string plugin_root
  )" || fail "Cannot interpret the previous plugin release directory."
  PREVIOUS_MCP_LAUNCHER="$(
    printf '%s' "$PREVIOUS_RUNTIME_JSON" | json_required_string launcher_path
  )" || fail "Cannot interpret the previous managed MCP launcher."
  PREVIOUS_RUNTIME_PYTHON="$(
    DEV_FLOW_RUNTIME_DIR="$PREVIOUS_RUNTIME_DIR" python_no_bytecode -I -S -c '
import os
from pathlib import Path
runtime = Path(os.environ["DEV_FLOW_RUNTIME_DIR"])
python = runtime / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.is_file():
    raise SystemExit("previous managed runtime Python is unavailable")
print(python)
'
  )" || fail "Cannot interpret the previous managed MCP runtime."
fi

if [ -f "$MCP_LAUNCHER_PATH" ]; then
  MCP_LAUNCHER_PREEXISTED=1
  cp -p "$MCP_LAUNCHER_PATH" "$ROLLBACK_ROOT/dev-flow-mcp" \
    || fail "Cannot preserve the previous managed MCP launcher for rollback."
fi
if [ -f "$MARKETPLACE_FILE" ]; then
  MARKETPLACE_PREEXISTED=1
  cp -p "$MARKETPLACE_FILE" "$ROLLBACK_ROOT/marketplace.json" \
    || fail "Cannot preserve the personal marketplace for rollback."
fi
if [ -f "$LAUNCHER_PATH" ]; then
  LAUNCHER_PREEXISTED=1
  cp -p "$LAUNCHER_PATH" "$ROLLBACK_ROOT/dev-flow" \
    || fail "Cannot preserve the previous managed CLI launcher for rollback."
fi

render_cli_launcher() {
  cli_plugin_root="$1"
  cli_destination="$2"
  DEV_FLOW_PLUGIN_ROOT="$cli_plugin_root" \
  DEV_FLOW_LAUNCHER_DESTINATION="$cli_destination" \
  DEV_FLOW_LAUNCHER_MARKER="$LAUNCHER_MARKER" \
  python_no_bytecode -I -S -c '
import os
from pathlib import Path
import shlex

plugin_root = Path(os.environ["DEV_FLOW_PLUGIN_ROOT"]).expanduser().resolve()
target = Path(os.environ["DEV_FLOW_LAUNCHER_DESTINATION"])
marker = os.environ["DEV_FLOW_LAUNCHER_MARKER"]
launcher = plugin_root / "scripts" / "dev_flow_python_launcher"
handler = plugin_root / "scripts" / "dev_flow.py"
if not launcher.is_file() or not handler.is_file():
    raise SystemExit("validated Dev Flow launcher sources are unavailable")
payload = "\n".join((
    "#!/bin/sh",
    marker,
    "set -eu",
    "export PYTHONDONTWRITEBYTECODE=1",
    "exec {} {} \"$@\"".format(
        shlex.quote(str(launcher)),
        shlex.quote(str(handler)),
    ),
    "",
)).encode("utf-8")
with target.open("xb") as stream:
    stream.write(payload)
    stream.flush()
    os.fsync(stream.fileno())
target.chmod(0o755)
'
}

inject_test_source_drift_at launcher-generation-before
render_cli_launcher "$CANDIDATE_PLUGIN_ROOT" "$ROLLBACK_ROOT/candidate-dev-flow" \
  || fail "Cannot stage the candidate dev-flow launcher."
if [ -n "$PREVIOUS_RELEASE_ID" ]; then
  render_cli_launcher "$PREVIOUS_PLUGIN_ROOT" "$ROLLBACK_ROOT/previous-dev-flow" \
    || fail "Cannot stage the previous dev-flow launcher for rollback."
fi
inject_test_source_drift_at launcher-generation-after

replace_launcher() {
  launcher_target="$1"
  launcher_expected="$2"
  launcher_replacement="$3"
  DEV_FLOW_LAUNCHER_TARGET="$launcher_target" \
  DEV_FLOW_LAUNCHER_EXPECTED="$launcher_expected" \
  DEV_FLOW_LAUNCHER_REPLACEMENT="$launcher_replacement" \
  python_no_bytecode -I -S -c '
import os
from pathlib import Path
import stat
import tempfile

target = Path(os.environ["DEV_FLOW_LAUNCHER_TARGET"])
expected_value = os.environ["DEV_FLOW_LAUNCHER_EXPECTED"]
replacement_value = os.environ["DEV_FLOW_LAUNCHER_REPLACEMENT"]

def regular_bytes(path):
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"launcher is not a regular file: {path}")
    return path.read_bytes()

if expected_value:
    expected = Path(expected_value)
    if not target.exists() or target.is_symlink() or regular_bytes(target) != regular_bytes(expected):
        raise SystemExit(f"launcher changed concurrently: {target}")
elif target.exists() or target.is_symlink():
    raise SystemExit(f"launcher appeared concurrently: {target}")

if not replacement_value:
    target.unlink()
else:
    replacement = Path(replacement_value)
    payload = regular_bytes(replacement)
    mode = stat.S_IMODE(replacement.stat().st_mode)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(str(temporary), str(target))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
'
}

stage_marketplace() {
  DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" \
  DEV_FLOW_MARKETPLACE_SNAPSHOT="$ROLLBACK_ROOT/marketplace-member.json" \
  DEV_FLOW_CANDIDATE_PLUGIN_ROOT="$CANDIDATE_PLUGIN_ROOT" \
  DEV_FLOW_PREVIOUS_PLUGIN_ROOT="$PREVIOUS_PLUGIN_ROOT" \
  python_no_bytecode -I -S -c '
import json
import os
from pathlib import Path

path = Path(os.environ["DEV_FLOW_MARKETPLACE_FILE"]).expanduser().resolve()
candidate_root = Path(os.environ["DEV_FLOW_CANDIDATE_PLUGIN_ROOT"]).resolve()
previous_value = os.environ["DEV_FLOW_PREVIOUS_PLUGIN_ROOT"]
previous_root = Path(previous_value).resolve() if previous_value else None
if path.name != "marketplace.json" or path.parent.name != "plugins" or path.parent.parent.name != ".agents":
    raise SystemExit(f"{path} must be located at <marketplace-root>/.agents/plugins/marketplace.json")
marketplace_root = path.parent.parent.parent

def local_path(root):
    try:
        relative = root.relative_to(marketplace_root)
    except ValueError:
        raise SystemExit(f"{root} must be inside marketplace root {marketplace_root}") from None
    return "./" + relative.as_posix()

if path.exists():
    try:
        marketplace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Cannot read {path}: {error}")
    if not isinstance(marketplace, dict) or not isinstance(marketplace.get("plugins"), list):
        raise SystemExit(f"{path} must be a JSON object with a plugins array")
else:
    marketplace = None
plugins = marketplace["plugins"] if marketplace is not None else []
matches = [item for item in plugins if isinstance(item, dict) and item.get("name") == "dev-flow-orchestrator"]
if len(matches) > 1:
    raise SystemExit(f"{path} contains duplicate Dev Flow entries")
previous_entry = matches[0] if matches else None
candidate_entry = {
    "name": "dev-flow-orchestrator",
    "source": {"source": "local", "path": local_path(candidate_root)},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}
sealed_previous = None
if previous_root is not None:
    sealed_previous = dict(previous_entry or candidate_entry)
    sealed_previous["name"] = "dev-flow-orchestrator"
    sealed_previous["source"] = {"source": "local", "path": local_path(previous_root)}
else:
    sealed_previous = previous_entry
snapshot = {
    "file_existed": marketplace is not None,
    "previous_entry": previous_entry,
    "sealed_previous_entry": sealed_previous,
    "candidate_entry": candidate_entry,
}
Path(os.environ["DEV_FLOW_MARKETPLACE_SNAPSHOT"]).write_text(
    json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
)
'
}

update_marketplace() {
  marketplace_mode="$1"
  DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" \
  DEV_FLOW_MARKETPLACE_SNAPSHOT="$ROLLBACK_ROOT/marketplace-member.json" \
  DEV_FLOW_MARKETPLACE_MODE="$marketplace_mode" \
  python_no_bytecode -I -S -c '
import json
import os
from pathlib import Path
import tempfile

path = Path(os.environ["DEV_FLOW_MARKETPLACE_FILE"]).expanduser().resolve()
snapshot = json.loads(Path(os.environ["DEV_FLOW_MARKETPLACE_SNAPSHOT"]).read_text(encoding="utf-8"))
mode = os.environ["DEV_FLOW_MARKETPLACE_MODE"]
if path.exists():
    marketplace = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(marketplace, dict) or not isinstance(marketplace.get("plugins"), list):
        raise SystemExit(f"{path} must be a JSON object with a plugins array")
else:
    marketplace = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
plugins = marketplace["plugins"]
indexes = [index for index, item in enumerate(plugins) if isinstance(item, dict) and item.get("name") == "dev-flow-orchestrator"]
if len(indexes) > 1:
    raise SystemExit(f"{path} contains duplicate Dev Flow entries")
current = plugins[indexes[0]] if indexes else None
expected = snapshot["previous_entry"] if mode == "candidate" else snapshot["candidate_entry"]
replacement = snapshot["candidate_entry"] if mode == "candidate" else snapshot["sealed_previous_entry"]
if current != expected:
    raise SystemExit("Dev Flow marketplace member changed concurrently")
if indexes:
    if replacement is None:
        del plugins[indexes[0]]
    else:
        plugins[indexes[0]] = replacement
elif replacement is not None:
    plugins.append(replacement)

default_without_plugins = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
if mode == "restore" and not snapshot["file_existed"] and marketplace == default_without_plugins:
    path.unlink()
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".marketplace.", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as stream:
            json.dump(marketplace, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
'
}

stage_marketplace || fail "Cannot stage the personal marketplace member update."

TRANSACTION_ID="tx-$(date -u '+%Y%m%dT%H%M%SZ')-$$"
TRANSACTION_DIR="$RUNTIME_ROOT/transactions"
if [ -L "$TRANSACTION_DIR" ] || { [ -e "$TRANSACTION_DIR" ] && [ ! -d "$TRANSACTION_DIR" ]; }; then
  fail "$TRANSACTION_DIR must be a regular directory."
fi
mkdir -p "$TRANSACTION_DIR"
TRANSACTION_PATH="$TRANSACTION_DIR/$TRANSACTION_ID.json"
RETAINED_PATHS_FILE="$ROLLBACK_ROOT/retained-paths"
printf '%s\n' "$CANDIDATE_RUNTIME_DIR" >"$RETAINED_PATHS_FILE"
if [ -n "$PREVIOUS_RUNTIME_DIR" ] && [ "$PREVIOUS_RUNTIME_DIR" != "$CANDIDATE_RUNTIME_DIR" ]; then
  printf '%s\n' "$PREVIOUS_RUNTIME_DIR" >>"$RETAINED_PATHS_FILE"
fi
append_runtime_retained_paths() {
  retained_result="$1"
  printf '%s' "$retained_result" | python_no_bytecode -I -S -c '
import json
import sys
value = json.load(sys.stdin)
paths = value.get("retained_paths", []) if isinstance(value, dict) else None
if not isinstance(paths, list) or not all(isinstance(path, str) and path for path in paths):
    raise SystemExit("managed runtime retained paths are invalid")
for path in paths:
    print(path)
' >>"$RETAINED_PATHS_FILE"
}
append_runtime_retained_paths "$CANDIDATE_RUNTIME_JSON" \
  || fail "Cannot interpret retained candidate runtime paths."
if [ -n "$PREVIOUS_RELEASE_ID" ] && [ "$PREVIOUS_RELEASE_ID" != "$CANDIDATE_RELEASE_ID" ]; then
  append_runtime_retained_paths "$PREVIOUS_RUNTIME_JSON" \
    || fail "Cannot interpret retained previous runtime paths."
fi

TX_STEP="staged"
TX_OUTCOME="in_progress"
case "$INSTALL_ACTION" in
  installed) TX_OPERATION="install" ;;
  upgraded) TX_OPERATION="upgrade" ;;
  repaired) TX_OPERATION="repair" ;;
esac
TX_PLUGIN_STATE="$( [ -n "$PREVIOUS_VERSION" ] && printf previous || printf absent )"
TX_MARKETPLACE_STATE="original"
TX_MCP_STATE="original"
TX_CLI_STATE="original"
TX_RUNTIME_STATE="candidate-staged"
TX_BLIND_RETRY_SAFE=true

write_transaction() {
  DEV_FLOW_TRANSACTION_PATH="$TRANSACTION_PATH" \
  DEV_FLOW_TRANSACTION_ID="$TRANSACTION_ID" \
  DEV_FLOW_TRANSACTION_OPERATION="$TX_OPERATION" \
  DEV_FLOW_PREVIOUS_RELEASE="$PREVIOUS_RELEASE_ID" \
  DEV_FLOW_CANDIDATE_RELEASE="$CANDIDATE_RELEASE_ID" \
  DEV_FLOW_TRANSACTION_STEP="$TX_STEP" \
  DEV_FLOW_TRANSACTION_OUTCOME="$TX_OUTCOME" \
  DEV_FLOW_TRANSACTION_PLUGIN="$TX_PLUGIN_STATE" \
  DEV_FLOW_TRANSACTION_MARKETPLACE="$TX_MARKETPLACE_STATE" \
  DEV_FLOW_TRANSACTION_MCP="$TX_MCP_STATE" \
  DEV_FLOW_TRANSACTION_CLI="$TX_CLI_STATE" \
  DEV_FLOW_TRANSACTION_RUNTIME="$TX_RUNTIME_STATE" \
  DEV_FLOW_TRANSACTION_BLIND_RETRY="$TX_BLIND_RETRY_SAFE" \
  DEV_FLOW_TRANSACTION_RETAINED="$RETAINED_PATHS_FILE" \
  python_no_bytecode -I -S -c '
import json
import os
from pathlib import Path
import tempfile

path = Path(os.environ["DEV_FLOW_TRANSACTION_PATH"])
if path.is_symlink() or (path.exists() and not path.is_file()):
    raise SystemExit("transaction record path is unsafe")
previous = os.environ["DEV_FLOW_PREVIOUS_RELEASE"] or None
record = {
    "schema": "dev-flow-install-transaction/0.4.0",
    "transaction_id": os.environ["DEV_FLOW_TRANSACTION_ID"],
    "operation": os.environ["DEV_FLOW_TRANSACTION_OPERATION"],
    "previous_release": previous,
    "candidate_release": os.environ["DEV_FLOW_CANDIDATE_RELEASE"],
    "current_step": os.environ["DEV_FLOW_TRANSACTION_STEP"],
    "components": {
        "plugin": os.environ["DEV_FLOW_TRANSACTION_PLUGIN"],
        "marketplace": os.environ["DEV_FLOW_TRANSACTION_MARKETPLACE"],
        "mcp_launcher": os.environ["DEV_FLOW_TRANSACTION_MCP"],
        "cli_launcher": os.environ["DEV_FLOW_TRANSACTION_CLI"],
        "runtime": os.environ["DEV_FLOW_TRANSACTION_RUNTIME"],
    },
    "outcome": os.environ["DEV_FLOW_TRANSACTION_OUTCOME"],
    "blind_retry_safe": os.environ["DEV_FLOW_TRANSACTION_BLIND_RETRY"] == "true",
    "retained_paths": Path(os.environ["DEV_FLOW_TRANSACTION_RETAINED"]).read_text(encoding="utf-8").splitlines(),
}
descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
temporary = Path(name)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as stream:
        json.dump(record, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
'
}

observe_plugin_state() {
  observed_json="$(codex plugin list --marketplace personal --json)" || return 1
  printf '%s' "$observed_json" | python_no_bytecode -I -S -c '
import json
import sys
payload = json.load(sys.stdin)
installed = payload.get("installed") if isinstance(payload, dict) else None
if not isinstance(installed, list):
    raise SystemExit("plugin list JSON must contain an installed array")
matches = [item for item in installed if isinstance(item, dict) and item.get("pluginId") == "dev-flow-orchestrator@personal" and item.get("installed") is True]
if len(matches) > 1:
    raise SystemExit("plugin list contains duplicate installed entries")
if not matches:
    print("absent")
else:
    version = matches[0].get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit("installed plugin version is invalid")
    print(("active:" if matches[0].get("enabled") is True else "inactive:") + version)
'
}

verify_mcp_health() {
  health_python="$1"
  health_plugin_root="$2"
  health_launcher="$3"
  health_json="$(
    PYTHONDONTWRITEBYTECODE=1 "$health_python" -B -I \
      "$health_plugin_root/scripts/validate_installed_stage1.py" \
      --plugin-root "$health_plugin_root" \
      --launcher "$health_launcher" \
      --smoke-only
  )" || return 1
  printf '%s' "$health_json" | python_no_bytecode -I -S -c '
import json
import sys
value = json.load(sys.stdin)
journey = value.get("journey") if isinstance(value, dict) else None
if value.get("ok") is not True or not isinstance(journey, dict) or journey.get("read_smoke") is not True or journey.get("mutation_smoke") is not True:
    raise SystemExit("installed MCP health evidence is incomplete")
'
}

PREVIOUS_PLUGIN_REMOVED=0
CANDIDATE_ADD_ATTEMPTED=0

rollback_activation() {
  rollback_reason="$1"
  ROLLBACK_READY=0
  rollback_ok=1
  TX_STEP="rolling-back"
  TX_OUTCOME="in_progress"
  write_transaction || rollback_ok=0

  if [ -n "$PREVIOUS_RELEASE_ID" ] \
    || [ "$TX_PLUGIN_STATE" = "candidate" ] \
    || [ "$TX_PLUGIN_STATE" = "unknown" ]; then
    codex plugin remove "$PLUGIN_ID" >/dev/null 2>&1 || true
    rollback_plugin_state="$(observe_plugin_state 2>/dev/null || printf unknown)"
    if [ "$rollback_plugin_state" = "absent" ]; then
      TX_PLUGIN_STATE="absent"
    else
      TX_PLUGIN_STATE="unknown"
      rollback_ok=0
    fi
  fi

  if [ "$TX_MARKETPLACE_STATE" = "candidate" ]; then
    if update_marketplace restore; then
      TX_MARKETPLACE_STATE="original"
    else
      TX_MARKETPLACE_STATE="unknown"
      rollback_ok=0
    fi
  fi

  if [ "$TX_MCP_STATE" = "candidate" ]; then
    previous_mcp_source=""
    if [ -n "$PREVIOUS_RELEASE_ID" ]; then
      previous_mcp_source="$PREVIOUS_MCP_LAUNCHER"
    elif [ "$MCP_LAUNCHER_PREEXISTED" = "1" ]; then
      previous_mcp_source="$ROLLBACK_ROOT/dev-flow-mcp"
    fi
    if replace_launcher "$MCP_LAUNCHER_PATH" "$CANDIDATE_MCP_LAUNCHER" "$previous_mcp_source"; then
      TX_MCP_STATE="original"
    else
      TX_MCP_STATE="unknown"
      rollback_ok=0
    fi
  fi

  if [ "$TX_CLI_STATE" = "candidate" ]; then
    previous_cli_source=""
    if [ -n "$PREVIOUS_RELEASE_ID" ]; then
      previous_cli_source="$ROLLBACK_ROOT/previous-dev-flow"
    elif [ "$LAUNCHER_PREEXISTED" = "1" ]; then
      previous_cli_source="$ROLLBACK_ROOT/dev-flow"
    fi
    if replace_launcher "$LAUNCHER_PATH" "$ROLLBACK_ROOT/candidate-dev-flow" "$previous_cli_source"; then
      TX_CLI_STATE="original"
    else
      TX_CLI_STATE="unknown"
      rollback_ok=0
    fi
  fi

  if [ -n "$PREVIOUS_RELEASE_ID" ]; then
    if [ "$TX_PLUGIN_STATE" = "absent" ]; then
      maybe_rollback_add=0
      codex plugin add "$PLUGIN_ID" >/dev/null 2>&1 || maybe_rollback_add=$?
    else
      maybe_rollback_add=1
    fi
    rollback_plugin_state="$(observe_plugin_state 2>/dev/null || printf unknown)"
    rollback_mcp_json="$(codex mcp list --json 2>/dev/null || printf invalid)"
    if [ "$rollback_plugin_state" = "active:$PREVIOUS_VERSION" ] \
      && printf '%s' "$rollback_mcp_json" | check_mcp_registration_state 1 >/dev/null 2>&1 \
      && verify_mcp_health "$PREVIOUS_RUNTIME_PYTHON" "$PREVIOUS_PLUGIN_ROOT" "$MCP_LAUNCHER_PATH" \
      && PYTHONDONTWRITEBYTECODE=1 "$LAUNCHER_PATH" web status >/dev/null 2>&1; then
      TX_PLUGIN_STATE="previous"
    else
      TX_PLUGIN_STATE="unknown"
      rollback_ok=0
    fi
  elif [ "$TX_PLUGIN_STATE" != "absent" ]; then
    rollback_ok=0
  fi

  if [ "$rollback_ok" = "1" ]; then
    TX_STEP="rolled-back"
    TX_OUTCOME="rolled_back"
    TX_RUNTIME_STATE="candidate-retained"
    TX_BLIND_RETRY_SAFE=true
    write_transaction || rollback_ok=0
  fi
  if [ "$rollback_ok" = "1" ]; then
    if [ -n "$PREVIOUS_RELEASE_ID" ]; then
      printf 'Previous plugin activation was restored and verified after the failed candidate.\n' >&2
    fi
  else
    TX_STEP="rollback-incomplete"
    TX_OUTCOME="partial"
    TX_RUNTIME_STATE="candidate-retained"
    TX_BLIND_RETRY_SAFE=false
    write_transaction || true
    printf 'Installation rollback is partial; blind_retry_safe=false.\n' >&2
    printf 'Retained release paths are recorded in %s.\n' "$TRANSACTION_PATH" >&2
  fi
  printf 'Plugin activation failed: %s\n' "$rollback_reason" >&2
  printf 'Inspect transaction state at: %s\n' "$TRANSACTION_PATH" >&2
  return 0
}

write_transaction || fail "Cannot create the bounded installation transaction record."
ROLLBACK_READY=1
maybe_fail_at runtime-promotion

maybe_fail_at mcp-launcher
printf 'Installing the dev-flow-mcp PATH launcher...\n'
expected_mcp=""
[ "$MCP_LAUNCHER_PREEXISTED" = "0" ] || expected_mcp="$ROLLBACK_ROOT/dev-flow-mcp"
replace_launcher "$MCP_LAUNCHER_PATH" "$expected_mcp" "$CANDIDATE_MCP_LAUNCHER" \
  || fail "Cannot install the exact managed dev-flow-mcp launcher at $MCP_LAUNCHER_PATH."
TX_MCP_STATE="candidate"
TX_STEP="mcp-launcher"
write_transaction || fail "Cannot record the managed MCP launcher update."

maybe_fail_at cli-launcher
printf 'Installing the dev-flow PATH launcher...\n'
expected_cli=""
[ "$LAUNCHER_PREEXISTED" = "0" ] || expected_cli="$ROLLBACK_ROOT/dev-flow"
replace_launcher "$LAUNCHER_PATH" "$expected_cli" "$ROLLBACK_ROOT/candidate-dev-flow" \
  || fail "Cannot install the dev-flow launcher at $LAUNCHER_PATH."
TX_CLI_STATE="candidate"
TX_STEP="cli-launcher"
write_transaction || fail "Cannot record the CLI launcher update."

maybe_fail_at marketplace
inject_test_source_drift_at marketplace-write-before
update_marketplace candidate || fail "Cannot update the Dev Flow marketplace member."
inject_test_source_drift_at marketplace-write-after
TX_MARKETPLACE_STATE="candidate"
TX_STEP="marketplace"
write_transaction || fail "Cannot record the marketplace member update."

if [ -n "$PREVIOUS_VERSION" ]; then
  maybe_fail_at plugin-remove
  remove_status=0
  codex plugin remove "$PLUGIN_ID" || remove_status=$?
  observed_after_remove="$(observe_plugin_state || printf unknown)"
  if [ "$observed_after_remove" != "absent" ]; then
    TX_PLUGIN_STATE="unknown"
    fail "Cannot remove $PLUGIN_ID or prove it absent. Finish or cancel active Dev Flow tasks, then rerun this installer."
  fi
  PREVIOUS_PLUGIN_REMOVED=1
  TX_PLUGIN_STATE="absent"
  TX_STEP="plugin-removed"
  write_transaction || fail "Cannot record the observed plugin removal."
fi

maybe_fail_at plugin-add
inject_test_source_drift_at plugin-add-before
printf 'Installing the Codex plugin...\n'
CANDIDATE_ADD_ATTEMPTED=1
add_status=0
codex plugin add "$PLUGIN_ID" || add_status=$?
inject_test_source_drift_at plugin-add-after
observed_after_add="$(observe_plugin_state || printf unknown)"
if [ "$observed_after_add" != "active:$PLUGIN_VERSION" ]; then
  if [ "$observed_after_add" = "absent" ]; then
    TX_PLUGIN_STATE="absent"
  else
    TX_PLUGIN_STATE="unknown"
  fi
  if [ "$add_status" -ne 0 ]; then
    fail "Codex rejected the candidate plugin (command status $add_status). Rerun this installer after resolving the error above."
  fi
  fail "Codex did not expose the candidate plugin after activation."
fi
TX_PLUGIN_STATE="candidate"
TX_STEP="plugin-active"
write_transaction || fail "Cannot record the observed plugin activation."

printf 'Verifying bundled MCP registration visibility...\n'
POST_MCP_LIST_JSON="$(codex mcp list --json)" \
  || fail "Codex could not report MCP registrations after activation."
printf '%s' "$POST_MCP_LIST_JSON" | check_mcp_registration_state 1 \
  || fail "The activated bundled MCP registration is missing, disabled, duplicated, or shadowed."

maybe_fail_at health
inject_test_source_drift_at health-before
printf 'Running the installed MCP protocol health check...\n'
verify_mcp_health "$RUNTIME_PYTHON" "$CANDIDATE_PLUGIN_ROOT" "$MCP_LAUNCHER_PATH" \
  || fail "The real installed launcher failed initialize, catalog, read, or mutation smoke."
inject_test_source_drift_at health-after
TX_STEP="candidate-healthy"
write_transaction || fail "Cannot record the candidate MCP health result."

maybe_fail_at final-smoke
printf 'Running the installed CLI smoke check...\n'
PYTHONDONTWRITEBYTECODE=1 "$LAUNCHER_PATH" web status >/dev/null \
  || fail "The installed dev-flow launcher failed its final CLI smoke."
TX_STEP="final-smoke"
write_transaction || fail "Cannot record the final launcher smoke."

maybe_fail_at commit
inject_test_source_drift_at success-receipt-before
TX_STEP="committed"
TX_OUTCOME="committed"
TX_RUNTIME_STATE="candidate-active"
TX_BLIND_RETRY_SAFE=true
write_transaction || fail "Cannot publish the committed installation transaction."
INSTALL_COMMITTED=1
ROLLBACK_READY=0

case "$INSTALL_ACTION" in
  installed)
    ACTION_COLOR="$NEON_GREEN"
    ;;
  upgraded)
    ACTION_COLOR="$NEON_CYAN"
    ;;
  repaired)
    ACTION_COLOR="$NEON_PURPLE"
    ;;
esac

printf '\n%s%s┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓%s\n' \
  "$TEXT_BOLD" "$NEON_CYAN" "$COLOR_RESET"
printf '%s%s┃%s  %sDEV FLOW ORCHESTRATOR%s  %s// SYSTEM ONLINE%s\n' \
  "$TEXT_BOLD" "$NEON_CYAN" "$COLOR_RESET" \
  "$BRIGHT_WHITE" "$COLOR_RESET" "$NEON_PURPLE" "$COLOR_RESET"
printf '%s%s┃%s  %sCONTROL PLANE READY%s  %s·%s  VERSION %s%s%s\n' \
  "$TEXT_BOLD" "$NEON_CYAN" "$COLOR_RESET" \
  "$NEON_GREEN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" \
  "$NEON_BLUE" "$PLUGIN_VERSION" "$COLOR_RESET"
printf '%s%s┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛%s\n' \
  "$TEXT_BOLD" "$NEON_CYAN" "$COLOR_RESET"

printf '\n%s%s╭─ INSTALLATION RECEIPT%s\n' \
  "$TEXT_BOLD" "$NEON_PURPLE" "$COLOR_RESET"
printf '%s│%s  %sPLUGIN%s     %s\n' \
  "$NEON_PURPLE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$PLUGIN_ID"
printf '%s│%s  %sACTION%s     %s%s%s\n' \
  "$NEON_PURPLE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" \
  "$ACTION_COLOR" "$INSTALL_ACTION" "$COLOR_RESET"
if [ -n "$PREVIOUS_VERSION" ]; then
  printf '%s│%s  %sPREVIOUS%s   %s\n' \
    "$NEON_PURPLE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" \
    "$PREVIOUS_VERSION"
fi
printf '%s│%s  %sINSTALLED%s  %s%s%s\n' \
  "$NEON_PURPLE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" \
  "$NEON_GREEN" "$PLUGIN_VERSION" "$COLOR_RESET"
printf '%s╰─%s\n' "$NEON_PURPLE" "$COLOR_RESET"

printf '\n%s%s╭─ DIRECTORIES TOUCHED%s\n' \
  "$TEXT_BOLD" "$NEON_BLUE" "$COLOR_RESET"
printf '%s├─%s %sSOURCE%s       %s\n' \
  "$NEON_BLUE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$SOURCE_ROOT"
printf '%s├─%s %sMARKETPLACE%s  %s\n' \
  "$NEON_BLUE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" \
  "$(dirname "$MARKETPLACE_FILE")"
printf '%s├─%s %sCOMMAND%s      %s\n' \
  "$NEON_BLUE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$LAUNCHER_PATH"
printf '%s╰─%s %sCODEX STATE%s  %s\n' \
  "$NEON_BLUE" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$CODEX_ROOT"

printf '\n%s%s▶ NEXT MISSION%s\n' "$TEXT_BOLD" "$NEON_GREEN" "$COLOR_RESET"
printf '  %s1.%s Start a new Codex task and confirm the dev-flow MCP server is enabled.\n' \
  "$NEON_CYAN" "$COLOR_RESET"
printf '  %s2.%s Ask Codex to call dev_flow_server_info, then start a task for:\n\n' "$NEON_CYAN" "$COLOR_RESET"
printf '%s%s  <your requirement>%s\n' \
  "$TEXT_BOLD" "$BRIGHT_WHITE" "$COLOR_RESET"
printf '\n  Web UI: dev-flow web start\n'
