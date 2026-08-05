## Context

Dev Flow 0.3.0 is a local Python-standard-library controller for one task, one current action, one Codex executor, and one exact set of one to eight user-prepared Git worktrees. The controller is the sole task-state writer. It persists strict append-only task ledgers under the current product namespace, derives one canonical action projection, and provides a full read-only task view with current contract, snapshot, freshness, review, assurance, and Dossier information.

The current CLI exposes `list`, `show`, and `next`, but these paths are not a suitable physical read boundary for a read-only server. `TaskStore.load_with_definition()` acquires a file lock, and the inventory path ensures directories and permissions before loading tasks. Those operations can create lock paths, directories, or permission changes even when the caller intends only to inspect. The Web UI therefore needs a dedicated inspection path that reuses strict parsing and replay validation while performing no lock, directory, permission, or state mutation.

Repository-backed projection is also materially more expensive than stored-state inspection. One aggregate controller snapshot performs two complete captures over as many as eight repositories, and each repository client has a bounded command deadline. Inventory and ordinary detail must remain repository-independent; live action, freshness, and blocker information must be an explicit selected-task operation with bounded concurrency and cancellation.

The Web UI is shipped in the existing plugin snapshot and follows the exact current `0.3.0` product authority. It is a presentation adapter, not a new persisted protocol. Existing task bytes, `product_document()`, `PRODUCT_IDENTITY`, schema vocabulary, workflows, bindings, replay rules, and the `0.3.0` data namespace remain unchanged.

## Goals / Non-Goals

**Goals:**

- Provide a local browser cockpit for task search and filtering, stored detail, explicit live health, current action and why-next, timeline, Dossier state, inventory diagnostics, and a recovery brief.
- Make all Web UI storage inspection physically non-mutating, including a missing or damaged data namespace.
- Preserve the controller as the only state-transition authority and Git as user-owned source history.
- Protect local task data with loopback binding, process-local capability authority, exact Host and origin checks, a closed route and method set, response security policy, and safe DOM rendering.
- Keep inventory fast, deterministic, paged, and independent of repository availability.
- Bound live observation to one explicit aggregate capture at a time and support prompt process termination.
- Ship one Python-standard-library runtime and build-free same-origin browser asset set inside the existing plugin.
- Keep every product, package, Web UI, installed-evidence, and documentation version at the existing `0.3.0` authority without changing current task identity.

**Non-Goals:**

- Starting, applying, revising, deciding, disposing, cancelling, approving, waiving, retrying, or otherwise advancing a task through HTTP.
- Exposing action bindings, mutation payload templates, complete raw ledgers, file content, repository browsing, or arbitrary filesystem access.
- Remote or LAN access, proxy trust, team sharing, accounts, RBAC, durable sessions, or a hosted service.
- Background daemon installation, automatic startup, automatic browser launch, desktop integration, or a second plugin/application/MCP surface.
- Creating or managing branches, worktrees, commits, pushes, CI, pull requests, releases, Agents, or external drivers.
- Adding a Web UI semantic version, API version axis, data namespace, migration, compatibility parser, or persisted Web UI state.
- Completing the remaining interactive-workbench roadmap capabilities such as approvals, templates, named outcomes, conditional routing, cloning, archival, or workflow authoring.

## Decisions

### 1. Treat HTTP as a presentation adapter under the existing product identity

Every startup receipt and JSON response will carry `version: PRODUCT_VERSION` and `product_identity: PRODUCT_IDENTITY`. Responses will use stable `view` names such as `product-meta`, `task-inventory`, and `task-detail`; they will not add `/api/v1`, `api_version`, `WEB_UI_VERSION`, or a component-specific canonical schema. Embedded canonical task, workflow, agent, assurance, and Dossier summaries retain their existing identities.

The Web UI implementation will not add presentation fields to `product_document()` or the accepted persisted schema vocabulary. This preserves the exact current `PRODUCT_IDENTITY`, so a valid existing 0.3.0 task remains loadable byte-for-byte. Incompatible future HTTP changes advance with the whole product version.

Alternative considered: define a `dev-flow-web-ui/0.3.0` schema and include it in the product document. This would change `PRODUCT_IDENTITY` while the semantic version remained 0.3.0 and would make existing current tasks fail identity validation, so presentation metadata stays outside persisted identity.

