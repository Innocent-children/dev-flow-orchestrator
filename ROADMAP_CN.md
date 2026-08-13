# Dev Flow Orchestrator 路线图

[English](ROADMAP.md)

## 产品方向

Dev Flow Orchestrator 以一个本地 Controller 作为权威，为用户预先准备的一至八个 Git
工作树的精确集合提供可恢复、可验证的开发流程。它是个人使用的 multi-repository
controller：一个任务、一个当前 action 和一个 Codex executor。保障证据的部分复用
仅限当前且可证明互不相交的任务自有切片。自主管理 Git、并行执行、远程运行、外部 CI
和交付自动化均不在产品边界内。

交付采用小步兼容演进。新增复杂度必须回应具体的当前需求；推测性的平台、编排或生态
工作继续延期。

## 0.5.0：MCP 接口迁移

`0.5.0` 版本把主要 Codex integration 迁移到一个本地 STDIO MCP server。`0.6.0`
版本增加正式捆绑的 `dev-flow` Skill。持久化模型与任务数据命名空间仍严格为 `0.4.0`，
因此现有 0.4.x 任务无需状态或字节迁移即可恢复。

稳定产品 surface 继续包含一个有五个读取工具和六个 mutation 工具的 `dev-flow` MCP
server、现有 CLI 和本地只读 Web UI。Skill 提供激活和路由；Controller 保留所有
transition、repository、binding、assurance、review 与 Delivery Dossier 权威。

## 0.6.6 交付：版本化 release artifact

Installed delivery 正从永久保留源码 checkout 转换为精确版本 GitHub Release 资产集：

- 一个闭合的平台中立 archive，其中包含完整 sealed plugin、一个 pure-Python wheel、
  哈希锁定 requirements、生成它所用的 `uv.lock`、版本化 lifecycle helper 和内嵌
  manifest；
- 一个闭合 `release-index.json`，绑定 repository、version、source commit/tree
  publication assertion、archive 与原始 manifest digest；
- 内嵌相同标准库 Phase A verification 的版本匹配 `install.sh` 和 `install.ps1`
  bootstrap；
- 只由一个 active record 选择的 managed release，以及稳定的 `dev-flow`、
  `dev-flow-mcp` 和 `dev-flow-uninstall` dispatcher；
- 一把 installation-wide lifecycle lock、单调 generation 与 digest CAS、有界
  transaction journal，以及仅有 `committed`、`rolled_back` 或 `partial` 的终态；
- exact-version healthy/drift repair、target-version upgrade、激活失败时自动恢复
  immediate previous authority、interrupted recovery、有界 predecessor migration 与
  source-independent uninstall。

Phase A 在 parse 前验证固定 index，并在 artifact code 执行或产品状态修改前验证
archive、portable path、tar header、hard limit、安全 extraction、原始 manifest、完整
inventory 和静态 topology。Phase B 使用随附 wheel 与要求哈希的 wheel-only 依赖，
构建 candidate，并在 provisional plugin/marketplace activation 前完成 staged health。

Lifecycle 保留 `.codex-plugin/plugin.json`、`.mcp.json`、捆绑的
`skills/dev-flow/**`、`dev-flow-mcp --stdio`、Controller model、MCP tools 与 schema、
plugin ID、personal-marketplace mode、task data、无关 Codex state、unknown content
及每个 legacy checkout。

SHA-256 证明与 bootstrap、index 和 manifest 所固定字节一致。它不是独立签名，也不
表示 GitHub release publication 永远不可能被攻破。Source commit 与 tree 值是 release
builder assertion；最终用户安装不会从 checkout 重建 provenance。

## 完成证据

只有全部四个最终资产构建完成，并从其精确官方版本专属地址重新下载，且所有适用仓库
检查均通过后，release-artifact change 才能完成。有界 final-artifact journey 必须在
原生 macOS 和原生 Windows 10 22H2 x64 或 Windows 11 x64 上各运行一次，覆盖 fresh
install、healthy/drift repair、
successful upgrade、failed-activation rollback、interrupted recovery、startup、
predecessor migration、uninstall 与 task-data preservation。

受支持的 Python 3.10–3.14 运行轻量 wheel-only install 与 import/MCP smoke coverage，
不重复完整 lifecycle matrix。并发证据只覆盖 upgrade versus upgrade 和 upgrade versus
uninstall。Release candidate 使用真实 Codex host 验证精确 plugin read-back、bundled
Skill discovery、STDIO MCP startup 与 uninstall。

完整 unittest discovery 是仓库证据的一部分，但不能替代 installed lifecycle evidence。
当前主机 macOS 测试、deterministic fake-Codex integration 和静态 PowerShell 检查不能
证明原生 Windows、真实 Codex 或最终 promotion evidence。在这些 gate 于所需环境真实
运行，并记录 failure、skip、retained path、degradation 与 platform limitation 之前，
其状态保持未验证。Windows Server 不能替代受支持的客户端证据。

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
- commit、push、创建 Pull Request、发布 Release 或触发外部 CI；
- 协调并行 agent 或仓库 executor；
- 暴露通用 shell、原始 Store、任意文件系统或远程 MCP 工具；
- 将 MCP annotation 当作强制机制或自动授予 mutation approval；
- 仅为演进安装或 transport 而改变模型 `0.4.0` 身份；
- 增加独立签名、Sigstore、transparency log、offline fresh install、third-party mirror、
  自动更新 channel 或后台更新；
- 增加公共任意历史 rollback、无限 release retention、通用 Unicode artifact member、
  所有历史 installer 的 migration 或 dispatcher-protocol migration framework。

任何改变这些边界的未来提案，都必须在实施前通过单独的 OpenSpec change 说明具体用户
价值、权威模型、失败恢复、兼容性影响和证据成本。
