## ADDED Requirements

### Requirement: Runtime receipt v2 records exact installed release content

Every new managed release SHALL contain one closed, bounded, versioned receipt v2
recording at least:

- schema version and `release_id`;
- verified source commit and tree;
- wheel SHA-256;
- Dev Flow distribution metadata digest;
- Dev Flow installed-file paths and digests;
- exact normalized installed dependency name/version inventory;
- dependency metadata and RECORD digests;
- Python executable identity;
- runtime and release paths;
- launcher digest;
- ownership manifest digest.

The inventories SHALL be derived from the installed release rather than copied from
requested inputs. Missing, extra, duplicate, or changed installed distributions or
files SHALL be mismatches. The receipt and ownership manifest SHALL use direct
references and SHALL NOT require a recursive digest graph.

#### Scenario: A new runtime receipt is created

- **WHEN** a sealed wheel and its dependencies have been installed into staged
  runtime
- **THEN** receipt v2 records the actual installed package, metadata, RECORD,
  dependency, Python, launcher, release, and ownership evidence before promotion

#### Scenario: Dev Flow package bytes or metadata differ

- **WHEN** an installed Dev Flow file, distribution METADATA, RECORD, or recorded
  file inventory differs from receipt v2
- **THEN** complete verification fails even when a version or behavioral probe could
  still succeed

#### Scenario: Dependency inventory differs

- **WHEN** a dependency is missing, extra, duplicated, has a different version, or
  has changed METADATA or RECORD content
- **THEN** complete verification fails and the runtime is not reusable

### Requirement: Launchers verify receipt v2 before importing Dev Flow

POSIX and PowerShell CLI and MCP launchers SHALL invoke the same standard-library
verifier with bytecode disabled before importing Dev Flow. The verifier SHALL parse
bounded receipt v2, confirm expected release and runtime paths, verify Python
identity, Dev Flow package and distribution content, exact dependency inventory,
dependency metadata/RECORD content, launcher identity, and ownership-manifest
identity, and only then execute the installed product.

Startup SHALL fail non-zero with repair guidance on missing, malformed,
incompatible, wrong-path, or mismatched evidence and SHALL NOT modify or repair the
runtime. Installer and repair SHALL also validate launcher bytes independently.

#### Scenario: Runtime receipt is missing

- **WHEN** a launcher resolves an installed release without receipt v2
- **THEN** startup exits before Dev Flow import and directs the operator to repair

#### Scenario: Runtime receipt is malformed or incompatible

- **WHEN** receipt JSON is malformed, violates its bound, lacks required fields, or
  uses an unsupported schema
- **THEN** startup exits before Dev Flow import with a bounded receipt error

#### Scenario: Release or Python identity is wrong

- **WHEN** receipt paths or `release_id` name another release, or the selected Python
  executable identity differs
- **THEN** startup exits before Dev Flow import and directs the operator to repair

#### Scenario: Package metadata or dependency content drifts

- **WHEN** Dev Flow bytes, METADATA, RECORD, dependency membership, dependency
  version, or dependency metadata/RECORD differs
- **THEN** startup exits before Dev Flow import rather than relying on a successful
  smoke response

#### Scenario: Ownership manifest differs

- **WHEN** the ownership manifest is missing or its digest differs from receipt v2
- **THEN** startup exits before Dev Flow import and does not treat the release as
  completely verified

### Requirement: Repair reuses only a complete receipt v2 match

Repair SHALL run the complete verifier and independent launcher-byte check before
returning `reused=true`. Any mismatch SHALL rebuild from the sealed Git release into
new staging and SHALL NOT patch or bless the suspect runtime in place. A missing or
legacy receipt SHALL trigger the same rebuild path without adopting current runtime
contents. A legacy or suspect path SHALL be retained whenever exact ownership does
not authorize its removal.

The guarantee detects accidental modification, loss, and content drift when the
conforming launcher invokes the verifier. It SHALL NOT be described as protection
against an actor able to replace the launcher, verifier, receipt, and runtime
coherently.

#### Scenario: Clean runtime is repaired

- **WHEN** receipt v2, installed content, Python, launcher, release path, and
  ownership manifest all match
- **THEN** repair may return `reused=true` without changing the runtime

#### Scenario: Runtime content is tampered before repair

- **WHEN** package, metadata, RECORD, dependency, Python, release path, or ownership
  evidence differs
- **THEN** repair stages and selects a rebuilt release, returns `reused=false`, and
  the tampered marker is absent from the selected runtime

#### Scenario: Launcher bytes are tampered before repair

- **WHEN** the installed launcher no longer matches the expected digest, including
  when it no longer invokes the verifier
- **THEN** repair detects the mismatch independently and stages a conforming release
  and launcher instead of reusing the installation

#### Scenario: Legacy receipt is repaired

- **WHEN** the selected runtime has a missing, v1, or otherwise incompatible receipt
- **THEN** repair rebuilds a receipt-v2 release without silently adopting the old
  runtime inventory and reports any retained legacy path
