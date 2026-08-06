## 1. Confirm the runtime prerequisite and release boundary

- [x] 1.1 Merge or otherwise establish the accepted `add-native-windows-runtime` path, storage, Git process, snapshot, and core-journey behavior before enabling Windows product claims.
- [x] 1.2 Record the current Hook JSON shape, launcher contract, installer authority rules, uninstaller safety rules, Web UI lifecycle, package validator asset list, and public support text that this change will touch.
- [x] 1.3 Add a scope gate proving that this change does not create separate Windows workflows, Schemas, state fields, product versions, Web UI code paths, or historical migration logic.

## 2. Add native Windows Hook launch

- [x] 2.1 Add `scripts/dev_flow_python_launcher.cmd` with disabled delayed expansion, handler validation, supported 64-bit Python selection, `-X utf8 -I -S`, original argument forwarding, and nonzero no-Python diagnostics.
- [x] 2.2 Add `commandWindows` to SessionStart, UserPromptSubmit, and PreToolUse while preserving every current POSIX command, matcher, timeout, and status message.
- [x] 2.3 Update the public Hook bootstrap and internal fallback to select the `.cmd` launcher only on Windows.
- [ ] 2.4 Test the real Windows command string and launcher with ordinary, spaced, and Unicode plugin/data paths plus missing or unsupported Python.

## 3. Add the PowerShell locator and bounded guard behavior

- [x] 3.1 Render Windows Controller locators with one PowerShell call operator and single-quoted literal arguments; retain POSIX `shlex.join` unchanged.
- [x] 3.2 Recognize only the exact generated Windows Controller prefix and reject obvious PowerShell command tails without introducing a general parser.
- [x] 3.3 Route `Write`, `Edit`, and `apply_patch` paths through the runtime host comparison before inventory loading; add simple literal and `PLUGIN_DATA` environment-reference checks for Windows shell commands.
- [x] 3.4 Test SessionStart, UserPromptSubmit, no-task guidance, secondary-member discovery, exact locator execution, structured data-path denial, ordinary repository writes, and fail-open Hook exceptions on Windows.
- [x] 3.5 Update Hook and installation text to describe the guard as useful but not complete enforcement and to require `/hooks` review of the exact installed definition.

## 4. Implement native PowerShell installation

- [x] 4.1 Add a Windows PowerShell 5.1-compatible `scripts/install.ps1` with strict error handling, x64/64-bit Python checks, Git/Codex discovery, current environment overrides, and literal-path handling.
- [x] 4.2 Implement fresh authoritative `main` clone and existing-source verification, explicit fetch, equal or fast-forward-only update, ignored-path collision protection, and final clean exact-commit verification without stash, clean, reset, branch switch, or merge.
- [x] 4.3 Run the verified candidate's package validator before marketplace or plugin activation and read the installed version from the validated manifest rather than hard-coding a Windows version.
- [x] 4.4 Implement strict marketplace validation, unrelated-entry preservation, exactly-one Dev Flow replacement, same-directory atomic write, and source-within-marketplace-root validation.
- [x] 4.5 Implement absent/install, same-version repair, and older-version upgrade flows using `codex plugin list --marketplace personal --json`, remove, and add; return nonzero with recovery commands on activation failure.
- [x] 4.6 Print a bounded receipt containing action, versions, source, marketplace, Codex state root, first prompt, and an explicit `/hooks` review requirement without claiming Hook trust.

## 5. Implement conservative PowerShell uninstallation

- [x] 5.1 Add `scripts/uninstall.ps1` with `-KeepSource` and help, validating marketplace and plugin state before mutation.
- [x] 5.2 Remove only the installed plugin and Dev Flow marketplace entry while preserving unrelated entries and all external Controller task data.
- [x] 5.3 Remove source by default only after validating product identity, allowed origin, attached `main`, clean tracked/untracked/ignored state, and no local-only commits; otherwise preserve it with an actionable refusal.
- [x] 5.4 Add focused Windows lifecycle tests for fresh install, repair, eligible fast-forward, dirty refusal, malformed marketplace, activation failure, uninstall, `-KeepSource`, and unsafe source refusal using isolated local Git remotes and stub Codex executables.

## 6. Prove the installed product surfaces

- [x] 6.1 Run the existing Web UI on Windows and fix only concrete integration defects in startup receipt, loopback binding, authenticated inventory/detail, explicit live observation, cancellation, Ctrl+C shutdown, or no-mutation behavior.
- [x] 6.2 Add one installed Windows vertical journey covering verified source, marketplace, plugin activation, Hook bootstrap, one representative task through current assurance/Dossier completion, Web UI inspection, and uninstall.
- [x] 6.3 Add one shorter two-repository smoke proving Hook discovery and resume from the non-first member and one aggregate snapshot path.

## 7. Extend validation and publish the bounded support claim

- [x] 7.1 Add `.cmd` and PowerShell assets and tests to package inventory/version scanning; validate paired `command`/`commandWindows` values and make validator result text host-neutral.
- [ ] 7.2 Extend the focused Windows CI path with launcher, Hook, lifecycle, Web UI, and installed-smoke tests while retaining the existing macOS job as the broad product regression gate.
- [ ] 7.3 Record a complete Windows 11 x64 client install-to-uninstall journey and a shorter Windows 10 22H2 x64 smoke, including OS build, PowerShell, Python, Git, and Codex versions.
- [x] 7.4 Update README, INSTALL, ARCHITECTURE, ROADMAP, and CONTRIBUTING in English and Simplified Chinese with PowerShell commands, Hook trust, supported Windows x64 clients, exclusions, Web UI use, validation limits, and no-migration boundaries.
- [ ] 7.5 Run the package validator on macOS and Windows, run existing macOS installer/uninstaller and focused suites, run `openspec validate ship-native-windows-support --type change --strict`, and review the final diff for runtime duplication or test-matrix expansion.
