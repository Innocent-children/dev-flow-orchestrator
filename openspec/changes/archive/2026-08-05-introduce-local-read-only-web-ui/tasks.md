## 1. Preserve Product Identity and Add Physical Inspection

- [x] 1.1 Add regression tests that pin the existing `0.3.0` version and `product_document` / `PRODUCT_IDENTITY`, and reject a WebUI-specific version, package, plugin, namespace, API-version prefix, or persisted schema identity.
- [x] 1.2 Refactor the store's strict no-follow state read into a shared, physically read-only primitive, then add inventory and detail inspection entry points that never acquire task locks, create directories, change permissions, or write files; keep every authoritative CLI/controller path on its existing locking behavior.
- [x] 1.3 Add a controller-facing inspection facade that accepts only the current `0.3.0` namespace, isolates corrupt or unsupported task entries, and returns bounded sanitized diagnostics without exposing raw state, bindings, snapshots, commands, or absolute paths.
- [x] 1.4 Test missing state namespaces, hostile symlinks, malformed and partially replaced files, concurrent atomic replacement, unsupported `0.2` state, and before/after file identities, bytes, modes, timestamps, directory entries, and lock-file inventories to prove inspection causes no mutation.

## 2. Build the Read-Only Presentation Model

- [x] 2.1 Implement metadata and deterministic stored-inventory projections with query, status, workflow, repository, and terminal filters; `offset` pagination; a default limit of 50 and maximum of 100; and ordering by descending `updated_at` with task ID as the stable tie-breaker.
- [x] 2.2 Implement stored task detail, health, why-next, recovery guidance, bounded timeline pages, Delivery Dossier summaries, and a copyable `$follow-dev-flow` prompt using persisted state only and without invoking Git.
- [x] 2.3 Implement the explicit live-detail projection so one aggregate snapshot is captured for the selected task and reused for both the rendered view and agent projection; re-read the persisted task afterward and return `VIEW_STALE` without automatic retry when its revision changed.
- [x] 2.4 Define and test the closed response contracts, pagination bounds, terminal and active health states, corrupt-entry diagnostics, missing-task errors, unavailable-repository results, binding-field scrubbing, and response-size limits.
- [x] 2.5 Add tests proving inventory and stored detail never invoke Git, live detail invokes one aggregate snapshot only, stored terminal tasks remain terminal, active stored tasks report live health as not evaluated, and all projections preserve the existing product identity.

## 3. Bound and Cancel Live Repository Capture

- [x] 3.1 Add optional cancellation support to the existing Git subprocess execution path while preserving current behavior for all callers that do not supply a cancellation signal.
- [x] 3.2 Add one process-global, non-queued live-capture slot for the Web UI; reject competing live requests with `429` and `Retry-After` instead of accumulating work, while allowing stored views to remain responsive.
- [x] 3.3 On server shutdown or client abandonment, terminate the active Git subprocess, wait for a bounded grace period, then kill it if necessary; ensure no child process or capture slot remains orphaned.
- [x] 3.4 Test default Git-client compatibility, capture contention, cancellation before and during a command, timeout/cancellation races, graceful and forced child termination, slot release after every outcome, and bounded request-handler concurrency.

## 4. Add the Integrated Loopback Server and CLI Entry Point

- [x] 4.1 Add a standard-library server module inside the existing runtime package and expose it through `dev-flow --data-dir <path> web [--port <port>]`, binding only numeric `127.0.0.1`, using port `0` by default, remaining in the foreground, and never opening a browser or daemonizing.
- [x] 4.2 Generate a process-local 256-bit bearer token, place it only in the startup URL fragment and process memory, emit one strict JSON startup receipt, avoid request/token logging, and clear the secret on shutdown.
- [x] 4.3 Implement the fixed static and API route table, strict JSON envelopes, safe error mapping, `Cache-Control: no-store`, CSP and other security headers, exact Host/origin validation, Fetch Metadata checks, and an explicit no-CORS policy.
- [x] 4.4 Reject undeclared routes, malformed encodings, traversal and normalization variants, invalid tokens, DNS-rebinding Host values, cross-site requests, and every unsupported HTTP method without touching task storage.
- [x] 4.5 Add CLI and HTTP tests for startup receipts, explicit and ephemeral ports, foreground lifecycle, signal shutdown, loopback-only binding, authentication, allowed routes and methods, response headers, hostile paths and origins, absent state directories, and unchanged behavior of all existing CLI commands.

## 5. Deliver the Native Browser Experience

- [x] 5.1 Package build-free HTML, CSS, and JavaScript assets with the existing plugin, using no external resources, telemetry, service worker, cookies, persistent browser storage, framework runtime, or Node.js build step.
- [x] 5.2 Implement the inventory, filters, corrupt-entry diagnostics, stored detail, explicit live refresh, health and why-next explanations, timeline pagination, Delivery Dossier summary, recovery guidance, and copyable follow-up prompt defined by the presentation contracts.
- [x] 5.3 Consume the startup fragment token into memory and remove it from the visible URL; render every state-derived value through safe text APIs; do not perform background polling or automatic live capture.
- [x] 5.4 Provide keyboard-operable controls, visible focus, semantic landmarks and tables, announced loading/error states, sufficient contrast, reduced-motion support, and responsive layouts for narrow and wide viewports.
- [ ] 5.5 Add real-browser checks for initial load, token handling, inventory and filtering, stored and live detail, concurrency errors, empty/corrupt/unavailable/terminal states, adversarial text rendering, keyboard navigation, responsive layout, CSP compliance, console errors, and absence of external requests or persistent storage.

