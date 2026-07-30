## Context

当前 repository 只 package 一个 plugin，但同时携带多个内部 workflow generation。
其 catalog 包含 V2、V3 和 V4 bundle；其 runtime 需要面向旧 task schema 的 frozen
adapter；其 V4 handler 仍在 generation-bound V3 transaction 和 reducer 外保留
wrapper；其 release ledger 还要求前代 implementation byte 继续保留在 package 中。

目标 deployment 中没有历史 runtime data。因此，期望的最终 state 并不是
compatibility-preserving upgrade，而是一套看起来就像 V4 是产品起点的纯净 V4
implementation。只有 Git history 和已归档的 OpenSpec change 会保留开发记录，两者
都不属于 executable runtime contract。

当前的高风险接缝包括：

- `workflows/catalog.json`、`workflows/activation.json`、bundle root、runtime
  manifest 和 package inventory；
- `workflow_runtime._workflow_runtime_legacy_adapters`、task state loading、
  workflow resolution、projection 和 creation；
- `workflow_v3_handlers.py`、`workflow_v4_handlers.py`、action transaction、
  journal、reconciliation、orchestration action 和 sealed registry；
- `release_ledger.py`、前代 provenance file、package candidate identity 和
  package validator；
- CLI、MCP、Hook、Skill、中英文 documentation、fixture 和 test。

runtime 继续只使用 Python standard library。在这台 macOS host 上开展工作并不能
建立 native Windows 或 Linux validation 结论。

## Goals / Non-Goals

**目标（Goals）：**

- 保留一个 plugin identity 和一个已安装 plugin，其 major version 为 V4。
- 仅 package `full@4` 和 `lite@4`，不包含任何 V2/V3 workflow asset。
- 仅 persist task schema v4，并直接以 V4 identity 实现 workflow-specific runtime
  contract。
- 移除那些仅因早期 generation 曾经存在而存在的 adapter、wrapper、alias、
  fallback、fixture、test、documentation 和 release rule。
- 保持 lock、CAS、evidence、approval、recoverable effect、manager authority 和
  bounded hostless intervention 的现有 safety invariant。
- 根据最终的精确 package 建立新的 V4 provenance genesis。
- 保持 verification 规模小且聚焦当前 version；当本地 automation 会变得不真实时，
  将真实 Codex-host check 交由 user 执行。

**非目标（Non-Goals）：**

- 检测、拒绝、读取、迁移、修复、recovery 或测试历史 runtime data。
- 提供旧 plugin rollback path 或 dual-version installation。
- 为保持 provenance continuity 而保留前代 file。
- 仅因为某个通用 protocol 自身的当前 version 是 `/v1` 或 `/v2` 就对其 rename；
  只有 workflow-generation-bound name 才统一为 V4。
- 运行 full test discovery 或 native Windows/Linux validation。

## Decisions

### 1. 保留一个 plugin identity，并让 V4 成为 in-place major replacement

`.codex-plugin/plugin.json` 保留现有 plugin name。在所有可安装 package input
稳定之后、但在计算 provenance inventory 或 candidate identity 之前，其 semantic
version 变为 `4.0.0+codex.<cachebuster>`。cachebuster 是最终确定的 manifest input，
而不是从所属 candidate 派生出的 digest，并且在 candidate freeze 后不得更改。
Marketplace metadata 和 installation guidance 均指向这一个 identity。不得创建
`dev-flow-orchestrator-v4` sibling plugin，因为那会重新引入本 change 旨在消除的
多重安装问题。

考虑过的替代方案：发布单独的 V4 plugin identity 和 data root。这可以提供更强的
lineage isolation，但也会有意允许两个 plugin 以及重复的 Hook/MCP server 共存。
user 已确认不存在旧 data，并且只需要一个纯净 plugin，因此单独 identity 会带来
不必要的复杂性。

### 2. 将 live workflow 和 persistence identity 对齐到 V4

新 task state 使用 `schema_version: 4`。workflow identity 仍为 `full@4` 和
`lite@4`。与代际绑定的 state schema、action contract、reducer ID、
journal/index domain、proof domain、function、module、fixture 和 test name 均重建为
V4，而不是通过 V3 wrapper 访问。

具体而言，仍在使用的 `workflow_v3_handlers.py`、`execute_v3_*`、`recover_v3_*`、
`reducer.v3-*` 和 `dev-flow-v3-action-execution-*` 等名称，要么重命名为直接 V4
implementation，要么在不可达时删除。`workflow_v4_handlers.py` 成为直接
implementation boundary，而不是旧 generation 之上的 facade。

考虑过的替代方案：保留 task schema v3 和以 V3 命名的内部 implementation，因为
现有 V4 bundle 已依赖它们。这样 diff 更小，但无法达到所要求的“仿佛 V4 最先构建”
最终 state，还会保留同样令未来工作成本高昂的概念分层。

当 `agent-v1`、JSON-RPC、evidence-contract `/v1` 或 bundle canonicalization `/v1`
等通用 contract 的 identifier 描述的是该 protocol 的第一个 version，而不是前代
workflow 时，它们保留各自的 version。

### 3. 仅从两个 V4 closure 派生 runtime

