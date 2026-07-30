## MODIFIED Requirements

### Requirement: The controller and manager preserve single-writer authority
controller SHALL 继续作为唯一持久化 task state、node state、evidence
acceptance、barrier status 和 workflow transition 的 component。在 agent
plane 内，只有 designated manager role SHALL 获得请求 mutating controller
operation 的 authorization。repository worker MUST 获得 read-only
controller capability，并且 MUST 向 manager 返回 candidate result，而不是
写入 state file、推进 node、接受 evidence 或调用 mutating controller tool。
manager request MUST 仍满足 controller lock、expected-revision check、
guard、approval 和 evidence contract；manager designation MUST NOT 绕过
kernel policy。

每次通过 CLI 或 MCP 进行的 schema-v4 agent-plane mutation 还 MUST 提供由
controller 为一个 task、manager session、permitted action set 和 expiry
签发的 short-lived manager capability。controller SHALL 生成至少 256 位
randomness，仅持久化 verifier 以及 issuance、revocation 和 request-nonce
state，仅通过 manager-scoped secret channel 而不是 command argument 或 log
接受 plaintext proof，并在取得 mutation authority 前拒绝 missing、expired、
revoked、cross-task、cross-session、replayed 或 action-mismatched proof。
worker assignment 和 lease credential MUST NOT 包含或继承 manager proof；
lease credential 可以标识 candidate output，但不授予任何 transition、
approval、cancellation、evidence-acceptance 或 result-acceptance operation。

standard-library V4 CLI SHALL 提供显式的 local operator authorization 和
revocation path，使 recovery 不依赖 MCP 或 SDK。issuance 本身 MUST 经过
confirmation gate、接受 audit、不出现在 model 或 worker output 中，并且不能
绕过任何 workflow guard。

仅当 host adapter 能够证明 worker sandbox 和 tool set 排除 controller data
directory、direct task-state path、manager secret channel 和 mutating
controller tool，同时允许 assigned worktree 时，才支持 writable native-worker
dispatch。如果 host 无法提供这种 separation，controller MUST 对 parallel
writable worker dispatch fail closed，或 fallback 到 manager-owned serial
execution。filesystem isolation 是 host boundary，而不是仅由 Python code
提出的 claim；out-of-scope worktree effect 还会在 result 和 integration
evidence validation 时被检测到，且绝不会作为 workflow success 接受。

#### Scenario: worker 完成 implementation
- **WHEN** repository worker 完成分配给它的 implementation 和 test
- **THEN** 它向 manager 返回 candidate structured result，且不直接更改 task 或 node state

#### Scenario: worker 请求 transition
- **WHEN** repository worker 尝试调用 mutating transition 或 evidence-acceptance operation
- **THEN** 该 operation 在 state persistence 前被拒绝，且 worker result 保持 unaccepted

#### Scenario: worker 知道 controller 和 task identity
- **WHEN** 以同一 operating-system user 身份运行的 worker 可以找到 controller，并知道 task ID 和 current revision，但没有 manager capability
- **THEN** CLI 和 MCP mutation request 在 state persistence、approval change、lease change 或 event delivery 前被拒绝

#### Scenario: 重放 manager capability request
- **WHEN** 调用方重复使用已消耗的 manager request nonce，或在其 task、session、action 或 expiry scope 之外使用 proof
- **THEN** controller 返回 stable capability error，且不 commit state 或 event

#### Scenario: 授权 CLI-only V4 recovery
- **WHEN** operator 在没有 MCP 或 SDK 的情况下使用 standard-library CLI，并显式确认 scoped schema-v4 recovery session
- **THEN** controller 通过 local secret channel 签发 manager capability，并且之后的每次 mutation 仍需通过正常的 revision、evidence、approval 和 recovery check

#### Scenario: host 无法隔离 writable worker
- **WHEN** adapter 无法阻止 worker 读取 manager secret channel 或 controller data directory，或无法阻止它发现 mutating tool
- **THEN** controller 不 dispatch 该 parallel writable worker，并报告受支持的 manager-serial fallback

