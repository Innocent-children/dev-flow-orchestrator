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
  printf 'Dev Flow installation failed: %s\n' "$1" >&2
  exit 1
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

  if [ "$CURRENT_HEAD" != "$APPROVED_HEAD" ]; then
    if git -C "$SOURCE_ROOT" merge-base --is-ancestor "$CURRENT_HEAD" "$APPROVED_HEAD"; then
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

"$PYTHON" -c 'import struct,sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) and struct.calcsize("P") == 8 else 1)' \
  || fail "64-bit Python 3.10-3.14 is required."

if [ "$(uname -s)" != "Darwin" ]; then
  fail "This Dev Flow installer supports macOS; use the documented PowerShell installer on Windows."
fi

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

printf 'Validating the package...\n'
"$PYTHON" -I -S "$SOURCE_ROOT/scripts/validate_package.py"
PLUGIN_VERSION="$(
  "$PYTHON" -I -S -c '
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = manifest.get("version")
if not isinstance(version, str) or not version:
    raise SystemExit("plugin manifest must contain a non-empty version")
print(version)
' "$SOURCE_ROOT/.codex-plugin/plugin.json"
)" || fail "Cannot read the validated plugin version."

printf 'Inspecting the installed Codex plugin...\n'
PLUGIN_LIST_JSON="$(codex plugin list --marketplace personal --json)" \
  || fail "Cannot inspect the installed Codex plugins."
PLUGIN_STATE="$(
  printf '%s' "$PLUGIN_LIST_JSON" | "$PYTHON" -I -S -c '
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
  "$PYTHON" -I -S -c '
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

printf 'Building the isolated locked MCP runtime...\n'
RUNTIME_JSON="$(
  "$PYTHON" "$SOURCE_ROOT/scripts/manage_runtime.py" \
    --source-root "$SOURCE_ROOT" \
    --runtime-root "$RUNTIME_ROOT" \
    --source-commit "$VERIFIED_HEAD" \
    --data-root "$DATA_ROOT"
)" || fail "Cannot build and validate the managed MCP runtime."
RUNTIME_PYTHON="$(
  printf '%s' "$RUNTIME_JSON" | "$PYTHON" -I -S -c '
import json
import os
import sys
from pathlib import Path
payload = json.load(sys.stdin)
runtime = Path(payload["runtime_dir"])
python = runtime / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if payload.get("ok") is not True or not python.is_file():
    raise SystemExit("managed runtime result is invalid")
print(python)
'
)" || fail "Cannot interpret the managed MCP runtime result."

ROLLBACK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dev-flow-install-rollback.XXXXXX")" \
  || fail "Cannot create the bounded installation rollback directory."
INSTALL_COMMITTED=0
MCP_LAUNCHER_PREEXISTED=0
MARKETPLACE_PREEXISTED=0
cleanup_rollback() {
  if [ "$INSTALL_COMMITTED" != "1" ]; then
    if [ "$MARKETPLACE_PREEXISTED" = "1" ] && [ -f "$ROLLBACK_ROOT/marketplace.json" ]; then
      cp -p "$ROLLBACK_ROOT/marketplace.json" "$MARKETPLACE_FILE" || true
    elif [ "$MARKETPLACE_PREEXISTED" = "0" ]; then
      rm -f "$MARKETPLACE_FILE"
    fi
    if [ "$MCP_LAUNCHER_PREEXISTED" = "1" ] && [ -f "$ROLLBACK_ROOT/dev-flow-mcp" ]; then
      cp -p "$ROLLBACK_ROOT/dev-flow-mcp" "$MCP_LAUNCHER_PATH" || true
    elif [ "$MCP_LAUNCHER_PREEXISTED" = "0" ]; then
      rm -f "$MCP_LAUNCHER_PATH"
    fi
  fi
  rm -rf "$ROLLBACK_ROOT"
}
trap cleanup_rollback EXIT HUP INT TERM
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

printf 'Installing the dev-flow-mcp PATH launcher...\n'
DEV_FLOW_BIN_DIR="$BIN_DIR" \
DEV_FLOW_RUNTIME_PYTHON="$RUNTIME_PYTHON" \
DEV_FLOW_MCP_LAUNCHER_MARKER="$MCP_LAUNCHER_MARKER" \
DEV_FLOW_SOURCE_ROOT="$SOURCE_ROOT" \
"$PYTHON" -I -S -c '
import os
from pathlib import Path
import shlex
import tempfile

