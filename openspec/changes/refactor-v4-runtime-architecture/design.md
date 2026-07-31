## Context

当前 `scripts/dev_flow.py` 按固定顺序读取 `scripts/dev_flow_parts/*.py`，再通过
`exec(..., globals(), globals())` 将全部 source fragment 拼成一个 runtime。
`scripts/dev_flow_parts/` 约 11 万行，其中多个文件超过 4,000 行，
`orchestration_service.py` 超过 12,000 行。文件名提供了物理分隔，但 dependency、
authority 和 ownership 仍由共享 namespace、加载顺序和字符串式 late binding
决定。

当前 product contract 还将三个本应正交的维度混为一体：

1. workflow depth：`full` 或 `lite`；
2. repository topology：`single-repository` 或 `multi-repository`；
3. workspace strategy：`in-place`、`branch` 或 `worktree`。

结果是 repository 数量大于一被 risk policy 自动解释为 `full`，catalog 又拒绝
`lite` 携带 multi-repository metadata。三份代码常量、activation JSON、workflow
graph、test 和 documentation 同时复制同一错误矩阵。

旧 change `establish-v4-only-runtime` 已归档但未更新主 specs。它和当前 runtime
只作为 capability、安全 invariant 与 failure mode 的参考，不作为新 architecture
的 planning、module layout 或 evidence baseline。本次重构按 greenfield project
实现，没有 historical task data，不需要 migration、compatibility、fallback 或
双读写。

## Goals / Non-Goals

**Goals:**

- 用真正可 import 的 Python module 替换 ordered shared-global fragment runtime。
- 先建立一条最小、可运行、可测试的 vertical slice，再逐个重新实现 workflow node。
- 让每个 node 的 input、output、authority、state write、effect、failure 和 recovery
  一眼可见。
- 让一个 application mutation boundary 成为 task state 的唯一 writer。
- 让需要额外 authority 的 mutation 在同一个 controller boundary 内创建准确、
  持久、无超时的 Codex conversation confirmation request；只有后续精确
  `UserPromptSubmit` 事件确认后才能重试，public adapter 不接收 actor、approval
  boolean、authority proof 或 raw prompt。该事件仅是会话确认，不冒充 macOS
  用户身份认证。
- 让 workflow depth、repository topology 和 workspace strategy 独立建模，并支持
  四个 V4 profile。
- 让一个 product matrix 成为 profile、suite 和 capability 的唯一 source of truth。
- 保持 standard-library-only、macOS-only、V4-only、state-outside-repository 和
  deterministic gated Git mutation。
- 在每个 vertical slice 中同步完成 code、focused test、validator 和 documentation；
  新 package 从始至终不依赖旧 implementation，达到 cutover gate 后统一删除旧
  runtime。

**Non-Goals:**

- 不 import、调用、包装、继承或逐行翻译旧 runtime layout；不保留 facade
  monkeypatch identity 或 shared-global loading。
- 不保证旧内部 Python API、内部 response shape 或测试 fixture 的兼容。
- 不读取、检测、拒绝、迁移或恢复 historical task data。
- 不在本次工作中验证或宣称 Windows/Linux 支持。
- 不建立通用 plugin framework、dependency injection container、event bus、ORM、
  repository framework 或可动态加载的第三方 handler system。
- 不因为未来可能存在第二个 consumer 而提前创建 abstraction。
- 不运行 full test suite。

## Decisions

### 1. 先交付最小 skeleton，而不是先复制全部现有层

第一阶段只创建以下独立 importable package：

```text
src/dev_flow_orchestrator/
├── __init__.py
├── model.py          # V4 task、profile、node value
├── product.py        # 唯一 product/profile/capability matrix
├── store.py          # task state filesystem store 和 lock boundary
├── engine.py         # pure node eligibility、transition 和 mutation plan
├── controller.py     # 唯一 application mutation boundary
├── git_client.py     # 明确、受限的 Git subprocess effect
└── cli.py            # JSON command parsing 和 response envelope
```

开发阶段由 focused test 直接 import 新 package。达到 cutover gate 后，
`scripts/dev_flow.py` 只负责将固定的 package-owned `src/` 加入 isolated Python
module search path、import `dev_flow_orchestrator.cli.main` 并退出。第一条 vertical
slice 只实现 `start`、`show` 和 `preflight`，但同时证明：

- 四个 profile 均可创建并固定；
- state 位于明确的 `--data-dir`；
- 所有 mutation 通过 `Controller.apply(...)`；
- engine 在 effect 前生成 bounded mutation plan；
- preflight 的 Git read 通过 `git_client.py`；
- CLI stdout 仍为一个 JSON object。

选择这个 slice 是因为它同时穿过 entrypoint、product model、domain、mutation、
storage 和 Git read boundary，但不需要先实现完整 orchestration。