删除之前，implementation 需要记录 `full@4` 和 `lite@4` 的 transitive closure：
graph、schema、playbook、command、guard、reducer、gate、executor、recovery handler
和 implementation file set。每项当前 runtime asset 都必须能从其中一个 closure
到达，或者能从加载和执行这些 closure 所必需的共享 controller infrastructure
到达。

最终 catalog 恰好包含两个 entry，最终 activation manifest 只包含以下 profile 和
suite set：

| Profile | Required suites |
|---|---|
| `full@4` / `single-repository` | `v4-static-closure`, `v4-core-runtime`, `v4-effect-recovery`, `v4-external-tools` |
| `full@4` / `multi-repository` | 上述 `full@4` / `single-repository` 的全部 suite，再加上 `v4-multi-repository` |
| `lite@4` / `single-repository` | `v4-static-closure`, `v4-core-runtime`, `v4-effect-recovery` |

`v4-static-closure` 枚举每个可达 action placement，并证明每个 placement 恰好
resolve 为一份完整 V4 contract。随后，聚焦的 behavioral suite 为每个密封 contract
class 运行一个代表用例，而不是为每个声明式 placement 重复 test。startup 和 task
creation 要求精确适用的 suite set；不存在 default-to-V2/V3 path。旧版 bundle
directory、adapter manifest、resolver policy、oracle 和 compatibility fixture 全部
删除。

删除依据是 semantic reachability 与 source inspection，而不是盲目搜索数字。这样
既保留版本化的通用 protocol，也确保没有 workflow-generation V2/V3
implementation 残留。

### 4. 重建 V4 execution core，而不是 bridge

现有 transition-engine、lock、revision、approval、evidence、manager capability、
effect-claim、receipt、quarantine 和 recovery invariant 继续具有权威性。它们的
generation-bound representation 只重写一次，成为 schema-v4/V4 contract。

最终结果包含：

- 一个 V4 task validator 和一个 V4 workflow resolver；
- 一个 V4 command/action catalog 和一个 transition commit-proof boundary；
- 一种 V4 journal/index/containment format；
- 一套 V4 recovery 和 reconciliation implementation；
- 一个当前 CLI/MCP/Hook/Skill projection model；
- 不包含 schema selector、frozen adapter、前代 oracle、alias 或 wrapper。

本 change 不会为历史 data 添加 special error、root marker、preflight 或 test
path。这类 path 本身就是 compatibility code。

### 5. 以 acyclic identity DAG 开启新的 V4 provenance genesis

前代 release ledger、`first-introduction.json`、
`reserved-v3-activation.json` 和 introduction-epoch chain 将从 live package 中
移除。替代 identity model 有意保持单向：

1. **L0 runtime inventory**覆盖最终可安装 V4 package input，包括最终 manifest
   version/cachebuster，但排除 genesis 自身、OpenSpec、test/CI，以及生成的
   validation、review 或 handoff evidence。
2. **L1 V4 genesis**存放在 candidate 中，并绑定 L0、恰好两个 workflow 及其
   bundle、transitive V4 handler identity、catalog、activation 和最终 manifest。
   它不包含 candidate、review 或 handoff digest。
3. **L2 canonical candidate**包含精确的 L1 byte，以及当前 source、聚焦 test、
   validator、CI input 和 distribution documentation。它排除 OpenSpec 和所有生成的
   L3 record。L2 内部没有任何 file 包含 L2 digest。
4. **L3 evidence**由 candidate root 之外的聚焦 validation、独立 review
   和 handoff record 组成。每条 record 都绑定 frozen L2，并且绝不修改它。

L0 和 L2 都在 verification specification 中定义了规范的 byte-level preimage 和
test vector。这一 ordering 消除了 self-reference：manifest 和 cachebuster 在 L0
之前稳定；L1 绑定 L0；L2 包含 L1；L3 绑定 L2。任何较低层 byte change 都会使全部
较高层 identity 和 evidence 失效。

V4 genesis 不包含前代 ledger，也不声称 plugin 本身在 history 上是从 V4 才首次
引入。它定义了 V4 runtime lineage 的起点。未来 provenance metadata 可以记录后续
V4 candidate，但 validator 只要求当前 inventory 中的 executable byte。

由于仍在使用且以 V3 命名的 implementation 将重建为 V4，identity drift 是有意的。
只有在 rename 和 pruning 完成后，才会 freeze 当前 bundle 和 handler digest；
与前代 digest compatibility 并不是目标。

### 6. 有意保持 automated verification 规模小

不设旧 data、旧 schema、V2/V3 pin、migration、fallback 或
compatibility-response test matrix。旧版 golden fixture 和 oracle 会直接删除，
而不是转化为 negative test。

automated check 仅覆盖本次工作所改变的 seam：

