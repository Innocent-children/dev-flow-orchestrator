# State-machine reference router

This compatibility page is not the normal execution entry point. Read
[state-machine-common.md](state-machine-common.md), then use the immutable
`flow` and current `status` to load one flow document and its single applicable
gate bundle:

- [flow-lite.md](flow-lite.md)
- [flow-full.md](flow-full.md)

The full-flow status-to-gate routing table lives in `flow-full.md`. Do not load
all gate documents eagerly.

## Per-transition confirmation

Moved to
[state-machine-common.md#per-transition-confirmation](state-machine-common.md#per-transition-confirmation).

## Lite flow

Moved to [flow-lite.md](flow-lite.md).
