## ADDED Requirements

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
