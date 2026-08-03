#!/bin/sh
set -eu

REPOSITORY_URL="${DEV_FLOW_REPOSITORY_URL:-https://github.com/Innocent-children/dev-flow-orchestrator.git}"
REPOSITORY_REF="main"
SOURCE_ROOT="${DEV_FLOW_SOURCE_ROOT:-$HOME/plugins/dev-flow-orchestrator}"
MARKETPLACE_FILE="${DEV_FLOW_MARKETPLACE_FILE:-$HOME/.agents/plugins/marketplace.json}"

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
  fail "Dev Flow Orchestrator 0.2.0 currently supports macOS."
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

mkdir -p "$(dirname "$MARKETPLACE_FILE")"
DEV_FLOW_MARKETPLACE_FILE="$MARKETPLACE_FILE" \
DEV_FLOW_SOURCE_ROOT="$SOURCE_ROOT" \
"$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["DEV_FLOW_MARKETPLACE_FILE"]).expanduser()
source_root = str(Path(os.environ["DEV_FLOW_SOURCE_ROOT"]).expanduser().resolve())
entry = {
    "name": "dev-flow-orchestrator",
    "source": {"source": "local", "path": source_root},
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

printf 'Installing the Codex plugin...\n'
if ! codex plugin add dev-flow-orchestrator@personal; then
  printf '\nIf Dev Flow is already installed, finish or cancel active tasks, then run:\n' >&2
  printf '  codex plugin remove dev-flow-orchestrator@personal\n' >&2
  printf '  codex plugin add dev-flow-orchestrator@personal\n' >&2
  exit 1
fi

printf '\nDev Flow Orchestrator is installed.\n'
printf '1. Start a new Codex task and review the installed Hook in /hooks.\n'
printf '2. Copy this first prompt:\n\n'
printf 'Use $follow-dev-flow to start a lite task in this repository for: <your requirement>\n'
