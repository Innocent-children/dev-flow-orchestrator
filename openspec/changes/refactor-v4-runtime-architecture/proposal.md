## Why

当前 package 已经收敛为 V4-only product，但内部 runtime 仍由约 11 万行有序
source fragment 通过共享 `globals()` 组成；产品维度也把 `full`/`lite` workflow
深度、single/multi-repository 拓扑和 workspace strategy 错误绑定。这使严格的
registry、digest 和 validation 能够一致地证明一个难以维护、并遗漏
`lite@4` multi-repository 的设计。

本次变更把现有实现仅作为功能与安全经验的参考，在同一个 plugin identity 下按
greenfield project 重新建立产品和 architecture。先交付一条可运行的最小 vertical
slice，再按真实产品需要逐节点重新实现能力。最终 architecture 可以庞大，但每个
节点的输入、输出、authority、state write、effect、失败和恢复边界必须清楚。

## What Changes

- **BREAKING** 将 activation model 改为四个正交 profile：
  `full@4`/`single-repository`、`full@4`/`multi-repository`、
  `lite@4`/`single-repository`、`lite@4`/`multi-repository`。
- **BREAKING** repository 数量不再强制选择 `full`；workflow 深度、repository
  topology 和 workspace strategy 分别选择并进行显式组合验证。
- 建立真正可 import 的 standard-library Python package。`scripts/dev_flow.py`、
  MCP 和 Hook 只保留薄 entrypoint，不再通过 ordered `exec(..., globals())`
  拼装 runtime，也不再通过共享 namespace 字符串查找 operation。
- 新 package 不 import、调用、包装或继承 `scripts/dev_flow_parts/`。现有代码只用于
  提取用户可见 capability、安全 invariant 和已知 failure mode，不作为新 module、
  class、function 或 protocol layout 的模板。
- 先实现最小 vertical slice：profile selection、task creation、task inspection、
  preflight、单一 transition/mutation boundary 和 filesystem state store；该骨架可
  独立启动、验证和理解后，才逐节点重新实现其余 workflow capability。
- 为每个重新实现的节点定义统一 node contract：typed input/output、所需 authority、
  allowed state writes、effect port、idempotency、failure 和 recovery。一个节点
  完成并通过 focused test 后，才把它加入新 product；不保留指向旧 fragment 的
  wrapper。
- 将 profile、suite 和 capability matrix 收敛到一个 package-owned source of
  truth；activation、runtime、registry、validation 和 documentation 从该定义派生
  或对其验证。
- 将 mutation authority 收敛为一个 application boundary；domain policy 保持纯净，
  filesystem、Git、process、Codex host 和 MCP 均通过显式 port 进入。
- **BREAKING** 不保证旧内部 Python symbol、shared-global monkeypatch path、内部
  response shape 或开发者测试 fixture 的兼容；只重新实现经过新 specs 确认的用户
  capability。
- 保留当前 V4 task schema 和必要的独立版本化通用 protocol，但删除仅为旧加载布局、
  facade monkeypatch 或重复 validation 存在的 abstraction。
- 保持 macOS-only、standard-library-only、state-outside-repository、显式 Git
  authority 和无 historical data 的产品边界；不添加 legacy detection、migration、
  fallback 或 compatibility layer。
- verification 只覆盖当前 greenfield vertical slice 和精确受影响节点；禁止 full suite，
  不对 Windows/Linux 作验证或支持推断。

## Capabilities

### New Capabilities

- `runtime-architecture`: 定义最小可运行骨架、显式 module dependency、node contract、
  mutation boundary、port 以及逐节点 greenfield rebuild 和 cutover 规则。
- `workflow-product-model`: 定义 workflow 深度、repository topology、workspace
  strategy 三个正交维度及四个 V4 activation profile。

### Modified Capabilities

- `versioned-workflow-bundles`: 以唯一 product matrix 派生四个 V4 profile、suite
  activation 和 bundle closure。
- `multi-repository-orchestration`: 让 lite 和 full 共用最小 repository
  orchestration kernel，并按 workflow 深度增加不同 gate，而不是把多仓库等同于
  full。
- `pluggable-workflow-execution`: 使用直接 V4 node implementation、单一 mutation
  boundary 和显式 effect port，移除 shared-global fragment runtime。
- `codex-runtime-adapters`: CLI、MCP、Hook 和 Skill 使用薄 entrypoint 调用相同
  application API，不拥有 workflow policy 或兼容性分支。
- `compact-agent-protocol`: 仅描述当前 V4 response 和 node contract，不保留 legacy
  response path。
- `cross-platform-git-evidence`: 保留当前 macOS host 所需的精确 Git evidence，不
  宣称或验证 Windows/Linux parity。
- `cross-platform-plugin-invocation`: package 只提供并验证当前 macOS launch profile。
- `cross-platform-runtime-safety`: runtime skeleton 使用明确的 macOS
  filesystem/lock/process port，并保持 fail-closed mutation 和 fail-open Hook。
- `cross-platform-verification`: 使用 skeleton-first、逐节点 focused verification，
  并明确排除 full suite、historical data 和 Windows/Linux validation。

## Impact

- 新增独立的 `src/dev_flow_orchestrator/` greenfield runtime，并影响
  `scripts/dev_flow.py`、`scripts/dev_flow_mcp.py`、`hooks/`、`workflows/`、
  focused V4 tests、README/INSTALL 以及 package validator。
- 现有 launch command 和 plugin identity 原地保留；入口切换前，新 runtime 不与旧
  runtime dual-dispatch。
- workflow 与 repository profile selection 是有意的行为变更；现有错误的三 profile
  activation 和 `LITE_REQUIRES_FULL` cross-repository policy 将被移除。
- runtime candidate byte、bundle identity 和 provenance evidence 将随逐节点 rebuild 重新
  计算；旧 change 的 evidence 只保留在 archive 中，不作为新 architecture 的证明。
- 新 runtime 达到 cutover gate 后一次切换 package entrypoint，并删除
  `scripts/dev_flow_parts/`；旧实现不会作为 compatibility layer 随 package 保留。
- 不新增第三方 runtime dependency，不读取或迁移 historical task data，不自动执行
  stash、reset、clean、commit、push、rebase 或 merge。
