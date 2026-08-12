#!/bin/sh
# Repository-invoked uninstall is intentionally unsupported.  The installed
# stable dispatcher verifies and copies the minimal removal driver before the
# active managed runtime is removed.
set -eu

printf 'Repository-invoked uninstall is no longer supported. Run the installed dev-flow-uninstall command; it requires neither Git nor a source checkout.\n' >&2
exit 2
