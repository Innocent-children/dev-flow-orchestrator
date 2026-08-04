## 1. Authoritative Source Enforcement

- [x] 1.1 Pin fresh installation to `main` and verify the fetched commit before package validation.
- [x] 1.2 Gate existing installations on expected origin, clean attached `main`, safe fast-forward ancestry, and exact post-update commit equality.
- [x] 1.3 Preserve the non-destructive failure boundary and actionable activation recovery output.
- [x] 1.4 Make the admitted fast-forward refuse ignored-path overwrites without rejecting unrelated ignored content.

## 2. Installer Behavior Coverage

- [x] 2.1 Build an isolated macOS standard-library test fixture with real temporary Git remotes and a recording fake Codex executable.
- [x] 2.2 Cover fresh selection, idempotent and fast-forward upgrades, dirty state, unexpected origin/ref, and local-ahead/diverged histories.
- [x] 2.3 Cover marketplace preservation and malformed input plus plugin activation failure behavior.
- [x] 2.4 Cover an ignored local path colliding with an incoming tracked path, including unchanged HEAD, bytes, marketplace, and activation state.

## 3. Package Integration and Documentation

- [x] 3.1 Add the installer suite to static package validation and the focused macOS workflow.
- [x] 3.2 Update English and Chinese public installation guidance with the authoritative `main` and safe-upgrade contract.

## 4. Verification

- [x] 4.1 Run the focused installer/package/documentation tests and POSIX shell syntax check.
- [x] 4.2 Validate the OpenSpec change, package, every packaged skill, and plugin manifest on macOS.
