#!/bin/sh
set -eu

DEFAULT_REPOSITORY_URL="https://github.com/Innocent-children/dev-flow-orchestrator.git"
REPOSITORY_URL="${DEV_FLOW_REPOSITORY_URL:-$DEFAULT_REPOSITORY_URL}"
REPOSITORY_REF="main"
SOURCE_ROOT="${DEV_FLOW_SOURCE_ROOT:-$HOME/plugins/dev-flow-orchestrator}"
MARKETPLACE_FILE="${DEV_FLOW_MARKETPLACE_FILE:-$HOME/.agents/plugins/marketplace.json}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
RUNTIME_ROOT="${DEV_FLOW_RUNTIME_HOME:-$HOME/.local/share/dev-flow-orchestrator/runtime}"
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
  printf 'Dev Flow uninstallation failed: PATH has no writable absolute directory; set DEV_FLOW_BIN_DIR explicitly.\n' >&2
  exit 1
}
LAUNCHER_PATH="$BIN_DIR/dev-flow"
MCP_LAUNCHER_PATH="$BIN_DIR/dev-flow-mcp"
PLUGIN_ID="dev-flow-orchestrator@personal"
LAUNCHER_MARKER="# dev-flow-orchestrator managed launcher"
MCP_LAUNCHER_MARKER="# dev-flow-orchestrator managed MCP launcher"
REMOVE_SOURCE=1

usage() {
  printf 'Usage: uninstall.sh [--keep-source]\n'
  printf '\n'
  printf 'Removes the Codex plugin and its personal marketplace entry.\n'
  printf 'The clean installer-managed source checkout is removed by default.\n'
  printf 'External Dev Flow task data is always preserved.\n'
}

fail() {
  printf 'Dev Flow uninstallation failed: %s\n' "$1" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --keep-source)
      REMOVE_SOURCE=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument '$1'."
      ;;
  esac
  shift
done

command -v git >/dev/null 2>&1 || fail "Git is required."
command -v codex >/dev/null 2>&1 || fail "Codex with plugin support is required."

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  fail "Python 3.10-3.14 is required."
fi

LAUNCHER_STATE="already absent"
if [ -e "$LAUNCHER_PATH" ] || [ -L "$LAUNCHER_PATH" ]; then
  [ ! -L "$LAUNCHER_PATH" ] && [ -f "$LAUNCHER_PATH" ] \
    || fail "$LAUNCHER_PATH is not a regular installer-managed launcher."
  grep -Fqx "$LAUNCHER_MARKER" "$LAUNCHER_PATH" \
    || fail "$LAUNCHER_PATH exists but is not owned by Dev Flow; preserve it and remove it manually."
  LAUNCHER_STATE="present"
fi
MCP_LAUNCHER_STATE="already absent"
if [ -e "$MCP_LAUNCHER_PATH" ] || [ -L "$MCP_LAUNCHER_PATH" ]; then
  [ ! -L "$MCP_LAUNCHER_PATH" ] && [ -f "$MCP_LAUNCHER_PATH" ] \
    || fail "$MCP_LAUNCHER_PATH is not a regular installer-managed launcher."
  grep -Fqx "$MCP_LAUNCHER_MARKER" "$MCP_LAUNCHER_PATH" \
    || fail "$MCP_LAUNCHER_PATH exists but is not owned by Dev Flow; preserve it and remove it manually."
  MCP_LAUNCHER_STATE="present"
fi

RUNTIME_STATE="already absent"
if [ -e "$RUNTIME_ROOT" ] || [ -L "$RUNTIME_ROOT" ]; then
  [ ! -L "$RUNTIME_ROOT" ] && [ -d "$RUNTIME_ROOT" ] \
    || fail "$RUNTIME_ROOT is not a regular managed runtime directory."
  [ -f "$RUNTIME_ROOT/.dev-flow-managed-runtime" ] \
    && [ "$(cat "$RUNTIME_ROOT/.dev-flow-managed-runtime")" = "dev-flow-managed-runtime/1" ] \
    || fail "$RUNTIME_ROOT does not have the Dev Flow managed-runtime marker."
  DEV_FLOW_RUNTIME_ROOT="$RUNTIME_ROOT" "$PYTHON" -I -S -c '
