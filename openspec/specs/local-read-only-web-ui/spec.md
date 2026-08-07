# local-read-only-web-ui Specification

## Purpose
TBD - created by archiving change introduce-local-read-only-web-ui. Update Purpose after archive.
## Requirements
### Requirement: The Web UI is one current-product presentation surface
The local Web UI SHALL obtain its product name, `RELEASE_VERSION`, and compatibility-model `PRODUCT_IDENTITY` from the existing runtime authorities. Its startup receipt, JSON views, page chrome, plugin metadata, package metadata, installed evidence, and public guidance SHALL identify the same `dev-flow-orchestrator` release while stored task views retain the exact `0.4.0` model schemas. The Web UI SHALL NOT define a component version, independent semantic-version line, package, plugin, marketplace entry, release gate, controller data namespace, persisted schema vocabulary, or compatibility policy.

Adding, replacing, or serving the presentation assets SHALL leave `product_document()`, `PRODUCT_IDENTITY`, `PLUGIN_DATA_NAMESPACE`, every persisted task and record schema, workflow identity, binding contract, replay rule, and retained prior-version boundary unchanged. Non-persisted HTTP view names and static-asset content digests SHALL remain presentation metadata and SHALL NOT enter task identity or become mutation inputs.

#### Scenario: Current Web UI reports product identity
- **WHEN** the installed Web UI starts and its page and JSON views are inspected
- **THEN** every presentation surface reports `dev-flow-orchestrator` `RELEASE_VERSION` and the installed model `PRODUCT_IDENTITY` without a Web UI-specific version field

#### Scenario: Existing current task is viewed
- **WHEN** the Web UI opens a valid task created under the same `0.4.0` compatibility model before the current release was installed
- **THEN** the controller loads and projects that task without migration, repair, identity replacement, ledger mutation, or state rewrite

#### Scenario: Component-specific version is introduced
- **WHEN** a candidate declares a Web UI version, separate namespace, separate package identity, or presentation release other than the shared `RELEASE_VERSION`
- **THEN** candidate validation fails before installation

### Requirement: The Web UI runs as an explicit loopback foreground process
The existing CLI SHALL expose `dev-flow --data-dir <path> web` with an optional `--port` argument. The command SHALL bind exactly `127.0.0.1`; an omitted port or `--port 0` SHALL request an operating-system-selected ephemeral port, and an explicit port SHALL be a valid available TCP port. The command SHALL expose no non-loopback host option.

After binding succeeds, the command SHALL write and flush one strict-JSON startup receipt containing the existing product identity, the exact bound address and port, and a launch URL whose fragment carries the process-local access token. It SHALL then remain in the foreground until interrupted or terminated. Shutdown SHALL close the listener and SHALL leave no daemon, PID file, token file, Web UI configuration, task cache, browser auto-launch effect, or controller-state mutation.

#### Scenario: Web UI starts on an ephemeral port
- **WHEN** the operator runs the `web` command without an explicit nonzero port
- **THEN** the command binds `127.0.0.1` on an available port, emits one machine-readable launch receipt, and remains in the foreground

#### Scenario: Requested port is unavailable
- **WHEN** the operator requests a loopback port that cannot be bound
- **THEN** the command exits nonzero with a machine-readable error and creates no listener, token file, UI state, or task mutation

#### Scenario: Web UI process stops
- **WHEN** the foreground process receives normal interrupt or termination
- **THEN** the listener closes and no task, repository, installed asset, PID, token, cache, or configuration file is created or changed by shutdown

### Requirement: Every task-data request has process-local access authority
Each Web UI process SHALL generate at least 256 bits of cryptographically secure random access authority. The launch URL SHALL carry that value only in its fragment. The bootstrap script SHALL read it into memory, remove it from the visible URL with history replacement before loading task data, and send it only as an `Authorization: Bearer` header to same-origin JSON requests. The token SHALL NOT appear in an HTTP request target, cookie, referrer, server request log, local storage, session storage, IndexedDB, service worker, controller state, or filesystem.

Every `/api/` request SHALL require a constant-time match against the process token. The server SHALL require the exact bound `127.0.0.1:<port>` Host authority and SHALL accept an absent Origin or the exact same origin only. It SHALL reject every other Host or Origin and every `Sec-Fetch-Site: cross-site` request and SHALL emit no `Access-Control-Allow-Origin` authority. Static bootstrap assets SHALL contain no task data and SHALL confer no API access by themselves.

