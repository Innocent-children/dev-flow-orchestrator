## 1. Preserve the confirmed failures

- [x] 1.1 Add real-process regressions for unreachable status, duplicate start,
  stop authority loss, and startup-timeout orphaning; record the failures before
  implementation.
- [x] 1.2 Add exact identity, stale death recovery, termination failure, safe
  restart/open, and concurrent start regressions with bounded cleanup.

## 2. Separate runtime facts

- [x] 2.1 Implement centralized process-liveness, HTTP reachability, and exact
  identity classification, including POSIX-only signal-zero probing and
  alive/dead/unknown containment on unsupported hosts, with proven death terminal
  before any HTTP probe.
- [x] 2.2 Extend authenticated read-only metadata with managed instance and process
  identity while preserving standalone unmanaged behavior and HTTP safety.

## 3. Preserve lifecycle authority

- [x] 3.1 Make status observational and make start fail closed for starting,
  unreachable, unknown-liveness, and identity-conflicting state.
- [x] 3.2 Separate presentation from process mutation authority; make stop signal
  only exact identity with proven alive liveness and clean only an exact dead
  instance; make restart preserve the same gate while status/open retain exact
  presentation behavior for unknown liveness. Revalidate instance ID, PID, and
  death before stale cleanup so port reuse or replacement state cannot override it.
- [x] 3.3 Reap an owned failed-start child before exact reservation cleanup and
  retain state when death cannot be confirmed.
- [x] 3.4 Prove two concurrent starts create at most one child under the existing
  bounded control lock.

## 4. Verify compatibility and scope

- [x] 4.1 Run focused lifecycle, direct Web/CLI, Phase 1, and Phase 2 regressions and
  freeze the implementation, including platform-neutral non-POSIX containment
  exact-identity signal-authority, and real reused-port stale recovery tests on the
  POSIX development host.
- [x] 4.2 Run one complete unittest discovery, package validation, all active
  OpenSpec strict validation, and `git diff --check`.
- [x] 4.3 Run one independent final read-only review; complete this task only after
  `APPROVE` with no findings.
