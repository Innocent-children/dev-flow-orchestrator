#!/bin/sh
# Source template for the version-matched GitHub Release bootstrap.
# scripts/build_release.py replaces each release marker before promotion
# and publishes the result as install-<version>.sh.
set -eu

DEV_FLOW_BOOTSTRAP_SCHEMA='@DEV_FLOW_BOOTSTRAP_SCHEMA@'
DEV_FLOW_REPOSITORY='@DEV_FLOW_REPOSITORY@'
DEV_FLOW_RELEASE_VERSION='@DEV_FLOW_RELEASE_VERSION@'
DEV_FLOW_ARCHIVE_NAME='@DEV_FLOW_ARCHIVE_NAME@'
DEV_FLOW_INDEX_SHA256='@DEV_FLOW_INDEX_SHA256@'
DEV_FLOW_PHASE_A_B64='@DEV_FLOW_PHASE_A_B64@'

case "$DEV_FLOW_INDEX_SHA256" in
  *'@'*)
    printf 'This file is a release template; run the version-specific install.sh asset from an official GitHub Release.\n' >&2
    exit 2
    ;;
esac
if [ "${DEV_FLOW_SOURCE_ROOT+x}" = x ]; then
  printf 'DEV_FLOW_SOURCE_ROOT is not supported by artifact installation.\n' >&2
  exit 1
fi

phase_a_python=''
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -I -S -c 'import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (3, 15)))'; then
    phase_a_python="$candidate"
    break
  fi
done
if [ -z "$phase_a_python" ]; then
  printf 'Python >=3.10,<3.15 is required.\n' >&2
  exit 1
fi

phase_a_dir="$(mktemp -d "${TMPDIR:-/tmp}/dev-flow-bootstrap.XXXXXX")"
phase_a_b64="$phase_a_dir/release_artifact.b64"
phase_a_path="$phase_a_dir/release_artifact.py"
cleanup_phase_a() {
  rm -f "$phase_a_b64" "$phase_a_path"
  rmdir "$phase_a_dir" 2>/dev/null || true
}
trap cleanup_phase_a EXIT HUP INT TERM
printf '%s' "$DEV_FLOW_PHASE_A_B64" >"$phase_a_b64"
"$phase_a_python" -I -S -c 'import base64,pathlib,sys; pathlib.Path(sys.argv[2]).write_bytes(base64.b64decode(pathlib.Path(sys.argv[1]).read_bytes(), validate=True))' "$phase_a_b64" "$phase_a_path"
set +e
"$phase_a_python" -I -S "$phase_a_path" bootstrap \
  --repository "$DEV_FLOW_REPOSITORY" \
  --version "$DEV_FLOW_RELEASE_VERSION" \
  --archive-name "$DEV_FLOW_ARCHIVE_NAME" \
  --index-sha256 "$DEV_FLOW_INDEX_SHA256" \
  -- "$@"
phase_a_status=$?
set -e
exit "$phase_a_status"
