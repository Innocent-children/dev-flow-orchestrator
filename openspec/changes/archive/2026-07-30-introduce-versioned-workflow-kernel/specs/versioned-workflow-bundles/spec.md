## ADDED Requirements

### Requirement: Complete package-owned workflow bundles
The controller SHALL load every bundle-aware workflow from a package-owned
workflow bundle. A bundle SHALL contain or transitively reference its graph,
node definitions, handler contract identities, guard and gate identities,
input and output schemas, human-readable playbooks, and all metadata required
to derive workflow progress and legal actions. Its transitive references SHALL
also include every recovery policy, schema, validator, and executable handler
that can dispatch, observe, settle, reattach, stop, reconcile, abandon,
compensate, return bounded hostless operator intervention, close containment,
archive, or unblock an action. Every
bundle-relative reference MUST resolve to exactly one file within the bundle
root. Target repositories, task data directories, environment variables,
hooks, Skills, generic recovery helpers, and external tools MUST NOT add,
replace, or shadow a workflow bundle or executable handler.

#### Scenario: Load a complete packaged bundle
- **WHEN** the controller starts with a packaged bundle whose transitive references all resolve within its bundle root
- **THEN** the controller loads the complete bundle as one catalog entry without consulting a target repository or task data directory for missing workflow content

#### Scenario: Reject a bundle reference that escapes its root
- **WHEN** a bundle contains an absolute path, traversal segment, symlink escape, or another reference that resolves outside the bundle root
- **THEN** bundle validation fails with a structured diagnostic and the controller does not expose or execute that bundle

#### Scenario: Ignore a repository-provided workflow override
- **WHEN** a target repository contains a workflow file using the same identifier and version as a packaged bundle
- **THEN** the controller continues to resolve the package-owned bundle and does not load executable workflow behavior from the target repository

#### Scenario: Reject an incomplete recovery closure
- **WHEN** an action can reach a receipt observer, live-target verifier, stop, abandonment, compensation, hostless operator-intervention, containment, archive, or unblock implementation that is absent from the bundle's transitive handler closure
- **THEN** bundle validation rejects the action before activation or recovery and does not substitute a generic unversioned helper

### Requirement: Canonical bundle identity
Every workflow bundle SHALL have a deterministic SHA-256 identity computed from
a canonical manifest of all transitive bundle content using
`dev-flow-bundle-identity/v1`. `U64BE` means an unsigned 64-bit big-endian
integer. Bundle paths MUST be repository-relative UTF-8 POSIX paths with no
absolute, drive, UNC, backslash, empty, `.` or `..` segment; every segment MUST
be NFC, pass the existing portable package-path validator, and be unique under
NFC plus Unicode case-folding. Symlinks and special files are forbidden.

The bundle manifest MUST explicitly classify each transitively referenced
regular file as JSON (`J`), text (`T`), or binary (`B`), without globs. JSON
payloads MUST decode as UTF-8 without a BOM, reject duplicate object keys,
non-NFC keys or strings, floats, integers outside the signed 64-bit range,
`NaN`, and infinities, then encode exactly as Python standard-library
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
allow_nan=False).encode("utf-8")`. Text payloads MUST decode as UTF-8 without a
BOM, contain NFC text, and canonicalize CRLF and CR to LF. Binary payloads
preserve their bytes exactly.

For each referenced handler, the static registration manifest MUST declare an
exact non-empty set of package-relative implementation files and classify each
one as `J`, `T`, or `B` under the same canonical payload rules used by bundle
files; globs, inferred file kinds, and runtime discovery are forbidden. Its
implementation digest is:

```text
SHA256(
  b"dev-flow-handler-implementation-v1\0"
  || U64BE(len(handler_id)) || UTF8(handler_id)
  || U64BE(len(contract_id)) || UTF8(contract_id)
  || U64BE(file_count)
  || for each canonical path in UTF-8 byte order:
       U64BE(len(path)) || UTF8(path)
       || kind_byte
       || U64BE(len(canonical_payload)) || canonical_payload
)
```

The graph digest is
`SHA256(b"dev-flow-graph-v1\0" || U64BE(len(root_json)) || root_json)`, where
`root_json` is the canonical JSON payload of the root graph. The bundle digest
is:

```text
SHA256(
  b"dev-flow-workflow-bundle-v1\0"
  || U64BE(file_count)
  || for each file in UTF-8 path-byte order:
       U64BE(len(path)) || UTF8(path)
       || kind_byte
       || U64BE(len(canonical_payload)) || canonical_payload
  || U64BE(handler_count)
  || for each handler in UTF-8 handler-ID byte order:
       U64BE(len(handler_id)) || UTF8(handler_id)
       || U64BE(len(contract_id)) || UTF8(contract_id)
       || raw_32_byte_implementation_digest
)
```

`kind_byte` is `0x4a`, `0x54`, or `0x42` for `J`, `T`, or `B`. The identity
MUST cover the graph, node definitions, schemas, playbooks, handler contract
identifiers and versions, and every declared handler implementation file. The
handler manifest SHALL be the complete transitive closure of happy-path and
recovery behavior, including dispatch, receipt and live-target observation,
runtime settlement or reattachment, target-bound control,
`ACCEPTED`/`ABANDONED`/`UNRESOLVED` decisions, compensation planning and
verification, containment closure, archive, and scope unblocking. Any unlisted
transitive reference or runtime call target, duplicate manifest path, portable
path collision, unsupported content kind, or malformed canonical payload MUST
fail before activation or recovery. Repeated independent macOS validations of
the same logical bundle and registered implementations MUST produce the same
identity, while any semantic content or happy-path/recovery handler
implementation change MUST produce a different identity. The byte contract
remains portable, but this delivery makes no native Windows or Linux claim.

#### Scenario: Compute a portable bundle identity
- **WHEN** the same logical JSON definitions, text playbooks, binary content, and handler implementations are validated from independent macOS checkouts
- **THEN** canonicalization produces the same ordered manifest and SHA-256 bundle identity in every run

#### Scenario: Ignore insignificant JSON formatting
- **WHEN** only JSON object key order or insignificant JSON whitespace differs between two otherwise identical bundle sources
- **THEN** both sources produce the same canonical JSON bytes and bundle identity

#### Scenario: Detect a handler implementation change
- **WHEN** a registered handler implementation changes while the graph, node definitions, handler identifier, and declared handler contract version remain unchanged
- **THEN** the handler implementation digest and enclosing bundle identity change

#### Scenario: Detect recovery-only semantic drift
- **WHEN** only an abandonment verifier, compensation gate or bridge adapter, receipt observer, containment closer, archive helper, or another transitive recovery implementation changes
- **THEN** its handler implementation identity and every enclosing bundle identity change exactly as for happy-path handler drift

#### Scenario: Reject colliding logical package paths
- **WHEN** two bundle entries normalize to the same portable relative-path identity
- **THEN** validation rejects the bundle before computing an activatable identity

#### Scenario: Reject ambiguous semantic JSON
- **WHEN** a bundle JSON file contains a duplicate key, float, out-of-range integer, non-NFC string, BOM, `NaN`, or infinity
- **THEN** canonicalization returns a stable structured error and computes no activatable graph or bundle identity

#### Scenario: Match the normative identity vectors
- **WHEN** the macOS validator processes the normative bundle, text-newline, binary, and handler-only-drift vectors
- **THEN** it produces the exact declared graph, handler, and bundle digests, and the drift vectors produce the exact distinct declared digests

The following is the normative minimal vector. Quoted source payloads use the
visible escapes shown; `hex:` payloads are literal bytes.

```text
bundle files, sorted by path:
  blob.bin      kind B  source hex:00ff0a
  graph.json    kind J  source "{\"workflow_version\":1,\r\n \"workflow_id\":\"vector\"}\r\n"
  playbook.md   kind T  source "Step one.\r\n"

