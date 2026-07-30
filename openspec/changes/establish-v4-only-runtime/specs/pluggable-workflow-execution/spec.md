## ADDED Requirements

### Requirement: V4 workflow-specific runtime identities are direct and closed
凡版本跟随 workflow generation 的 persistence schema、command、action、
handler、guard、reducer、gate、journal、engine proof、containment record
和 recovery contract，均 SHALL 使用 V4 identity，并 SHALL 由 V4 runtime
直接实现。package MUST NOT 保留 V2/V3 adapter、generation bridge、唯一
目的只是调用早期 generation 入口点的 wrapper，或将早期 workflow contract
呈现为 V4 的 alias。

保留的 runtime closure SHALL 从准确的 `full@4` 和 `lite@4` graph 及其
transitive manifest 中推导。独立版本化的 generic protocol MAY 保留 `/v1`
等 identifier，前提是该后缀是 protocol 自身的版本，而不是 workflow
generation identity。

#### Scenario: 构建 V4 runtime closure
- **WHEN** startup 封闭 `full@4` 和 `lite@4` 的 runtime registry
- **THEN** 每个与 generation 绑定且可达的 identity 和 implementation 都是 V4-native，且没有注册任何 predecessor adapter 或 wrapper

#### Scenario: 保留独立版本化的 protocol
- **WHEN** V4 handler 引用当前 semantic contract 为 `/v1` 的 generic protocol
- **THEN** 除非 protocol 自身的语义发生变化，否则它保留 `/v1`，且不会被归类为旧 workflow implementation

### Requirement: Schema-v4 public actions are catalog-exhaustive and node-exact
每个公共 schema-v4 mutation command 和 trigger 均 SHALL 在其准确的
current node 解析为一条 identity-covered V4 action edge，该 edge 声明
stable action 和 edge identifier、public command、canonical audit event
type、准确的 handler、guard、reducer 和 gate、confirmation mode、允许的
node-owned write、kernel-owned write 和 invalidation、external-effect
classification、canonical concurrency class 和 effect scope、
dependency/parallel policy、synchronous-quiescence 或
asynchronous-handoff settlement、接受的 receipt schema、dispatch 和
idempotency policy、target-bound control action、quarantine
reconciliation/compensation 以及 recovery policy。一个 action identity
MUST 恰好映射到一个 semantic validator、event contract 和 write/effect
set。alias、generic artifact kind 或 same-status transition MUST NOT 成为
未声明的 fallback。

#### Scenario: 封闭完整的 V4 action catalog
- **WHEN** 两个 V4 graph 及其 action manifest 均已加载
- **THEN** 每个可达的 public action 都在其准确 node 恰好解析一次，并具有完整的 handler、policy、write、effect、receipt 和 recovery closure

#### Scenario: 拒绝声明 node 之外的 action
- **WHEN** schema-v4 调用方在 pinned V4 catalog 未声明该准确 action edge 的 node 请求某个 action
- **THEN** engine 返回稳定的 placement error，且不更改 task、outbox、journal、Git、filesystem、registry 或 external system

#### Scenario: 拒绝 action 语义重载
- **WHEN** 一个 V4 action identifier 在不同 placement 被分配给不同的 validator、canonical event 或 write/effect set
- **THEN** catalog sealing 拒绝该 bundle，并要求使用不同的 V4 action identity

#### Scenario: 强制执行已声明的 note guard
- **WHEN** blocking、rework、reassessment、reopen 或 cancellation edge 声明必须提供 operator note，而调用方省略 note 或提供空 note
- **THEN** guard 在 reducer 求值或任何受保护 effect 之前拒绝该 action

#### Scenario: 拒绝未声明的 artifact kind
- **WHEN** schema-v4 调用方提交 current node action 和 evidence contract 未列入 allowlist 的 artifact kind
- **THEN** engine 拒绝该 artifact，而不是持久化任意的 same-node artifact

## MODIFIED Requirements

### Requirement: One transition engine owns all workflow movement
每个 forward、rework、retry、skip、automatic、approval、failure 和 terminal
V4 workflow transition 均 SHALL 经过同一个 controller transition engine。
对于每次尝试的 transition，engine MUST 获取适用 lock、重新加载已提交的
schema-v4 state、强制执行调用方的 expected revision、解析准确的 pinned
V4 bundle、验证 task 和 node lifecycle、选择一条已声明 edge、重新求值
guard、evidence、approval 和 side-effect precondition、应用 bounded
reducer，并通过 atomic state/outbox protocol 提交所得 revision 和 durable
event。任何 command handler、Hook、Skill、agent、executor 或 adapter 均
不得在此 engine 之外改变 workflow state。

