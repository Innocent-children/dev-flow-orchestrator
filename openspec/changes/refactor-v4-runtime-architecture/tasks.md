## 1. Greenfield Boundary

- [x] 1.1 记录当前用户可见 command、capability、安全 invariant 和 failure mode 的 reference inventory，并逐项标记 `rebuild`、`simplify` 或 `drop`；不得把旧 call graph 或 module layout 当作目标。
- [x] 1.2 冻结 workflow depth、repository topology、workspace strategy、四个 V4 profile、task schema v4 和显式 creation input 的 product contract。
- [x] 1.3 冻结 greenfield module dependency、node contract、单一 mutation boundary、effect phase 和 Atomic Greenfield Cutover contract。
- [x] 1.4 建立 architecture validation 规则，能够检测旧 runtime import/source execution、shared-global lookup、重复 product matrix、domain→infrastructure dependency、adapter state write、wrapper/fallback 和 public dual-dispatch。

> **G1 — Greenfield Contract Gate**：reference inventory 只描述“要实现什么”和必须
> 保持的 invariant；product、node、dependency、mutation 和 cutover contract 完整；
> 不包含历史 data 或 compatibility obligation。G1 通过前不得创建 runtime skeleton。

## 2. Minimal Runnable Skeleton

- [x] 2.1 创建独立的 `src/dev_flow_orchestrator/` package 和最小普通 import bootstrap；新 package 不 import、读取或执行 `scripts/dev_flow_parts/`。
- [x] 2.2 在 `product.py` 实现唯一不可变 product matrix，包括四个 profile、workspace compatibility、suite 和 capability binding。
- [x] 2.3 在 `model.py` 实现最小 schema-v4 task、profile、node decision、mutation plan 和 V4 receipt value，并保持 domain module 无 filesystem/process dependency。
- [x] 2.4 在 `store.py` 实现显式 `--data-dir`、private directory/file、task lock、revision check 和 atomic JSON replace。
- [x] 2.5 在 `engine.py` 实现 pure `start`/`preflight` eligibility、bounded write-set validation 和 deterministic mutation plan。
- [x] 2.6 在 `git_client.py` 实现 macOS current Git read boundary，使用 argument vector 返回 bounded repository evidence，不提供 mutation。
- [x] 2.7 在 `controller.py` 实现唯一 state writer 和 effect-free/read-effect plan→commit path。
- [x] 2.8 在 `cli.py` 实现 greenfield `start`、`show`、`preflight` 与单 JSON stdout/error envelope；workflow 与 workspace strategy 均为显式 input。
- [x] 2.9 添加只覆盖 skeleton 的 focused tests：四 profile creation、lite multi-repository、private schema-v4 persistence、stale revision、preflight evidence、source independence 和 JSON response。

> **G2 — Minimal Skeleton Gate**：`start`、`show`、`preflight` 可在 `-I -S`、
> standard library 和临时 `--data-dir` 下独立运行；四 profile 全部成立；只有
> controller 写 state；architecture validation 与 focused skeleton tests 通过。G2
> 通过前不得增加下一组 capability。

## 3. Core Workflow Vertical Slices

- [x] 3.1 实现 graph-derived `agent-v1` projection 和 bounded current-node receipt，不复制 CLI/MCP/Hook state table。
- [x] 3.2 实现 approval node contract，使 approval 只产生 controller-owned mutation plan，不授予 adapter 或 model authority。
- [x] 3.3 实现 full workflow 的 baseline、impact 和 route nodes；lite graph 明确跳过这些 node，而不是在 handler 内分支。
- [x] 3.4 实现 workspace node 与 gated Git effect port，覆盖 `in-place`、`branch`、`worktree` 的显式 product compatibility。
- [x] 3.5 实现 planning、implementation、test、review 和 finalization nodes；每个 node 只拥有自己的 input、write set、effect 和 failure。
- [x] 3.6 为每个新增 node contract 添加最小 success、authority/write-set failure 和必要 effect case focused test，并更新 capability inventory。

> **G3 — Core Workflow Gate**：single-repository 的 `full@4` 与 `lite@4` 可以仅通过
> greenfield package 完成各自 workflow；node 差异存在于 graph/product contract，
> 不存在 flow-specific duplicate kernel。

## 4. Effect Journal and Recovery

- [x] 4.1 实现最小 action journal value、idempotency binding 和 durable receipt，不复制旧 transaction/service class hierarchy。
- [x] 4.2 实现 controller 的 effect plan→dispatch→receipt→commit 三阶段，并明确 short-lock boundary 与 revision revalidation。
- [x] 4.3 实现 current V4 uncertain-effect quarantine、inspect、reattach、settle、abandon 和 bounded operator intervention nodes。
- [x] 4.4 实现 recovery 的 scope blocking、single-dispatch、target-bound evidence 和 dual-boundary compensation invariant。
- [x] 4.5 添加每个 recovery contract class 的一条代表 focused test；不测试 historical data、legacy response 或 predecessor recovery。