canonical graph.json:
  "{\"workflow_id\":\"vector\",\"workflow_version\":1}"

handler:
  handler_id  = "guard.vector/v1"
  contract_id = "dev-flow-guard/v1"
  implementation file:
    scripts/vector_guard.py
    kind T
    source "def guard(ctx):\r\n    return True\r\n"

expected graph_sha256:
  d2933a444dbd4bc91552fabe14840fbafdd663e25b4eccef9855d45b6cedf52c
expected handler implementation sha256:
  2a725499ab81891164ea25f08b8fbb9cfb89c316c051b6c7c91c5370628f8d80
expected bundle_sha256:
  e7330dd1bd61cba66e19cd4c687be98d3a484a42216ddb411196e292f5b6fb2a
```

The normative handler-only drift vector changes only `return True` to
`return False`, retaining the CRLF source ending and every other input:

```text
expected drifted handler implementation sha256:
  9fb28a7f17498bfe38925dad0b97efa0345c667d801cfe7733da559346a7442c
expected unchanged graph_sha256:
  d2933a444dbd4bc91552fabe14840fbafdd663e25b4eccef9855d45b6cedf52c
expected drifted bundle_sha256:
  d3a9189eb355c773d215e80901d8424a88c3ade5678cdb5480d0d20b40e23c87