#### Scenario: Launch fragment is consumed
- **WHEN** the browser loads the emitted launch URL
- **THEN** the token remains only in page memory, disappears from the address bar before task data is fetched, and reaches the server only in the Authorization header

#### Scenario: API token is missing or incorrect
- **WHEN** a task-data request omits the bearer token or supplies a different value
- **THEN** the server returns an authorization error containing no task, repository, diagnostic, or product-state data

#### Scenario: Host or origin is not the bound origin
- **WHEN** a request carries another Host authority or a cross-origin Origin value
- **THEN** the server rejects the request, emits no permissive CORS header, and returns no task data

### Requirement: The HTTP surface is closed, bounded, and read-only
The server SHALL use an explicit router and a fixed packaged-asset allowlist. It SHALL serve only `GET` and `HEAD` for `/`, `/assets/app.js`, and `/assets/styles.css`, and authenticated `GET` for `/api/meta`, `/api/tasks`, `/api/tasks/<task-id>`, and `/api/tasks/<task-id>/live`. API task IDs SHALL pass the existing task-ID validator before any state path is selected. The router SHALL NOT expose directory listing, arbitrary filesystem paths, repository files, raw task-state files, action bindings, controller mutation commands, or generic static-file traversal.

Every other method, including `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, `TRACE`, and `CONNECT`, SHALL return a method error without dispatching controller code. Unknown, malformed, overlong, traversal, encoded-separator, or invalid-query targets SHALL fail with a bounded error. JSON responses SHALL use strict UTF-8 JSON and `application/json`; asset responses SHALL use fixed content types. Responses SHALL omit server-version disclosure and CORS authority, ignore rather than trust forwarded-host headers, and apply `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Cross-Origin-Resource-Policy: same-origin`, frame denial, and a content-security policy limited to same-origin scripts, styles, connections, and images with no object, base, form, or frame authority.

#### Scenario: Unsafe HTTP method is attempted
- **WHEN** any route receives `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, `TRACE`, or `CONNECT`, with or without a valid token
- **THEN** the server returns a method error and invokes no start, apply, contract-revision, decision, finding-disposition, cancellation, Git mutation, or external effect

#### Scenario: Filesystem traversal is attempted
- **WHEN** a request target contains a raw or encoded traversal, separator, absolute path, or non-allowlisted asset
- **THEN** the router rejects it without reading any arbitrary plugin, controller-data, repository, or user file

#### Scenario: Browser security policy is inspected
- **WHEN** the bootstrap page, an asset, and an API response are fetched
- **THEN** their content types and security headers match the closed local policy and no response grants cross-origin read authority

### Requirement: Inspection storage reads are physically non-mutating
The Web UI SHALL use a dedicated inspection store and controller facade that never acquires or creates a task lock, never calls a directory-creation or permission-normalization helper, and never writes, replaces, touches, repairs, or removes controller data. A missing controller namespace SHALL produce an empty inventory observation without creating the data directory. Existing task directories, state files, workflow selectors, and inventory entries SHALL be read with no-follow regular-file and containment checks and SHALL pass the same task ID, `MODEL_VERSION`, model `PRODUCT_IDENTITY`, selected-workflow identity, strict state-shape, record-ledger, and deterministic replay validation required by authoritative loads.

Inventory inspection SHALL isolate invalid entries through stable error codes and bounded safe identifiers. It SHALL NOT expose a raw operating-system error, traceback, access token, controller data-root path, or followed symlink target. Concurrent atomic state replacement SHALL yield either one complete old revision or one complete new revision and SHALL never combine record or scalar fields from different revisions. Inspection SHALL never enumerate a prior-version namespace.

#### Scenario: Missing data namespace is inspected
- **WHEN** the Web UI starts against a controller data directory whose current namespace does not exist
- **THEN** inventory is empty and the directory tree, permissions, lock paths, and filesystem bytes remain unchanged

#### Scenario: Healthy task is inspected
- **WHEN** inventory and stored detail read a valid task
- **THEN** state bytes, record count, revision, modification time, mode, lock directory, and workflow bytes remain unchanged and no lock or directory is created

#### Scenario: State is atomically replaced during inspection
- **WHEN** an authorized controller writer atomically replaces a task state while inspection reads it
- **THEN** inspection returns one fully validated old or new revision or a bounded stale diagnostic and never a mixed state

#### Scenario: Tasks root is a symlink
- **WHEN** the current tasks root or a task state entry is a symlink
- **THEN** inspection does not follow it, returns a bounded safe diagnostic, and reads or changes nothing behind the link

