#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)" || {
  printf 'Dev Flow uninstallation failed: cannot resolve the uninstaller directory.\n' >&2
  exit 1
}
RUNTIME_INTEGRITY_HELPER="$SCRIPT_DIR/runtime_integrity.py"

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

usage() {
  printf 'Usage: uninstall.sh [--keep-source]\n'
  printf '\n'
  printf 'Removes the Codex plugin and its personal marketplace entry.\n'
  printf 'The source checkout is always retained while exact ownership is unavailable.\n'
  printf '%s\n' '--keep-source remains accepted for compatibility and has the same behavior.'
  printf 'External Dev Flow task data is always preserved.\n'
}

fail() {
  printf 'Dev Flow uninstallation failed: %s\n' "$1" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --keep-source)
      :
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

command -v codex >/dev/null 2>&1 || fail "Codex with plugin support is required."

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

SOURCE_ROOT="$(
  DEV_FLOW_SOURCE_ROOT_VALUE="$SOURCE_ROOT" python_no_bytecode -I -S -c '
import os

print(os.path.abspath(os.path.expanduser(os.environ["DEV_FLOW_SOURCE_ROOT_VALUE"])))
'
)" || fail "Cannot determine the lexical absolute source path."

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
  if [ -L "$RUNTIME_ROOT" ] || [ ! -d "$RUNTIME_ROOT" ]; then
    RUNTIME_STATE="retained (runtime root is not a regular directory)"
  else
    RUNTIME_STATE="present"
  fi
fi

python_no_bytecode -c 'import struct,sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) and struct.calcsize("P") == 8 else 1)' \
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
  DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" python_no_bytecode -I -S -c '
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
RUNTIME_RETAINED_PATHS=""
if [ "$RUNTIME_STATE" = "present" ]; then
  if [ ! -f "$RUNTIME_INTEGRITY_HELPER" ] || [ -L "$RUNTIME_INTEGRITY_HELPER" ]; then
    RUNTIME_ACTION="retained (exact ownership helper unavailable)"
    RUNTIME_RETAINED_PATHS="$RUNTIME_ROOT"
  else
    RUNTIME_REMOVAL_JSON="$(
      python_no_bytecode -I -S "$RUNTIME_INTEGRITY_HELPER" remove-owned \
        --runtime-root "$RUNTIME_ROOT"
    )" || true
    RUNTIME_REMOVAL_ACTION="$(
      printf '%s' "$RUNTIME_REMOVAL_JSON" | python_no_bytecode -I -S -c '
import json
import sys
try:
    value = json.load(sys.stdin)
except (OSError, json.JSONDecodeError):
    print("retained")
else:
    action = value.get("action")
    print(action if action in {"removed", "partial", "retained"} else "retained")
'
    )"
    RUNTIME_RETAINED_PATHS="$(
      printf '%s' "$RUNTIME_REMOVAL_JSON" | python_no_bytecode -I -S -c '
import json
import sys
try:
    value = json.load(sys.stdin)
except (OSError, json.JSONDecodeError):
    raise SystemExit(0)
paths = value.get("retained_paths")
if isinstance(paths, list):
    for path in paths:
        if isinstance(path, str):
            print(json.dumps(path, ensure_ascii=False))
'
    )"
    case "$RUNTIME_REMOVAL_ACTION" in
      removed)
        RUNTIME_ACTION="removed (exact ownership manifest)"
        ;;
      partial)
        RUNTIME_ACTION="partial (unknown or changed content retained)"
        ;;
      *)
        RUNTIME_ACTION="retained (legacy, missing, or mismatched exact ownership)"
        if [ -z "$RUNTIME_RETAINED_PATHS" ]; then
          RUNTIME_RETAINED_PATHS="$RUNTIME_ROOT"
        fi
        ;;
    esac
  fi
elif [ "$RUNTIME_STATE" != "already absent" ]; then
  RUNTIME_ACTION="$RUNTIME_STATE"
  RUNTIME_RETAINED_PATHS="$RUNTIME_ROOT"
fi

MARKETPLACE_ACTION="already absent"
if [ "$MARKETPLACE_STATE" = "present" ]; then
  DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" python_no_bytecode -I -S -c '
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

SOURCE_ACTION="already absent (no deletion attempted)"
if [ -e "$SOURCE_ROOT" ] || [ -L "$SOURCE_ROOT" ]; then
  SOURCE_ACTION="retained (destructive removal disabled)"
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
printf '%s│%s  %sOUTCOME%s      partial\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET"
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
if [ -n "$RUNTIME_RETAINED_PATHS" ]; then
  printf '%s│%s  %sRUNTIME RETAINED%s %s\n' \
    "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$RUNTIME_RETAINED_PATHS"
fi
printf '%s│%s  %sSTANDALONE%s   preserved / no owned registration removed\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET"
printf '%s│%s  %sSOURCE%s       %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$SOURCE_ACTION"
printf '%s│%s  %sSOURCE PATH%s  %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$SOURCE_ROOT"
printf '%s│%s  %sSOURCE REASON%s destructive removal disabled: no verifiable exact-ownership manifest\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET"
printf '%s│%s  %sTASK DATA%s    preserved\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET"
printf '%s╰─%s\n' "$NEON_CYAN" "$COLOR_RESET"

printf '\n%s%sPRESERVED%s\n' "$TEXT_BOLD" "$NEON_GREEN" "$COLOR_RESET"
printf '  External Dev Flow task data under Codex-managed state was not deleted.\n'
printf '  Codex-managed state root: %s\n' "$CODEX_ROOT"
if [ -n "$RUNTIME_RETAINED_PATHS" ]; then
  printf '  Retained runtime content: %s\n' "$RUNTIME_RETAINED_PATHS"
fi
printf '\n%s%sMANUAL ACTION%s\n' "$TEXT_BOLD" "$NEON_GREEN" "$COLOR_RESET"
printf '  Inspect and back up the retained source checkout, then independently confirm ownership before any manual action.\n'
