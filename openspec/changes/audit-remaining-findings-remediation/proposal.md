# Audit remaining findings remediation

## Why

The current audit records reproducible gaps in task evidence, repository leases, MCP
protocol boundaries, supported platform lifecycle, and release validation. Phase 0 and
the installer/runtime remediation already address DFO-AUDIT-001, 002, 006–010, and 017.
This change closes only the remaining findings identified by the audit report.

## What Changes

- Capture committed Git tree changes, compare complete typed locators, and continuously
  validate active repository leases (DFO-AUDIT-003–005).
- Isolate malformed MCP input, close current-action schemas, propagate cancellation to
  Git children, retain completion uncertainty, and hash the full observable catalog
  (DFO-AUDIT-012–014, 023–024).
- Contain Windows lifecycle fixtures, honor `DEV_FLOW_PYTHON`, install the supported
  Windows CLI/Web launcher, remove stale Hook assertions, and make bundled MCP the sole
  supported installation mode while preserving foreign standalone registrations
  (DFO-AUDIT-011, 015, 016, 019, 021).
- Restore reachable semantic package validation and evaluate obsolete specifications
  and validation reports against the current HEAD without restoring deleted files
  (DFO-AUDIT-018, 020, 022).

## Scope

The implementation reuses the existing Git client, membership/repository/task lock
order, MCP transport and result envelopes, lifecycle scripts, receipt/ownership model,
and package validator. It adds no installation mode, registry, transaction framework,
lock tier, or release platform. Native Windows lifecycle execution remains outside the
available host evidence.
