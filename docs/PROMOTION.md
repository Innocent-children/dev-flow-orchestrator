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

## Build and deterministic comparison

From the exact tagged source, build twice into two new empty directories:

```sh
VERSION=0.6.0
uv sync --locked
uv run python scripts/build_release.py \
  --version "$VERSION" \
  --output-dir "/tmp/dev-flow-release-$VERSION-a"
uv run python scripts/build_release.py \
  --version "$VERSION" \
  --output-dir "/tmp/dev-flow-release-$VERSION-b"
```

Compare every byte in the two closed four-asset sets. Each directory must
contain exactly:

- `dev-flow-orchestrator-<version>.tar.gz`
- `release-index.json`
- `install.sh`
- `install.ps1`

The archive contains the sealed plugin tree, one pure-Python project wheel,
hash-locked `runtime-requirements.txt`, the generating `uv.lock`, versioned
`lifecycle/**`, and `release-manifest.json`. The manifest inventories every
archive descendant except itself. The index pins the SHA-256 of the manifest's
original UTF-8 bytes; no canonical-JSON self-hash is used.

Run the contract checks once against the candidate:

```sh
uv run python -m unittest tests.test_release_artifact tests.test_release_builder
uv run python scripts/validate_package.py
openspec validate install-versioned-release-artifact --strict
```

## Native and real-host gates

Before promotion, execute the bounded final-artifact lifecycle once on native
macOS and once on native Windows 10 22H2 x64 or Windows 11 x64. Use the exact
generated bootstrap asset and cover fresh install, healthy repair, drift
repair, successful upgrade, forced failed-activation rollback, interrupted
transaction recovery, public startup, frozen-predecessor migration, uninstall,
and Controller task-data preservation.

For the release candidate, use a real Codex host to read back the personal
marketplace plugin, discover the bundled `dev-flow` Skill and `.mcp.json`, run
`dev-flow-mcp --stdio`, and uninstall through `dev-flow-uninstall`.

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

With an authenticated `gh` session and explicit publication authority, create
the release once and write the promotion record outside the repository:

```sh
VERSION=0.6.0
uv run python scripts/promote_release.py \
  --version "$VERSION" \
  --asset-dir "/tmp/dev-flow-release-$VERSION-a" \
  --record "/tmp/dev-flow-promotion-$VERSION.json"
```

Promotion refuses an existing same-version release, validates all four assets
before upload, then re-downloads them from their exact canonical
version-specific GitHub locators. The record includes source commit/tree,
release ID, all asset digests, and the index, archive, raw manifest, wheel,
requirements, lock, plugin, lifecycle, and bootstrap component digests.

The canonical GitHub repository and Release are the publication source. The
version-matched bootstrap fixes repository, version, archive name, and index
digest; SHA-256 proves that acquired bytes match those pinned bytes. It is not
an independent digital signature and this release does not add signing,
Sigstore, a transparency log, mirrors, or update channels.

Do not commit generated archives, wheels, asset directories, promotion records,
temporary profiles, virtual environments, downloads, or credentials.