### 2. Add a pure inspection path alongside the authoritative locked path

`TaskStore` will separate pure state reading from lock acquisition and directory normalization. The existing strict `_read_state_with_definition()` behavior will become the shared parsing and validation core. Authoritative controller paths keep their existing locks and atomic mutation behavior. New inspection methods will:

- validate task IDs before constructing paths;
- inspect the current namespace and task entries without `mkdir`, `chmod`, lock creation, or atomic write;
- use no-follow directory and regular-file checks plus existing containment helpers;
- parse strict JSON and validate `PRODUCT_VERSION`, `PRODUCT_IDENTITY`, selected workflow identity, complete `TaskState`, record count, and deterministic replay;
- return valid `(state, definition)` pairs and sanitized diagnostics in one observation;
- treat a missing current namespace as an empty inventory;
- never enumerate the retained 0.2 namespace.

Atomic state replacement already guarantees a regular-file reader sees an old or new file body. The inspection layer validates the complete body and reports a bounded stale or invalid diagnostic rather than attempting repair. It does not use filesystem metadata or a separately editable inventory as task authority.

Alternative considered: reuse `Controller.list_tasks()`, `show_view()`, and `next()` directly. Those call locked store paths that can create or normalize filesystem objects, and calling both `show_view()` and `next()` would capture the same repository set more than once. A dedicated inspection facade provides the required physical read guarantee and one-observation consistency.

### 3. Split stored inspection from explicit live observation

`GET /api/tasks` and `GET /api/tasks/<task-id>` will use only validated persisted state. Pure projection helpers will create allowlisted inventory, timeline, stored Dossier, and recovery summaries. They will not invoke `GitClient`.

`GET /api/tasks/<task-id>/live` will be the only repository-observing route. It will:

1. inspect one validated task and workflow definition;
2. acquire the process-global live slot without waiting;
3. run the existing aggregate two-pass snapshot exactly once with a cancellation event;
4. re-inspect the task and compare task ID, revision, product and workflow identities, and immutable repository-set identity;
5. derive the full task view and agent projection from the same accepted snapshot;
6. remove the canonical action binding and other mutation-ready values from the presentation response;
7. release the live slot in every outcome.

If task identity or revision changes during capture, the response reports `VIEW_STALE` and does not retry the expensive operation. If repository capture fails, stored detail remains available and live status is `unavailable`. The UI never polls the live route and exposes an explicit refresh control.

Alternative considered: calculate live health for every inventory row or poll selected tasks. A worst-case aggregate snapshot can traverse eight repositories twice under per-repository command deadlines. Explicit single-task capture prevents page loading from amplifying that cost and keeps an unavailable repository from blocking inventory.

### 4. Bound HTTP and live-capture concurrency

The server will use a custom bounded standard-library HTTP server. It will allow a small fixed number of request handlers so static assets and stored views remain responsive, while a separate nonblocking lock admits only one live capture process-wide. A competing live request returns `429` and `Retry-After` immediately; there is no live queue or background refresh.

The existing Git subprocess path will accept an optional cancellation event. The default remains unset for all existing controller operations. Web live capture passes the process event; selector and capture boundaries check it, terminate the active process group through the existing TERM, grace, and KILL cleanup, and raise a bounded observation-cancelled result. SIGINT or SIGTERM stops listener admission, sets cancellation, waits only for the declared cleanup interval, clears in-memory session data, and exits.

Alternative considered: use an unbounded `ThreadingHTTPServer` and rely only on Git timeouts. A local malicious or accidental request burst could create unbounded handlers or several multi-repository captures, so both handler and capture concurrency are explicit product bounds.

### 5. Use one explicit foreground CLI entry point

The existing CLI parser will add the `web` command and delegate its long-running behavior to a separate `web.py` module. The normal one-command JSON paths remain unchanged. After successful bind, `web` writes and flushes one strict-JSON startup receipt and then owns the foreground process. The command accepts only `--port`; it has no host, proxy, daemon, open-browser, or persistence option.

