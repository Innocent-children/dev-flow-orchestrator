## Why

Dev Flow already preserves multiple resumable tasks and derives authoritative task, action, assurance, review, freshness, and Dossier views, but the current CLI exposes either a complete raw task state or one task at a time. A secure local read-only Web UI will make task discovery, diagnosis, and recovery usable from one cockpit while preserving the controller as the sole task-state writer.

## What Changes

- Add a local Web UI launched by the existing Dev Flow CLI. It serves packaged HTML, CSS, and JavaScript plus a bounded read-only JSON view over task inventory, selected-task detail, timeline, health, blocker, why-next, and recovery information.
- Bind the server exclusively to `127.0.0.1`, issue one process-local capability token, validate the exact loopback `Host` and same-origin request context, emit no CORS authority, and apply a closed set of HTTP methods, routes, assets, content types, and browser security headers.
- Keep inventory reads fast and repository-independent. Live Git snapshot, freshness, action, and blocker derivation occurs only for a selected task and uses one stable controller observation with explicit unavailable or stale diagnostics.
- Render only controller-derived, allowlisted presentation fields. The Web UI does not expose mutation endpoints, action bindings, raw task records, arbitrary files, repository contents, or external network resources.
- Preserve the current `dev-flow-orchestrator` version, runtime `PRODUCT_VERSION`, `PRODUCT_IDENTITY`, plugin/package version, controller data namespace, persisted schemas, workflow contracts, and replay rules at `0.3.0`. The Web UI has no independent version, package identity, compatibility line, or state namespace.
- Package and validate the Web UI as part of the existing plugin, retain a Python-standard-library-only runtime and build-free browser assets, add installed HTTP and browser journeys, and synchronize the English source documentation with complete Simplified Chinese translations.

## Capabilities

### New Capabilities

- `local-read-only-web-ui`: Defines the loopback-only server, ephemeral access authority, closed read-only HTTP surface, task cockpit views, browser behavior, failure isolation, and controller/Git non-mutation guarantees.

### Modified Capabilities

- `personal-delivery-workflows`: Extends the single `0.3.0` product-version authority to the local Web UI while preserving the current persisted protocol, namespace, and product identity.
- `package-delivery-validation`: Requires candidate, installed, security, non-mutation, packaging, browser, and bilingual-documentation evidence for the local Web UI.

## Impact

- Runtime: a new read-model module, a custom standard-library HTTP server, packaged static assets, and a `web` CLI command; controller, engine, and store receive read-only projection entry points only.
- Public local interface: loopback HTTP endpoints and browser views for inventory and task inspection; existing CLI, Hook, Skill, workflow, binding, ledger, and Dossier contracts remain authoritative and unchanged.
- Security and privacy: process-local bearer authority, strict Host/origin checks, no CORS, no external resources or telemetry, output encoding, request and response bounds, and no task or repository mutation path.
- Persistence and compatibility: no data migration, no new data directory, no persisted Web UI state, no change to the current `0.3.0` product identity computation, and no discovery of prior-version namespaces.
- Validation and documentation: focused unit/security tests, installed loopback and browser journeys, candidate-package validation, and synchronized `README`, `ROADMAP`, `ARCHITECTURE`, `CONTRIBUTING`, and `INSTALL` English/Chinese pairs.
- Dependencies: shipped Python remains standard-library-only; browser assets use native HTML, CSS, and JavaScript with no runtime CDN, package manager, transpilation, or build step.
