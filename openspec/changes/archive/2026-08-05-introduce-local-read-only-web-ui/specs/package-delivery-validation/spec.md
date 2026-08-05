## ADDED Requirements

### Requirement: Candidate and installed validation prove the local read-only Web UI
The candidate package SHALL require the local Web UI server module, read-model module, CLI bootstrap, HTML, CSS, and JavaScript assets and SHALL include them in current-product version scanning, installed asset inventory, and immutable installed-snapshot digests. It SHALL prove that plugin manifest, Python package metadata, lock file, runtime authority, startup receipt, HTTP views, page display, installed evidence, and every English and Simplified Chinese public document identify the same `dev-flow-orchestrator` version `0.3.0`. It SHALL reject an independent Web UI version, package, plugin, marketplace entry, application or MCP declaration, data namespace, persisted schema authority, release gate, third-party runtime import, Node runtime or build requirement, remote browser resource, telemetry endpoint, write capability, or non-loopback server claim.

Focused validation SHALL cover the physically non-mutating inspection store, CLI contract, server lifecycle, token authority, exact Host, Origin and fetch-metadata checks, absent CORS authority, fixed routes and assets, method denial, traversal denial, response bounds and security headers, deterministic inventory filtering and pagination, corrupt-entry isolation, stored detail with zero Git calls, explicit live detail using one aggregate observation, global live-capture exclusion and `429`, capture cancellation, snapshot-unavailable and stale-view behavior, why-next, recovery brief, timeline projection, disclosure minimization, output encoding, responsive browser states, and the complete no-mutation boundary. Candidate tests SHALL prove that Web UI observation and invalid requests do not create or acquire controller locks, create data directories, normalize permissions, or change task bytes, records, revisions, timestamps, repository `HEAD`, index or worktree identities, installed assets, marketplace state, or prior-version bytes.

The installed `dev-flow-installed-evidence/0.3.0` suite SHALL contain one `local-read-only-web-ui` journey from the immutable installed candidate. It SHALL create representative active and terminal tasks, start the installed server on an ephemeral loopback port, verify the startup receipt and asset digests, fetch the bootstrap, metadata, authenticated inventory, stored detail, and explicit live detail with the standard-library HTTP client, exercise missing and incorrect authority, hostile Host, Origin and fetch metadata, unsafe methods, invalid task IDs and traversal, missing-member diagnostics, concurrent live capture, capture termination, task refresh after an external controller mutation, and clean foreground shutdown. It SHALL record before-and-after directory, lock, mode, task, repository, installed-snapshot, and prior-namespace identities proving that the Web UI itself made no change.

Installed browser evidence SHALL render empty, multi-task, selected active, blocked or unavailable, terminal, timeline, recovery, diagnostic, and adversarial-text states at desktop and narrow viewport widths. It SHALL verify keyboard access, visible focus, safe text rendering, security-policy compliance, absence of external requests and console errors, and the visible read-only and current-product identities. If the release environment cannot observe a real browser, installed evidence SHALL mark browser rendering `manual-unverified`; HTTP success alone SHALL NOT be reported as complete Web UI release evidence.

Public documentation validation SHALL require the English source and complete Simplified Chinese counterpart for `README`, `ROADMAP`, `ARCHITECTURE`, `CONTRIBUTING`, and `INSTALL`. It SHALL verify matching commands, routes, product version, loopback and access model, read-only authority, task views, runtime-dependency boundary, support status, language-switch links, and installed validation limits. The roadmap SHALL mark only the delivered local read-only cockpit slice and SHALL keep the remaining interactive-workbench capabilities at their actual planned status.

#### Scenario: Candidate Web UI assets are inspected
- **WHEN** candidate validation scans required files, runtime imports, browser assets, manifests, metadata, lock data, version literals, network references, and capability declarations
- **THEN** every required asset is present under the single 0.3.0 plugin, runtime dependencies remain standard-library-only, browser assets require no build or remote resource, and every independent version, package, namespace, write, remote, app, or MCP claim fails validation

#### Scenario: Installed authorized journey succeeds
- **WHEN** the installed server receives an exact-host same-origin request with its process token for representative task inventory and detail
- **THEN** the installed views match controller state and current projection summaries, report product version `0.3.0`, and record no task or repository mutation

#### Scenario: Installed hostile requests are denied
- **WHEN** the installed server receives missing or incorrect authority, a hostile Host or Origin, an unsafe method, an invalid task ID, a traversal target, or a non-allowlisted route
- **THEN** each request fails with the specified bounded response, exposes no protected task data, invokes no mutation, and leaves all before-and-after identities unchanged

#### Scenario: Installed repository is unavailable
- **WHEN** an installed journey opens a valid task whose member cannot be captured
- **THEN** inventory remains available, selected detail reports the bounded unavailable diagnostic, and neither task membership nor repository state is repaired, substituted, hidden, or changed

#### Scenario: Browser renders adversarial task text
- **WHEN** installed browser evidence displays task and diagnostic text containing markup, script, style, URL, and path syntax
- **THEN** the text remains inert, no external request or executable DOM is created, browser security policy remains effective, and the task is unchanged

#### Scenario: Browser observation is unavailable
- **WHEN** installed HTTP validation passes but no real browser observation is available
- **THEN** the release evidence reports browser rendering as `manual-unverified` and does not claim complete Web UI validation

#### Scenario: Bilingual Web UI guidance drifts
- **WHEN** a public English or Simplified Chinese document omits or changes the Web UI command, version, loopback, read-only, support-status, validation-limit, or language-switch contract relative to its counterpart
- **THEN** candidate documentation validation fails