> **G4 — Effect Safety Gate**：任一 effect 在 interruption 后只有一个 durable
> outcome path；无 adapter、node 或 caller assertion 可绕过 controller；不存在旧
> runtime fallback。

## 5. Shared Multi-Repository Kernel

- [x] 5.1 实现 canonical repository set、deterministic ordering、repository-scoped ownership 和 pinned dependency DAG。
- [x] 5.2 实现 map expansion、bounded concurrency、lease/attempt 和 repository-scoped result node。
- [x] 5.3 实现 serialized idempotent CAS、result barrier、integration binding、retry、cancellation 和 recovery nodes。
- [x] 5.4 让 `full@4` 与 `lite@4` 的 multi-repository profile 解析到同一 repository kernel；差异只来自各自 workflow graph 的 gate。
- [x] 5.5 添加 lite/full multi-repository representative focused tests，证明四 profile、共享 authority 和无 `LITE_REQUIRES_FULL` repository-count coercion。

> **G5 — Four-Profile Gate**：四个 profile 都可通过新 package 创建和执行其声明节点；
> lite multi-repository 不进入 full-only node；repository invariant 只有一个 owner。

## 6. Codex Entry Points

- [x] 6.1 以 greenfield controller API 重建 MCP stdio adapter，只保留 current bounded tool schema，不包含自动 CLI fallback。
- [x] 6.2 以 greenfield projection 和 scope policy 重建 Hook；Hook 保持小型、advisory、内部错误 fail open 且不执行 transition。
- [x] 6.3 更新 Skill command 和 node guidance，使其只调用 injected current CLI/MCP locator，不包含旧 command、state table 或 runtime path。
- [x] 6.4 更新 plugin manifest、`.mcp.json` 和 macOS launcher，使其在 cutover candidate 中只引用 greenfield entrypoint。
- [x] 6.5 添加 CLI/MCP/Hook 同 controller semantics、packaged launch 和 source independence 的最小 focused tests。

> **G6 — Adapter Gate**：CLI、MCP、Hook 和 Skill 只负责 wire/advisory concern，所有
> mutation 与 workflow policy 由同一 greenfield controller 拥有。

## 7. Atomic Greenfield Cutover

- [x] 7.1 同时切换 public CLI、MCP、Hook 和 Skill entrypoint 到
  `src/dev_flow_orchestrator/`，不得按 command、task、environment 或 failure
  dual-dispatch。
- [x] 7.2 删除 `scripts/dev_flow_parts/`、ordered fragment loader、shared-global
  runtime service、字符串式 late binding 以及仅服务旧 runtime 的 wrapper、
  manifest、validator、test 和 documentation。
- [x] 7.3 更新 workflow graph、static node catalog、activation 和 runtime inventory，
  使四 profile 从唯一 product matrix 派生并只引用 direct greenfield node。
- [x] 7.4 运行 package-wide source closure audit，证明无旧 runtime code、asset、
  name、wrapper、adapter、fallback、test、documentation 或 predecessor provenance
  obligation。

> **G7 — Atomic Cutover Gate**：package 只能启动 greenfield runtime；删除任一旧
> runtime path 后所有 focused current-V4 tests 仍通过；不得在半旧半新状态冻结
> candidate。

## 8. Candidate Freeze and Handoff

- [x] 8.1 重写 README、中文 README、INSTALL 和 architecture documentation，准确
  描述四 profile、显式 workflow/workspace selection、scope、真实安装、node
  boundary、恢复和当前 macOS support。
- [x] 8.2 验证所有 Skill、plugin manifest、MCP/Hook launch、package inventory、
  OpenSpec strict validation 和 `git diff --check`。
- [x] 8.3 稳定所有 candidate input 后计算新的 bundle、handler、runtime inventory
  和 V4 provenance identity；freeze 后任何 candidate byte change 都使 evidence
  失效并重新打开本组。
- [x] 8.4 只对 frozen candidate 运行精确 focused current-V4 tests，明确跳过 full
  suite、historical-data、Windows 和 Linux validation。
- [x] 8.5 完成独立只读 implementation review，修复发现后重新执行受影响 gate，并
  生成外部 handoff evidence。

> **G8 — Release Candidate Gate**：同一 frozen candidate 通过 focused test、所有
> package validator、strict validation、source closure audit 和独立 review。

## 9. User Acceptance

- [ ] 9.1 用户在真实 Codex installation 中确认只有一个 enabled
  `dev-flow-orchestrator` plugin，且加载的是 frozen greenfield candidate。
- [ ] 9.2 用户确认真实 Hook 和 optional MCP pickup。
- [ ] 9.3 用户在真实项目分别完成至少一个 lite multi-repository 与代表性 full
  workflow smoke，并决定是否接受和 archive 本 change。
