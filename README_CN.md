# Dev Flow Orchestrator

[English](README.md)

Dev Flow Orchestrator 让跨一个至八个用户预先准备的 Git 工作树的长期 Codex
开发任务保持可恢复、上下文有界且可验证。`0.6.12` 版本捆绑名为 `dev-flow` 的正式
Codex Skill 和本地 STDIO MCP 服务器，同时保留持久化 `0.4.0` 模型与任务数据
命名空间。

Skill 负责激活 Codex 并将其路由到 MCP 工作流，它不是另一套工作流协议。
Controller 仍是唯一的状态转换权威。MCP、CLI 和只读 Web UI 都是同一 Controller
之上的适配器。它们不会创建或切换分支/工作树、发布 Git 改动、运行并行执行器，
也不会调度外部 CI、Pull Request 或 Release。

## 快速开始

最终用户安装需要受支持的 64 位 CPython 3.10–3.14、`uv`、支持插件/Skill/MCP 的
Codex、平台 HTTPS 下载工具，以及一个已经位于 `PATH` 上的可写绝对目录。受支持的
Windows 客户端是原生 Windows 10 22H2 x64 与 Windows 11 x64。Git 不是安装前提。
目标仓库仍需提供一至八个现有且由用户预先准备的 Git 工作树根目录，因为它们是产品
所控制的工作对象。

下载并运行首次安装入口，使用 `latest` 或精确的 `MAJOR.MINOR.PATCH`（如
`0.6.12`）：

```sh
(installer="$(mktemp "${TMPDIR:-/tmp}/dev-flow-install.XXXXXX")" && trap 'rm -f "$installer"' 0 HUP INT TERM && curl -fsSL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.sh" -o "$installer" && /bin/sh "$installer" latest)
```