考虑过的替代方案：把现有几十个 fragment 逐层搬迁或创建一一对应的新 module。该
方案会复制复杂度和错误边界，让旧 architecture 继续决定新项目，因此拒绝。

### 2. 使用简单 module dependency，不使用 container 或 runtime registry

允许的 dependency direction 为：

```text
cli
  → controller
      → engine
      → store
      → git_client
engine
  → model
controller/store/engine
  → product
```

`model.py` 和 `product.py` 不导入 controller、store、Git、process、MCP 或 Hook。
`engine.py` 是 pure logic，不读取 filesystem、不执行 subprocess、不访问环境变量。
`controller.py` 显式接收 store 和 effect collaborator；只有外部 effect boundary 或
test injection 确有需要时才使用 `typing.Protocol`。

禁止：

- `exec`、`eval` 或把 module source 执行到共享 namespace；
- 通过 global symbol string 解析 function；
- service locator、dependency injection container 或 ambient mutable singleton；
- 为保留旧测试 monkeypatch path 而增加 facade；
- 新旧 runtime dual-dispatch。

考虑过的替代方案：保留 `RuntimeServices` 并将其改造成完整 container。它仍会隐藏
真实 dependency，并让每次调用跨越额外 wrapper，因此拒绝。

### 3. product matrix 是唯一 source of truth

`product.py` 定义不可变值：

```text
workflow: full@4 | lite@4
topology: single-repository | multi-repository
workspace: in-place | branch | worktree
```

四个 profile 均存在：

| Workflow | Topology |
|---|---|
| `full@4` | `single-repository` |
| `full@4` | `multi-repository` |
| `lite@4` | `single-repository` |
| `lite@4` | `multi-repository` |

workspace strategy 不再推导 workflow。CLI 必须获得显式 `--workflow` 和
`--workspace-strategy`，或者由一个公开且可测试的默认规则选择；默认规则不得查看
repository count。首个实现使用显式参数，避免隐藏 policy。

activation JSON、bundle graph、validator 和 documentation 必须读取或逐 byte 验证
这一个 matrix，不允许再定义第二份 Python profile map。

### 4. 每个 workflow node 使用同一个最小 contract

每个 node implementation 由一个普通 Python module/function 表示，并在相邻 manifest
中声明：

- stable node/action ID；
- input fields 和 output fields；
- required authority；
- allowed task-state JSON pointer；
- effect kind 和 effect port；
- idempotency key；
- failure result；
- recovery action；无 effect 的 node 明确写 `none`。

node function 接收 immutable projection，返回 `NodeDecision` 或 `MutationPlan`。它不
直接写 state、filesystem、Git、process、registry 或 external system。

不建立通用 handler inheritance tree。只有当至少两个已实现 node 产生完全相同且
稳定的代码时，才提取小型 helper；helper 不获得新的 authority。

### 5. 一个 mutation boundary，三个清楚阶段

`Controller.apply(...)` 是 task state 的唯一 writer，顺序固定为：

1. **plan**：在 task lock 下读取 current revision，由 engine 产生 `MutationPlan`；
2. **effect**：释放不应跨外部调用持有的 lock，调用明确 effect port，并获得 receipt；
3. **commit**：重新获得 task lock，校验 revision、plan binding 和 receipt，然后
   atomic replace state。

无 external effect 的 action 可在同一个 lock scope 内完成 plan 和 commit。任何
uncertain effect 必须进入当前 V4 quarantine/recovery node，不能由 CLI、Hook、MCP
或 node function 猜测结果。

新的 transaction、journal 和 recovery 只按 vertical slice 所需的最小字段从产品
contract 重新设计；不复制旧 abstraction。安全 invariant 不因简化 architecture 而
减弱。

### 6. multi-repository 是共享 kernel，不是 full 专属流程

multi-repository kernel 只负责：

- canonical repository set；
- repository-scoped ownership；
- dependency DAG；
- bounded concurrency；
- result barrier；
- integration binding。

`lite` 与 `full` 使用相同 kernel。差异由 workflow graph 的 node/gate 决定：

- `lite` 跳过 full-only baseline、impact、route、managed-worktree planning 和
  independent-review gate；
- `full` 保留这些 gate；
- topology 只决定是否需要 map/barrier/integration node，不改变 workflow depth。

第一阶段只让四 profile creation 和 state model 成立。后续 vertical slice 再实现
plan、lease、result、barrier 和 integration，避免 skeleton 一开始就包含完整
orchestration service。

### 7. greenfield capability 按 vertical slice 填充

greenfield rebuild 顺序：

1. skeleton：`start`、`show`、`preflight`；
2. projection 与 approval；
3. baseline、impact 和 route；
4. workspace 与 gated Git mutation；
5. planning、implementation、test 和 review；
6. action effect、journal 和 recovery；
7. multi-repository map、lease、result、barrier 和 integration；
8. MCP、Hook、Skill 与 package validator。