### Requirement: Inventory is a deterministic persisted-state summary
`GET /api/tasks` SHALL enumerate validated current-namespace tasks through the physically non-mutating inspection facade and SHALL derive summaries without capturing repository snapshots or running Git commands. The response SHALL identify the current product, `view: task-inventory`, observation time, normalized filters, total match count, offset, limit, continuation state, valid task summaries, inventory health, and bounded corruption diagnostics.

Each task summary SHALL contain only task ID, a bounded current-contract summary, revision, created and updated timestamps, workflow ID and version, persisted status, terminal flag, current node, repository IDs, and repository count. It SHALL exclude the original requirement, record ledger, commands, absolute repository and data paths, and raw diagnostics. Active rows SHALL label live workspace health as `not-evaluated`; terminal rows SHALL label it `terminal`. The endpoint SHALL support bounded `q`, `status`, `workflow`, `repository`, and `terminal` filters, a nonnegative offset, and a limit whose default is 50 and maximum is 100. Repository filtering SHALL compare only against validated persisted repository identities and canonical paths and SHALL NOT treat the filter as a filesystem path to open. It SHALL apply filters before pagination and sort matches by `updated_at` descending and UTF-8 task ID ascending.

Invalid current-namespace entries SHALL never become task authority or valid rows. Their existing read-only diagnostics SHALL remain separately visible, and their presence SHALL mark inventory health degraded without preventing healthy tasks from being listed or implying that any active membership lease was released.

#### Scenario: Multiple tasks are filtered
- **WHEN** inventory contains active and terminal tasks across different workflows and repositories and the caller supplies valid filters
- **THEN** the endpoint returns the matching summaries in canonical order with exact pagination metadata and performs no repository snapshot or Git command

#### Scenario: Current inventory contains a corrupt entry
- **WHEN** one candidate task entry is invalid while other current tasks are valid
- **THEN** valid tasks remain listed, inventory health is degraded, the invalid entry appears only as a bounded diagnostic, and no lease or task authority is inferred from it

#### Scenario: Repository is unavailable during inventory
- **WHEN** a valid task's persisted repository path is missing or inaccessible
- **THEN** the persisted summary remains listable with live health `not-evaluated` because inventory performs no live repository observation

### Requirement: Stored task detail is immediate and repository-independent
`GET /api/tasks/<task-id>` SHALL load one validated task and selected workflow definition through the inspection facade and SHALL derive a bounded stored detail without capturing a repository snapshot or running Git. The response SHALL identify the current product, `view: task-detail`, observation time, task and contract summaries, acceptance criteria, repositories, revision, workflow, persisted status, stored artifact and Dossier summaries, timeline page, and recovery context. It SHALL label an active task's live health and why-next availability `not-evaluated`; a terminal task SHALL be `terminal` with no next action.

Stored detail SHALL exclude canonical action bindings, raw record payloads, complete snapshot path entries, file content, raw artifact bodies, raw operating-system errors, data-root paths, and mutation-ready request values. The browser SHALL present stored detail before any live observation and SHALL require an explicit operator action to request live health.

#### Scenario: Active task stored detail is opened
- **WHEN** an operator selects an active task
- **THEN** stored contract, membership, status, timeline, and recovery context render immediately with live health `not-evaluated` and Git is not invoked

#### Scenario: Terminal task stored detail is opened
- **WHEN** the selected task is `DONE`, `INCOMPLETE`, or `CANCELLED`
- **THEN** stored detail reports `terminal`, no next action, and the available terminal outcome and Dossier summary without a repository capture

### Requirement: Live task detail is explicit, stable, and globally bounded
`GET /api/tasks/<task-id>/live` SHALL be the only HTTP route that captures a current repository-set snapshot. One invocation SHALL call the existing complete two-pass aggregate snapshot operation at most once and SHALL derive the full task view and current action projection from that same accepted snapshot. The controller SHALL re-read task revision and identity after capture; if either changed, it SHALL return a bounded `VIEW_STALE` result and SHALL NOT combine revisions or automatically repeat the expensive capture.

The process SHALL permit at most one active live capture globally and SHALL queue none. A second live request SHALL immediately return `429` with `Retry-After` and SHALL invoke no Git command. The browser SHALL trigger live capture only through an explicit operator action, SHALL never poll it automatically, and SHALL show progress and cancellation or shutdown state. Normal shutdown SHALL stop accepting requests, terminate any active Web UI-owned Git observation through the existing bounded TERM-to-KILL process cleanup, release the live slot and listener, clear process memory, and leave no child process or persisted state.