import datetime
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["DEV_FLOW_RUNTIME_ROOT"]).expanduser().resolve()
releases = root / "releases"
if not releases.is_dir() or releases.is_symlink():
    raise SystemExit("managed runtime releases directory is missing or unsafe")
release_dirs = sorted(releases.iterdir())
if not release_dirs:
    raise SystemExit("managed runtime has no receipt-owned release")

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

for release in release_dirs:
    if not release.is_dir() or release.is_symlink():
        raise SystemExit("managed runtime contains a non-release entry")
    receipt_path = release / "runtime-receipt.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit("managed runtime receipt cannot be read") from error
    fields = {
        "schema", "release_version", "source_commit", "python",
        "dependency_lock_sha256", "launcher_identity", "runtime_identity",
        "activation_action", "activated_at",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise SystemExit("managed runtime receipt fields are invalid")
    commit = receipt.get("source_commit")
    lock = receipt.get("dependency_lock_sha256")
    python = receipt.get("python")
    if (
        receipt.get("schema") != "dev-flow-runtime-receipt/1.0.0"
        or receipt.get("release_version") != "0.5.0"
        or receipt.get("launcher_identity") != "dev-flow-mcp --stdio"
        or receipt.get("runtime_identity") != hashlib.sha256(
            os.path.normcase(str(release.resolve())).encode("utf-8")
        ).hexdigest()
        or receipt.get("activation_action") not in {"create", "update"}
        or not isinstance(commit, str) or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or not isinstance(lock, str) or len(lock) != 64
        or any(character not in "0123456789abcdef" for character in lock)
        or not isinstance(python, dict)
        or set(python) != {"executable_sha256", "version", "architecture", "bits"}
        or python.get("bits") != 64
        or release.name != "{}-{}-{}".format(receipt["release_version"], commit[:12], lock[:12])
    ):
        raise SystemExit("managed runtime receipt identity is invalid")
    executable = release / "venv" / "bin" / "python"
    if not executable.is_file() or sha256(executable) != python.get("executable_sha256"):
        raise SystemExit("managed runtime Python does not match its receipt")
    try:
        datetime.datetime.fromisoformat(str(receipt["activated_at"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise SystemExit("managed runtime activation timestamp is invalid") from error
' || fail "$RUNTIME_ROOT contains a missing, stale, or mismatched runtime ownership receipt; preserve it for manual handling."
  RUNTIME_STATE="present"
fi

"$PYTHON" -c 'import struct,sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) and struct.calcsize("P") == 8 else 1)' \
  || fail "64-bit Python 3.10-3.14 is required."

if [ "$(uname -s)" != "Darwin" ]; then
  fail "This Dev Flow uninstaller supports macOS; use the documented PowerShell uninstaller on Windows."
fi

NEON_CYAN=""
NEON_PURPLE=""
NEON_GREEN=""
TEXT_DIM=""
TEXT_BOLD=""
COLOR_RESET=""
if [ -z "${NO_COLOR:-}" ] && {
  [ "${DEV_FLOW_FORCE_COLOR:-0}" = "1" ] \
    || { [ -t 1 ] && [ "${TERM:-}" != "dumb" ]; }
}; then
  COLOR_ESCAPE="$(printf '\033')"
  NEON_CYAN="${COLOR_ESCAPE}[38;5;51m"
  NEON_PURPLE="${COLOR_ESCAPE}[38;5;213m"
  NEON_GREEN="${COLOR_ESCAPE}[38;5;82m"
  TEXT_DIM="${COLOR_ESCAPE}[2m"
  TEXT_BOLD="${COLOR_ESCAPE}[1m"
  COLOR_RESET="${COLOR_ESCAPE}[0m"
fi

MARKETPLACE_STATE="$(
  DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" "$PYTHON" -I -S -c '
import json
import os
from pathlib import Path

path = Path(os.environ["DEV_FLOW_MARKETPLACE_FILE"]).expanduser().resolve()
if (
    path.name != "marketplace.json"
    or path.parent.name != "plugins"
    or path.parent.parent.name != ".agents"
):
    raise SystemExit(
        f"{path} must be located at "
        "<marketplace-root>/.agents/plugins/marketplace.json"
    )
if not path.exists():
    print("absent")
else:
    try:
        marketplace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Cannot read {path}: {error}")
    if not isinstance(marketplace, dict) or not isinstance(
        marketplace.get("plugins"), list
    ):
        raise SystemExit(f"{path} must be a JSON object with a plugins array")
    matches = [
        item
        for item in marketplace["plugins"]
        if isinstance(item, dict)
        and item.get("name") == "dev-flow-orchestrator"
    ]
    if len(matches) > 1:
        raise SystemExit(f"{path} contains duplicate Dev Flow entries")
    print("present" if matches else "no-entry")
'
)" || fail "Cannot validate the personal marketplace before uninstalling."

printf 'Inspecting the installed Codex plugin...\n'
PLUGIN_LIST_JSON="$(codex plugin list --json)" \
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
    raise SystemExit("plugin list contains duplicate Dev Flow entries")
if not matches or matches[0].get("installed") is not True:
    print("not-installed")
elif matches[0].get("enabled") is True:
    print("installed-active")
else:
    print("installed-inactive")
'
)" || fail "Cannot interpret the installed Codex plugin state."

PLUGIN_BUNDLED_ACTIVE=0
if [ "$PLUGIN_STATE" = "installed-active" ]; then
  PLUGIN_BUNDLED_ACTIVE=1
fi

MCP_LIST_JSON="$(codex mcp list --json)" \
  || fail "Cannot inspect standalone MCP registrations before uninstalling."
printf '%s' "$MCP_LIST_JSON" | \
  DEV_FLOW_PLUGIN_BUNDLED_ACTIVE="$PLUGIN_BUNDLED_ACTIVE" \
  DEV_FLOW_CODEX_CONFIG="$CODEX_ROOT/config.toml" \
  DEV_FLOW_MCP_LAUNCHER="$MCP_LAUNCHER_PATH" \
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
            registration_name = next(value for value in values[:3] if value is not None)
            command = next(value for value in values[3:] if value is not None)
            if owned_command(command):
                names.append(registration_name)
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
        "remove them explicitly before uninstalling bundled mode".format(
            ", ".join(sorted(explicit_owned)), config_path
        )
    )

owned_rows = [item for item in payload if isinstance(item, dict) and is_owned(item)]
canonical = [item for item in payload if is_canonical(item)]
if os.environ["DEV_FLOW_PLUGIN_BUNDLED_ACTIVE"] == "1":
    if len(canonical) != 1 or len(owned_rows) != 1:
        raise SystemExit(
            "active bundled plugin must expose exactly one enabled canonical dev-flow STDIO "
            "registration and no additional owned-launcher registrations"
        )
elif owned_rows:
    names = sorted(str(item.get("name", "<unnamed>")) for item in owned_rows)
    raise SystemExit(
        "standalone Dev Flow MCP registration(s) {} target the launcher/runtime selected "
        "for removal; remove them explicitly with codex mcp first".format(", ".join(names))
    )
' || fail "Bundled or standalone Dev Flow MCP registration state is unsafe; preserve it and resolve it before uninstalling."

SOURCE_STATE="absent"
if [ -e "$SOURCE_ROOT" ]; then
  SOURCE_STATE="present"
  if [ "$REMOVE_SOURCE" = "1" ]; then
  [ ! -L "$SOURCE_ROOT" ] \
    || fail "$SOURCE_ROOT is a symbolic link; preserve and remove it manually."
  [ -d "$SOURCE_ROOT/.git" ] \
    || fail "$SOURCE_ROOT is not the expected Git checkout."

  CANONICAL_SOURCE="$(
    DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" \
    DEV_FLOW_SOURCE_ROOT="$SOURCE_ROOT" \
    "$PYTHON" -I -S -c '
import json
import os
from pathlib import Path

marketplace_path = Path(os.environ["DEV_FLOW_MARKETPLACE_FILE"]).expanduser().resolve()
marketplace_root = marketplace_path.parent.parent.parent
source_root = Path(os.environ["DEV_FLOW_SOURCE_ROOT"]).expanduser().resolve()
try:
    relative = source_root.relative_to(marketplace_root)
except ValueError:
    raise SystemExit(
        f"{source_root} must be inside marketplace root {marketplace_root}"
    ) from None
if not relative.parts or source_root == marketplace_root:
    raise SystemExit("refusing to remove the marketplace root")
manifest_path = source_root / ".codex-plugin" / "plugin.json"
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"Cannot read {manifest_path}: {error}")
if manifest.get("name") != "dev-flow-orchestrator":
    raise SystemExit(f"{source_root} is not the Dev Flow plugin source")
