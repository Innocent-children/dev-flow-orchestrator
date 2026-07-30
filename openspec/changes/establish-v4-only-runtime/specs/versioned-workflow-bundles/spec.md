## ADDED Requirements

### Requirement: V4 release provenance starts from a new product-line genesis
现有插件 SHALL（必须）以一个规范 genesis 和 current-inventory 记录开启
新的 V4 主版本 provenance line；其 schema 与已退役的多代发布 ledger
不同。Genesis SHALL（必须）绑定精确的 `full@4` 和 `lite@4` bundle
identity、它们完整的传递 handler identity、activation manifest、最终插件
manifest/version/cachebuster，以及下层 `runtime_inventory_sha256`。该
inventory digest SHALL（必须）覆盖精确的可安装 V4 runtime allowlist，
并 SHALL（必须）排除 genesis 记录本身、OpenSpec 规划产物、聚焦测试源码、
CI 配置、生成的 validation/review/handoff evidence，以及其他所有不可安装
文件。Genesis
MUST NOT（不得）包含外层 candidate digest 或任何 review/handoff digest。
它 MUST（必须）不包含任何 V2 或 V3 workflow、bundle、handler、adapter
或 predecessor-ledger entry。

规范 candidate SHALL（必须）仅在最终 genesis 写入后计算，并且
SHALL（必须）包含 genesis 字节。独立测试、审查和交接记录 SHALL（必须）
位于 candidate root 之外，并绑定该已完成的 candidate digest。创建这些
记录后，不得更改任何 candidate 文件。

未来仅支持 V4 的发布 MAY（可以）保留早期 V4 candidate 的 provenance
metadata，但当前 package validation SHALL（必须）只要求精确 current
inventory 中的可执行字节。Provenance history MUST NOT（不得）要求已退役
的 bundle 或 handler 实现继续保留在 package 中。更改当前 V4 中受 identity
覆盖的字节需要一个经重新审查的 current inventory；它 MUST NOT（不得）
静默保留旧 identity。

#### Scenario: 验证 V4 genesis
- **WHEN** 发布验证计算下层 runtime inventory 并读取最终 V4 genesis
- **THEN** inventory digest、manifest identity、activation data、workflow 和传递 handler 完全匹配，且可执行 workflow inventory 恰好为 `full@4` 和 `lite@4`

#### Scenario: 在不发生递归的情况下冻结外层 candidate
- **WHEN** 已根据下层 inventory 写入最终 genesis
- **THEN** candidate identity 包含 genesis 字节，同时 genesis 和其他 candidate 文件均不包含 candidate、review 或 handoff digest

#### Scenario: 将 external evidence 绑定到 candidate
- **WHEN** 聚焦验证、独立审查或交接完成
- **THEN** 其记录存储在 candidate root 之外，并在不改变 candidate 字节的情况下绑定已经冻结的 candidate digest

#### Scenario: 更改当前受 identity 覆盖的实现
- **WHEN** current inventory 冻结后，一个保留的 V4 handler 或 bundle 字节发生更改
- **THEN** 验证要求新的、经审查的 V4 current inventory 和 candidate identity，并拒绝复用已冻结的 digest

## MODIFIED Requirements

### Requirement: Canonical bundle identity
每个 V4 workflow bundle SHALL（必须）具有一个确定性的 SHA-256 identity；
该 identity 使用独立版本化的 `dev-flow-bundle-identity/v1` protocol，
从所有传递性 bundle content 的 canonical manifest 计算得出。`U64BE`
表示无符号 64 位大端整数。Bundle path MUST（必须）是 repository-relative
UTF-8 POSIX path，不得含 absolute、drive、UNC、backslash、empty、`.` 或
`..` segment；每个 segment MUST（必须）为 NFC、通过当前 package path
validator，并且在 NFC 加 Unicode case-folding 下保持唯一。禁止 symlink
和 special file。