A successful live response SHALL add snapshot summary, artifact freshness, assurance and budget summary, review summary, Dossier summary, current action summary, and why-next derived from the one observation. It SHALL omit the canonical action binding and other mutation-ready values. Live health SHALL be exactly `ready`, `blocked`, `unavailable`, or `terminal`. Capture failure SHALL preserve stored detail and report `unavailable` with a bounded safe diagnostic.

#### Scenario: Active task has a stable ready action
- **WHEN** an explicit live request observes a stable selected task and the controller derives a current action with a valid binding
- **THEN** live detail reports health `ready` and an action summary derived from that projection while omitting the binding itself

#### Scenario: Task changes during live capture
- **WHEN** another authorized controller operation changes the task revision while live detail is being captured
- **THEN** the request returns stored context plus `VIEW_STALE` without combining revisions, repeating the capture, or mutating either revision

#### Scenario: Repository snapshot cannot be captured
- **WHEN** a selected task member is missing, moved, inaccessible, unsafe, or unstable
- **THEN** live detail preserves stored task information, reports health `unavailable` and a bounded safe snapshot error, and does not repair membership, substitute a repository, hide the task, or mutate state

#### Scenario: Another live capture is active
- **WHEN** a second task or browser requests live detail while one capture owns the global slot
- **THEN** the second request immediately returns `429` with `Retry-After`, performs no Git read, and changes no state

#### Scenario: Server stops during live capture
- **WHEN** the foreground process is terminated while a Web UI-owned Git observation is active
- **THEN** the listener and child process terminate within the bounded cleanup interval, the port and live slot are released, and controller, repository, and installed bytes remain unchanged

### Requirement: Why-next and recovery information remain derived guidance
For an active selected task before live observation, `why_next` SHALL identify the stored current node and mark live readiness `not-evaluated`. After a successful or failed explicit live observation, it SHALL identify the exact current node and declared action, whether it is ready, blocked, unavailable, or stale, the governing assurance obligation when present, remaining retry and assurance budget summaries, and the controller-derived reason and recovery choices. For a terminal task it SHALL identify the terminal outcome and absence of another action. Presentation text SHALL be derived from stable machine-readable codes and current projection values and SHALL NOT create workflow authority, reinterpret a binding, or claim completion.

The recovery brief SHALL include task ID and revision, bounded requirement and contract summaries, repository membership, last update, workflow and status, current or terminal state, why-next, outstanding or exhausted assurance, freshness and review summaries, recent timeline context, and a copyable `$follow-dev-flow` resume prompt. It SHALL NOT contain an action binding, automatically start Codex, invoke a controller mutation, or present the browser as the task executor.

#### Scenario: Assurance obligation is next
- **WHEN** adaptive assurance selects one outstanding obligation
- **THEN** why-next identifies that obligation, its exact action and remaining allowance, and the recovery brief directs resumption through the authoritative task without fabricating another check

#### Scenario: Ambient drift blocks progress
- **WHEN** the controller projection reports ambient drift or another explicit blocker
- **THEN** why-next preserves the blocker code, bounded evidence and controller recovery choices and does not offer a Web UI state-change action

#### Scenario: Recovery prompt is copied
- **WHEN** the operator copies the recovery prompt from the page
- **THEN** the prompt names the exact task for `$follow-dev-flow` and contains no bearer token, action binding, or claim that the task has advanced

### Requirement: Timeline is a bounded projection of sealed history
Selected-task detail SHALL expose timeline events derived in descending revision order from sealed task records. Timeline pagination SHALL default to 50 events and accept a maximum of 100. Each event SHALL contain only its revision, recorded timestamp, record kind, action and node identifiers when present, before and after status or node when present, bounded outcome or actor labels when present, and artifact type, ID, and digest summaries when present. Event summaries SHALL retain enough identity to correlate with CLI inspection while excluding raw payloads, complete snapshots, task-change entries, file contents, and bearer or action-binding values.

#### Scenario: Long task timeline is paged
- **WHEN** a task contains more events than the requested timeline limit
- **THEN** detail returns the canonical newest page with exact total, offset, limit, and continuation metadata and no raw record body

#### Scenario: Decision and assurance events are shown
- **WHEN** sealed history contains decisions, assurance executions, review results, and finalization
- **THEN** the timeline reports their revision, kind, bounded labels, transitions, and artifact identities without granting decision, retry, review, or finalization authority