print(source_root)
'
  )" || fail "Cannot validate the source removal target."
  SOURCE_ROOT="$CANONICAL_SOURCE"

  EXISTING_REMOTE="$(git -C "$SOURCE_ROOT" remote get-url origin 2>/dev/null || true)"
  if [ "${DEV_FLOW_REPOSITORY_URL+x}" = "x" ]; then
    [ "$EXISTING_REMOTE" = "$REPOSITORY_URL" ] \
      || fail "$SOURCE_ROOT origin is '$EXISTING_REMOTE', expected '$REPOSITORY_URL'."
  else
    case "$EXISTING_REMOTE" in
      "$DEFAULT_REPOSITORY_URL"|git@github.com:Innocent-children/dev-flow-orchestrator.git)
        ;;
      *)
        fail "$SOURCE_ROOT origin is '$EXISTING_REMOTE', not an official Dev Flow repository URL."
        ;;
    esac
  fi

  CURRENT_BRANCH="$(git -C "$SOURCE_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  [ "$CURRENT_BRANCH" = "$REPOSITORY_REF" ] \
    || fail "$SOURCE_ROOT is on '${CURRENT_BRANCH:-a detached HEAD}', expected branch '$REPOSITORY_REF'."

  SOURCE_STATUS="$(git -C "$SOURCE_ROOT" status --porcelain 2>/dev/null)" \
    || fail "Cannot inspect the working tree at $SOURCE_ROOT."
  [ -z "$SOURCE_STATUS" ] \
    || fail "$SOURCE_ROOT has local changes; preserve them before uninstalling."

  IGNORED_STATUS="$(git -C "$SOURCE_ROOT" status --ignored --porcelain 2>/dev/null)" \
    || fail "Cannot inspect ignored paths at $SOURCE_ROOT."
  [ -z "$IGNORED_STATUS" ] \
    || fail "$SOURCE_ROOT contains ignored paths; preserve or remove them manually before uninstalling."

  LOCAL_ONLY_COUNT="$(git -C "$SOURCE_ROOT" rev-list --count --all --not --remotes=origin 2>/dev/null)" \
    || fail "Cannot inspect local-only Git history at $SOURCE_ROOT."
  [ "$LOCAL_ONLY_COUNT" = "0" ] \
    || fail "$SOURCE_ROOT contains commits that are not present on origin; preserve them before uninstalling."
  fi
