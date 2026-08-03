## Why

The public installer currently clones whichever branch the remote advertises and upgrades whichever branch is already checked out. That can activate unapproved, locally advanced, or diverged source even though the repository URL and working tree checks pass. In addition, Git's default merge behavior may overwrite an ignored local path when authoritative `main` starts tracking the same path, because the ordinary porcelain status check does not report ignored files.

## What Changes

- Define `main` as the installer's authoritative repository ref and select it explicitly for fresh installs.
- Require existing installations to use the expected origin, a clean `main` checkout, and an exact verified `origin/main` commit before activation.
- Permit upgrades only when the installed commit can be fast-forwarded to the fetched authoritative commit; reject local-ahead and diverged histories without rewriting user work.
- Make the fast-forward itself refuse to overwrite ignored local paths while allowing unrelated ignored content to remain in place.
- Add isolated installer behavior tests and focused validation coverage for install, upgrade, rejection, marketplace, and activation-failure paths.
- Document the source/ref and safe-upgrade guarantees in the public installation guidance.

## Capabilities

### New Capabilities

- `authoritative-plugin-installation`: Defines authoritative source selection, safe upgrade eligibility, pre-activation verification, marketplace registration, and activation failure behavior for the public installer.

### Modified Capabilities

None.

## Impact

- Affected code: `scripts/install.sh`, `scripts/validate_package.py`, and the isolated installer test module.
- Affected automation: the focused macOS workflow runs the installer behavior suite.
- Affected documentation: the English and Chinese install surfaces describe the authoritative `main` ref and refusal conditions.
- Runtime dependencies remain unchanged; shipped runtime code continues to use only the Python standard library.
