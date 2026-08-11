# Phase 3 Traceability

| Requirement | Implementation | Regression evidence |
| --- | --- | --- |
| Signal-zero probing is POSIX-only | `_supports_non_destructive_pid_probe`, `_process_liveness` | `test_non_posix_liveness_never_calls_signal_zero` |
| Unknown liveness never proves stopped or authorizes PID mutation | `_classify_runtime`, `RuntimeClassification.can_signal_process`, `_stop_web` | non-POSIX failed-probe tests plus exact-probe stop/restart authority tests |
| Exact authenticated evidence establishes presentation running or conflict | `_probe_runtime`, `_classify_runtime`, `RuntimeClassification.identity_is_exact` | non-POSIX exact status/open/start and identity-conflict tests |
| PID signal authority requires exact identity and proven alive liveness | `RuntimeClassification.can_signal_process`, `_signal_authority_error`, `_stop_web` | exact unknown stop/restart, alive exact stop, and alive identity-conflict tests |
| Proven death is terminal before HTTP probing | `_classify_runtime` DEAD-first gate | real reused-port 401/404/conflict/exact-looking tests |
| Stale cleanup revalidates exact identity, PID, and death | `_clear_stale_runtime_state`, `_remove_runtime_state` | dead stop/start/restart and replacement-state race tests |
| Reused fixed ports affect only the new child | `_start_web`, `_cleanup_start_attempt` | occupied fixed-port bind failure with unrelated service retained |
| Exact startup child authority remains bounded | `_reap_owned_child`, `_cleanup_start_attempt` | startup timeout and unconfirmed-child tests |
| POSIX managed lifecycle remains exact and recoverable | process liveness, safe start/stop, exact state cleanup | live unreachable, exact stop, dead recovery, and concurrent start tests |

The non-POSIX rows are shared-code containment tests executed on the POSIX test
host through the capability boundary. They do not implement or claim native
Windows process-liveness support.