Bundle manifest MUST（必须）将每个被传递性引用的 regular file 显式分类
为 JSON（`J`）、text（`T`）或 binary（`B`），且不得使用 glob。JSON
payload MUST（必须）在不含 BOM 的情况下解码为 UTF-8，拒绝重复 object
key、非 NFC 的 key 或 string、float、超出有符号 64 位范围的 integer、
`NaN` 和 infinity，然后精确编码为 Python 标准库
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
allow_nan=False).encode("utf-8")`。Text payload MUST（必须）在不含 BOM
的情况下解码为 UTF-8、包含 NFC text，并对 CRLF 和 CR 执行
canonicalization，结果为 LF。Binary payload 原样保留其字节。

对于每个被引用的 handler，static registration manifest MUST（必须）声明
一组精确且非空的 package-relative implementation file，并按照 bundle
文件所用的同一套 canonical payload rule 将每个文件分类为 `J`、`T` 或
`B`；禁止 glob、推断 file kind 和 runtime discovery。其 implementation
digest 为：

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

Graph digest 为
`SHA256(b"dev-flow-graph-v1\0" || U64BE(len(root_json)) || root_json)`，其中
`root_json` 是 V4 root graph 的 canonical JSON payload。Bundle digest 为：

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

对于 `J`、`T` 或 `B`，`kind_byte` 分别为 `0x4a`、`0x54` 或 `0x42`。
Identity MUST（必须）覆盖 graph、node definition、schema、playbook、
handler contract identifier 和 version，以及每个已声明的 handler
implementation file。Handler manifest SHALL（必须）是 happy-path 和
recovery behavior 的 complete transitive closure，包括 dispatch、receipt 和 live-target
observation、runtime settlement 或 reattachment、target-bound control、
`ACCEPTED`/`ABANDONED`/`UNRESOLVED` decision、compensation planning 与
verification、containment closure、archive 和 scope unblocking。任何
未列出的 transitive reference 或 runtime call target、重复的 manifest
path、portable path collision、不受支持的 content kind，或格式错误的
canonical payload，都 MUST（必须）在 activation 或 recovery 前失败。
对于同一个逻辑 V4 bundle 和 registered implementation，重复进行的独立
macOS validation MUST（必须）产生相同 identity；而任何 semantic content
或 happy-path/recovery handler implementation 发生变化时，MUST（必须）
产生不同 identity。该 byte contract 保持可移植，但本次发布不对原生
Windows 或 Linux 作出声明。

#### Scenario: 计算 V4 bundle identity
- **WHEN** 从相互独立的 macOS checkout 验证相同逻辑的 V4 JSON definition、text playbook、binary content 和 handler implementation
- **THEN** 每次运行的 canonicalization 都产生相同的有序 manifest 和 SHA-256 bundle identity

#### Scenario: 忽略无关紧要的 JSON 格式差异
- **WHEN** 两个其他方面完全相同的 V4 bundle source 仅在 JSON object key 顺序或无关紧要的 JSON whitespace 上不同
- **THEN** 两个 source 产生相同的 canonical JSON byte 和 bundle identity

#### Scenario: 检测 handler implementation 变更
- **WHEN** registered V4 handler implementation 发生变化，而 graph、node definition、handler identifier 和已声明的 handler contract version 保持不变
- **THEN** handler implementation digest 和外层 bundle identity 均发生变化

#### Scenario: 检测仅 recovery 语义漂移
- **WHEN** 仅 V4 abandonment verifier、compensation gate 或 bridge adapter、receipt observer、containment closer、archive helper，或其他传递性 recovery implementation 发生变化
- **THEN** 其 handler implementation identity 和每个外层 bundle identity 均按 happy-path handler 漂移的相同方式变化

#### Scenario: 拒绝发生冲突的逻辑 package path
- **WHEN** 两个 V4 bundle entry 规范化为相同的 package-relative path identity
- **THEN** 验证在计算 activatable identity 之前拒绝该 bundle

#### Scenario: 拒绝存在歧义的语义 JSON
- **WHEN** V4 bundle JSON 文件包含 duplicate key、float、out-of-range integer、non-NFC string、BOM、`NaN` 或 infinity
- **THEN** canonicalization 返回稳定的 structured error，且不计算 activatable graph 或 bundle identity

#### Scenario: 匹配 V4 normative identity vector
- **WHEN** macOS validator 处理规范 V4 bundle、text-newline、binary 和 handler-only-drift vector
- **THEN** 它产生精确的已声明 graph、handler 和 bundle digest，且 drift vector 产生精确的、彼此不同的已声明 digest

以下是 normative minimal V4 vector。带引号的 source payload 使用所示的可见转义；
`hex:` payload 是字面字节。以下 `/v1` 后缀属于相互独立的 identity、guard
和 handler protocol；`workflow_version` 是 V4 workflow generation。

```text
bundle files, sorted by path:
  blob.bin      kind B  source hex:00ff0a
  graph.json    kind J  source "{\"workflow_version\":4,\r\n \"workflow_id\":\"vector\"}\r\n"
  playbook.md   kind T  source "Step one.\r\n"

