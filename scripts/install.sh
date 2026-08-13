#!/bin/sh
# Source template for the canonical GitHub Release first-install entry.
# scripts/build_release.py replaces each release marker before promotion.
# This entry accepts <MAJOR.MINOR.PATCH|latest>, resolves and downloads the
# matching versioned bootstrap, and executes it; Phase A and Phase B then run
# exactly as in the versioned asset.
set -eu

DEV_FLOW_BOOTSTRAP_SCHEMA='@DEV_FLOW_BOOTSTRAP_SCHEMA@'
DEV_FLOW_REPOSITORY='@DEV_FLOW_REPOSITORY@'
DEV_FLOW_RESOLVER_B64='@DEV_FLOW_RESOLVER_B64@'

case "$DEV_FLOW_BOOTSTRAP_SCHEMA" in
  *'@'*)
    printf 'This file is a release template; run the version-specific install asset from an official GitHub Release.\n' >&2
    exit 2
    ;;
esac
if [ "${DEV_FLOW_SOURCE_ROOT+x}" = x ]; then
  printf 'DEV_FLOW_SOURCE_ROOT is not supported by artifact installation.\n' >&2
  exit 1
fi
if [ "$#" -lt 1 ]; then
  printf 'Usage: install.sh <MAJOR.MINOR.PATCH|latest> [Phase B options]\n' >&2
  exit 2
fi
requested="$1"
shift

resolver_python=''
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -I -S -c 'import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (3, 15)))'; then
    resolver_python="$candidate"
    break
  fi
done
if [ -z "$resolver_python" ]; then
  printf 'Python >=3.10,<3.15 is required.\n' >&2
  exit 1
fi

resolver_dir="$(mktemp -d "${TMPDIR:-/tmp}/dev-flow-install.XXXXXX")"
resolver_b64="$resolver_dir/release_resolver.b64"
resolver_path="$resolver_dir/release_resolver.py"
cleanup_resolver() {
  rm -f "$resolver_b64" "$resolver_path"
  rmdir "$resolver_dir" 2>/dev/null || true
}
trap cleanup_resolver EXIT HUP INT TERM
printf '%s' "$DEV_FLOW_RESOLVER_B64" >"$resolver_b64"
"$resolver_python" -I -S -c 'import base64,pathlib,sys; pathlib.Path(sys.argv[2]).write_bytes(base64.b64decode(pathlib.Path(sys.argv[1]).read_bytes(), validate=True))' "$resolver_b64" "$resolver_path"
set +e
"$resolver_python" -I -S "$resolver_path" install \
  --repository "$DEV_FLOW_REPOSITORY" \
  --requested "$requested" \
  -- "$@"
resolver_status=$?
set -e
exit "$resolver_status"