#### Scenario: manager 提交 authorized result
- **WHEN** designated manager 使用 current expected revision 提交 valid candidate result
- **THEN** controller 独立 validate 该 result，并在其 task lock 下执行 permitted mutation

#### Scenario: manager 尝试绕过 gate
- **WHEN** manager 请求的 transition 缺少 required current evidence 或 approval
- **THEN** controller 拒绝该 request，方式与拒绝任何其他 unauthorized caller 完全相同

### Requirement: Every orchestration operation uses the unified engine-proof boundary
V4 package SHALL 维护一个 exhaustive、catalog-sealed orchestration
operation matrix，覆盖 repository-plan proposal 和 approval、map expansion
和 invalidation、frontier readiness、assignment、lease
issue/revoke/expiry、dispatch、stop、reconciliation、recovery、retry、
timeout、cancellation、result acceptance 和 invalidation、barrier closure
和 reopening、integration capture 和 verification、independent review、
finalization 以及 manager-capability issue/revoke。每个 operation-specific
validator SHALL 为一条准确的 same-node V4 action edge 生成 typed
`ActionOutcome`，common transition engine SHALL 生成并消耗 single-use
commit proof。specialized validator、manager capability、lease credential
或 request nonce 是 necessary evidence，但其本身 MUST NOT 成为 parallel
state-commit authority。

每个 matrix entry MUST 使用一个 stable V4 action identity 对应一个 semantic
validator、canonical event 和 write/effect set。frontier advancement 和
assignment issuance，以及 runtime recovery observation 和 attempt
abandonment，分别是具有不同 action identity 的 distinct operation。catalog
MUST NOT 注册 compatibility alias，也不得跨这些 semantics overload 同一个
action identity。

每个 proof MUST 绑定 task、revision、V4 workflow bundle、operation、action
edge、candidate digest、需要时的 manager authorization 以及 event batch。
missing 或 mismatched proof 以及 proof replay MUST 使 task byte、outbox、
manager nonce state、Git、worktree 和 external state 保持不变。manager
request nonce 及其 target business mutation SHALL 在同一个 atomic
state/outbox transaction 中被消耗。

capability issuance 是持有 existing manager capability 这一要求的 explicit
bootstrap exception，而不是 engine 的 exception。它要求 local operator
confirmation 和 secret-channel contract、task lock、expected revision、
准确的 `manager.authorize` action edge 以及 fresh issuance nonce；engine
以原子方式 commit verifier record 和 audit event。revocation 使用其已声明的
operator proof 或 current-manager proof，并遵循相同 engine path。

#### Scenario: 应用 sealed orchestration operation
- **WHEN** operation-specific validator 接受 current V4 plan、lease、result、barrier、integration、review、recovery 或 manager-registry outcome
- **THEN** unified engine 重新求值其准确的 catalog action edge，并以原子方式随 business mutation 和 audit batch 一起消耗 manager request nonce 和一个 single-use commit proof

#### Scenario: 拒绝 forged orchestration proof
- **WHEN** orchestration request 省略 proof、更改 proof 的 task、revision、bundle、operation、action、candidate digest 或 event binding，或 replay 已消耗的 proof
- **THEN** task byte、pending 和 delivered outbox record、nonce state、Git、worktree 和 external system 保持不变

#### Scenario: 引导 manager capability
- **WHEN** local operator 在尚未持有 manager capability 的情况下，为 current schema-v4 task 显式确认 capability issuance
- **THEN** 已声明的 bootstrap action 验证 operator 和 secret channel、expected revision、task lock 和 fresh issuance nonce，然后 engine 以原子方式记录 verifier 和 audit event

#### Scenario: 拒绝在没有 target mutation 时消耗 nonce
- **WHEN** crash、invalid candidate 或 stale engine proof 阻止 authorized orchestration mutation
- **THEN** manager request nonce 不会被单独消耗，且调用方只能根据相同 current authorization contract 安全 retry

#### Scenario: 拒绝 overloaded orchestration action identity
- **WHEN** V4 catalog 将一个 action identity 分配给 frontier advancement 和 assignment issuance，或同时分配给 runtime recovery observation 和 attempt abandonment
- **THEN** catalog sealing 失败，并要求使用独立的 action、validator、event 和 write/effect contract