每次 schema-v4 business-state commit MUST 消耗一个不透明且不可序列化的
`EngineCommitProof`；该 proof 由 V4 kernel 在持有所需 lock 期间签发。
proof MUST 绑定 canonical task directory 和 held-lock capability、
task/revision/bundle/edge identity、old state 和 candidate state digest、
action outcome、event batch 以及任何 verified receipt；它 MUST 由
controller 启动实例私有的 key material 和 one-shot issuance registry
进行认证。公共 `TransitionEvaluation`、serialized object、调用方创建的
mapping、复制的 context value、manager authorization 或匹配的 digest
MUST NOT 足以构造或 replay 该 proof。proof MUST NOT 跨 restart 持久存在；
recovery 在提交已验证 receipt 前重新求值当前事实，以铸造一个 fresh proof。

#### Scenario: 应用有效的 V4 transition
- **WHEN** 一条已声明 V4 edge 在 expected revision 下合法，且所有 current guard、evidence、approval 和 side-effect precondition 均满足
- **THEN** engine 通过 transaction protocol 恰好提交一个 next revision 及其对应的 durable event

#### Scenario: 拒绝直接 state mutation
- **WHEN** command、node handler 或 adapter 尝试在不调用 transition engine 的情况下更改 workflow state
- **THEN** controller 拒绝或丢弃 candidate change，且不提交任何 revision

#### Scenario: 应用 same-node action
- **WHEN** 已声明的 V4 node action 在不改变 task coarse status 的情况下记录 evidence 或其他允许的 task fact
- **THEN** catalog-derived action edge、类型化 `ActionOutcome`、已注册 reducer 和同一个 transition engine 对 bounded change 进行授权并提交

#### Scenario: 拒绝未经 proof 的 same-node commit
- **WHEN** schema-v4 代码提交 same-status candidate 以供持久化，但未提供 task-pinned engine 的 single-use proof
- **THEN** 即使 generic manager authorization 在其他方面有效，durable commit boundary 也会拒绝 business-state change

#### Scenario: 在 proof process 退出后 recovery
- **WHEN** 某个 effect 已有 verified durable receipt，但持有其 engine proof 的 process 在 task-state replacement 之前退出
- **THEN** recovery 在所需 lock 下重新加载 current V4 state、重新求值每个 guard 和 binding，并在不重新 dispatch 该 effect 的情况下铸造新的 one-shot proof

#### Scenario: 重新求值此前 preview 的 transition
- **WHEN** 在 transition preview 后，evidence、approval、workspace state、pinned bundle 或 task revision 发生变化
- **THEN** apply 重新求值所有 current precondition，并拒绝 stale preview，且不产生 protected side effect

### Requirement: Guards and reducers have bounded authority
guard SHALL 是其 declared input projection 的 deterministic read-only
function，并且 MUST NOT 修改 state、file、Git、registry 或 external system。
reducer SHALL 生成 candidate state delta 和 event，且不执行 external side
effect。commit 前，engine MUST 计算实际更改的 JSON Pointer path，并证明
它们是 node 已验证 `allowed_state_writes` 的子集。node-level write
permission MUST 永不包括 task identity、pinned workflow identity、
committed revision、approval record、evidence provenance、durable outbox
state、quarantine state、lock metadata、workspace ownership 或其他
kernel-protected field。external effect SHALL 仅通过由 kernel recovery
rule 治理、单独授权的 V4 effect executor 运行。

只有 package-owned 且 statically inventoried 的 V4 guard 和 reducer
implementation MAY 在进程内运行。contract MUST 接受 immutable canonical
value projection 和一个 explicit kernel capability object；guard capability
MAY 仅公开已声明的 read-only evidence query，而 reducer capability MAY
不公开任何 filesystem、Git、process、network、registry-registration 或
commit operation。static registration validation MUST 根据当前 handler
audit policy，拒绝未声明的 global、import、implementation file 和
capability requirement。

Python runtime 并非任意 trusted code 的 isolation boundary。untrusted 或
dynamically supplied logic MUST 作为 external executor 运行并返回 evidence
candidate；它 MUST NOT 进入 `GuardRegistry` 或 `ReducerRegistry`。如果
capability membrane、static audit 或 post-evaluation state comparison
检测到 contract violation，transition evaluation MUST fail closed，而任何
可观察到的 external uncertainty MUST 进入正常 blocker 或 quarantine path。