canonical graph.json:
  "{\"workflow_id\":\"vector\",\"workflow_version\":4}"

handler:
  handler_id  = "guard.vector/v1"
  contract_id = "dev-flow-guard/v1"
  implementation file:
    scripts/vector_guard.py
    kind T
    source "def guard(ctx):\r\n    return True\r\n"

expected graph_sha256:
  ab05d23d09fc06ec1943f593db990f4fca9dc79ec7c5f01db91758707a8557b2
expected handler implementation sha256:
  2a725499ab81891164ea25f08b8fbb9cfb89c316c051b6c7c91c5370628f8d80
expected bundle_sha256:
  dbd1f12c45207c91cadf43664f63e7b5a45111931f7e88675deb5a3af64e387b
```

Normative handler-only drift vector 只将 `return True` 更改为
`return False`，并保留 CRLF source ending 和其他所有输入：

```text
expected drifted handler implementation sha256:
  9fb28a7f17498bfe38925dad0b97efa0345c667d801cfe7733da559346a7442c
expected unchanged graph_sha256:
  ab05d23d09fc06ec1943f593db990f4fca9dc79ec7c5f01db91758707a8557b2
expected drifted bundle_sha256:
  9a55ddb10f66fb0317840e48c8a02169c2e4ba8bfd0d970131dcf5c7c1c582e0
