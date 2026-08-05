#!/bin/sh
set -eu

REPOSITORY_URL="${DEV_FLOW_REPOSITORY_URL:-https://github.com/Innocent-children/dev-flow-orchestrator.git}"
REPOSITORY_REF="main"
SOURCE_ROOT="${DEV_FLOW_SOURCE_ROOT:-$HOME/plugins/dev-flow-orchestrator}"
MARKETPLACE_FILE="${DEV_FLOW_MARKETPLACE_FILE:-$HOME/.agents/plugins/marketplace.json}"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
PLUGIN_ID="dev-flow-orchestrator@personal"

fail() {
  printf 'Dev Flow installation failed: %s\n' "$1" >&2
  exit 1
}

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
  fail "Dev Flow Orchestrator 0.3.0 currently supports macOS."
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

printf '\n============================================================\n'
printf '  Dev Flow Orchestrator %s is ready.\n' "$PLUGIN_VERSION"
printf '  Resume with confidence. Verify with evidence.\n'
printf '============================================================\n'
printf '\nInstallation receipt\n'
printf '  Plugin: %s\n' "$PLUGIN_ID"
printf '  Action: %s\n' "$INSTALL_ACTION"
if [ -n "$PREVIOUS_VERSION" ]; then
  printf '  Previous version: %s\n' "$PREVIOUS_VERSION"
fi
printf '  Installed version: %s\n' "$PLUGIN_VERSION"
printf '  Directories touched:\n'
printf '    - Source checkout: %s\n' "$SOURCE_ROOT"
printf '    - Marketplace metadata: %s\n' "$(dirname "$MARKETPLACE_FILE")"
printf '    - Codex-managed state: %s\n' "$CODEX_ROOT"
printf '\nNext steps\n'
printf '  1. Start a new Codex task and review the installed Hook in /hooks.\n'
printf '  2. Copy this first prompt:\n\n'
printf 'Use $follow-dev-flow to start a lite task in this repository for: <your requirement>\n'
