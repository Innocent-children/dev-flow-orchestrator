> **Milestone rule**：只有对应 `Exit criteria` 全部成立时，才能建立 checkpoint
> 或进入下一 Milestone。不得在 V2/V3 删除一半、V4 replacement 只完成一半，
> 或 candidate identity 尚未稳定时，把中间状态视为可验收 snapshot。
>
> **M0 — Plan Freeze（已完成）Exit criteria**：旧 OpenSpec change 已 archive，
> `establish-v4-only-runtime` 是唯一 active change；全部 planning artifact 已完成
> strict validation，并通过绑定当前 artifact、guidance snapshot 和 main spec
> manifest identity 的独立只读 plan review。

## 1. 冻结纯净 V4 boundary

- [x] 1.1 从当前 package 中记录精确的 `full@4` 和 `lite@4` graph、schema、playbook、handler、guard、reducer、gate、executor、recovery 及 implementation-file closure。
- [x] 1.2 将每个带编号的当前 identifier 和 file 分类为 workflow-generation-bound、独立版本化的通用 protocol 或可移除的前代 content；删除 code 前 review 该 classification。
- [x] 1.3 定义最终 schema-v4 task contract、V4 generation-bound naming map、恰好包含两个 bundle 的 catalog、恰好三个 activation profile、五个具名 suite contract，以及 L0/L1/L2/L3 provenance schema。

> **M1 — V4 Boundary Freeze Exit criteria**：`full@4` 和 `lite@4` 的完整
> implementation-file closure 已记录；每个带编号的 identifier 和 file 均已
> review 并被唯一归类为 V4 replacement、独立版本化的通用 protocol 或删除项；
> schema-v4 task contract、V4 naming map、catalog、activation profile、focused
> suite contract 和 provenance schema 均已冻结，尚未在 classification 之前删除
> implementation code。

## 2. 将 task state 和 workflow resolution 重建为 V4

- [x] 2.1 将 task schema constant、model、validator、default、fixture 和当前 state writer 替换为 schema v4，不保留 schema selector 或前代 state branch。
- [x] 2.2 将 `workflow_runtime` 中的旧版 adapter selection 和 workflow fallback，替换为对已安装的精确 `full@4` 或 `lite@4` bundle 进行直接 resolution。
- [x] 2.3 让 task creation、loading、projection、recovery 和 orchestration service 直接使用唯一的 schema-v4 runtime contract。
- [x] 2.4 在 V4-reachable replacement 启用后，移除旧版 adapter service、frozen state table、task-resolution policy、compatibility response branch 和 predecessor-only cleanup/recovery helper。

## 3. 让 execution kernel 成为 V4-native

- [x] 3.1 将每个 V4-reachable handler、guard、reducer、gate、command 和 executor，从 generation-bound V3 identity 迁移到已 review 的 V4 identity 和 registry entry。
- [x] 3.2 以直接 V4 module 和 function 替换 `workflow_v3_handlers.py`、`execute_v3_*`、`recover_v3_*`、`reducer.v3-*` 及等价的当前 wrapper；删除 wrapper 而不是保留 alias。
- [x] 3.3 将 generation-bound action transaction、journal、index、engine-proof、containment、quarantine、receipt 和 reconciliation schema 与 digest domain 替换为其 V4 definition。
- [x] 3.4 更新 manager-capability、multi-repository orchestration、review、workspace、external-tool 和 recovery call path 以使用 schema-v4/V4 contract，同时保持 lock、CAS、evidence、approval 和 effect-safety invariant。
- [x] 3.5 更新 CLI、MCP、Hook、Skill 和 compact projection，以使用唯一的 V4 command/action/result model，且不包含旧版 grammar 或 response branch。

## 4. 将 workflow 和 package asset 缩减为一个 V4 product