fi

PLUGIN_ACTION="already absent"
if [ "$PLUGIN_STATE" = "installed-active" ] || [ "$PLUGIN_STATE" = "installed-inactive" ]; then
  printf 'Removing the Codex plugin...\n'
  if ! codex plugin remove "$PLUGIN_ID"; then
    fail "Cannot remove $PLUGIN_ID. Finish or cancel active Dev Flow tasks, then rerun this uninstaller."
  fi
  PLUGIN_ACTION="removed"
fi

LAUNCHER_ACTION="already absent"
if [ "$LAUNCHER_STATE" = "present" ]; then
  printf 'Removing the dev-flow PATH launcher...\n'
  rm -f -- "$LAUNCHER_PATH"
  [ ! -e "$LAUNCHER_PATH" ] && [ ! -L "$LAUNCHER_PATH" ] \
    || fail "Could not remove $LAUNCHER_PATH."
  LAUNCHER_ACTION="removed"
fi
MCP_LAUNCHER_ACTION="already absent"
if [ "$MCP_LAUNCHER_STATE" = "present" ]; then
  printf 'Removing the dev-flow-mcp PATH launcher...\n'
  rm -f -- "$MCP_LAUNCHER_PATH"
  [ ! -e "$MCP_LAUNCHER_PATH" ] && [ ! -L "$MCP_LAUNCHER_PATH" ] \
    || fail "Could not remove $MCP_LAUNCHER_PATH."
  MCP_LAUNCHER_ACTION="removed"