#### Scenario: 应用 bounded reducer
- **WHEN** V4 reducer 仅更改其已声明的 node-instance result path，并返回 valid event
- **THEN** engine 接受 candidate delta，并继续正常的 transition validation

#### Scenario: 拒绝未声明的写入
- **WHEN** reducer 更改 node 已验证 allowed-write set 之外的 path
- **THEN** engine 报告意外的 JSON Pointer path，并且既不提交 candidate state，也不提交其 event

#### Scenario: 拒绝 protected-field grant
- **WHEN** V4 bundle 尝试授予 node reducer 更改 revision、workflow identity、approval、outbox、quarantine 或 workspace ownership 的 permission
- **THEN** bundle validation 在 node 能够运行之前失败

#### Scenario: 在 registration 时拒绝被禁止的 guard authority
- **WHEN** guard 声明或静态引用 filesystem-write、Git-mutation、process、network、registry-mutation 或 external-system capability
- **THEN** registry validation 在任何 task 能够执行该 handler 之前将其拒绝

#### Scenario: 拒绝 guard state mutation
- **WHEN** 进程内 V4 guard 改变提供给它的 projection 或另一个可观察的 candidate-state value
- **THEN** immutable input enforcement 或 post-evaluation comparison 使 transition 失败，并且既不提交 state，也不提交 event

#### Scenario: 将 untrusted logic 移出 guard registry
- **WHEN** workflow 需要无法满足 package-owned in-process audit 和 capability contract 的 logic
- **THEN** workflow 使用 external executor，其 output 在 package-owned guard 验证之前始终是 untrusted evidence candidate

### Requirement: Side-effecting node execution is recoverable
在 dispatch 能够更改 repository、filesystem 或 external system 的 V4
node work 前，engine SHALL 持久记录一项 schema-v4 execution intent，该
intent 绑定 task revision、node attempt、input digest、authorized effect
plan 和 executor contract。completion SHALL 要求 validated receipt 和
phase-appropriate postcondition evidence。engine MUST NOT replay 无法证明
其 idempotency 或 quiescence 的 effect，且 uncertainty MUST 进入 durable
quarantine path。

pre-effect intent 和 post-effect commit intent SHALL 是两个独立的 V4
contract。在每个 effect 前，controller SHALL 在
`action-executions/index.json` 持久化一个严格的
`dev-flow-v4-action-execution-index/v1`，并在
`action-executions/active/<execution-id>.json` 持久化一个严格的
`dev-flow-v4-action-execution-journal/v1`；terminal journal SHALL 移至
`action-executions/archive/<execution-id>.json`。per-effect containment
record SHALL 使用
`action-executions/containment/<execution-id>/<effect-id>.json`。
不存在 singleton predecessor quarantine format 或 compatibility
containment path。

index 和 journal update MUST 使用独立的 monotonic revision、record digest，
并在 task lock 加上每个所需 repository、worktree、lease 或 registry lock
之下执行 compare-and-swap。write-ahead reservation SHALL 存储
`pending_record_sha256`，以原子方式写入 active journal，并在任何 claim 或
dispatch 前将该值提升为 `record_sha256`。每个 effect 都有一个 durable
claim；任何第二调用方均不得 claim 或 dispatch 它。在 index removal 或
runtime-reservation promotion 前，archive byte MUST 持久且经过验证。

canonical byte SHALL 使用 `dev-flow-bundle-identity/v1` 中的严格 semantic
JSON rule。V4 journal、index、manager seal 和 engine proof domain SHALL 分别为
`dev-flow-v4-action-execution-journal-record-v1`、
`dev-flow-v4-action-execution-index-record-v1`、
`dev-flow-v4-action-execution-journal-seal-v1` 和
`dev-flow-v4-engine-commit-proof-v1`。manager secret 仅可通过已验证的
secret channel 获取；raw nonce、secret 和 capability MUST NOT 被持久化。
digest 和 HMAC comparison MUST 使用 `hmac.compare_digest`。

