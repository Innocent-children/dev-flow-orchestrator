## Why

`add-native-windows-runtime` makes the core Controller, CLI, state store, Git execution, and workspace snapshots usable on common Windows x64 clients. It does not yet make the installed Codex plugin usable there. The packaged Hook still has only a POSIX command and launcher, the controller locator is rendered as a POSIX shell command, installation and uninstallation are shell-only and reject non-macOS hosts, focused validation treats the package as macOS-only, and public guidance advertises only macOS.

The missing work is product integration, not another runtime redesign. This change completes that integration while keeping the same Controller, workflows, assurance logic, Delivery Dossier, persisted model, plugin identity, and Web UI.

## Prerequisite

This change depends on the accepted behavior of `add-native-windows-runtime`:

- native Windows path comparison and task discovery;
- controller state storage and locking;
- bounded Git execution and cancellation;
- ordinary Windows worktree snapshots;
- the core CLI lifecycle.

If implementation reveals a defect in those foundations, the defect is fixed at that existing platform seam with a targeted regression test. This change SHALL NOT introduce a second Windows runtime.

## User Value

After this change, a developer on a common Windows 10 22H2 x64 or Windows 11 x64 client can:

1. install Dev Flow from PowerShell without WSL, Git Bash, or Cygwin;
2. review and trust the installed Hook through Codex;
3. start or resume the same task from any member repository;
4. receive the current Controller projection and use a copyable PowerShell locator;
5. use the existing workflows, assurance, review, Dossier, and read-only Web UI; and
6. uninstall the plugin and marketplace registration while preserving external task data.

## What Changes

- Add `commandWindows` beside every existing plugin Hook command.
- Add `scripts/dev_flow_python_launcher.cmd` and select it from the public Hook bootstrap on Windows.
- Render the injected Controller locator using PowerShell literal quoting while retaining POSIX `shlex` rendering on macOS.
- Keep structured `Write`, `Edit`, and `apply_patch` data-path checks authoritative; add only simple, conservative Windows shell checks rather than a PowerShell parser.
- Add `scripts/install.ps1` and `scripts/uninstall.ps1` using Windows PowerShell 5.1-compatible syntax and argument-array process invocation.
- Apply the existing authoritative `main`, clean-checkout, fast-forward-only, candidate validation, marketplace isolation, plugin activation, and conservative source-removal rules to Windows.
- Make installation receipts explicitly tell the user that plugin installation does not establish Hook trust and that `/hooks` review is required.
- Validate the existing Web UI on Windows through its current loopback, token, read-only, explicit-live, cancellation, and foreground-shutdown contracts.
- Extend candidate validation and CI with Windows assets and representative installed behavior without cloning the complete macOS business matrix.
- Update English and Simplified Chinese public guidance and support boundaries.

## What Does Not Change

- No Windows-specific Controller, workflow, assurance profile, Skill, Schema, state shape, data namespace, Delivery Dossier, or Web UI is created.
- No general shell or PowerShell parser is introduced; Hook shell inspection remains a useful fail-open guardrail.
- No custom Windows ACL management, background service, MSI/MSIX package, automatic updater, telemetry, or browser launcher is introduced.
- No support is claimed for Windows ARM64, 32-bit Python, Windows Server, WSL execution, UNC/SMB/NAS paths, `\\wsl$`, or mapped network storage.
- No historical data migration or cross-operating-system task-transfer feature is added.
- This change does not require a Windows-specific version or independently choose the next product version. If normal release policy changes `PRODUCT_VERSION`, that remains one whole-product cut under the project's existing no-compatibility policy.
- The Windows job does not rerun every workflow, assurance profile, Python minor, repository cardinality, and boundary maximum.

## Capabilities

### New Capabilities

- `native-windows-product-support`: Defines the installed Windows Hook, Controller locator, support boundary, Hook trust handoff, and one-product integration contract.

### Modified Capabilities

- `authoritative-plugin-installation`: Adds native PowerShell install/uninstall entry points under the existing source, marketplace, plugin activation, and conservative-removal authority rules.
- `local-read-only-web-ui`: Proves the existing integrated foreground read-only Web UI on the Windows runtime without adding a new UI implementation.
- `package-delivery-validation`: Requires the Windows assets, proportional automation, installed journey, client smoke evidence, and consistent bilingual support claims.

## Impact

Expected production changes are concentrated in:

- `hooks/hooks.json`;
- `hooks/dev_flow_hook.py`;
- `src/dev_flow_orchestrator/hook.py`;
- `scripts/dev_flow_python_launcher.cmd`;
- `scripts/install.ps1`;
- `scripts/uninstall.ps1`;
- `scripts/validate_package.py`;
- focused Hook, installer, uninstaller, Web UI, and installed-journey tests;
- `.github/workflows/focused.yml` or one focused Windows workflow;
- current English and Simplified Chinese public documents.

The runtime platform package, Controller, model, engine, workflow definitions, assurance planner, review governance, snapshot schemas, and Dossier generation change only if a concrete integration defect requires a narrow fix.

## Definition of Done

The change is complete when:

1. installed plugin Hooks launch through the native Windows command and launcher;
2. SessionStart and UserPromptSubmit restore the same task context, including from a secondary member repository;
3. the injected locator executes unchanged in PowerShell for ordinary paths with spaces and Unicode;
4. PowerShell fresh install, repair, eligible fast-forward update, activation failure, uninstall, and `-KeepSource` behavior satisfy the existing authority boundaries;
5. installation clearly requires `/hooks` review and does not claim an untrusted Hook is active;
6. the existing Web UI starts, observes one live task, cancels capture, and shuts down cleanly on Windows;
7. one installed Windows journey and one multi-repository recovery smoke pass;
8. Windows 11 x64 client evidence and a shorter Windows 10 22H2 x64 smoke both pass;
9. bilingual public guidance states the tested support boundary; and
10. the existing macOS focused and installer suites remain green.
