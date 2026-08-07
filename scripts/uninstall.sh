#!/bin/sh
set -eu

DEFAULT_REPOSITORY_URL="https://github.com/Innocent-children/dev-flow-orchestrator.git"
REPOSITORY_URL="${DEV_FLOW_REPOSITORY_URL:-$DEFAULT_REPOSITORY_URL}"
REPOSITORY_REF="main"
SOURCE_ROOT="${DEV_FLOW_SOURCE_ROOT:-$HOME/plugins/dev-flow-orchestrator}"
MARKETPLACE_FILE="${DEV_FLOW_MARKETPLACE_FILE:-$HOME/.agents/plugins/marketplace.json}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
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
PLUGIN_ID="dev-flow-orchestrator@personal"
LAUNCHER_MARKER="# dev-flow-orchestrator managed launcher"
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
  fail "Python 3.9-3.14 is required."
fi

LAUNCHER_STATE="already absent"
if [ -e "$LAUNCHER_PATH" ] || [ -L "$LAUNCHER_PATH" ]; then
  [ ! -L "$LAUNCHER_PATH" ] && [ -f "$LAUNCHER_PATH" ] \
    || fail "$LAUNCHER_PATH is not a regular installer-managed launcher."
  grep -Fqx "$LAUNCHER_MARKER" "$LAUNCHER_PATH" \
    || fail "$LAUNCHER_PATH exists but is not owned by Dev Flow; preserve it and remove it manually."
  LAUNCHER_STATE="present"
fi

"$PYTHON" -c 'import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] <= (3, 14) else 1)' \
  || fail "Python 3.9-3.14 is required."

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
installed = payload.get("installed")
if not isinstance(installed, list):
    raise SystemExit("plugin list JSON must contain an installed array")
matches = [
    item
    for item in installed
    if isinstance(item, dict)
    and item.get("pluginId") == "dev-flow-orchestrator@personal"
    and item.get("installed") is True
]
if len(matches) > 1:
    raise SystemExit("plugin list contains duplicate installed entries")
print("installed" if matches else "not-installed")
'
)" || fail "Cannot interpret the installed Codex plugin state."

PLUGIN_ACTION="already absent"
if [ "$PLUGIN_STATE" = "installed" ]; then
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
printf '%s│%s  %sSOURCE%s       %s\n' \
  "$NEON_CYAN" "$COLOR_RESET" "$TEXT_DIM" "$COLOR_RESET" "$SOURCE_ACTION"
printf '%s╰─%s\n' "$NEON_CYAN" "$COLOR_RESET"

printf '\n%s%sPRESERVED%s\n' "$TEXT_BOLD" "$NEON_GREEN" "$COLOR_RESET"
printf '  External Dev Flow task data under Codex-managed state was not deleted.\n'
printf '  Codex-managed state root: %s\n' "$CODEX_ROOT"