现有代码只用于先建立一份 capability/invariant reference inventory。实现者必须从
新 specs 和真实用户路径设计新 node，不复制旧 call graph。每个 slice 的完成条件：

- 新 package 独立实现该 slice，且不 import 旧 runtime；
- focused current-V4 test 通过；
- 没有指向旧 function 的 wrapper、alias、fallback 或 dual write；
- product matrix、documentation 和 package inventory 保持一致。

在开发阶段，旧 runtime 仅保留为不可调用的 reference implementation，package public
entrypoint 仍指向旧 candidate，避免半成品被误装。全部必需 slice 完成后执行一次
Atomic Greenfield Cutover：

1. 将 CLI、MCP、Hook 和 Skill entrypoint 同时切换到新 package；
2. 删除 `scripts/dev_flow_parts/` 和仅服务旧 runtime 的 test、manifest 与 validator；
3. 证明 package 中不存在到旧 runtime 的 import、source execution、wrapper 或
   fallback；
4. 此后任何缺失 capability 必须在新 architecture 中实现，不能恢复旧路径。

### 8. complexity budget 是 review gate

- 一个 module 只拥有一个可用一句话表达的责任。
- public function 名称必须表达业务动作，不能使用 `_osc_*`、`_workflow_tx_*` 一类
  subsystem prefix 模拟 namespace。
- function 出现多个独立阶段时优先拆成同 module 的具名函数；跨 module 抽取必须有
  明确 dependency boundary。
- 同一 invariant 只能有一个 owner；其他层调用 owner，不复制 validation。
- architecture document 必须能把每个 public command 映射到 controller action、
  engine node、state write 和 effect port。
- review 发现 ordered-global dependency、重复 product matrix、超大多职责 module
  或 compatibility wrapper 时，milestone 不通过。

不设置机械行数上限，因为安全 validation 有时天然较长；但任何超过一个屏幕且包含
多个业务阶段的 function 必须在 review 中解释或拆分。

## Risks / Trade-offs

- **[greenfield 填充期间新 package 暂时不完整]** → 开发 focused test 直接调用新
  package；public entrypoint 在 Atomic Greenfield Cutover 前不指向半成品，未完成
  worktree 不作为 installable candidate。
- **[简化 abstraction 可能遗漏安全 invariant]** → 每个 slice 先列出原路径的
  authority、lock、CAS、effect 和 recovery invariant，再用 focused test 证明后删除。
- **[四 profile 增加组合数]** → product matrix 统一派生组合；每个共享 contract
  class 测一条代表路径，不对声明式 placement 重复测试。
- **[直接 import 改变 facade-local monkeypatch 行为]** → 该行为不是产品 contract；
  测试改为向 controller 注入明确 collaborator，不保留 facade compatibility。
- **[bundle digest 大面积漂移]** → skeleton 和每个 slice 稳定后才计算 candidate
  identity；最终 freeze 前不把中间 digest 当作 release evidence。
- **[主 specs 仍包含旧 generation requirement]** → 本 change 的 delta 明确删除
  legacy/compatibility requirement；archive 时由新 change 一次更新主 specs。
- **[用户要求继续使用现有安装]** → 已安装版本不自动替换；新 candidate 完成并经用户
  acceptance 后才更新安装来源。

## Migration Plan

1. 记录当前用户可见 capability、state write、effect 和 safety invariant inventory，
   只作为 reference checklist，不作为新 module layout 或 call graph 模板。
2. 建立 importable skeleton 和四 profile product matrix。
3. 通过新 package 的 `start`、`show`、`preflight` focused test，但不建立到旧
   runtime 的 wrapper 或 dual-dispatch。
4. 按上述 vertical slice 顺序重新实现 capability；每个 slice 都执行 source
   independence audit、focused test、manifest validation 和 `git diff --check`。
5. 所有必需 slice 完成后执行 Atomic Greenfield Cutover，并删除 `dev_flow_parts`
   shared-global loader、
   `_WorkflowRuntimeOperation`/`_WorkflowRuntimeValue` late binding 和不再可达的
   service/adapter。
6. 稳定 bundle、activation、runtime inventory 和 documentation candidate bytes，
   再计算新的 provenance identity。
7. 在 frozen candidate 上运行最小 current-V4 verification 和独立只读 review。
8. 将真实 Codex installation、唯一 enabled plugin、Hook/MCP pickup 以及真实项目
   workflow smoke 留给用户 acceptance；在此前不 archive 新 change。

没有 historical data migration 或 runtime rollback。若新 candidate 在 acceptance
前失败，继续使用当前已安装版本；source worktree 保留未完成 change 供修复。

## Open Questions

没有阻塞 skeleton 的 open question。后续 node rebuild 若发现一个现有安全
invariant 无法放入明确 owner，必须暂停该 slice、更新 design/spec，再继续实施，
不得用 wrapper 或 shared helper 隐藏问题。