The default address is the numeric IPv4 loopback `127.0.0.1` and the default port is `0`. A port conflict fails explicitly. The installer continues to activate one plugin and does not start the server. Installed guidance provides the explicit command and normal interrupt behavior.

Alternative considered: add a second launcher, plugin, Codex app, or auto-start Hook. A single explicit CLI command keeps distribution and authority within the current plugin and prevents session hooks or installation from opening a long-lived listener.

### 6. Protect task data with an ephemeral browser capability

The server will generate a 32-byte token with `secrets`, disclose it once in the startup URL fragment, and compare bearer values with `hmac.compare_digest`. The bootstrap asset contains no task data. JavaScript reads the fragment into memory, removes it with `history.replaceState`, and sends it only in the Authorization header. Refresh after fragment removal requires reopening the startup URL; no cookie or persistent browser storage is used.

Before any store, controller, or Git operation, API routing validates:

- exactly one Host equal to the bound `127.0.0.1:<port>` authority;
- an absent Origin or the exact same origin;
- fetch metadata that is not cross-site;
- the bearer token;
- the fixed method, route, query, and validated task ID.

The server ignores forwarded-host headers, emits no CORS authority, disables identifying access logs, and returns sanitized errors. This protects against cross-site requests and DNS rebinding while keeping the service local.

Alternative considered: rely on loopback and the browser same-origin policy alone. Local web services are reachable by hostile pages and DNS rebinding can alter Host authority, so loopback binding is combined with explicit request capability and origin validation.

### 7. Serve only allowlisted same-origin assets and views

The explicit route table is:

| Method | Path | Behavior |
| --- | --- | --- |
| `GET`, `HEAD` | `/` | Packaged bootstrap HTML; no task data |
| `GET`, `HEAD` | `/assets/app.js` | Packaged fixed JavaScript |
| `GET`, `HEAD` | `/assets/styles.css` | Packaged fixed CSS |
| `GET` | `/api/meta` | Current product identity and supported view capabilities |
| `GET` | `/api/tasks` | Paged persisted-state inventory and diagnostics |
| `GET` | `/api/tasks/<task-id>` | Stored detail, timeline, and recovery context |
| `GET` | `/api/tasks/<task-id>/live` | Explicit bounded live observation |

No route maps caller input to a filesystem path. Static assets are resolved from a fixed package table rather than `SimpleHTTPRequestHandler`. Every change-capable method and `OPTIONS`, `TRACE`, or `CONNECT` returns `405` before protected work. Errors contain stable codes and bounded safe context only.

HTML and JSON are `no-store`. The server sets no CORS header and applies a strict content-security policy, no-referrer policy, MIME sniffing denial, same-origin resource policy, and frame denial. JavaScript uses `textContent` and DOM property setters for every task-derived string. The page has no external script, style, font, image, telemetry, analytics, service worker, runtime download, or build output.

Alternative considered: use `SimpleHTTPRequestHandler` or a generated repository directory as the document root. A fixed in-package asset map closes directory traversal, listing, content-type guessing, and accidental repository disclosure.

### 8. Define bounded presentation views rather than returning raw state

The response envelope is strict JSON with `ok`, the current product version and identity, `view`, `observed_at`, and one allowlisted result or error. It has no independent API version. Inventory defaults to 50 rows and caps at 100, filters before pagination, and sorts by updated time descending then UTF-8 task ID. Inventory includes a bounded contract summary and repository identities/count but omits the original requirement, raw records, commands, absolute repository and data paths, and raw errors.

Stored detail can disclose the selected task's bounded requirement, contract, acceptance criteria, and canonical repository membership after authorization. Timeline defaults to 50 events and caps at 100; it returns event identity and transition summaries rather than record bodies. Recovery combines stored context with the latest explicit live result, when present in the current response only. The server persists no view or live cache. All error mapping removes raw `OSError`, traceback, environment, data-root, token, request header, and subprocess output unless an existing safe controller code explicitly permits a bounded public field.

Alternative considered: return `TaskState.as_dict()` and the complete action projection. Raw state contains the whole record ledger, snapshots, bindings, paths, and payloads. Allowlisted projections reduce disclosure and prevent the presentation surface from becoming a mutation-template API.

### 9. Keep the browser a thin accessible renderer