```

### Requirement: Workflow generation and task schema evolve independently
The V4 safety successors SHALL use workflow identities `full@4` and `lite@4`
while continuing to persist task schema v3. A workflow-version increment MUST
NOT implicitly increment, migrate, or reinterpret `schema_version`; a task
schema change requires its own separately specified storage contract. The first
V4 task revision SHALL therefore contain `schema_version: 3` and an exact
workflow reference whose workflow version is `4`. The controller MUST reject a
caller or bundle that treats workflow version 4 as task schema v4.

#### Scenario: Create a V4 full task
- **WHEN** the exact `full@4` profile is valid and explicitly activated for new creation
- **THEN** the first task state records task schema v3 and an exact pinned `full@4` bundle identity

#### Scenario: Create a V4 lite task
- **WHEN** the exact `lite@4` profile is valid and explicitly activated for new creation
- **THEN** the first task state records task schema v3 and an exact pinned `lite@4` bundle identity

#### Scenario: Conflate the two version axes
- **WHEN** a caller, validator, or migration path infers task schema v4 solely because the pinned workflow is `full@4` or `lite@4`
- **THEN** validation fails before the first commit and no task is created or migrated

### Requirement: New tasks pin an exact validated bundle
Before creating a bundle-aware task, the controller SHALL validate and resolve
one exact workflow bundle and SHALL persist a workflow reference containing its
workflow identifier, workflow version, bundle schema version, and bundle
identity in the task's first committed state. Every subsequent mutation MUST
resolve that exact identity and MUST NOT substitute another bundle solely
because its identifier or version matches. Bundle resolution and task creation
MUST occur under the normal task-creation serialization so the selected bundle
cannot change between validation and the first commit.

#### Scenario: Create a task with a pinned bundle
- **WHEN** a caller creates a task using a valid active workflow bundle
- **THEN** the first task revision records the exact workflow identifier, version, bundle schema version, and bundle identity used to initialize the task

#### Scenario: Resume after the installed default changes
- **WHEN** the installed default workflow advances after a task has pinned an older bundle
- **THEN** the controller continues to evaluate the task with its exact pinned bundle and does not adopt the new default

#### Scenario: Detect a same-name substitution
- **WHEN** a task pins a bundle identity but the available bundle with the same workflow identifier and version has a different identity
- **THEN** the controller returns a structured bundle-mismatch blocker and performs no task, state, workspace, or Git mutation

### Requirement: Bundle-aware task creation is explicitly activated
Support for reading and validating a bundle MUST NOT by itself make that bundle
eligible for new tasks. A package-owned activation manifest SHALL enable
schema-v3 creation per exact bundle identity and execution profile only after
every reachable node kind, edge, handler, guard, gate, reducer, side effect,
recovery path, and rollback rehearsal required by that profile has passed its
declared compatibility and safety suite. Single-repository and
multi-repository profiles MUST be activated separately. An inactive profile
MUST fail closed before the first task commit. Deactivation SHALL affect only
future creation and MUST NOT prevent an existing task from resolving and
executing its pinned bundle.

Activation completeness SHALL include both movement reachability and action
closure. For every movement-reachable node, every publicly declared node
action MUST compile uniquely into an identity-covered same-node action edge
whose complete transitive happy-path/recovery handler closure, guards, gate,
reducers, confirmation, bounded writes, side effects, canonical concurrency
class and scopes, synchronous-quiescence or asynchronous-handoff settlement,
receipt, dispatch, control, live-target abandonment evidence,
workflow-gated/host-one-shot-approved compensation, containment/archive/
unblock, and recovery contracts all resolve and whose required compatibility,
concurrency, recovery, and rollback suites have passed. Same-node action edges
do not create workflow movement cycles, but an unknown, duplicate, uncompiled,
untested, identity-incomplete, or partially recoverable action MUST make the
profile inactive.

For every reachable node that declares an external-tool capability, activation
closure MUST also include the package-owned external-tool capability and
evidence suite. That suite MUST prove least-capability assignment; distinct
controller-selected baseline and current-generation workspace project
identities with exact phase, generation, repository, and source-snapshot
binding; source-coverage validation; and serial enforcement of a request-bound
one-shot workflow authorization plus current host approval by a host-owned
write bridge for every externally visible write.

For a macOS profile whose current host does not provide trusted abandonment or
compensation authority, recovery closure SHALL instead require the
identity-covered `UNRESOLVED` path, bounded
`dev-flow-v4-operator-intervention/v1`, explicit user-action stop, and proof of
zero automatic redispatch, compensation, replacement, archive/unblock, or
assertion-derived authority. This satisfies the required absence-of-host safety
closure only; it does not claim a successful trusted-host `ABANDONED` or
`COMPENSATED` capability and does not itself authorize profile activation. If a
profile advertises either trusted success path, its exact host authority and
suite remain separately required. A future trusted host may exercise such a
path only through a fresh authorized attempt.

The existing ledger reservations for `full@3`, `lite@3`, and their recorded
handler identities are immutable historical facts, but no V3 profile completed
the independent review, reproducible handoff, native evidence, publication,
installation, activation, or pin-eligibility sequence. They MUST remain
inactive for new creation. V4 activation applies only to exact `full@4` and
`lite@4` bundle identities after their V4-specific suites and evidence pass;
neither the V3 reservation nor any V3 local test result satisfies a V4 gate.

#### Scenario: Read task schema v3 before V4 creation activation
- **WHEN** the controller supports task-schema-v3 parsing and V4 bundle resolution but the selected `full@4` or `lite@4` profile is inactive
- **THEN** it can inspect readable supported tasks but rejects creation of a new task using that profile

#### Scenario: Observe a V3 release reservation
- **WHEN** validation finds the exact reserved `full@3` or `lite@3` ledger entry without a matching completed external review, handoff, and activation record
- **THEN** it preserves the reservation and handlers as immutable history, keeps V3 creation inactive, and does not infer handoff, publication, installation, activation, or pin eligibility

#### Scenario: Reject a partially ready profile
- **WHEN** any reachable contract or required recovery test for a proposed activation is missing or disabled
- **THEN** activation validation fails and no new task can pin the bundle

#### Scenario: Reject an incomplete action closure
- **WHEN** a movement-reachable node exposes an action that does not compile uniquely or lacks its complete transitive handler identity, guard, gate, reducer, effect scope/concurrency, settlement, receipt, single-dispatch, target-bound live-evidence abandonment, dual-boundary compensation, containment/archive/unblock, recovery, rollback, or compatibility contract
- **THEN** activation validation fails even though every movement edge itself is valid

#### Scenario: Validate the declared hostless recovery profile
- **WHEN** a macOS profile declares trusted-host abandonment and compensation unavailable but identity-covers bounded `UNRESOLVED` operator intervention and proves every affected scope remains blocked with zero automatic effect
- **THEN** the absence-of-host safety closure may pass without claiming trusted `ABANDONED`, trusted `COMPENSATED`, release readiness, or activation authorization

#### Scenario: Claim trusted recovery from hostless evidence
- **WHEN** release or activation evidence presents the hostless `UNRESOLVED` path, a caller assertion, or an intervention packet as proof that trusted `ABANDONED` or `COMPENSATED` succeeded
- **THEN** validation rejects that claim while preserving the hostless safety closure and immutable bundle history

#### Scenario: Activate single-repository execution only
- **WHEN** V4 single-repository full/lite coverage is complete but V4 multi-repository map/join coverage is not
- **THEN** new task-schema-v3 single-repository tasks may pin the activated V4 profile while multi-repository V4 creation remains unavailable

#### Scenario: Disable future creation
- **WHEN** an operator or package rollback disables an activated profile after v3 tasks already exist
- **THEN** new creation uses a supported fallback or fails explicitly while every existing task continues through its exact pinned bundle

#### Scenario: Tighten an unreleased inactive candidate
- **WHEN** an identity-covered action or engine contract changes before the package release ledger reserves that identifier-version, all profiles remain inactive and never pin-eligible, and continuous authoritative prior-release provenance proves the identifier-version absent from every official release
- **THEN** the candidate identities may be regenerated under the same unreleased candidate workflow and handler contract versions before release

#### Scenario: Tighten a released active bundle
- **WHEN** the same safety change is required after the exact identity has a package release reservation, has been externally exposed, or any task could have pinned it
- **THEN** the package publishes a new workflow and handler contract version and retains the prior bundle and handler contracts read-only until every pinned task is terminal or explicitly archived

### Requirement: Reserved bundle versions are immutable
A package-owned `workflows/release-ledger.json` conforming to
`dev-flow-workflow-release-ledger/v1` SHALL provide the authoritative portable
record of the immutability boundary. It SHALL contain strict canonical JSON
with a unique reservation per workflow identifier/version, where each complete
reservation object binds the graph and bundle identities plus the sorted set of
handler IDs, contract IDs, and implementation identities. Every existing
reservation object SHALL remain an exact ordered prefix of every
successor ledger. New reservations SHALL be appended as one contiguous
introduction-epoch batch whose predecessor reservation count and canonical
predecessor-ledger SHA-256 match the existing ledger. The predecessor digest is
the SHA-256 of the exact strict canonical bytes of the predecessor
`workflows/release-ledger.json`; validation SHALL reconstruct those bytes from
the declared prefix and schema. Entries SHALL be sorted only within that batch
by `(workflow_id UTF-8 bytes, numeric workflow_version)`; validation MUST NOT
globally sort the combined reservation list or move, rewrite, or delete an
earlier prefix entry.

Let `batch_bytes` be the strict semantic-JSON canonical bytes of the complete
reservation-object list for one append batch, including every graph, bundle,
handler-contract, and handler-implementation identity. The epoch's batch digest
SHALL be:

```text
SHA256(
  b"dev-flow-workflow-release-ledger-append-batch-v1\0"
  || U64BE(len(batch_bytes))
  || batch_bytes
)
```

The ledger MUST NOT store a digest that includes its own bytes; the separate
canonical package-candidate and handoff manifests SHALL cover the completed
ledger.
Before the first installation, publication, external handoff, or activation
attempt that could expose an exact identifier-version, the release process
MUST add its reservation after the cachebuster and all identity-covered
workflow inputs are stable and before the exposing operation. The reservation
itself crosses the boundary even when the later operation fails. Reserved
entries and their transitive handler implementations MUST be append-only
package history; removing or changing one, reordering the historical prefix, or
pairing its identifier-version with different identity-covered bytes MUST fail
release and catalog validation.

For the historical first introduction, the package MUST preserve
`workflows/release-provenance/first-introduction.json` conforming to strict
canonical `dev-flow-workflow-first-introduction-provenance/v1`. The manifest
MUST bind its change ID, Git object format, immutable base commit
`2dc397411ad1ea5f2a43d43e881523b125bb5eec`, resolved base tree
`ee7de366a818d8800b4808015f2d8ae4c4405136`, the sorted unique set of
introduced workflow identifier/version and handler identity keys, inventory
contract `dev-flow-first-introduction-git-tree/v1`, and exact baseline
inventory SHA-256. Let `raw_inventory` be the unmodified bytes emitted by
`git ls-tree -rz --full-tree <base_commit>`. The digest SHALL be:

```text
SHA256(
  b"dev-flow-first-introduction-git-tree-v1\0"
  || U64BE(len(raw_inventory))
  || raw_inventory
)
```

Validation with the source repository available MUST independently resolve the
commit and tree, reproduce the raw inventory and digest, and prove none of the
declared introduced identities exists in that baseline. Wrong object format,
commit, tree, inventory, introduced-key set, unknown field, mutable source, or
an identity already present in the baseline MUST fail closed. The manifest
MUST NOT contain its own, candidate, review, or handoff digest. Its exact V2/V3
introduced workflow and handler key sets and canonical bytes are immutable;
the exact canonical file SHA-256 SHALL be
`72e301d16546001abb397e37600cf3a141ca2955e7052f5d7dabdbb96f02016a`,
and validation MUST reject a replacement manifest even when a caller also
recomputes and supplies the replacement's digest;
later versions MUST treat those historical keys as a subset of the cumulative
package introduction history and MUST NOT edit the file to add `full@4`,
`lite@4`, or successor handler keys.

An official first-introduction pre-handoff independent review SHALL produce an
external `dev-flow-release-review/v1` record binding reviewer identity, the provenance
manifest SHA-256, its base commit/tree/inventory, and the frozen candidate
digest. The external handoff manifest SHALL repeat those exact bindings.
Native or CI validation MUST NOT claim that the V3 first introduction was
reviewed, handed off, published, installed, or activated without both matching
records. The existing `full@3`/`lite@3` and legacy ledger prefix is immutable,
but those external V3 facts were not completed. Reservation MUST NOT be
reinterpreted as handoff or activation.

Every later introduction SHALL use a separate strict successor manifest under
`workflows/release-provenance/introduction-epochs/` conforming to
`dev-flow-workflow-introduction-epoch-provenance/v1`. It SHALL bind its schema
and change ID; a unique monotonic epoch sequence and ID; one
`predecessor_kind`; predecessor provenance SHA-256, reservation count, and
canonical predecessor-ledger SHA-256; immutable base commit/tree/inventory
bindings; sorted introduced workflow and handler keys; append start/count; the
exact append-batch digest defined above; result-ledger SHA-256; and a digest of
the resulting cumulative workflow/handler identity sets. The introduced keys
SHALL equal exactly the current package identity keys minus the cumulative keys
established by the complete predecessor provenance chain; cumulative handler
history MUST NOT be reconstructed from the smaller union of handlers referenced
by ledger reservations. The ledger suffix keys SHALL equal exactly the epoch's
introduced workflow keys, and every complete suffix reservation SHALL equal
the reservation independently recomputed from the exact current package. The
manifest MUST NOT contain its own digest or the current candidate, review, or
handoff digest.

For `predecessor_kind: official-release`, the successor manifest SHALL bind the
exact preceding independent review and reviewed handoff identities and
validation SHALL require their continuous chain. For
`predecessor_kind: reserved-unexposed`, it SHALL instead bind the immutable
`first-introduction.json` SHA-256, predecessor ledger SHA-256 and reservation
count, exact inactive activation-manifest identity, and explicit
`reviewed=false`, `handoff=false`, `published=false`, `installed=false`,
`activated=false`, and `pin_eligible=false` facts for the predecessor. The
current successor candidate's independent review SHALL confirm this
reserved-but-unexposed supersession before handoff. This mode MUST NOT invent a
V3 review or handoff, discard its reservations, or permit V3 bytes to change.
Missing, discontinuous, or mismatched evidence required by the selected
predecessor kind MUST fail closed.

For this V3 predecessor, the reserved-unexposed anchors SHALL be reservation
count `4`, predecessor-ledger SHA-256
`89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062`,
and the immutable first-introduction SHA-256 above. An `active=false` field or
an empty/partial data-root scan alone MUST NOT prove never-pin-eligible or
unexposed status; the later independent supersession review SHALL validate the
authoritative package release and activation evidence and reject any observed
contradiction.

The current independent review SHALL emit an external record binding the
successor manifest SHA-256, immutable predecessor prefix, completed append
batch and ledger digest, and frozen successor candidate digest. The external
handoff manifest SHALL repeat those bindings. A later official successor uses
that reviewed ledger and handoff chain and MUST NOT regenerate or extend
`first-introduction.json`.

Before a reservation exists, identity-covered bytes and digests MAY be
regenerated within the same working workflow and handler contract version only
when every profile remains inactive and has never been pin-eligible and
authoritative prior-release provenance proves the identifier-version absent
from every preceding official release. That provenance MUST be the exact
selected introduction-epoch predecessor chain: a previous reviewed release
ledger plus handoff for `official-release`, the immutable first-introduction
and reserved/inactive/no-exposure bindings for `reserved-unexposed`, or an
immutable package baseline for the original first introduction. Missing,
discontinuous, or mismatched provenance required by that predecessor kind MUST
fail closed and require a new workflow and handler version.

Because callers may select arbitrary controller data roots, scanning any set
of roots MUST NOT serve as positive proof that no pin exists. A discovered
task reference is a negative blocker and crosses the boundary for its observed
identity, but an empty or partial scan MUST NOT authorize regeneration. A
persisted task reference, pin-eligible activation, installation, publication,
or external handoff also crosses the boundary fail-closed even if a required
reservation is missing. After any of these conditions, a catalog SHALL bind
each workflow identifier and version to at most one bundle identity.
Changing any identity-covered content after that boundary MUST create a new
workflow and handler contract version and MUST NOT replace the meaning of an
existing identifier-version pair. The exact bundle required by every
non-terminal task SHALL remain available in the package catalog or a
controller-managed read-only bundle archive. If it is unavailable, the
controller MUST block mutation rather than fall back or reconstruct behavior
from current files. An active task MUST NOT be migrated to a different bundle
in place; adopting a different workflow requires creation of a new task or
explicit clone whose provenance refers to the source task.

Because the complete transitive recovery semantics changed after the V3
reservation, this change SHALL introduce `full@4` and `lite@4` plus new
versioned handler contracts for every changed recovery implementation while
retaining the exact V3 bundles, handler contracts, implementation files, and
reservation objects. Task schema remains v3. V4 provenance SHALL use the
`reserved-unexposed` predecessor kind unless authoritative external evidence
later proves a different historical fact; it MUST NOT fabricate such evidence.

#### Scenario: Regenerate only a provably unreleased candidate
- **WHEN** every profile for an identifier-version is inactive and never pin-eligible, its release ledger has no reservation, and an immutable baseline plus continuous prior-release provenance proves it absent from every official release
- **THEN** candidate content and digests may be regenerated without claiming that the identifier-version was previously published

#### Scenario: Scan an empty explicit data root
- **WHEN** a release validator scans an empty or partial set of caller-selected controller data roots without complete authoritative prior-release provenance
- **THEN** it MUST NOT treat the scan as no-pin proof or authorize same-version regeneration

#### Scenario: Discover an unreserved pin
- **WHEN** a diagnostic data-root scan finds a task reference whose exact identity lacks a release reservation
- **THEN** validation preserves and blocks that observed identity as missing provenance and requires reconstruction from authoritative release evidence or a new version rather than replacing it in place

#### Scenario: Lose prior-release provenance
- **WHEN** an `official-release` predecessor lacks its reviewed ledger or handoff, or a `reserved-unexposed` predecessor lacks its exact immutable prefix, inactive-manifest, or false-exposure binding
- **THEN** release validation rejects same-version regeneration and requires a new workflow and handler version

#### Scenario: Append a V4 reservation batch
- **WHEN** the V4 introduction epoch names the exact predecessor V3 reservation count and canonical predecessor-ledger digest and supplies complete `full@4` and `lite@4` reservation objects sorted within the batch
- **THEN** validation hashes the canonical complete reservation list, appends it after the unchanged V3 prefix, and preserves every V3 bundle and handler identity

#### Scenario: Globally reorder an append-only ledger
- **WHEN** a validator or formatter moves an earlier reservation to make the combined V3 and V4 list globally lexical
- **THEN** prefix validation fails even if every individual reservation object and the resulting set of keys is unchanged

#### Scenario: Tamper with a batch identity
- **WHEN** a V4 append batch keeps the same workflow keys but changes any graph, bundle, handler contract, or handler implementation identity after its epoch digest is recorded
- **THEN** the domain-separated complete-object batch digest mismatches and release validation fails before exposure

#### Scenario: Append a reservation that differs from the package
- **WHEN** the batch digest is internally consistent but any complete suffix reservation differs from the graph, bundle, or handler identities independently recomputed from the exact current package
- **THEN** validation rejects the epoch rather than accepting the self-consistent forged batch

#### Scenario: Preserve the immutable first introduction
- **WHEN** V4 adds `full@4`, `lite@4`, or successor handler keys
- **THEN** `first-introduction.json` remains byte-for-byte unchanged and the new keys appear only in the chained introduction-epoch manifest

#### Scenario: Rewrite the first introduction and its supplied digest
- **WHEN** a caller adds, deletes, reorders, duplicates, or changes a historical workflow/handler key and supplies the SHA-256 of those replacement bytes
- **THEN** validation rejects the replacement against the fixed historical SHA and canonical V2/V3 key set

#### Scenario: Reject an incomplete introduction delta
- **WHEN** successor provenance omits a newly introduced current-package key, repeats a historical V2/V3 key as new, or its ledger suffix differs from its introduced workflow key set
- **THEN** validation rejects the epoch without rewriting the prior ledger prefix or first-introduction manifest

#### Scenario: Supersede a reserved but unexposed V3 prefix
- **WHEN** the V4 successor manifest binds the immutable V3 first-introduction SHA, exact ledger prefix SHA and count, inactive activation identity, and explicit false exposure facts, and the current independent supersession review later binds that manifest and candidate
- **THEN** validation accepts `reserved-unexposed` continuity without asserting or requiring a nonexistent V3 handoff and without relaxing V3 immutability

#### Scenario: Omit the current supersession review
- **WHEN** a reserved-unexposed V4 candidate reaches handoff or later finalization without the independent current review that binds its successor manifest, immutable prefix, completed batch, ledger, and candidate
- **THEN** handoff and finalization remain blocked even though V4 candidate generation and reservation did not fabricate a V3 handoff

#### Scenario: Claim unexposed status from weak evidence
- **WHEN** reserved-unexposed validation relies only on `active=false` or an empty/partial controller data-root scan without authoritative never-pin-eligible and no-release-exposure evidence
- **THEN** successor handoff and finalization fail closed while the V3 reservation prefix remains immutable

#### Scenario: Forge a V3 handoff during supersession
- **WHEN** V4 successor provenance represents the V3 reservation as reviewed, handed off, published, installed, activated, or pin-eligible without authoritative matching evidence
- **THEN** validation fails closed and preserves the factual reserved-but-unexposed history

#### Scenario: Chain from an official release
- **WHEN** a successor selects `official-release` as its predecessor kind
- **THEN** validation requires the exact continuous prior independent review and reviewed handoff identities and rejects the epoch when either is absent or mismatched

#### Scenario: Verify first-introduction provenance
- **WHEN** release validation receives the exact source repository, first-introduction manifest, independent review record, and handoff manifest
- **THEN** it recomputes the declared base tree and inventory, proves every introduced identity absent, and accepts the provenance only when every review and handoff binding matches

#### Scenario: Forge a first-introduction baseline
- **WHEN** a caller attempts to assert an official V3 first release or regenerate a reserved V3 identity while the manifest is missing, mutable, uses the wrong base commit/tree/object format/inventory or introduced-key set, names an identity already present at baseline, or lacks the external review/handoff required for that official-release claim
- **THEN** validation rejects the claim or same-V3-version regeneration and requires corrected immutable provenance or a new workflow and handler version; it does not fabricate the absent V3 handoff for a V4 reserved-unexposed successor

#### Scenario: Reserve an identity before exposure
- **WHEN** the release process has stabilized the cachebuster and every identity-covered input and is about to install, publish, hand off, or make the candidate pin-eligible
- **THEN** it first writes the exact release-ledger reservation and treats that identifier-version as immutable even if the exposing operation fails

#### Scenario: Detect an unreserved exposed identity
- **WHEN** validation finds a task reference, pin-eligible activation, installed-release evidence, or external handoff evidence for an identifier-version without its exact release-ledger reservation
- **THEN** it fails closed, preserves the observed identity, and requires the reservation to be reconstructed from authoritative evidence or a new workflow and handler version rather than permitting in-place replacement

#### Scenario: Preserve identity after the immutability boundary
- **WHEN** an identifier-version has a release reservation, has been externally exposed, or could have been pinned by a task even if no task currently exists
- **THEN** any semantic bundle or handler change uses a new workflow and handler contract version while the prior identity remains resolvable

#### Scenario: Reject two identities for one version
- **WHEN** catalog discovery finds two bundle identities using the same workflow identifier and version
- **THEN** catalog activation fails deterministically and neither definition becomes executable

#### Scenario: Encounter a missing pinned bundle
- **WHEN** a non-terminal task refers to a bundle identity absent from both the package catalog and controller-managed archive
- **THEN** the controller reports the missing identity and performs no workflow transition or protected side effect

#### Scenario: Request an in-place workflow upgrade
- **WHEN** a caller asks to replace the pinned bundle of an active task with a newer workflow version
- **THEN** the controller rejects the in-place change and leaves the task revision and workflow reference unchanged

### Requirement: Workflow bundles pass complete graph validation
The controller SHALL validate the complete catalog before activating any new
bundle. Validation MUST prove portable and unique workflow, node, edge, and
schema identifiers; resolve every graph, schema, playbook, handler, guard,
gate, reducer, and executor reference; verify at least one entry and terminal
node; reject unreachable nodes and dangling edges; and verify that every
reachable non-terminal node has a path to a terminal node or a declared waiting
or blocker outcome. Cycles MUST use explicitly classified retry or rework edges,
and every cyclic component MUST expose an exit path. Validation MUST also prove
that node schemas, allowed state-write paths, transition priorities, and
handler contract versions are supported by the sealed runtime registries.
Diagnostics MUST be deterministic, and one invalid bundle MUST NOT leave a
partially registered graph.

#### Scenario: Activate a valid rework cycle
- **WHEN** a graph contains a declared rework cycle whose nodes and edges all resolve and whose cyclic component has a reachable terminal exit
- **THEN** validation accepts the cycle and activates the complete bundle atomically

#### Scenario: Reject an implicit cycle
- **WHEN** a graph contains a cycle with an edge not explicitly classified as retry or rework
- **THEN** validation reports the participating nodes and edges and does not activate the bundle

#### Scenario: Reject an unreachable or dangling node
- **WHEN** a graph contains a node unreachable from every entry or an edge referring to an unknown node
- **THEN** validation returns deterministic diagnostics and no task can select the invalid bundle

#### Scenario: Reject an unregistered execution contract
- **WHEN** a node references an unknown handler, guard, gate, reducer, executor, or unsupported contract version
- **THEN** validation fails after registry sealing and the controller does not expose that node as a legal action

### Requirement: Graph-derived workflow metadata has one source of truth
The pinned workflow bundle SHALL be the sole source for node ordering, display
metadata, legal edges, rework relationships, approval classification, required
evidence, progress, and node playbook locators. Controller responses, compact
agent projections, CLI and MCP action descriptions, hooks, and Skills MUST
consume controller-produced projections derived from the same pinned bundle and
MUST NOT maintain independent workflow-state or next-action tables. Failure to
derive a required projection from the pinned bundle MUST block the affected
workflow action rather than use hard-coded fallback semantics.

#### Scenario: Project a newly added declarative node
- **WHEN** a valid new bundle version adds a node using already registered contracts
- **THEN** controller progress and legal-action projections include that node without a separate state table in a hook, Skill, CLI adapter, or MCP adapter

#### Scenario: Project a legacy task
- **WHEN** a caller requests progress for a legacy task
- **THEN** the controller derives labels, ordering, and legal actions from the task's frozen legacy adapter rather than the current default workflow

#### Scenario: Fail to derive required metadata
- **WHEN** a pinned definition lacks metadata required to determine a legal action or approval classification
- **THEN** the controller returns a structured workflow-definition blocker and does not infer the missing behavior from documentation

### Requirement: Unsupported bundle contracts fail closed
Every bundle SHALL declare its bundle schema version and every executable
reference SHALL declare a supported contract version. A controller encountering
a bundle schema or handler contract newer than it supports, an unknown required
field, or a bundle created by an incompatible canonicalization contract MUST
return a structured compatibility blocker. It MUST preserve task data and
worktrees unchanged and MUST NOT reinterpret the bundle as an older contract.
Read-only inspection SHALL still report the pinned identities and the exact
unsupported versions when the state schema itself is readable.

#### Scenario: Load a task using a newer bundle schema
- **WHEN** a readable task pins a bundle schema version newer than the running controller supports
- **THEN** read-only inspection reports that version while every mutation returns a structured compatibility blocker

#### Scenario: Encounter a newer handler contract
- **WHEN** the pinned bundle requires a handler contract version unavailable to the running controller
- **THEN** the controller performs no transition or side effect and identifies the missing handler contract

#### Scenario: Attempt a silent downgrade
- **WHEN** an older controller finds a bundle whose identifier is familiar but whose canonicalization or schema contract is newer
- **THEN** it refuses to substitute its older interpretation and preserves all task and workspace data

### Requirement: Existing reserved V3 tasks fail closed without V4 substitution
The controller SHALL treat any discovered task-schema-v3 task pinned to
reserved but never activated `full@3` or `lite@3` as historical
reserved-unexposed state. It SHALL preserve the exact workflow reference, task
bytes, journals, receipts, containment records, runtime reservations, scopes,
artifacts, worktrees, bundle files, handler contracts, and implementation
identities. Read-only inspection and idempotent delivery of an already
authoritatively committed outbox MAY continue. State advancement, ordinary
dispatch, retry, replacement attempt, and protected Git/filesystem/registry/
external effects MUST fail closed.

A target-bound stop, live observation, or reconciliation safety control MAY run
only when the exact V3 bundle identity transitively covers every handler,
schema, validator, gate, evidence source, and closure step used by that
operation and the current evidence satisfies that historical contract. Missing
or incomplete V3 recovery identity MUST leave the affected scope blocked. The
controller MUST NOT execute a V3 action with V4 handlers, infer abandonment
from missing evidence, reinterpret a V3 receipt, migrate the task in place, or
delete historical bytes merely because V3 was never expected to be
pin-eligible.

#### Scenario: Inspect a discovered V3 task
- **WHEN** the controller opens a readable task pinned to the exact reserved `full@3` or `lite@3` identity
- **THEN** it reports the pinned identity and reserved-unexposed blocker while preserving every task, journal, receipt, scope, artifact, worktree, bundle, and handler byte

#### Scenario: Request ordinary V3 advancement
- **WHEN** a caller asks a discovered reserved-unexposed V3 task to transition, dispatch, retry, replace an attempt, or start another protected effect
- **THEN** the controller returns a stable historical-workflow safety blocker with zero task, outbox, journal, scope, Git, filesystem, registry, or external-system change

#### Scenario: Attempt V4 recovery substitution
- **WHEN** V4 has a stronger abandonment or compensation implementation but the pinned V3 transitive handler closure lacks that exact contract
- **THEN** the controller does not call the V4 handler or migrate the task and leaves the V3 execution and affected scope blocked

#### Scenario: Run an identity-complete V3 safety control
- **WHEN** the exact pinned V3 closure declares a target-bound stop or observation action and every current live-evidence and authorization requirement succeeds
- **THEN** the controller may execute only that bounded safety control through its V3 identity without authorizing ordinary work or adopting V4 semantics

#### Scenario: Finish an already committed V3 outbox delivery
- **WHEN** authoritative V3 task state already contains a committed pending event batch
- **THEN** recovery may deliver that exact batch idempotently without advancing workflow state, starting an effect, or changing the pinned bundle

### Requirement: Schema-v1 and schema-v2 tasks use frozen legacy adapters
The controller SHALL keep schema-v1 and schema-v2 tasks readable and mutable
through immutable package-owned legacy workflow adapters selected
deterministically from the persisted state schema and flow identity. Adapter
selection itself MUST NOT add a bundle reference, rewrite the stored task
schema, increment its revision, or select the current default workflow.
Existing `load_state` recovery and safety behavior remains authoritative:
pending durable events MUST still be delivered idempotently and existing
sensitive-state cleanup MUST still run when its historical contract requires a
safe persisted rewrite. Each legacy adapter MUST
preserve the applicable historical states, forward and rework edges, approval
requirements, evidence gates, automatic-action policy, and protected side
effects. Legacy behavior MUST be covered by golden transition vectors before a
bundle-aware workflow becomes the default.

#### Scenario: Read a clean legacy task without adapter migration
- **WHEN** the current controller opens a valid schema-v1 or schema-v2 task that has no pending recovery or sensitive-state cleanup work
- **THEN** it selects the matching frozen adapter and leaves the persisted bytes, schema, revision, and workflow semantics unchanged

#### Scenario: Recover a legacy pending outbox
- **WHEN** a readable legacy task contains a pending durable event batch
- **THEN** normal load recovery delivers it idempotently before returning the adapter-backed view without adding a workflow reference or changing the stored task schema

#### Scenario: Sanitize legacy sensitive state
- **WHEN** historical load safety requires sensitive-state cleanup for a readable legacy task
- **THEN** the controller performs the existing safe cleanup and audit behavior without treating that rewrite as an adapter migration

#### Scenario: Mutate a legacy task through its adapter
- **WHEN** an approved legacy transition satisfies the same revision, evidence, workspace, and side-effect conditions required before this change
- **THEN** the adapter produces the historically equivalent state transition and event without converting the task to a bundle-aware schema

#### Scenario: Reject ambiguous legacy selection
- **WHEN** persisted legacy fields do not identify exactly one compatible frozen adapter
- **THEN** the controller returns a structured compatibility blocker and performs no state or Git mutation

#### Scenario: Verify legacy equivalence
- **WHEN** golden vectors exercise every supported legacy forward, rework, automatic, approval, and terminal transition
- **THEN** adapter results match the pre-refactor state, event, evidence, and protected-side-effect semantics for every vector
