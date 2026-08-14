# Versioned Release Promotion

This guide is for an operator producing and publishing one immutable Dev Flow
Orchestrator release. Running repository tests does not publish anything.
`scripts/promote_release.py` is the explicit external mutation and must be run
only by an operator with GitHub Release permission.

## Preconditions

- Use the canonical `Innocent-children/dev-flow-orchestrator` repository.
- Check out the exact clean `vMAJOR.MINOR.PATCH` tag. The tag, `HEAD`, and the
  recorded source commit/tree must agree.
- Use the exact Python, `uv`, build backend, tar, and gzip profile pinned in
  `release-builder.json`.
- Run all Python commands through the project `uv` environment.
- Do not provide cache, home-directory, temporary, credential, untracked, or
  ignored content as release inputs.

The clean tagged checkout is a release-builder input only. It is never shipped
as installed authority and is not used by end-user install, repair, upgrade,
rollback, migration, or uninstall.

## One-command version update

Set all checked-in current-release references to the next version with one
command. The version is mandatory and must use `MAJOR.MINOR.PATCH` without a
`v` prefix:

```sh
uv run python scripts/update_version.py --version 0.6.10
```

The updater synchronizes release metadata, English and Chinese public docs,
promotion examples, installed-release acceptance, and exact release assertions.
It fails if the current version appears in a tracked file outside that managed
set and reports every changed path as JSON. Review and commit those changes
before publishing. The publisher intentionally requires that committed, clean
source so the tag, built assets, and GitHub Release all identify the same
commit.

## One-command release

After committing the version metadata and all intended source changes, run the
one-command publisher from the repository. The version is mandatory:

```sh
uv run python scripts/publish_release.py --version 0.6.10
```

The publisher requires a clean tracked and untracked worktree, validates the
canonical `origin` and authenticated `gh` session, and builds twice from an
exact temporary clean checkout. It compares all six asset sets byte for byte
before it creates or reuses the local `v<version>` tag. It then pushes that
exact tag only when the canonical remote does not already have it and runs the
journaled Draft, upload, authenticated re-download, and publication workflow.
It never moves an existing local or remote tag and never force-pushes or
overwrites a same-version Release.

The default promotion journal is
`<system-temp>/dev-flow-promotion-<version>.json`. Use `--record` to select a
different path outside the repository when durable operator policy requires
one:

```sh
uv run python scripts/publish_release.py \
  --version 0.6.10 \
  --record /tmp/dev-flow-promotion-0.6.10.json
```

The lower-level build and promotion commands below remain available for manual
evidence collection and recovery.

## Build and deterministic comparison

From the exact tagged source, build twice into two new empty directories:

```sh
VERSION=0.6.10
uv sync --locked
uv run python scripts/build_release.py \
  --version "$VERSION" \
  --output-dir "/tmp/dev-flow-release-$VERSION-a"
uv run python scripts/build_release.py \
  --version "$VERSION" \
  --output-dir "/tmp/dev-flow-release-$VERSION-b"
```

Compare every byte in the two closed six-asset sets. Each directory must
contain exactly:

- `dev-flow-orchestrator-<version>.tar.gz`
- `release-index.json`
- `install.sh` and `install.ps1` (version-agnostic first-install entries)
- `install-<version>.sh` and `install-<version>.ps1` (version-matched
  bootstraps)

The archive contains the sealed plugin tree, one pure-Python project wheel,
hash-locked `runtime-requirements.txt`, the generating `uv.lock`, versioned
`lifecycle/**`, and `release-manifest.json`. The manifest inventories every
archive descendant except itself. The index pins the SHA-256 of the manifest's
original UTF-8 bytes; no canonical-JSON self-hash is used.

Run the contract checks once against the candidate:

```sh
uv run python -m unittest tests.test_release_artifact tests.test_release_builder \
  tests.test_release_resolver tests.test_release_commands
uv run python scripts/validate_package.py
uv run openspec validate --all --strict
```

## Native and real-host gates

Before promotion, execute the bounded final-artifact lifecycle once on native
macOS and once on native Windows 10 22H2 x64 or Windows 11 x64. Use the exact
generated bootstrap assets and the published one-line install entries, and
cover fresh install with an exact version, fresh install with `latest`
dynamic resolution, healthy repair, drift repair, `dev-flow update` upgrade,
idempotent update on the latest version, forced failed-activation rollback,
interrupted transaction recovery, `dev-flow reinstall` data clearing and
rollback, public startup, frozen-predecessor migration, uninstall, and
Controller task-data preservation. Verify that an invalid version, a missing
Release, and a simulated download failure exit non-zero before any product
state changes.

For the release candidate, use a real Codex host to read back the personal
marketplace plugin, discover the bundled `dev-flow` Skill and `.mcp.json`, run
`dev-flow-mcp --stdio`, and exercise `dev-flow update`, `dev-flow reinstall`,
and `dev-flow-uninstall`.

Static PowerShell inspection, deterministic fake Codex adapters, macOS results,
WSL, Wine, and shared Python verifier tests are not native Windows evidence.
Simulated or static checks are not real Codex evidence. If a required
environment is unavailable, leave that gate open and record the exact missing
environment rather than inferring success.

## Promotion and re-download verification

First validate the local asset set without publishing. The focused promotion
tests exercise this operation with a fake GitHub command runner:

```sh
uv run python -m unittest tests.test_release_builder.PromotionTests
```

With an authenticated `gh` session and explicit publication authority, run the
journaled promotion outside the repository:

```sh
VERSION=0.6.10
uv run python scripts/promote_release.py \
  --version "$VERSION" \
  --asset-dir "/tmp/dev-flow-release-$VERSION-a" \
  --record "/tmp/dev-flow-promotion-$VERSION.json"
```

Promotion first validates all six local assets and proves that the remote tag's
commit and tree equal the source identity in `release-index.json`. It then
creates a Draft Release, uploads the closed six-asset set, reads back the exact
asset IDs, and downloads every asset through GitHub's authenticated official
release-asset API. The same full asset and component-digest validation runs on
those downloaded bytes. Only after exact equality does promotion change the
Draft Release to public.

`--record` is a bounded, closed, atomically replaced promotion journal, not only
a final summary. It records the local identity, current phase, Draft Release ID,
uploaded asset IDs, final digests, and a bounded diagnostic. Rerunning the same
command resumes only the exact matching recorded draft after re-reading the
remote tag, release, and assets. An unrecorded draft, a mismatched release, or a
published same-version release without durable prior remote-verification
evidence is ambiguous and is refused; promotion never overwrites it. If upload,
download, or validation fails, the release remains draft.

The final journal includes source commit/tree, release ID, all asset digests,
and the index, archive, raw manifest, wheel, requirements, lock, plugin,
lifecycle, and bootstrap component digests. Repository tests exercise this
workflow only through fake command/API adapters and never mutate GitHub.

The canonical GitHub repository and Release are the publication source. The
version-matched bootstrap fixes repository, version, archive name, and index
digest; SHA-256 proves that acquired bytes match those pinned bytes. The
first-install entries and the installed `dev-flow update` and
`dev-flow reinstall` commands share the same version grammar and canonical
HTTPS download rules; `latest` resolves only from the canonical repository's
official release listing and rejects drafts and prereleases. None of this is
an independent digital signature, and this release does not add signing,
Sigstore, a transparency log, mirrors, or update channels.

Do not commit generated archives, wheels, asset directories, promotion records,
temporary profiles, virtual environments, downloads, or credentials.