在原生 Windows 上，下载同一入口的 `install.ps1` 资产，并从 PowerShell 5.1 或
PowerShell 7 运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$p=Join-Path ([IO.Path]::GetTempPath()) ("dev-flow-install-"+[guid]::NewGuid().ToString("N")+".ps1"); $status=1; try { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.ps1" -OutFile $p; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p latest; $status=$LASTEXITCODE } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }; exit $status'
```

首次安装入口在下载任何内容之前校验 `MAJOR.MINOR.PATCH` 或 `latest`；当版本无效、
目标 Release 不存在或下载失败时，以非零状态退出且本地安装保持原样。`latest` 只通过
HTTPS 读取规范 GitHub 仓库的官方 release listing，且绝不会选中 draft 或
prerelease。两条路径都会下载并执行所选 Release 的版本匹配 bootstrap，后者固定规范
仓库、版本、制品名称与 `release-index.json` digest。该 bootstrap 从精确的规范地址
`https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v<version>/install-<version>.sh`
下载（Windows 使用对应的 `.ps1` 资产）。在执行任何制品代码或修改任何产品状态之前，
其内嵌的标准库 Phase A verifier 会检查 index、archive、tar member、
内嵌 manifest 的原始字节、完整 inventory、资源限制和所需包拓扑。随后 Phase B 使用
随附的 pure-Python wheel 与哈希锁定、仅 wheel 依赖构建隔离的 managed release，
运行 staged health，并以事务方式激活。它会在密封插件快照中保留 Skill。整个过程
不创建或保留源码 checkout。

已安装的生命周期命令继续从 `PATH` 提供：

```sh
dev-flow update      # 升级到最新正式 Release（幂等）
dev-flow uninstall   # 删除产品自有安装；完整保留所有用户数据
dev-flow reinstall   # 清空 Dev Flow 自有任务数据，然后安装最新版本
```

`update` 与 `reinstall` 由稳定 dispatcher 在解析 active release 之前处理，因此
active release 无法启动时仍然可以运行；它们始终选择最新正式 Release。`reinstall`
只在证明所有权后删除安装证据记录的 Dev Flow 自有任务数据条目（Controller 任务、
历史、状态、证据、锁、Web UI runtime 状态与日志），在安装 commit 之前保留带 digest
验证的备份；失败或中断时只有仍可证明精确回滚才会恢复之前的数据，否则会保留证据
并报告 `partial`。

信任边界、一行安装命令、修复、升级、激活失败自动回滚、迁移、终态、持久路径、数据
边界与源码无关卸载参见 [INSTALL_CN.md](INSTALL_CN.md)。

安装后启动一个新的 Codex 任务，并显式调用 Skill：

```text
$dev-flow 在当前仓库实现这个需求并完成验证。
```

对于需要多步骤处理的实现、缺陷修复、重构、调查、审核和验证工作，Codex 也可隐式
激活它。目标项目无需额外添加 `AGENTS.md` 规则。

Skill 驱动以下由 Controller 掌权的顺序：

1. 使用 `dev_flow_find_tasks_for_path` 或 `dev_flow_list_tasks` 发现任务；
2. 显式选择任务，必要时使用 `dev_flow_start_task` 启动任务；
3. 调用 `dev_flow_get_next_action`；
4. 只在精确仓库集合上执行投影的当前动作；
5. 提交精确动作 ID、闭合 payload 和未经修改的精确 binding；
6. 重复执行，直到任务生成终止 Delivery Dossier。

如果发现多个可能匹配的活动任务，Skill 会让用户选择，而不是按时间擅自决定。如果
mutation 响应状态不确定，它会先读取任务并刷新当前动作，再判断是否能安全重试。

## 已安装 release 模型

每个 release archive 都是平台中立的，包含完整 sealed plugin tree、
`.codex-plugin/plugin.json`、`.mcp.json`、`skills/dev-flow/**`、一个 pure-Python
项目 wheel、`runtime-requirements.txt`、生成它所用的 `uv.lock`、版本化
`lifecycle/**` helper 和 `release-manifest.json`。Manifest inventory 覆盖除自身
以外的所有后代；外部 index 固定 manifest 的原始 UTF-8 字节。

Active record 是本地选择 active release 的唯一权威。它包含单调递增 generation、
release ID、contained 的绝对 managed-release path、receipt digest、dispatcher
protocol 和执行提交的 transaction ID。Runtime receipt 对完整已安装 release 做证明。
产品自有的小型 `dev-flow`、`dev-flow-mcp` 和 `dev-flow-uninstall` dispatcher 在普通
修复、升级与自动回滚期间保持稳定；版本化验证和生命周期代码位于每个 managed
release 内。`dev-flow update` 与 `dev-flow reinstall` 由稳定 dispatcher 在解析
active release 之前识别；它们与首次安装共享相同的版本语法和规范 HTTPS release
下载规则。digest 固定的安装记录记录 runtime root、dispatcher 目录、Codex home、
marketplace 文件、任务数据根目录和 Dev Flow 自有数据路径，之后的每个生命周期命令
都从该证据推导自己的精确路径。

每个 lifecycle operation 都持有同一把 installation-wide lock，并且只会以以下一种
状态结束：

- `committed`：请求的权威已被读回并证明；
- `rolled_back`：candidate 不再具有权威，并且 immediate previous authority（对于
  失败的全新安装则是无权威状态）已恢复并证明；
- `partial`：无法精确证明请求的权威或 previous authority，因此保留不确定内容，并
  停止 identity-specific mutation。

没有面向任意历史版本的公共 rollback 命令。本版本中的 rollback 只是在当前激活事务
尚未终结时，自动恢复 immediate previous authority。

## Codex Skill 与 MCP 接口

插件 manifest 注册 `./skills/`。捆绑 Skill 位于 `skills/dev-flow/`，包含
`SKILL.md`、`agents/openai.yaml` 和
`references/activation-and-routing.md`。它支持显式 `$dev-flow` 调用与依据 description
隐式激活。
它绝不定义 Controller action、payload schema、状态转换、review obligation 或
终止规则；这些内容来自实时 MCP 结果。

捆绑的 `.mcp.json` 只暴露一个名为 `dev-flow` 的本地 STDIO 服务器，调用
`dev-flow-mcp --stdio`。不支持 HTTP、SSE、监听 socket、token 或 OAuth transport。

只读工具：

- `dev_flow_server_info`
- `dev_flow_list_tasks`
- `dev_flow_find_tasks_for_path`
- `dev_flow_get_task`
- `dev_flow_get_next_action`

变更工具：

- `dev_flow_start_task`
- `dev_flow_apply_action`
- `dev_flow_revise_contract`
- `dev_flow_record_decision`
- `dev_flow_dispose_finding`
- `dev_flow_cancel_task`

每个工具都具有闭合输入 schema、结构化成功/错误 envelope、有界结果、请求 ID、闭世界
annotation，并禁用 MCP task augmentation。Annotation 只描述意图，不是授权或操作
系统强制边界。

## Workflow 与任务数据

正式 workflow catalog 为 `lite`、`feature`、`bugfix`、`investigation`、`refactor`
和 `full`。它们继续使用 `dev-flow-workflow/0.4.0`、
`dev-flow-agent/0.4.0`、action binding、record、assurance、review 和 Delivery
Dossier 标识。

任务成员是不可变的规范仓库数组。任务数据位于每个目标仓库之外的模型 `0.4.0`
命名空间，也位于 managed release 与 lifecycle state 之外。实时下一动作捕获覆盖完整
集合，并返回下一次 mutation 所需的精确 binding。从第二成员仓库发现任务会返回同一
任务；多个活动声明造成的歧义会失败关闭。现有 0.4.x 任务无需状态迁移即可恢复。
修复、升级、迁移和卸载都不会删除或修改 Controller task data。只有
`dev-flow reinstall` 会清空 Dev Flow 自有任务数据，而且只在通过记录的 data root
与 marker 证明所有权之后执行，失败时精确回滚。

## CLI 与只读 Web UI

CLI 和本地 Web UI 继续作为同一 Controller 的视图：

```sh
dev-flow --help
dev-flow web start
dev-flow web status
dev-flow web stop
```

Web UI 绑定 `127.0.0.1`，默认读取存储任务视图，没有 mutation authority。MCP 是
Codex 的主要执行接口。

## 信任与证据边界

规范 GitHub 仓库及其 Release 发布权限是 release provenance 的一部分。版本匹配
bootstrap 固定 repository、version、asset 和 index digest；`latest` 路径额外信任
规范仓库的官方 release listing 来指出当前 Release，该 Release 随后接受与固定版本
完全相同的 Phase A、Phase B 校验。SHA-256 证明下载到的字节与 bootstrap、index 和
manifest 所固定的字节一致；它能检测损坏及跨 release 混用。SHA-256 不是独立数字
签名，也不能证明 GitHub 账户从未被攻破。Source commit 与 tree 值是 release builder
验证并记录的 publication assertion，而不是最终用户机器从 checkout 重建的 source
provenance。

此设计不声称能抵御可一致替换同一用户全部本地 trust input 的攻击者。它不增加签名、
Sigstore、transparency log、third-party mirror、offline fresh install、更新 channel 或
后台更新。

原生 Windows final-artifact 证据、对真实 Codex host 的 release-candidate 证据，以及
最终 promotion/re-download 证据都必须在对应的真实环境中取得。macOS 测试、
deterministic fake 和静态 PowerShell 检查都不能证明这些结果。在取得记录之前，这些
门禁必须报告为未验证，不能靠推断得出。

## 开发

使用项目环境及仓库检查：

```sh
uv sync --locked
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python scripts/validate_package.py
openspec validate install-versioned-release-artifact --strict
```

参见 [CONTRIBUTING_CN.md](CONTRIBUTING_CN.md)、
[ARCHITECTURE_CN.md](ARCHITECTURE_CN.md) 和 [ROADMAP_CN.md](ROADMAP_CN.md)。

## 许可证

Apache-2.0。参见 [LICENSE](LICENSE)。