- [x] 4.1 更新 `full@4` 和 `lite@4` 的 graph、schema、runtime manifest、playbook 和 transitive implementation manifest，使其仅引用直接 schema-v4/V4 runtime closure。
- [x] 4.2 将 `workflows/catalog.json` 缩减为恰好 `full@4` 和 `lite@4`；将 `workflows/activation.json` 缩减为指定的三个 profile 及其精确具名 suite set，不保留其他 creation fallback。
- [x] 4.3 删除 V2/V3 bundle root、旧版 adapter manifest、前代 playbook/schema、compatibility fixture、oracle 和 predecessor-only test module。
- [x] 4.4 审计当前 package、source、test、Skill 和当前 documentation 中残留的前代 workflow identity；只保留 task 1.2 所论证的独立版本化通用 protocol。
- [x] 4.5 移除仅为已退役 support claim 而存在的 Windows/Linux-only launcher、runtime branch、native runner、fixture、CI job 和 documentation，同时保留共享且平台中立的 V4 code。

> **M2 — Atomic V4 Cutover Exit criteria**：task state、workflow resolution、
> execution kernel、CLI/MCP/Hook/Skill projection、workflow asset 和 package
> 已作为一个整体切换为 V4-only；catalog 恰好包含 `full@4` 和 `lite@4`，
> activation 恰好包含三个指定 profile；V4-reachable closure 中不存在 V2/V3
> runtime、code、asset、name、wrapper、adapter、fallback 或 predecessor-only
> branch；M1 closure inventory、task 4.4 source/package reachability audit 和必要的
> startup/import smoke 均支持该结论。正式 `v4-static-closure` validator 不属于
> 此 gate；它由 task 5.4 实现，并在 M4 对 frozen L2 运行。Task group 2–4
> 未全部满足本 gate 前，不建立可验收 checkpoint。

## 5. 稳定每个 L0 和 L2 identity input

- [x] 5.1 更新 README、README.zh-CN、INSTALL、CONTRIBUTING、example、manifest text、marketplace metadata 和 playbook，使其描述一个受 macOS 支持的 V4 architecture，不包含 generation choice、migration、compatibility、前代 recovery 或 Windows/Linux support claim。
- [x] 5.2 更新每个已纳入 package 的 Skill 和 default prompt，使其仅输出当前 V4 command、field、projection 和 recovery instruction。
- [x] 5.3 将 Hook 和 MCP launch configuration 缩减为指定的 macOS contract，并让 package/default-discovery validation 强制执行精确的当前 V4 target。
- [x] 5.4 实现 `v4-static-closure`，以证明恰好两个 bundle 的 package purity，并用一个完整且直接的 V4 contract identity 枚举每个可达 action placement。
- [x] 5.5 实现 `v4-core-runtime`，为 `full@4` 覆盖一次 schema-v4 creation 及 common transition path，并为 `lite@4` 覆盖一次。
- [x] 5.6 实现 `v4-effect-recovery`，为每个保留的 settlement/recovery contract class 覆盖一个代表用例，并在适用时覆盖指定的 bounded hostless `UNRESOLVED` safety path。
- [x] 5.7 为 full profile 实现 `v4-external-tools`，覆盖 least-capability evidence 和 serialized host/workflow write boundary。
- [x] 5.8 为 full profile 实现 `v4-multi-repository`，覆盖 plan、lease、result、barrier、integration 和 serialized-CAS invariant。
- [x] 5.9 以指定的 L0/L1/L2/L3 schema、精确 allowlist、规范 preimage、test vector 和 layer-order check，替换前代 ledger command 及 validator。
- [x] 5.10 删除 `first-introduction.json`、`reserved-v3-activation.json`、前代 introduction epoch、frozen predecessor digest 及其 package requirement。
- [x] 5.11 保留现有 plugin name，将其最终 semantic version 设为 `4.0.0+codex.<cachebuster>`，更新唯一的 marketplace entry，并证明未创建第二个 V4-suffixed plugin identity。
- [x] 5.12 在计算 provenance identity 前，稳定所有聚焦 suite source/fixture、validator、CI input、可安装 runtime、workflow、Skill、adapter、documentation、manifest 和 cachebuster byte。