```

### Requirement: Complete package-owned workflow bundles
仅支持 V4 的 package SHALL（必须）恰好包含两个 workflow bundle：
`full@4` 和 `lite@4`。每个 bundle SHALL（必须）包含或传递性引用其 graph、
node definition、handler contract identity、guard 和 gate identity、input
和 output schema、人类可读的 playbook，以及推导 workflow progress 和
legal action 所需的全部 metadata。其 transitive reference 还
SHALL（必须）包括每个 recovery policy、schema、validator 和 executable
handler；这些 handler 能够 dispatch、observe、settle、reattach、stop、
reconcile、abandon、compensate、返回有界的 hostless operator intervention、
close containment、archive 或 unblock action。每个 bundle-relative
reference MUST（必须）恰好解析到 bundle root 内的一个文件。Target
repository、task data directory、environment variable、Hook、Skill、
generic recovery helper 和 external tool MUST NOT（不得）添加、替换或
遮蔽 workflow bundle 或 executable handler。Catalog 或 installable
package 中 SHALL（必须）不包含 V2 或 V3 workflow bundle 或 compatibility
adapter。

#### Scenario: 加载完整的 V4 package
- **WHEN** controller 启动时，package 中包含完整的 `full@4` 和 `lite@4` transitive closure
- **THEN** 它恰好加载这两个 catalog entry，且不会向 target repository 或 task data directory 查询缺失的 workflow content

#### Scenario: 拒绝逃逸 root 的 bundle reference
- **WHEN** bundle 包含 absolute path、traversal segment、symlink escape 或其他解析到 bundle root 之外的 reference
- **THEN** bundle validation 以 structured diagnostic 失败，且 controller 不公开或执行该 bundle

#### Scenario: 忽略 repository 提供的 workflow override
- **WHEN** target repository 包含使用与 packaged bundle 相同 identifier 和 version 的 workflow 文件
- **THEN** controller 继续解析 package-owned bundle，且不从 target repository 加载 executable workflow behavior

#### Scenario: 拒绝不完整的 recovery closure
- **WHEN** action 可到达的 receipt observer、live-target verifier、stop、abandonment、compensation、hostless operator-intervention、containment、archive 或 unblock implementation 不在 bundle 的 transitive handler closure 中
- **THEN** bundle validation 在 activation 或 recovery 前拒绝该 action，且不替换为 generic unversioned helper

### Requirement: Workflow generation and task schema evolve independently
仅支持 V4 的 workflow SHALL（必须）使用 identity `full@4` 和 `lite@4`，
同时仅持久化 task schema v4。Workflow generation 和 persistence schema
仍是相互独立的 contract axis，但这条 clean-slate major line 有意让二者
都从 `4` 开始。第一个 task revision SHALL（必须）包含
`schema_version: 4`，以及一个 workflow version 为 `4` 的精确 workflow
reference。Runtime source、schema 和 workflow-specific contract identity
MUST（必须）直接描述该当前 V4 state，而不是改造更早的 schema
implementation。

#### Scenario: 创建 V4 full task
- **WHEN** 精确的当前 `full@4` profile 有效，且已为新建显式激活
- **THEN** 第一个 task state 记录 task schema v4 和精确的已安装 `full@4` bundle identity

#### Scenario: 创建 V4 lite task
- **WHEN** 精确的当前 `lite@4` profile 有效，且已为新建显式激活
- **THEN** 第一个 task state 记录 task schema v4 和精确的已安装 `lite@4` bundle identity

### Requirement: New tasks pin an exact validated bundle
创建 task 之前，controller SHALL（必须）验证并解析一个精确的当前已安装
V4 workflow bundle，并 SHALL（必须）在 task 的第一个 committed state
中持久化 task schema v4，以及一个包含其 workflow identifier、workflow
version、bundle schema version 和 bundle identity 的 workflow reference。
此后每个 operation MUST（必须）将该 identity 解析到精确的当前 V4
inventory，并且 MUST NOT（不得）仅仅因为另一个 bundle 的 identifier
或 version 匹配就进行替换。Bundle resolution 和 task creation
MUST（必须）在正常的 task-creation serialization 下执行，以确保所选
bundle 在 validation 与 first commit 之间无法改变。

#### Scenario: 创建固定 bundle 的 task
- **WHEN** caller 使用有效且已激活的当前 V4 bundle 创建 task
- **THEN** 第一个 task revision 记录用于初始化该 task 的精确 workflow identifier、version、bundle schema version 和 bundle identity

#### Scenario: 解析当前 V4 task
- **WHEN** controller 打开由当前 package 创建的 task
- **THEN** 它解析创建时记录的精确 `full@4` 或 `lite@4` identity，且不查询 default 或 compatibility selector

### Requirement: Bundle-aware task creation is explicitly activated
Activation manifest SHALL（必须）恰好包含以下 profile 和 named suite set：

- `full@4` / `single-repository`: `v4-static-closure`,
  `v4-core-runtime`、`v4-effect-recovery` 和 `v4-external-tools`；
- `full@4` / `multi-repository`：全部 full single-repository suite，外加
  `v4-multi-repository`;
- `lite@4` / `single-repository`: `v4-static-closure`,
  `v4-core-runtime` 和 `v4-effect-recovery`。

未定义其他 profile。对于冻结的 candidate，只有在某个 profile 的精确
bundle identity 和 named suite 通过后，该 profile 才 SHALL（必须）
激活。未激活或不完整的 V4 profile MUST（必须）在首次
task commit 前失败，且 creation 没有其他 workflow fallback。

`v4-static-closure` SHALL（必须）确定性枚举每个 movement-reachable node
和 public same-node action，并证明 unique action placement、direct V4
handler identity、guard、gate、reducer、bounded write、effect class 与
scope、settlement、receipt、dispatch、control、containment 和 recovery
closure。由于这些 action 组合了相同的 sealed contract，activation 不要求
为每个 declarative placement 单独执行 behavioral test。

`v4-core-runtime` SHALL（必须）覆盖一条 full path 和一条 lite path 的
通用 schema-v4 creation、engine proof、guard/reducer、revision 和
projection invariant。`v4-effect-recovery` SHALL（必须）覆盖每个保留的
settlement/recovery class 的一个代表，而非每个 command。
`v4-external-tools` SHALL（必须）覆盖 full profile 的 least-capability
evidence 和 serial host/workflow write boundary。`v4-multi-repository`
SHALL（必须）覆盖 full-profile plan、lease、result、barrier、integration
和 serialized-CAS invariant。这些 named suite 取代 compatibility、
golden-equivalence、shadow-equivalence 和 broad rollback matrix。

如果 macOS profile 的当前 host 不提供可信的 abandonment 或 compensation
authority，则 recovery closure SHALL（必须）改为要求受 identity 覆盖的
`UNRESOLVED` path、有界的 `dev-flow-v4-operator-intervention/v1`、显式
user-action stop，以及不存在 automatic redispatch、compensation、
replacement、archive/unblock 或 assertion-derived authority 的 proof。
这仅满足所要求的 absence-of-host safety closure；它不声称具备成功的
trusted-host `ABANDONED` 或 `COMPENSATED` capability，也不自行授权
profile activation。如果 profile 声明任一可信 success path，则仍需单独
提供其精确 host authority 和 suite。未来的 trusted host 只能通过一次
全新且已授权的 attempt 执行这样的 path。

#### Scenario: 在所选 V4 profile 未激活时创建
- **WHEN** 所选的精确 `full@4` 或 `lite@4` profile 未激活或不完整
- **THEN** creation 在 first commit 前失败，且不选择 fallback workflow

#### Scenario: 拒绝仅部分 ready 的 profile
- **WHEN** profile 所需的精确 bundle identity、static closure 或任何 named suite 缺失或失败
- **THEN** activation validation 失败，且任何新 task 均无法固定该 bundle

#### Scenario: 拒绝不完整的 action closure
- **WHEN** movement-reachable node 公开的 action 无法唯一编译，或缺少其完整 transitive handler identity、guard、gate、reducer、effect scope/concurrency、settlement、receipt、single-dispatch、target-bound live-evidence abandonment、dual-boundary compensation、containment/archive/unblock、recovery 或 rollback contract
- **THEN** 即使每条 movement edge 本身都有效，activation validation 仍会失败

#### Scenario: 对一个 declarative action class 验证一次
- **WHEN** 多个 V4 action placement 使用相同的 sealed handler、effect、receipt 和 recovery contract class，且 `v4-static-closure` 证明每个 placement 完整
- **THEN** 适用的 focused runtime suite 可以验证一条代表性 contract-class path，而无需为每个 placement 重复 behavioral test

#### Scenario: 验证已声明的 hostless recovery profile
- **WHEN** macOS profile 声明 trusted-host abandonment 和 compensation 不可用，但其 identity 覆盖有界的 `UNRESOLVED` operator intervention，并证明每个受影响 scope 均保持 blocked 且没有任何 automatic effect
- **THEN** absence-of-host safety closure 可以通过，而无需声称 trusted `ABANDONED`、trusted `COMPENSATED`、release readiness 或 activation authorization

#### Scenario: 根据 hostless evidence 声称可信 recovery
- **WHEN** release 或 activation evidence 将 hostless `UNRESOLVED` path、caller assertion 或 intervention packet 作为 trusted `ABANDONED` 或 `COMPENSATED` 已成功的 proof
- **THEN** validation 在保留 hostless safety closure 的同时拒绝该声明

#### Scenario: 仅激活 single-repository execution
- **WHEN** 当前 V4 single-repository full/lite coverage 完整，但 V4 multi-repository map/join coverage 不完整
- **THEN** 新的 task-schema-v4 single-repository task 可以固定已激活的 V4 profile，而 multi-repository V4 creation 仍不可用

#### Scenario: 禁用未来创建
- **WHEN** operator 禁用一个已激活的当前 V4 profile
- **THEN** 新建会明确失败，因为未定义其他 workflow

#### Scenario: 收紧尚未冻结的 V4 candidate
- **WHEN** 受 identity 覆盖的 action 或 engine contract 在 V4 genesis/current inventory 冻结前发生变化，且任何 task 都不可能已固定它
- **THEN** 在新的 L1/L2 freeze 之前重新运行 V4 closure，随后将任何 validation 或 review evidence 创建为新的外部 L3 evidence

### Requirement: Graph-derived workflow metadata has one source of truth
精确的当前 pinned V4 workflow bundle SHALL（必须）是 node ordering、display
metadata、legal edge、rework relationship、approval classification、required
evidence、progress 和 node playbook locator 的唯一来源。Controller
response、compact agent projection、CLI 与 MCP action description、Hook
和 Skill MUST（必须）使用 controller 产出的、从同一个 pinned bundle
派生的 projection，并且 MUST NOT（不得）维护独立的 workflow-state 或
next-action table。若无法从 pinned bundle 派生所需 projection，
MUST（必须）阻止受影响的 workflow action，而不是使用 hard-coded
fallback semantics。

#### Scenario: 投影新添加的 declarative V4 node
- **WHEN** 有效的当前 V4 bundle 添加一个使用已注册 contract 的 node
- **THEN** controller progress 和 legal-action projection 包含该 node，且 Hook、Skill、CLI adapter 或 MCP adapter 中无需单独的 state table

#### Scenario: 无法派生所需 metadata
- **WHEN** 当前 pinned V4 definition 缺少确定 legal action 或 approval classification 所需的 metadata
- **THEN** controller 返回结构化 workflow-definition blocker，且不从文档推断缺失的 behavior

### Requirement: Unsupported bundle contracts fail closed
每个当前 V4 bundle SHALL（必须）声明其 bundle schema version，每个
executable reference SHALL（必须）声明受支持的 contract version。如果 controller 遇到比
自身支持版本更新的当前 bundle schema 或 handler contract、未知的
required field，或由不兼容 canonicalization contract 创建的 bundle，
则 MUST（必须）返回结构化 current-package validation blocker，并且
MUST NOT（不得）将该 bundle 重新解释为较旧的 contract。

#### Scenario: 验证已安装的 bundle schema
- **WHEN** startup 验证准确的已安装 `full@4` 和 `lite@4` bundle schema
- **THEN** controller 进入 ready 前，两个 schema 和所有被引用的 handler contract 均必须受支持

#### Scenario: 在当前 package 中遇到更新的 handler contract
- **WHEN** 准确的当前 V4 bundle 要求一个 running controller 不具备的 handler contract
- **THEN** startup validation 在 controller 接受 task operation 前失败，并标明缺失的 handler contract

#### Scenario: 尝试静默降级
- **WHEN** controller 发现一个 identifier 熟悉但 canonicalization 或 schema contract 不受支持的当前 V4 bundle
- **THEN** 它拒绝替换为较旧的解释，且不执行任何 task 或 external operation

## REMOVED Requirements

### Requirement: Reserved bundle versions are immutable
**Reason**: Append-only multi-generation ledger 迫使当前 package 保留已退役的 V2/V3 executable byte；它将由仅支持 V4 的 genesis 和 current-inventory contract 取代。

**Migration**: 无。V4 主版本线从新的 provenance genesis 开始，且不交付 predecessor executable byte。

### Requirement: Existing reserved V3 tasks fail closed without V4 substitution
**Reason**: 即使是 bounded inspection、outbox completion 和 V3 safety control，也构成此 product line 不提供的 historical runtime compatibility。

**Migration**: 无。范围内不存在 historical runtime data，也未规定 replacement behavior。

### Requirement: Schema-v1 and schema-v2 tasks use frozen legacy adapters
**Reason**: Frozen adapter、golden oracle、cleanup、outbox recovery 和 mutation equivalence 是被移除 legacy branch 的主要来源。

**Migration**: 无。范围内不存在 historical runtime data。
