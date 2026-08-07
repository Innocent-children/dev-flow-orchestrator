#!/bin/sh
set -eu

REPOSITORY_URL="${DEV_FLOW_REPOSITORY_URL:-https://github.com/Innocent-children/dev-flow-orchestrator.git}"
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
  printf 'Dev Flow installation failed: PATH has no writable absolute directory; set DEV_FLOW_BIN_DIR explicitly.\n' >&2
  exit 1
}
LAUNCHER_PATH="$BIN_DIR/dev-flow"
PLUGIN_ID="dev-flow-orchestrator@personal"
LAUNCHER_MARKER="# dev-flow-orchestrator managed launcher"

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

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  fail "Python 3.9-3.14 is required."
fi

"$PYTHON" -c 'import sys; raise SystemExit(0 if (3, 9) <= sys.version_info[:2] <= (3, 14) else 1)' \
  || fail "Python 3.9-3.14 is required."

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
if not matches:
    print("not-installed")
else:
    version = matches[0].get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit("installed plugin entry must contain a version")
    print("installed:" + version)
'
)" || fail "Cannot interpret the installed Codex plugin state."

INSTALL_ACTION="installed"
PREVIOUS_VERSION=""
case "$PLUGIN_STATE" in
  not-installed)
    ;;
  installed:*)
    PREVIOUS_VERSION="${PLUGIN_STATE#installed:}"
    if [ "$PREVIOUS_VERSION" = "$PLUGIN_VERSION" ]; then
      INSTALL_ACTION="repaired"
      printf 'Repairing Dev Flow Orchestrator %s...\n' "$PLUGIN_VERSION"
    else
      INSTALL_ACTION="upgraded"
      printf 'Upgrading Dev Flow Orchestrator from %s to %s...\n' \
        "$PREVIOUS_VERSION" "$PLUGIN_VERSION"
    fi
    if ! codex plugin remove "$PLUGIN_ID"; then
      fail "Cannot remove $PLUGIN_ID. Finish or cancel active Dev Flow tasks, then rerun this installer."
    fi
    ;;
  *)
    fail "Codex returned an unrecognized plugin state."
    ;;
esac

printf 'Installing the Codex plugin...\n'
if ! codex plugin add "$PLUGIN_ID"; then
  printf '\nPlugin activation failed. Rerun this installer after resolving the Codex error above.\n' >&2
  exit 1
fi

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
printf '  %s1.%s Start a new Codex task and review the installed Hook in /hooks.\n' \
  "$NEON_CYAN" "$COLOR_RESET"
printf '  %s2.%s Launch with this prompt:\n\n' "$NEON_CYAN" "$COLOR_RESET"
printf '%s%s  Use $follow-dev-flow to start a lite task in this repository for: <your requirement>%s\n' \
  "$TEXT_BOLD" "$BRIGHT_WHITE" "$COLOR_RESET"
printf '\n  Web UI: dev-flow web start\n'