## 6. 建立 acyclic V4 provenance line

- [x] 6.1 根据最终可安装 V4 allowlist 计算 L0 `runtime_inventory_sha256`，排除 genesis、OpenSpec、test/CI、生成的 evidence 和不可安装 file。
- [x] 6.2 将 L1 写成一个 V4 genesis，使其绑定 L0、恰好 `full@4` 和 `lite@4`、它们的 transitive handler、catalog、activation 和最终 manifest，且不包含 L2 或 L3 digest。
- [x] 6.3 仅在 L1 存在后 freeze L2；纳入精确 genesis byte 和所有指定的当前 candidate input，排除 OpenSpec 和 L3 record，并验证任何 candidate file 均不包含 L2 digest。

> **M3 — Candidate Freeze Exit criteria**：documentation、Skill、Hook、MCP、
> manifest、唯一 plugin identity、cachebuster、focused suite source/fixture、
> validator、CI input 及所有 installable byte 已稳定；L0 已从最终 allowlist
> 计算，L1 genesis 已绑定 L0，L2 已绑定精确 L1 byte 和全部 candidate input，
> 且 L0→L1→L2 保持 acyclic。此 gate 完成后，任何 candidate byte change 都必须
> 使 L2 与既有 evidence 失效，并重新打开 M3。

## 7. 仅运行 focused current-V4 verification

- [x] 7.1 针对 frozen L2，仅运行每个 activation profile 所需的精确具名 suite，以及受直接影响的 runtime-import、Skill、manifest、Hook/MCP launch、package、L0/L1/L2 identity 和严格 OpenSpec validator；将 result 写为外部 L3 evidence，不添加历史 input case，也不运行完整 unittest discovery。
- [x] 7.2 验证 activation evidence 将 `full@4` single-repository、`full@4` multi-repository 和 `lite@4` single-repository 映射到各自精确指定的 suite set 及 frozen L2 identity。
- [x] 7.3 针对 frozen L2 运行 `git diff --check` 和独立的只读 implementation review；将两者记录为外部 L3 evidence，并将 Windows/Linux validation 记录为未执行。
- [x] 7.4 在 candidate root 之外构建 deterministic handoff，在外部 L3 record 中将其绑定到 unchanged L2 digest，并验证 handoff creation 不会修改 L2。

> **M4 — Implementation Handoff Exit criteria**：仅针对 frozen L2 运行 activation
> profile 精确要求的 focused current-V4 suite 和直接受影响的 validator；未添加
> legacy-data case，未运行 full unittest discovery；`git diff --check` 与独立只读
> implementation review 已通过；外部 L3 evidence 和 deterministic handoff 已绑定
> unchanged L2，且 Windows/Linux 明确记录为未执行、不得由 macOS evidence 推断。

## 8. 完成 user-owned real-host acceptance

- [x] 8.1 User：用已 review 的 V4 candidate 替换已安装 plugin，并确认 Codex 恰好显示一个已启用的 Dev Flow Orchestrator instance。
- [ ] 8.2 User：确认真实 Codex host 能 pickup 已纳入 package 的 Hook，且 MCP initialize/tool discovery 使用已安装 candidate 成功。
- [x] 8.3 User：在真实项目中新建的 V4 task 内运行一个有代表性的 action，并确认 end-to-end command、projection 和 result experience。

> **M5 — Real-host Acceptance Exit criteria**：User 已用 reviewed candidate
> 替换真实安装并确认 Codex 中恰好存在一个 enabled plugin instance；Hook pickup
> 与 MCP initialize/tool discovery 成功；在真实项目中新建的 V4 task 中完成一个
> representative end-to-end action。此 gate 完成后，V4-only release 才视为最终验收。
