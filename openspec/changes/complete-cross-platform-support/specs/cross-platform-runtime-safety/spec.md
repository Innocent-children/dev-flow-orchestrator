## ADDED Requirements

### Requirement: Portable task identifiers
The controller SHALL accept a newly created task identifier only when it is 1–64 ASCII bytes matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, does not end in a dot, and maps to one unambiguous directory name on Windows, macOS, and Linux. It MUST reject every non-ASCII character, separator, traversal form, control character, trailing dot, Windows device-name stem (including case variants and names with extensions), and identifier whose ASCII-lowercase identity collides with another task. Existing schema-v1 tasks satisfying this portable contract MUST remain readable without migration.

#### Scenario: Create a portable task
- **WHEN** a caller creates a task with a 1–64 byte identifier satisfying the exact ASCII grammar and having no ASCII-case-equivalent task identity
- **THEN** the controller creates exactly one task directory and persists the identifier unchanged

#### Scenario: Enforce task identifier boundaries
- **WHEN** a caller supplies a 64-byte valid ASCII identifier, a 65-byte identifier, or an identifier containing a non-ASCII code point
- **THEN** the controller accepts only the 64-byte valid form and returns structured `INVALID_TASK_ID` errors for the others before creating any task path

#### Scenario: Reject a Windows reserved device name
- **WHEN** a caller attempts to create a task named `CON`, `con.txt`, `NUL`, `COM1`, or another Windows-reserved device name
- **THEN** the controller returns a structured `INVALID_TASK_ID` error before creating a task, lock, or workspace path

#### Scenario: Reject a path-equivalent task identifier
- **WHEN** a new valid ASCII identifier differs from an existing task identifier only by ASCII letter case
- **THEN** the controller serializes the task-namespace check and rejects the new identifier before creating its task directory or committing task state

#### Scenario: Load an existing portable task
- **WHEN** a schema-v1 task uses an identifier that is portable under the new validation contract
- **THEN** the controller loads that task without changing its schema, identifier, or state path

### Requirement: Filesystem-aware path identity
All path comparisons that protect state roots, lock roots, write boundaries, artifact locations, and ownership claims SHALL use one filesystem-aware canonical identity rather than raw string equality. The identity algorithm MUST account for native and alternate separators, drive-letter and UNC forms, existing symlink or junction aliases, Unicode normalization, and the case behavior of the hosting filesystem. If a security-sensitive identity cannot be determined unambiguously, the controller MUST fail closed before mutation.

#### Scenario: Recognize equivalent Windows spellings
- **WHEN** the same existing directory is supplied as native backslash, forward-slash, drive-letter case variant, or equivalent UNC spelling
- **THEN** every state and ownership comparison treats those spellings as one filesystem object

#### Scenario: Preserve distinct paths on a case-sensitive filesystem
- **WHEN** two existing directories differ only by case on a filesystem that proves they are distinct
- **THEN** the controller preserves their distinct identities and does not manufacture a collision

#### Scenario: Reject an ambiguous protected path
- **WHEN** a path used for a write boundary or ownership claim cannot be resolved to a stable filesystem identity
- **THEN** the controller returns a structured blocker and performs no protected mutation

### Requirement: Platform-native state directory and actor defaults
State directory resolution SHALL use, in order, a non-empty explicit `--data-dir`, a non-empty `DEV_FLOW_DATA_DIR`, a non-empty `PLUGIN_DATA`, and then the native per-user state location. The native default MUST be `%LOCALAPPDATA%\dev-flow-orchestrator` on Windows with a home-based local-app-data fallback, `~/Library/Application Support/dev-flow-orchestrator` on macOS, and `$XDG_STATE_HOME/dev-flow-orchestrator` on Linux with `~/.local/state/dev-flow-orchestrator` as fallback. Empty or whitespace-only environment values MUST be treated as unset and MUST NOT resolve relative to the current directory. Actor resolution SHALL prefer non-empty `DEV_FLOW_ACTOR`, then `USER`, then `USERNAME`, and finally the stable value `unknown`.

#### Scenario: Ignore empty state-directory variables
- **WHEN** `DEV_FLOW_DATA_DIR`, `PLUGIN_DATA`, and the relevant platform state variable are empty or whitespace-only
- **THEN** the controller selects the documented absolute home-based default and does not create state beneath the current working directory

#### Scenario: Use the Windows native default
- **WHEN** the controller runs on Windows without an explicit or plugin-provided data directory and `LOCALAPPDATA` is non-empty
- **THEN** the resolved data directory is the absolute `dev-flow-orchestrator` child of `LOCALAPPDATA`

#### Scenario: Use the macOS native default
- **WHEN** the controller runs on macOS without an explicit or plugin-provided data directory
- **THEN** the resolved data directory is the absolute `Library/Application Support/dev-flow-orchestrator` child of the user home