bin_dir = Path(os.environ["DEV_FLOW_BIN_DIR"]).expanduser().resolve()
# Keep the venv interpreter path itself.  On POSIX it is commonly a symlink;
# resolving that symlink would execute the base interpreter outside the venv.
runtime_python = Path(
    os.path.abspath(os.path.expanduser(os.environ["DEV_FLOW_RUNTIME_PYTHON"]))
)
target = bin_dir / "dev-flow-mcp"
marker = os.environ["DEV_FLOW_MCP_LAUNCHER_MARKER"]
template = Path(os.environ["DEV_FLOW_SOURCE_ROOT"]) / "scripts" / "dev_flow_mcp_launcher"
if not runtime_python.is_file():
    raise SystemExit("validated managed runtime Python is unavailable")
if not template.is_file() or template.is_symlink():
    raise SystemExit("validated POSIX MCP launcher template is unavailable")
template_text = template.read_text(encoding="utf-8")
placeholder = "__DEV_FLOW_RUNTIME_PYTHON__"
if (
    template_text.count(placeholder) != 1
    or template_text.splitlines()[:2] != ["#!/bin/sh", marker]
):
    raise SystemExit("validated POSIX MCP launcher template is invalid")
payload = template_text.replace(
    placeholder,
    shlex.quote(str(runtime_python)),
).encode("utf-8")
descriptor, temporary_name = tempfile.mkstemp(prefix=".dev-flow-mcp.", dir=str(bin_dir))
temporary = Path(temporary_name)
try:
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o755)
    os.replace(str(temporary), str(target))
finally:
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
' || fail "Cannot install the dev-flow-mcp launcher at $MCP_LAUNCHER_PATH."

mkdir -p "$(dirname "$MARKETPLACE_FILE")"
DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" \
DEV_FLOW_SOURCE_ROOT="$SOURCE_ROOT" \
"$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["DEV_FLOW_MARKETPLACE_FILE"]).expanduser().resolve()
source_root = Path(os.environ["DEV_FLOW_SOURCE_ROOT"]).expanduser().resolve()
if (
    path.name != "marketplace.json"
    or path.parent.name != "plugins"
    or path.parent.parent.name != ".agents"
):
    raise SystemExit(
        f"{path} must be located at "
        "<marketplace-root>/.agents/plugins/marketplace.json"
    )
marketplace_root = path.parent.parent.parent
try:
    relative_source = source_root.relative_to(marketplace_root)
except ValueError:
    raise SystemExit(
        f"{source_root} must be inside marketplace root {marketplace_root}"
    ) from None
source_path = "./" + relative_source.as_posix()
entry = {
    "name": "dev-flow-orchestrator",
    "source": {"source": "local", "path": source_path},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}

if path.exists():
    try:
        marketplace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Cannot read {path}: {error}")
    if not isinstance(marketplace, dict) or not isinstance(marketplace.get("plugins"), list):
        raise SystemExit(f"{path} must be a JSON object with a plugins array")
else:
    marketplace = {
        "name": "personal",
        "interface": {"displayName": "Personal"},
        "plugins": [],
    }

matches = [
    item
    for item in marketplace["plugins"]
    if isinstance(item, dict) and item.get("name") == entry["name"]
]
if len(matches) > 1:
    raise SystemExit(f"{path} contains duplicate Dev Flow entries")
marketplace["plugins"] = [
    item
    for item in marketplace["plugins"]
    if not (isinstance(item, dict) and item.get("name") == entry["name"])
] + [entry]