| Owner | Check | Why this owner |
|---|---|---|
| Codex | `v4-static-closure` | 证明每个可达 action placement 均 resolve 为精确且完整的 V4 contract，并证明 package/catalog/activation closure 只包含两个保留的 bundle |
| Codex | `v4-core-runtime` | 分别为 full 和 lite 各覆盖一次 schema-v4 creation 及通用 engine/guard/reducer/revision/projection path |
| Codex | `v4-effect-recovery` | 覆盖每个保留的 settlement 和 recovery contract class 各一个代表用例 |
| Codex | `v4-external-tools` | 覆盖 full profile 的 least-capability evidence 和 serialized host/workflow write boundary |
| Codex | `v4-multi-repository` | 覆盖 full multi-repository plan、lease、result、barrier、integration 和 serialized-CAS contract |
| Codex | Runtime-import、Skill、manifest、Hook/MCP launch、package、L0/L1/L2 identity 和 OpenSpec validator | 这些是带有可复现 assertion 的确定性 package contract |
| User | 替换已安装 plugin 并确认仅启用了一个 instance | 真实 Codex installation/cache state 仅存在于 user host 中 |
| User | 确认真实 Hook pickup 且 MCP initialize/tool discovery 成功| 这取决于实际 Codex host configuration 和 permission |
| User | 运行一个有代表性的真实项目 V4 workflow action | user 可以选择有意义的 repository，并且能以低于合成 compatibility suite 的成本判断 end-to-end experience |

不要求 user 验证 bundle hash、ledger structure、schema rejection、crash matrix 或每个
workflow node。这些 validation 要么已经自动化，要么有意不在范围内。

所有具名 suite source、fixture、validator、CI input 和 distribution documentation，
都在 L0/L1/L2 identity 工作之前完成。只有在 L2 freeze 后才执行聚焦 suite；其生成
result 属于 L3，因此不会改变它们所验证的 candidate。

### 7. 将 documentation 和 naming 作为 cleanup 的一部分

README、README.zh-CN、INSTALL、CONTRIBUTING、manifest text、marketplace metadata、
Skill、playbook、example 和 developer comment 只描述一种 V4 architecture。它们不
提及 generation selection、legacy task、migration、前代 recovery 或
compatibility behavior。

当前 source tree 和 test 对 generation-bound concept 使用 V4 name。已归档的
OpenSpec change 和 Git history 是唯一有意让已退役 architecture 继续可见的位置。

## Risks / Trade-offs

- **删除以 V3 命名的 implementation 时意外丢失 V4 行为** → 编辑前 freeze 两个 V4
  transitive closure，并对照这些 closure review 每个 generation-bound rename。
- **出于外观原因 rename 通用 protocol version** → 更改前将每个带编号的 identifier
  分类为 workflow-generation-bound 或 independently versioned。
- **wrapper 残留并在不可见处保留旧 architecture** → 要求直接 V4 registry target，
  并在 pruning 后搜索当前 package 中的前代 workflow symbol。
- **identity churn 掩盖非预期 semantic change** → 在 L0/L1 freeze 前重新计算并
  inspect graph、handler、bundle 和 catalog identity，然后通过外部 L3 validation
  和 review 绑定 frozen L2 snapshot。
- **现有 plugin identity 被 cache 为前代 package** → 在 package input 稳定后、L0
  之前提升 major version 和 cachebuster；replace 而不是 add installation，并由 user
  验证真实 host 只启用了一个 instance。
- **minimal testing 漏掉无关行为** → 在已改变的 architectural seam 上运行最小 test，
  在 spec 中保留当前 safety invariant，并执行一次 real-host V4 smoke；不得以 full
  suite 作为补偿。
- **platform cleanup 移除了仍有人期待的行为** → 在两种 language 中将 macOS 声明为
  唯一 supported V4 host；重新引入任何 Windows/Linux claim 之前，需要一个单独限定
  范围且带有 native evidence 的 change。

## Migration Plan

这是 replacement plan，不是 data migration。

1. 记录精确的 `full@4`/`lite@4` dependency closure，并将每个带编号的当前 contract
   分类为 generation-bound 或 generic。
2. 引入 schema-v4 state 和直接 V4 runtime name，然后将两个 V4 bundle 和
   registry 切换到这些 implementation。
3. 删除 V2/V3 bundle、旧版 adapter、前代 wrapper、compatibility branch、oracle、
   fixture、test 和 documentation。
4. 将 catalog、activation、package inventory、CLI/MCP/Hook/Skill surface、package
   validator、具名 suite source/fixture、CI input 和 macOS documentation 缩减为
   唯一 V4 architecture。
5. 在 identity computation 前，将现有 manifest identity 最终确定为
   `4.0.0+codex.<cachebuster>`。
6. 计算 L0，写入 L1 genesis，并在 candidate 内部不嵌入 L2 或 L3 digest 的情况下
   freeze L2。
7. 运行精确具名的聚焦 suite 和 validator；将 result 和独立 implementation review
   存储为绑定 L2 的外部 L3 record。
8. 将未经改动且已经 review 的 L2 candidate 交给 user，执行三项 real-host
   acceptance check。

不进行 runtime-data migration 或 compatibility rollback。publication 前仍可使用
常规 source-control reversion。publication 后在 V4 line 中向前修复 defect。

## Open Questions

无。user 已明确选择一个 in-place V4 plugin、不处理历史 data、不进行前代 workflow
fallback，并在 automated testing 与 real-host testing 之间采用最小分工。