#### Scenario: Use the Linux XDG default
- **WHEN** the controller runs on Linux without an explicit or plugin-provided data directory and `XDG_STATE_HOME` is non-empty
- **THEN** the resolved data directory is the absolute `dev-flow-orchestrator` child of `XDG_STATE_HOME`

#### Scenario: Resolve a Windows actor
- **WHEN** `DEV_FLOW_ACTOR` and `USER` are unset and `USERNAME` contains a non-empty Windows account name
- **THEN** every newly recorded event and approval uses that account name as the actor

### Requirement: Locale-independent UTF-8 protocols
Controller state, events, artifacts, CLI JSON, and hook JSON SHALL use UTF-8 independently of the active console code page or locale. Each CLI invocation MUST emit at most one JSON object followed by one LF when it emits a response, and controller-owned persisted text MUST use LF line endings. The runtime MUST accept platform-native CRLF on textual input, MUST preserve non-ASCII values, and MUST handle undecodable child-process bytes deterministically without corrupting byte-based evidence. It MUST NOT normalize line endings or bytes in target-repository files.

#### Scenario: Emit Unicode under a legacy Windows code page
- **WHEN** a task path, actor, or error contains non-ASCII characters while the Windows console uses a non-UTF-8 code page
- **THEN** the CLI and hook write valid UTF-8 JSON with the original Unicode value and do not fail after a completed mutation

#### Scenario: Accept CRLF hook input
- **WHEN** a hook receives valid UTF-8 JSON terminated with CRLF
- **THEN** it parses the payload and emits the same semantic response as the LF-terminated form

#### Scenario: Persist canonical controller text without changing repository bytes
- **WHEN** controller-owned JSON is written while a tracked repository file contains CRLF or arbitrary binary bytes
- **THEN** the controller-owned JSON ends in LF while the tracked file bytes remain unchanged and are evidenced byte-for-byte

#### Scenario: Report undecodable subprocess output
- **WHEN** a child process returns bytes that are invalid under the selected text encoding
- **THEN** the controller returns deterministic structured output or a structured command error without raising an encoding exception or discarding raw evidence used for hashing

### Requirement: Atomic portable state writes
Every controller-owned state replacement SHALL create a unique temporary file in the destination directory, flush its contents, use the strongest standard-library durability operation supported by the host, and atomically replace the destination. The runtime MUST clean up temporary files on success and best-effort on failure, MUST NOT treat POSIX mode bits as proof of Windows ACL security, and MUST leave the previously committed file intact when replacement fails.

#### Scenario: Replace state on Windows
- **WHEN** a state mutation succeeds on Windows
- **THEN** readers observe either the complete old UTF-8 document or the complete new UTF-8 document and never a partially written document

#### Scenario: Fail an atomic replacement
- **WHEN** the operating system reports a sharing violation or another replacement failure
- **THEN** the controller returns a structured error, retains the previously committed destination, and does not report the new revision as committed

#### Scenario: Clean a temporary file after interruption
- **WHEN** an atomic write is interrupted before replacement
- **THEN** the destination remains valid and the runtime removes the uncommitted temporary file when cleanup is possible

### Requirement: Controller-managed storage remains private
Controller-created data-root directories SHALL use private platform-native permissions and every mutation SHALL verify that replacement does not broaden access. On POSIX, the data root and controller-created directories MUST be mode `0700`, while state, event, configuration, lock, receipt, and temporary files MUST be mode `0600`. On Windows, the runtime MUST use standard-library Win32 bindings to verify a non-null readable DACL, an owner equal to the current user SID or a trusted SYSTEM/Administrators SID with an explicit current-user grant, and no write-capable allow ACE for Everyone, Anonymous Logon, BUILTIN Users, or Authenticated Users on the data root and replacement file. It MUST rely on and re-check the verified inherited DACL rather than claiming POSIX mode enforcement. An unverifiable or insecure controller-managed root MUST block mutation with a structured permissions error.

#### Scenario: Create and replace private POSIX state
- **WHEN** the controller creates or atomically replaces its directories and files on a POSIX host
- **THEN** directories remain `0700`, files remain `0600`, and replacement does not add group or other permissions

#### Scenario: Use a private inherited Windows DACL
- **WHEN** the controller runs under a Windows data root whose owner and inherited DACL can be verified and contain no broad write grant
- **THEN** it creates the temporary/replacement file under that root, verifies the resulting DACL against the same policy, and permits the mutation without describing POSIX modes as ACL protection

#### Scenario: Reject insecure or unverifiable Windows storage
- **WHEN** the Windows data root or replacement file has a null/unreadable security descriptor, unacceptable owner, or broad write grant
- **THEN** the controller returns a structured permissions blocker before committing state and leaves the prior committed file intact