### Requirement: The browser renders local data safely and accessibly
The packaged page SHALL provide a responsive task list, search and filter controls, inventory diagnostics, selected-task summary, repositories, an explicit live-health action, current action, why-next, assurance and review state, timeline, Dossier state, and recovery brief. It SHALL provide keyboard-operable controls, visible focus, semantic labels, and explicit loading, empty, degraded, busy, unavailable, stale, error, and terminal states at desktop and narrow viewport widths. It SHALL never poll the live endpoint. A persistent read-only indicator SHALL identify that task progression occurs through the controller and Codex workflow.

The client SHALL create task-derived content as text nodes or equivalent safe properties and SHALL NOT interpret task, requirement, path, contract, diagnostic, review, or timeline strings as HTML, CSS, script, URL authority, or executable markup. All HTML, CSS, and JavaScript SHALL be packaged in the existing plugin, compatible with the declared content-security policy, and free of external requests, telemetry, remote fonts, analytics, CDN resources, runtime package downloads, service workers, and persistent browser storage.

#### Scenario: Task text contains executable markup
- **WHEN** a task requirement, repository path, diagnostic, or timeline label contains HTML or script syntax
- **THEN** the page displays the exact text without creating executable DOM, fetching a derived URL, or weakening the content-security policy

#### Scenario: Inventory is empty or degraded
- **WHEN** no valid tasks exist or inventory contains isolated diagnostics
- **THEN** the page presents the corresponding empty or degraded state with actionable read-only explanation and remains keyboard navigable

#### Scenario: Browser has no external connectivity
- **WHEN** the complete task list and selected-task page are rendered with external network access unavailable
- **THEN** all supported content and interaction remains available and the page attempts no external request

### Requirement: Web UI observation never mutates delivery or repository state
The Web UI server and presentation read model SHALL depend only on the physically non-mutating inspection facade and the explicit bounded live-observation operation. Startup, asset delivery, inventory, stored detail, live detail, filtering, refresh, error handling, and shutdown SHALL NOT invoke task start, apply, contract revision, decision, finding disposition, cancellation, Hook mutation, Git mutation, external driver, Agent, CI, PR, release, installer, or marketplace operations. They SHALL NOT acquire or create a controller lock, normalize permissions, create a data directory, append a task record, change a revision or timestamp, rewrite controller data, create a repository file, alter Git `HEAD`, index, worktree, branch, worktree, or configuration, or modify installed plugin assets.

Live detail SHALL use only the existing bounded read-only Git observation path. The server SHALL persist no cache, filter, token, task selection, timeline, recovery brief, or derived health state. A separate authorized CLI, Hook, or Skill operation SHALL remain able to mutate the task through the controller; a later Web UI refresh SHALL observe the newly committed revision as data and SHALL NOT become part of that mutation.

#### Scenario: Complete browser journey is observed
- **WHEN** an operator starts the server, lists and filters tasks, opens active and terminal detail, refreshes live health, copies a recovery prompt, and stops the server
- **THEN** controller task bytes, record counts, revisions, repository Git and file identities, and installed asset digests remain unchanged

#### Scenario: Another controller client advances the task
- **WHEN** an authorized non-Web client commits a valid task mutation while the Web UI is running
- **THEN** a later refresh shows the complete new revision and the Web UI records no mutation or intermediate state of its own

### Requirement: The installed Web UI preserves its current product boundary on Windows

On documented Windows x64 clients, the installed `dev-flow --data-dir <path> web` command SHALL use the existing current-product server, routes, assets, token authority, inspection facade, read-only views, explicit live observation, and Controller runtime. It SHALL bind numeric `127.0.0.1`, remain in the foreground, and require no Windows-specific package, version, namespace, browser integration, service, or daemon.

Live observation and shutdown SHALL use the Windows runtime's bounded Git cancellation behavior. A normal Ctrl+C shutdown SHALL close the listener and release active capture resources without changing task, repository, marketplace, or installed plugin state.

#### Scenario: Installed Windows Web UI starts and serves stored views

- **WHEN** the operator starts the installed Web UI on an ephemeral port on a supported Windows client
- **THEN** it emits the current startup receipt and serves authenticated inventory and stored detail through the existing read-only contract

#### Scenario: Windows live observation succeeds

- **WHEN** the operator explicitly requests live detail for a stable task
- **THEN** the server performs one current aggregate observation and returns the existing ready, blocked, unavailable, or terminal view without exposing a mutation binding

#### Scenario: Windows Web UI is interrupted during live capture

- **WHEN** Ctrl+C or normal process termination occurs while a live Git observation is active
- **THEN** cancellation is requested through the existing runtime, the listener closes, and no task or repository mutation is attributed to the Web UI
