# Dev Flow Orchestrator 路线图

[English](ROADMAP.md)

## 产品方向

Dev Flow Orchestrator 以一个本地 Controller 作为权威，为用户预先准备（user-prepared）
的一至八个 Git 工作树的精确集合提供可恢复、可验证的开发流程。它是个人使用的
multi-repository 控制器：一个任务、一个当前动作和一个 Codex executor。保障证据的
部分复用仅限当前且
可证明互不相交的任务自有切片。自主管理 Git、并行执行、远程运行、外部 CI 和交付
自动化均不在当前产品边界内。

交付采用小步兼容演进。新增复杂度必须回应具体的当前需求；推测性的平台、编排或生态
工作继续延期。

## 0.5.0：MCP 接口迁移

`0.5.0` 将主要 Codex 集成从已安装 Skills 和 fail-open Hook 迁移到一个本地 STDIO MCP
服务器。持久化模型与任务数据命名空间仍严格为 `0.4.0`，因此现有 0.4.x 任务无需状态
迁移或字节迁移即可恢复。

### 当前实现

- 一个 `dev-flow` 服务器，以及恰好十一个有类型的 Controller 工具：五个读取工具和
  六个 mutation 工具；
- 有界的发现、存储任务检查、实时当前动作捕获、启动、应用、合同修订、决策、finding
  处置和取消；
- 闭合 schema、紧凑结果、带版本的当前动作 guidance、请求 ID、脱敏、同任务 mutation
  串行化、有界准入和不确定完成恢复；
- 仅承载协议的 stdout、有界 stderr 诊断、首次超限拒绝，以及对畸形 JSON/UTF-8、取消
  和断连的 fail-closed 处理；
- 位于源码和任务数据之外的隔离托管运行时；官方 MCP SDK 限定为 major 2，并使用精确
  解析的 lock 和绑定身份的 receipt；激活分阶段完成，并且只有身份精确匹配时才能复用；
- 使用同一 PATH launcher 的 bundled plugin 模式和显式 standalone 注册，并拒绝重复
  注册；
- 移除当前 Skills、Hooks、Hook bootstrap 和 Hook 专用 launcher；
- macOS 安装、修复、回滚和卸载路径，以及原生 Windows 10 22H2 x64 / Windows 11 x64
  PowerShell 预览路径；
- 继续由同一 Controller 支撑不变的 CLI；首个只读切片已交付为本地只读 Web UI。
  更完整的交互式工作台以及 Web UI 的 mutation 或审批权威仍处于规划中。

### 当前本机证据

当前 macOS source launcher 与 managed launcher 旅程证据通过真实 STDIO 使用官方 MCP
客户端，并保持协议、guidance、Controller 与持久化模型的权威彼此分离。它覆盖：

- 初始化、有界 instructions、恰好十一个工具的 catalog、全部工具映射、闭合输入与输出、
  领域/协议错误、结果限制、请求 ID、脱敏、并发、取消边界、stdout 纯净性、有界 stderr，
  以及不盲目重放 mutation 的断连恢复；
- 面向 preflight、impact、planning、implementation、investigation、documentation、
  rework、assurance/review、finalization、cancellation 和闭合通用 fallback 的有界
  guidance；
- 精确 lock 托管运行时创建、已安装 wheel smoke、receipt 匹配、安全复用、分阶段激活、
  构建/激活失败回滚、重复注册拒绝和 marker 限定范围的卸载保留；
- 所有六种官方 workflow 的源码确认 focused 与 closed-trigger 路径，包括 profile 下限、
  obligation allowance 与 ceiling、not-required 决策、review 规则和终态 Delivery
  Dossier；
- 单成员和精确多成员交付、从非首成员发现、重启/恢复，以及不确定断连恢复；
- 无迁移恢复由 0.4.2 CLI 创建的任务，OpenSpec governing 状态的
  available/stale/unavailable 路径，codebase-memory 保守降级，因果 review、有界
  rework、waiver 与 disposition、
  impact-gap 观察、精确恢复、重新规划与 implementation 重执行、带精确纳入漂移的合同
  修订、损坏 inventory 的准入失败，以及来自不同 linked worktree 的并发准入；
- 在完全隔离的 Codex 0.146.0 profile 中激活并执行幂等 repair、恰好一个已启用的 bundled
  `dev-flow` STDIO 注册、通过默认已安装数据路径发现现有 `0.4.0` 任务，以及经 managed
  PATH launcher 完成完整 workflow 旅程；随后 marker-scoped 卸载移除插件、注册、
  launcher 和 runtime，同时保留源码及字节完全一致的 current/prior-version 任务命名空间；
- 对保障证据部分复用、耗尽以及成功或 incomplete Dossier 终结的聚焦领域回归。

这些 macOS 和 current-host 证据不是原生 Windows 证据；隔离 profile 也不能证明另一个
外部 Codex 安装已启用该服务器。只有严格 OpenSpec 校验、包校验、完整 unittest
discovery、生命周期检查和每个声明的原生平台结果均为当前证据时，版本证据才完整。
Windows Server runner、静态 PowerShell 检查、WSL/Wine 或跳过的测试均不能满足
Windows 10/11 客户端门禁。

## 近期加固

1. 未来每次升级官方 MCP SDK 之前，都应保留有界的受支持 major，审慎更新精确 lock，
   并重新取得协议、托管运行时、已安装旅程、生命周期和包兼容性证据。
2. 在原生主机上为两个 Windows 预览客户端版本完成全新安装、修复、fast-forward 升级、
   构建失败、激活失败、重复注册、任务恢复、已安装 MCP workflow 和安全卸载矩阵。

## 后续产品工作

以下潜在工作将独立评估，并不由当前版本隐含承诺：

- 为 timeline、artifact、approval 和 why-next 解释提供更丰富的只读 cockpit 视图；
- 在验证 executor 行为和审批语义后支持其他本地 MCP host；
- 为 catalog 与 receipt 不匹配提供更好的运维诊断；
- 以原生安装和生命周期证据为基础扩展平台；
- 根据已观察到的任务失败选择性改善 workflow 或 guidance。

## 明确非目标

路线图不授权 Dev Flow：

- 创建、切换、修复或删除用户分支/工作树；
- commit、push、创建 pull request、发布 release 或触发外部 CI；
- 协调并行 agent 或仓库 executor；
- 暴露通用 shell、原始 Store、任意文件系统或远程 MCP 工具；
- 将 MCP annotations 当作强制机制或自动授予 mutation 审批；
- 仅为演进传输接口而改变模型 `0.4.0` 身份。

任何改变这些边界的未来提案，都必须在实施前说明具体用户价值、权威模型、失败恢复、
兼容性影响和证据成本。