catalog-sealed scoped execution MAY 仅在其 repository、node、worktree、
lease、path 和 external-resource scope 互不相交时共存；`exclusive-task`
与每个 ordinary effect 冲突。task、result 和 barrier commit 仍由 task lock
和 expected-revision CAS 串行化。每个 effect 按
`PLANNED -> CLAIMED -> RUNNING -> (QUIESCED |
HANDOFF_VERIFIED) -> VERIFIED` 推进；`HANDOFF_VERIFIED` 仅对已声明的
asynchronous runtime-dispatch contract 合法。claimed effect 绝不会被自动
重新 dispatch。

recovery SHALL 通过 fresh target-bound V4 attempt，reconcile 已存储的 intent、
receipt、containment、runtime handle 和 current postcondition，其 terminal
outcome 为 `ACCEPTED`、`ABANDONED`、`COMPENSATED` 或 `UNRESOLVED`。
`ACCEPTED` 在不 dispatch 的情况下复用 verified receipt。`ABANDONED` 需要
controller-owned target-bound live evidence。`COMPENSATED` 既需要 current
pinned V4 workflow gate，也需要 host-owned、用于准确 compensation invocation
的 opaque one-shot approval。缺少 authority 会产生 `UNRESOLVED`、使 scope
保持 blocked，并返回有界的 `dev-flow-v4-operator-intervention/v1` packet，
且不会自动 redispatch、compensation、replacement、archive 或 unblock。

#### Scenario: 执行并提交一个 current V4 effect
- **WHEN** engine 对一个 authorized schema-v4 effect 执行 prepare、claim、dispatch、observe 和 verify
- **THEN** engine 恰好 commit 一次 receipt-bound V4 outcome，并持久 archive journal

#### Scenario: 在 kernel authorization 前拒绝 effect
- **WHEN** schema-v4 command 在没有来自 pinned V4 engine 的 current durable authorization 时到达 Git、filesystem、repository-registry 或 external-system executor
- **THEN** executor 不会启动，workflow state 和 external state 均不会更改

#### Scenario: 并发调用方 claim 同一个 effect
- **WHEN** 两个调用方竞相 apply 同一个 current V4 execution authorization
- **THEN** 一个 durable compare-and-swap claim 获胜，并且最多启动一个 executor

#### Scenario: 在 journal promotion 中断后 recovery
- **WHEN** controller 在 index digest 处于 pending 状态或 V4 active journal 尚未 promotion 时停止
- **THEN** scope 保持 blocked，recovery 在任何 effect 可被 claim 前完成该准确 update 或将其 quarantine

#### Scenario: 并发 dispatch 互不相交的 repository scope
- **WHEN** 两个 current V4 scoped execution 以互不相交的 approved repository、worktree、lease、path 和 external resource 为目标
- **THEN** index 允许 independent claim，同时 task-state receipt 仍按顺序 commit

#### Scenario: 提交 asynchronous runtime handoff
- **WHEN** 已声明的 V4 runtime-dispatch executor 具有 durable lease、containment、runtime handle、stop/reconcile capability 以及 verified launch postcondition
- **THEN** dispatch journal 可以到达 `HANDOFF_VERIFIED` 并成为 indexed runtime reservation，而不会混淆 worker lifecycle 和 action completion

#### Scenario: 在不 redispatch 的情况下对 verified receipt 执行 recovery
- **WHEN** recovery 证明 stored receipt 和 current postcondition 满足 pinned V4 accept policy
- **THEN** recovery 复用该 receipt，通过 fresh engine proof commit 一次，且绝不再次调用 original executor

#### Scenario: 在没有 trusted Codex-host authority 时 recovery
- **WHEN** current host 无法认证 abandonment evidence 或消耗准确的 one-shot compensation approval
- **THEN** 此 attempt 变为 `UNRESOLVED`，返回 bounded V4 intervention packet，并使 original execution 和 scope 保持 blocked

#### Scenario: 捕获 V4 review snapshot
- **WHEN** schema-v4 review action 在 controller data directory 中写入 snapshot tree
- **THEN** 它首先 claim 其 V4 journal effect，并且只 commit verified content-addressed snapshot receipt

#### Scenario: 遇到 uncertain non-idempotent effect
- **WHEN** recovery 无法证明 non-idempotent external effect 是否已完成，或无法证明其 executor 是否 quiescent
- **THEN** engine 阻止 replay、保留 durable quarantine，并要求 explicit recovery evidence

## REMOVED Requirements

### Requirement: Schema-v3 public actions are catalog-exhaustive and node-exact
**Reason**: 全新 V4 runtime 直接定义 schema-v4 action 和 V4-native workflow contract。

**Migration**: 无。不保留或支持任何 schema-v3 runtime data。
