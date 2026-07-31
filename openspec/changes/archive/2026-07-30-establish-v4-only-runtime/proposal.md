## Why

当前，这个 plugin 在同一个 distribution 中携带了三个 workflow 代际：旧版 V2
adapter、预留的 V3 bundle 与 recovery 行为，以及当前启用的 V4 后继版本。继续让
这些历史版本保持可执行，会迫使新的 V4 工作保留过时的 package 字节、schema、alias、
fallback 分支、fixture 和 release-ledger 规则。对于本产品线已不再打算支持的 data
而言，这项成本如今已经超过 compatibility 本身的价值。

本变更有意开启一条破坏性的 V4-only 产品线。已纳入 package 且可执行的 workflow
将仅为 `full@4` 和 `lite@4`。本次变更所针对的 deployment 中不存在历史 runtime
data，因此历史 data 的检测、拒绝、迁移、检查、recovery、回滚和测试均不在范围内。
Git 历史和已归档的 OpenSpec change 足以作为开发记录；它们不会产生任何 runtime
compatibility 义务。

当前 implementation 将呈现为 V4 就是产品起点：workflow generation、持久化 task
schema、workflow-specific runtime contract、handler/reducer 名称、source layout、
测试和 documentation 均使用 V4 identity。对于独立版本化的通用 protocol，如果
`/v1` 或更高 contract version 描述的是 protocol 本身，而不是更早的 workflow
generation，则可以（MAY）保留这些 version。

## What Changes

- **BREAKING**: 仅 package、catalog、activate、create 和 execute `full@4` 与
  `lite@4`。删除 V2 和 V3 workflow bundle，以及所有唯一目的只是保留这些 workflow
  generation 的 runtime path。
- **BREAKING**: 保留现有的唯一 plugin identity，将其 product version 提升到 major
  V4，并原位替换先前的 package。不得创建可与其共存的第二个 installable plugin。
- **BREAKING**: 将 task schema v4 定义为唯一的 persistence schema，并让所有新
  state 使用已安装 V4 bundle 的精确 path。删除 importer、schema selector、
  compatibility adapter、predecessor workflow fallback、legacy response branch
  以及历史 inspection/recovery code，且不以新的 rejection layer 替代它们。
- 将 V4 availability 设为 startup 和 creation invariant。V4 asset 缺失、无效或
  inactive 时必须 fail closed，而不是 fallback 到旧版 workflow。
- 以 V4-only provenance genesis 替换历史上的多代际 package ledger，
  并覆盖精确保留的 V4 inventory。已归档的 OpenSpec artifact 与 Git history 在
  runtime package 之外保存开发历史。V4 major line 明确记录 provenance
  discontinuity，而无需前代 executable byte。
- 以 V4 workflow-specific identity，重建 `full@4` 和 `lite@4` 所需的精确
  transitive runtime closure。
  重命名或替换仍在使用的 `workflow_v3_*`、`reducer.v3-*`、`dev-flow-v3-*` 及等价的
  generation-bound symbol，而不是保留 compatibility wrapper。独立版本化的通用
  protocol 仅在其语义变化时才予以更改。
- 删除过时的 compatibility test、fixture、documentation、Skill instruction、
  package-validator expectation 和 release tooling。不得用枚举不受支持历史 format
  的 matrix 取代它们。
- automated verification 仅限于当前 V4 package identity、catalog、startup、
  `full@4`/`lite@4` minimum smoke behavior，以及受本次裁剪直接影响的 validator。
  真实 Codex installation、Hook/MCP pickup 和一次真实项目 workflow smoke 留给
  user acceptance。
- 保持 runtime 仅使用 standard library。首个纯净 V4 release 仅支持 macOS；
  Windows 和 Linux support 及 native validation 需要后续另行限定范围的 change。

## Capabilities

### New Capabilities

无。V4-only boundary 替换的是现有 capability 已经负责的行为。

### Modified Capabilities

- `versioned-workflow-bundles`: 将 package 和 catalog 缩减为两个 V4 bundle，建立
  V4-only distribution 与 provenance identity，要求精确固定到当前 V4，并移除历史
  support。
- `pluggable-workflow-execution`: 移除旧版 adapter、V3 workflow
  quarantine/recovery execution 及 compatibility dispatch，并使用 schema-v4 和
  V4 contract identity 重建当前 execution/recovery core。
- `compact-agent-protocol`: 移除历史 projection 和 compatibility response shape，
  使该 protocol 仅描述当前 V4 task。
- `codex-runtime-adapters`: 让 CLI、MCP、Hook、Skill 及可选 executor adapter
  仅支持 V4，不包含旧版 command grammar、schema selector、workflow fallback
  或旧版 task context。当前 MCP-to-CLI transport degradation 仍作为 V4
  operational path 保留。
- `multi-repository-orchestration`: 从 repository scheduling state 中移除
  schema-v1/schema-v2 alias 及 compatibility branch。
- `cross-platform-git-evidence`: 停止重新生成或解释旧版 schema-v1 Git
  evidence，并将 filesystem/Git evidence obligation 缩小到受支持的 macOS V4 host。
- `cross-platform-runtime-safety`: 移除 schema-v1 readability exception、
  Windows/Linux runtime contract 及其平台专用 branch，且不引入历史存储 admission
  layer。
- `cross-platform-plugin-invocation`: 将 POSIX/macOS launch 和 package discovery
  保留为受支持的 V4 host contract，并从本 release 中移除 Windows/Linux
  documentation claim。
- `cross-platform-verification`: 用聚焦于当前 V4 的 macOS verification，替换已归档
  的 full-suite release gate 和 Windows/Linux release gate，同时保留必需的
  Skill、manifest、package、runtime-import 和 OpenSpec validator。

## Impact

- Runtime code：task loading、workflow selection、catalog construction、
  transition dispatch、recovery、projection、Hook、outbox handling、
  multi-repository scheduling 和 startup validation。
- Packaged asset：V2/V3 bundle、旧版 adapter、历史 release ledger、
  compatibility fixture、package inventory、activation data 和 validator。
- Interface：command、projection、Hook 和 adapter 仅暴露当前 V4 语义。不提供历史
  input behavior contract。
- Persistent data：deployment 从 V4 state 开始，因此本变更不添加 data migration、
  root marker、旧版 root detection 或 rollback machinery。
- Documentation 和 test：移除面向 user 的 compatibility claim，醒目标明这一
  destructive boundary；automated test 仅覆盖精确保留的 inventory 和当前 V4
  行为。user 负责执行本地 automation 无法如实模拟的小型 real-host
  acceptance checklist。
- Release posture：这是一次有意为之的 breaking release，在 implementation 前需要
  独立 plan review。full test-suite execution 和非 macOS support claim
  仍不在本次 V4 release scope 内。