fi

RUNTIME_ACTION="already absent"
if [ "$RUNTIME_STATE" = "present" ]; then
  printf 'Removing the marker-validated managed MCP runtime...\n'
  rm -rf -- "$RUNTIME_ROOT"
  [ ! -e "$RUNTIME_ROOT" ] && [ ! -L "$RUNTIME_ROOT" ] \
    || fail "Could not remove $RUNTIME_ROOT."
  RUNTIME_ACTION="removed"
fi

MARKETPLACE_ACTION="already absent"
if [ "$MARKETPLACE_STATE" = "present" ]; then
  DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" "$PYTHON" -I -S -c '
import json
import os
from pathlib import Path

path = Path(os.environ["DEV_FLOW_MARKETPLACE_FILE"]).expanduser().resolve()
marketplace = json.loads(path.read_text(encoding="utf-8"))
marketplace["plugins"] = [
    item
    for item in marketplace["plugins"]
    if not (
        isinstance(item, dict)
        and item.get("name") == "dev-flow-orchestrator"
    )
]
temporary = path.with_name(path.name + ".tmp")
temporary.write_text(
    json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
temporary.replace(path)
'
  MARKETPLACE_ACTION="entry removed"
fi

SOURCE_ACTION="already absent"
if [ "$SOURCE_STATE" = "present" ]; then
  if [ "$REMOVE_SOURCE" = "1" ]; then
    printf 'Removing the validated source checkout...\n'
    rm -rf -- "$SOURCE_ROOT"
    [ ! -e "$SOURCE_ROOT" ] \
      || fail "Could not completely remove $SOURCE_ROOT."
    SOURCE_ACTION="removed"
  else
    SOURCE_ACTION="preserved (--keep-source)"
  fi
fi

printf '\n%s%s┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓%s\n' \
  "$TEXT_BOLD" "$NEON_PURPLE" "$COLOR_RESET"
printf '%s%s┃%s  %sDEV FLOW ORCHESTRATOR%s  %s// SYSTEM OFFLINE%s\n' \
  "$TEXT_BOLD" "$NEON_PURPLE" "$COLOR_RESET" \
  "$NEON_CYAN" "$COLOR_RESET" "$NEON_GREEN" "$COLOR_RESET"
printf '%s%s┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛%s\n' \
  "$TEXT_BOLD" "$NEON_PURPLE" "$COLOR_RESET"

printf '\n%s%s╭─ UNINSTALL RECEIPT%s\n' \
  "$TEXT_BOLD" "$NEON_CYAN" "$COLOR_RESET"
printf '%s│%s  %sPLUGIN%s       %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$PLUGIN_ACTION"
printf '%s│%s  %sMARKETPLACE%s  %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$MARKETPLACE_ACTION"
printf '%s│%s  %sCOMMAND%s      %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$LAUNCHER_ACTION"
printf '%s│%s  %sMCP COMMAND%s  %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$MCP_LAUNCHER_ACTION"
printf '%s│%s  %sMCP RUNTIME%s  %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$RUNTIME_ACTION"
printf '%s│%s  %sSTANDALONE%s   preserved / no owned registration removed\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET"
printf '%s│%s  %sSOURCE%s       %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$SOURCE_ACTION"
printf '%s╰─%s\n' "$NEON_CYAN" "$COLOR_RESET"

printf '\n%s%sPRESERVED%s\n' "$TEXT_BOLD" "$NEON_GREEN" "$COLOR_RESET"
printf '  External Dev Flow task data under Codex-managed state was not deleted.\n'
printf '  Codex-managed state root: %s\n' "$CODEX_ROOT"