### Requirement: Portable subprocess and interruption handling
The controller and hook runtime SHALL launch executables with argument vectors and `shell=False`, use platform-native null-device and temporary-directory APIs, and distinguish spawn failures from non-zero child exits. Paths containing spaces, Unicode, or shell metacharacters MUST remain single arguments. For a child participating in a protected mutation, interruption handling MUST request platform-appropriate termination, escalate when necessary, and wait/reap the owned child or process group before releasing mutation locks. If child quiescence cannot be proven, the controller MUST atomically persist an unready quarantine/blocker while still holding the lock, and every later mutation MUST remain blocked until recovery proves quiescence and validates partial postconditions. It MUST NOT require POSIX-only commands, shell builtins, signals, or executable suffixes.

#### Scenario: Execute an argument containing shell metacharacters
- **WHEN** a repository or data-directory path contains spaces, Unicode, `&`, or parentheses
- **THEN** the child process receives the complete path as one argument on Windows, macOS, and Linux without shell interpretation

#### Scenario: Report a missing executable
- **WHEN** an executable cannot be spawned on the host platform
- **THEN** the controller returns a structured `COMMAND_FAILED` response that distinguishes the spawn error from a child exit code

#### Scenario: Interrupt a managed operation
- **WHEN** the process receives the platform's interactive interruption while a subprocess-backed operation is incomplete
- **THEN** the controller terminates and reaps the owned child before releasing locks, marks no incomplete result ready, and starts recovery from the last committed revision

#### Scenario: Child does not become quiescent
- **WHEN** a mutating child ignores the first termination request or cannot be proven exited after escalation
- **THEN** the controller records a durable unready quarantine before unlocking and later mutation attempts fail until recovery proves the child is gone and validates every partial Git/filesystem postcondition

### Requirement: Fail-closed cross-platform locking
Task state, workspace registry, and configuration mutations SHALL enter their critical sections only after an exclusive operating-system lock has been successfully acquired on a stable non-empty lock range. The Windows and POSIX implementations MUST provide the same mutual-exclusion semantics. Missing lock support, lock initialization failure, timeout, acquisition failure, or unlock uncertainty MUST produce a structured blocker and MUST never fall back to an unlocked mutation.

#### Scenario: Serialize two writers at the same revision
- **WHEN** two native processes attempt to mutate the same task from the same expected revision
- **THEN** exactly one process commits the next revision and the other acquires the lock later and returns a stale-revision error without duplicating the mutation

#### Scenario: Reject a failed Windows lock
- **WHEN** the Windows byte-range locking API cannot initialize or acquire the protected byte
- **THEN** the controller returns a lock-specific structured error before reading and mutating protected state

#### Scenario: Reject an unsupported lock backend
- **WHEN** no verified locking backend is available for the state filesystem
- **THEN** the controller blocks task, workspace-registry, and configuration mutations instead of yielding an unlocked critical section

#### Scenario: Recover a lock after process death
- **WHEN** a process terminates while holding an operating-system lock
- **THEN** a later process can acquire the released kernel lock and validate the persisted revision before mutating

### Requirement: Hook failure remains an advisory boundary
Hook handlers SHALL remain side-effect-free guardrails and MUST fail open only for malformed hook input, unavailable auxiliary state, or hook-internal errors. A fail-open hook MUST exit successfully without emitting a denial or malformed JSON. The controller MUST independently enforce every approval, revision, workspace, snapshot, and mutation invariant, so hook absence or failure cannot authorize a controller transition.

#### Scenario: Encounter malformed hook input
- **WHEN** a hook cannot parse its input or encounters an internal exception
- **THEN** it exits successfully without a denial response, performs no state or Git mutation, and does not emit malformed protocol output

#### Scenario: Bypass a failed hook and call the controller
- **WHEN** a hook has failed open and an unapproved mutation is submitted directly to the controller
- **THEN** the controller rejects the mutation using its normal gate, revision, and workspace checks

#### Scenario: Evaluate a healthy hook
- **WHEN** valid hook input and readable auxiliary state are available
- **THEN** the hook returns only advisory context or a documented guardrail decision and leaves durable workflow transitions to the controller

### Requirement: Standard-library-only runtime parity
The shipped controller and hook runtime SHALL implement Windows, macOS, and Linux behavior using only the Python standard library and SHALL NOT require a POSIX compatibility layer. Optional planning and discovery tools MUST remain external integrations and MUST NOT become imports required to start the controller or bundled hooks.

#### Scenario: Start in an isolated Python environment
- **WHEN** the plugin runs with a supported Python interpreter and Git but without third-party Python packages or a POSIX shell
- **THEN** the controller and bundled hooks import, display help or process protocol input, and enforce their native runtime guards successfully