The packaged application is native HTML, CSS, and JavaScript. It presents list/search/filter, diagnostics, stored detail, explicit live refresh, health, current action, why-next, assurance/review/Dossier summaries, timeline, and a copyable `$follow-dev-flow` recovery prompt. It provides semantic controls, visible focus, keyboard operation, and desktop and narrow-width layouts, with explicit empty, loading, busy, degraded, unavailable, stale, terminal, and error states.

All machine reasoning remains in controller and pure projection code. JavaScript performs presentation filtering, navigation, request cancellation, and safe rendering only. The browser never reconstructs an action binding, infers completion, derives a workflow transition, or persists task state.

Alternative considered: implement task interpretation and health rules in JavaScript. That would create a second behavior authority and allow CLI, Hook, Skill, and browser output to diverge, so the server supplies all semantic codes and summaries.

### 10. Validate the same installed plugin at HTTP and browser levels

Candidate validation will treat the server, read model, and static files as required current-product assets and scan them for version, dependency, route, external-resource, and authority drift. Unit tests will exercise pure inspection, projections, filtering, concurrency, cancellation, HTTP security, safe errors, and byte-for-byte non-mutation.

The existing installed evidence family gains one `local-read-only-web-ui` journey. It starts the installed candidate on an ephemeral loopback port, verifies assets and startup identity, creates representative tasks, checks stored and live views with the standard-library HTTP client, exercises negative security cases, records before-and-after identities, and shuts down cleanly. A real-browser journey checks rendering, focus, responsive states, CSP, console and network behavior, and adversarial text. Browser evidence remains explicitly `manual-unverified` when the environment cannot render a browser.

Public documentation changes start in the five English source documents and are completely synchronized to their Simplified Chinese counterparts. The roadmap marks this local read-only cockpit slice accurately while retaining the remaining Horizon 2 capabilities as planned.

## Risks / Trade-offs

- [A live snapshot can take minutes across the maximum repository set] → Stored views never run Git; live capture is explicit, globally single-slot, nonqueued, cancellable, and visibly busy.
- [Existing read methods create locks or normalize permissions] → The Web UI uses a new inspection facade over shared pure validators, and focused tests compare directory trees, modes, mtimes, state bytes, and lock paths before and after.
- [A task changes while its repositories are being observed] → Re-inspect revision and identities after capture and discard the live projection as stale when they differ.
- [A malicious page targets the loopback service] → Require exact Host, same-origin or absent Origin, fetch metadata, bearer authority, no CORS, and a closed method/route table before protected work.
- [A local process obtains the startup token or reads the user's browser memory] → The token protects the browser boundary but does not claim operating-system account isolation; minimize disclosure, keep it process-local, avoid persistence and logs, and stop the process when inspection is complete.
- [Task text attempts markup or URL injection] → Keep a restrictive CSP, prohibit external resources, and render every task-derived value as text.
- [A corrupt entry exposes local paths or blocks the cockpit] → Isolate diagnostics, map them to safe stable fields, continue healthy inventory, and preserve fail-closed task admission authority outside the Web UI.
- [The Web UI and core drift while sharing version 0.3.0] → Package and installed validation bind all files to one candidate snapshot digest and reject independent version, namespace, schema, route, capability, or dependency claims.
- [Real-browser evidence is unavailable in a release environment] → Report the exact HTTP evidence and retain a separate `manual-unverified` browser field; do not infer rendering correctness.

## Migration Plan

1. Add the pure inspection facade and focused proof that existing authoritative loads and mutations retain their lock, CAS, replay, and atomic-write behavior.
2. Add bounded presentation projections, live-capture cancellation, the Web server, CLI delegation, and packaged static assets under the existing plugin and version.
3. Extend candidate and installed validation, then update the English public documents and synchronize their Simplified Chinese counterparts.
4. Install the same `0.3.0` candidate snapshot through the existing installer. Existing valid 0.3.0 task bytes load directly; no data migration or state rewrite occurs.
5. Rollback stops the foreground server and restores the prior plugin snapshot. The change has no persistent Web UI data to migrate or clean.

## Open Questions

None. The capability is confined to the current local read-only product surface and uses the existing product, state, and installation authorities.