temporary = path.with_name(path.name + ".tmp")
temporary.write_text(json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.replace(path)
print(f"Updated {path}")
PY

PREVIOUS_PLUGIN_REMOVED=0
NEW_PLUGIN_ACTIVE=0
rollback_activation() {
  reason="$1"
  if [ "$NEW_PLUGIN_ACTIVE" = "1" ]; then
    codex plugin remove "$PLUGIN_ID" >/dev/null 2>&1 || true
  fi
  if [ "$MARKETPLACE_PREEXISTED" = "1" ]; then
    cp -p "$ROLLBACK_ROOT/marketplace.json" "$MARKETPLACE_FILE" || true
  else
    rm -f "$MARKETPLACE_FILE"
  fi
  if [ "$MCP_LAUNCHER_PREEXISTED" = "1" ]; then
    cp -p "$ROLLBACK_ROOT/dev-flow-mcp" "$MCP_LAUNCHER_PATH" || true
  else
    rm -f "$MCP_LAUNCHER_PATH"
  fi
  if [ "$PREVIOUS_PLUGIN_REMOVED" = "1" ]; then
    if codex plugin add "$PLUGIN_ID" >/dev/null 2>&1; then
      printf 'Previous plugin activation was restored after the failed candidate.\n' >&2
    else
      printf 'Previous plugin reactivation also failed; after resolving Codex, run: codex plugin add %s\n' "$PLUGIN_ID" >&2
    fi
  fi
  printf 'Plugin activation failed: %s\n' "$reason" >&2
  printf 'Recovery: codex plugin remove %s && codex plugin add %s\n' "$PLUGIN_ID" "$PLUGIN_ID" >&2
  printf 'Inspect MCP state with: codex mcp list --json\n' >&2
  exit 1
}

# Existing plugin removal is delayed until the candidate runtime, launcher,
# marketplace entry, and candidate package have all passed their staged gates.
if [ -n "$PREVIOUS_VERSION" ]; then
  if ! codex plugin remove "$PLUGIN_ID"; then
    fail "Cannot remove $PLUGIN_ID. Finish or cancel active Dev Flow tasks, then rerun this installer."
  fi
  PREVIOUS_PLUGIN_REMOVED=1
fi

printf 'Installing the Codex plugin...\n'
if ! codex plugin add "$PLUGIN_ID"; then
  rollback_activation "Codex rejected the candidate plugin. Rerun this installer after resolving the error above."
fi
NEW_PLUGIN_ACTIVE=1

printf 'Verifying installed plugin visibility...\n'
POST_PLUGIN_LIST_JSON="$(codex plugin list --marketplace personal --json)" \
  || rollback_activation "Codex could not report the installed plugin after activation."
printf '%s' "$POST_PLUGIN_LIST_JSON" | DEV_FLOW_EXPECTED_VERSION="$PLUGIN_VERSION" "$PYTHON" -I -S -c '
import json
import os
import sys
payload = json.load(sys.stdin)
installed = payload.get("installed") if isinstance(payload, dict) else None
matches = [
    item for item in installed or []
    if isinstance(item, dict)
    and item.get("pluginId") == "dev-flow-orchestrator@personal"
    and item.get("installed") is True
    and item.get("enabled") is True
]
if len(matches) != 1 or matches[0].get("version") != os.environ["DEV_FLOW_EXPECTED_VERSION"]:
    raise SystemExit("activated plugin identity/version is not visible")
' || rollback_activation "The activated plugin identity or release is not visible."

printf 'Verifying bundled MCP registration visibility...\n'
POST_MCP_LIST_JSON="$(codex mcp list --json)" \
  || rollback_activation "Codex could not report MCP registrations after activation."
printf '%s' "$POST_MCP_LIST_JSON" | check_mcp_registration_state 1 \
  || rollback_activation "The activated bundled MCP registration is missing, disabled, duplicated, or shadowed."

printf 'Running the installed MCP protocol health check...\n'
MCP_HEALTH_JSON="$(
  "$RUNTIME_PYTHON" -I "$SOURCE_ROOT/scripts/validate_installed_stage1.py" \
    --plugin-root "$SOURCE_ROOT" \
    --launcher "$MCP_LAUNCHER_PATH" \
    --smoke-only
)" || rollback_activation "The real installed launcher failed initialize, catalog, read, or mutation smoke."
printf '%s' "$MCP_HEALTH_JSON" | "$PYTHON" -I -S -c '
import json
import sys
value = json.load(sys.stdin)
journey = value.get("journey") if isinstance(value, dict) else None
if (
    value.get("ok") is not True
    or not isinstance(journey, dict)
    or journey.get("read_smoke") is not True
    or journey.get("mutation_smoke") is not True
):
    raise SystemExit("installed MCP health evidence is incomplete")
' || rollback_activation "The installed MCP health evidence is invalid."

printf 'Installing the dev-flow PATH launcher...\n'
mkdir -p "$BIN_DIR"
DEV_FLOW_BIN_DIR="$BIN_DIR" \
DEV_FLOW_SOURCE_ROOT="$SOURCE_ROOT" \
DEV_FLOW_LAUNCHER_MARKER="$LAUNCHER_MARKER" \
"$PYTHON" -I -S -c '
import os
from pathlib import Path
import shlex
import tempfile

bin_dir = Path(os.environ["DEV_FLOW_BIN_DIR"]).expanduser().resolve()
source_root = Path(os.environ["DEV_FLOW_SOURCE_ROOT"]).expanduser().resolve()
target = bin_dir / "dev-flow"
marker = os.environ["DEV_FLOW_LAUNCHER_MARKER"]
launcher = source_root / "scripts" / "dev_flow_python_launcher"
handler = source_root / "scripts" / "dev_flow.py"
if not launcher.is_file() or not handler.is_file():
    raise SystemExit("validated Dev Flow launcher sources are unavailable")
payload = "\n".join((
    "#!/bin/sh",
    marker,
    "set -eu",
    "exec {} {} \"$@\"".format(
        shlex.quote(str(launcher)),
        shlex.quote(str(handler)),
    ),
    "",
)).encode("utf-8")
descriptor, temporary_name = tempfile.mkstemp(prefix=".dev-flow.", dir=str(bin_dir))
temporary = Path(temporary_name)
try:
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o755)
    os.replace(str(temporary), str(target))
finally:
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
' || fail "Cannot install the dev-flow launcher at $LAUNCHER_PATH."

INSTALL_COMMITTED=1

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