## 6. Extend Package and Installed-Artifact Validation

- [x] 6.1 Include the required server modules and browser assets in package inventories, version/identity scans, and plugin metadata validation while rejecting an independent WebUI app, MCP server, package, version constant, namespace, dependency set, or release gate.
- [x] 6.2 Extend candidate-package tests to prove the assets are present exactly once, import from the installed snapshot, use only the Python standard library at runtime, and preserve fresh-install, idempotent-reinstall, and fast-forward upgrade behavior.
- [x] 6.3 Extend the installed-product evidence journey to launch the packaged server, exercise stored and live HTTP paths plus hostile requests, capture a graceful shutdown, and compare task-state identities and bytes before and after observation.
- [ ] 6.4 Capture real-browser installed-artifact evidence for the representative workflow and safety states; when the required browser is unavailable, record the browser portion explicitly as manual-unverified instead of substituting source-tree or HTTP-only evidence.
- [x] 6.5 Test that evidence generation reports partial, failed, skipped, stale, and manual-unverified results accurately and never upgrades them into a full product-pass claim.

## 7. Synchronize Public Documentation

- [x] 7.1 Update the English source documents `README.md`, `ROADMAP.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, and `INSTALL.md` with the integrated `0.3.0` local read-only Web UI, its launch command, security model, stored/live boundary, validation workflow, and current scope.
- [x] 7.2 Fully translate the five updated English documents into `README_CN.md`, `ROADMAP_CN.md`, `ARCHITECTURE_CN.md`, `CONTRIBUTING_CN.md`, and `INSTALL_CN.md`, preserving commands, paths, versions, external links, product scope, and language-switch links.
- [x] 7.3 Extend documentation validation across all five English/Chinese pairs so drift, missing language links, unsupported WebUI claims, a separate WebUI version, and claims that all of Horizon 2 is delivered fail validation.

## 8. Verify the Change

- [ ] 8.1 Run the focused store, controller, Git-cancellation, server, security, browser, packaging, installed-evidence, and bilingual-documentation tests through the project `uv` environment and record the exact commands and results.
- [ ] 8.2 Build the candidate package and run the installed-plugin evidence journeys from the installed snapshot, including state non-mutation comparisons and standard-library-only runtime checks.
- [x] 8.3 Run the real-browser installed-artifact checks, or record only that portion as manual-unverified with the precise environmental limitation and remaining risk.
- [x] 8.4 Run the full project-prescribed candidate validation without substituting unrelated generic discovery, and report every failure, skip, stale result, or environment limitation without extrapolation.
- [x] 8.5 Run `openspec validate introduce-local-read-only-web-ui --type change --strict --no-interactive` and `openspec validate --all --strict --no-interactive`.
- [ ] 8.6 Obtain an independent read-only review of the complete OpenSpec proposal, design, delta specifications, and tasks for requirement/scenario coverage, version-identity preservation, security boundaries, implementation feasibility, validation evidence, and public-documentation synchronization; reconcile any approved findings before implementation begins.

## Validation Record — 2026-08-05

Environment: macOS current host, project uv-managed `.venv`, Python 3.14.4.

- `.venv/bin/python -m unittest tests.test_read_only_inspection tests.test_web_read_models tests.test_web_ui_product_identity tests.test_git_snapshot tests.test_cli tests.test_store_integrity tests.test_controller_contracts tests.test_package tests.test_install_script` — 123 tests passed in 91.405 seconds.
- `.venv/bin/python -m unittest tests.test_web_server` — 12 tests passed in 9.710 seconds; loopback binding required the managed sandbox's local-network approval.
- `.venv/bin/python -m unittest tests.test_installed_journeys` — 3 tests passed in 119.535 seconds. The installed runner completed its subprocess journeys while preserving the `unverified` release gate and `manual-unverified` installed-browser status.
- `.venv/bin/python scripts/validate_package.py` — candidate validation returned `ok: true` for all six built-in workflows.
- `openspec validate introduce-local-read-only-web-ui --type change --strict --no-interactive` — passed.
- `openspec validate --all --strict --no-interactive` — 12 items passed, 0 failed.
- `.venv/bin/python -m compileall -q src scripts tests` and `git diff --check` — passed with no output.

Remaining required evidence:

- The final browser assets changed after the source-candidate browser session, so that session is stale for the current candidate and task 5.5 remains open.
- The installed evidence runner has no browser-control channel. Its HTTP journey is bound to the inspected snapshot, while installed rendering, CSP enforcement, and browser persistence behavior remain `manual-unverified`; task 6.4 remains open.
- Installed journeys used the source root's focused self-test allowance rather than an immutable installed plugin cache snapshot; task 8.2 remains open.
- No independent complete-change review satisfying task 8.6 was obtained.
