# 安装 Dev Flow Orchestrator

[English](INSTALL.md)

本指南说明 `0.6.9` 版本的 release artifact 生命周期。它无需克隆或保留本仓库，
即可把正式 `dev-flow` Codex Skill 作为 bundled plugin 安装，并安装本地 STDIO MCP
服务器。持久化 Controller 模型和任务数据命名空间继续为 `0.4.0`。

## 1. 支持的安装与注册模式

Bundled personal-marketplace plugin/Skill/MCP 安装是唯一受支持的注册模式。
`.codex-plugin/plugin.json` 注册 Skill tree，`.mcp.json` 注册一个调用
`dev-flow-mcp --stdio` 的本地 `dev-flow` server。安装器不会采用或配置 standalone
MCP registration。无关或独立管理的 registration 仍归 operator 所有并予以保留。

Standalone provisioning 不受支持。

## 2. 要求

macOS 安装需要：

- 受支持的 macOS 主机；
- 64 位 CPython 3.10、3.11、3.12、3.13 或 3.14；
- `uv`；
- 支持 plugin、Skill 和 MCP server 的 Codex；
- 支持 HTTPS 的 `curl`；
- 一个已在 `PATH` 上且可写的绝对目录。

原生 Windows 安装需要 Windows 10 22H2 x64 或 Windows 11 x64、64 位 CPython
3.10–3.14、`uv`、Codex、PowerShell 5.1 或 PowerShell 7、`Invoke-WebRequest`，
以及一个已在 `PATH` 上且可写的绝对目录。Windows Server 与 POSIX 兼容层不在
受支持的客户端范围内。

Git、仓库克隆和 `.git` 不是最终用户前置条件。Release 生产使用精确的 clean Git
tag，但没有任何 checkout 会成为已安装 authority。用户选择的安装根目录可以包含
空格、撇号和 Unicode。

## 3. 一行首次安装

首次安装入口只接受一个版本参数：

- `MAJOR.MINOR.PATCH` 安装该精确的正式 Release；或
- `latest` 在执行时动态选择规范 GitHub 仓库的最新正式（非 draft、非
  prerelease）Release。

在 macOS 上：

```sh
(installer="$(mktemp "${TMPDIR:-/tmp}/dev-flow-install.XXXXXX")" && trap 'rm -f "$installer"' 0 HUP INT TERM && curl -fsSL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.sh" -o "$installer" && /bin/sh "$installer" latest)
```

要固定精确版本，把 `latest` 换成版本号即可：

```sh
(installer="$(mktemp "${TMPDIR:-/tmp}/dev-flow-install.XXXXXX")" && trap 'rm -f "$installer"' 0 HUP INT TERM && curl -fsSL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.sh" -o "$installer" && /bin/sh "$installer" 0.6.9)
```

在原生 Windows 上：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$p=Join-Path ([IO.Path]::GetTempPath()) ("dev-flow-install-"+[guid]::NewGuid().ToString("N")+".ps1"); $status=1; try { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.ps1" -OutFile $p; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p latest; $status=$LASTEXITCODE } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }; exit $status'
```

把 `latest` 换成 `0.6.9`（或其他已发布的 `MAJOR.MINOR.PATCH`）即可固定精确版本。

入口在下载任何内容之前就拒绝其他任何版本语法，包括前缀、区间、空白和预发布
后缀。对于 `latest`，它只通过 HTTPS 读取规范 GitHub 仓库的官方 Release 列表，
并要求一个 `vMAJOR.MINOR.PATCH` tag，且该 Release 必须同时携带两个版本化
bootstrap 资产；draft 和 prerelease 永远不会被选中。随后它从精确的
`https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v<version>/`
HTTPS 地址下载该 Release 的版本匹配 bootstrap（`install-<version>.sh` /
`install-<version>.ps1`）并执行，因此精确路径与动态路径最终进入同一个版本化
Phase A、Phase B 校验。在版本化 bootstrap 完成下载与
校验之前，不会修改任何产品状态：版本格式无效、目标 Release 不存在或下载失败时，
会以非零状态退出且本地安装保持原样。只使用规范仓库、其 Release API 与 GitHub
官方 HTTPS release 交付主机；镜像与任意下载 URL 一律拒绝。

版本匹配 bootstrap 固定规范仓库、版本、归档名与 `release-index.json` digest，
并内嵌下文所述的纯标准库 Phase A 校验器。透传选项保持在封闭的 Phase B 目标集合
（`--runtime-root`、`--bin-dir`、`--marketplace-file`、`--codex-home`、
`--data-root`、`--lock-timeout`）内。也支持从某版本专属 release 地址下载
`install.sh`/`install.ps1` 并以完全相同的版本运行，但上面的一行入口才是文档化
的使用方式。

## 4. Release 资产与 Phase A 校验

每个 `MAJOR.MINOR.PATCH` Release 发布以下一组身份匹配的资产：

- `dev-flow-orchestrator-<version>.tar.gz`；
- `release-index.json`；
- `install.sh` 与 `install.ps1`（版本无关的首次安装入口）；
- `install-<version>.sh` 与 `install-<version>.ps1`（版本匹配 bootstrap）。

平台中立的归档包含一个顶层目录，其中有完整的 sealed `plugin/**` tree、恰好一个
`dev_flow_orchestrator-<version>-py3-none-any.whl`、`runtime-requirements.txt`、
生成它所用的 `uv.lock`、版本化 `lifecycle/**` 辅助文件以及
`release-manifest.json`。插件树包含 `.codex-plugin/plugin.json`、`.mcp.json`、
`skills/dev-flow/**`、插件侧 CLI 资产和 installed-validation 资产。manifest 逐项
盘点除自身外的每个后代；`release-index.json` 固定 manifest 的原始 UTF-8 字节。

两个版本匹配 bootstrap 内嵌字节一致的纯标准库 Phase A 校验代码。在执行任何
artifact helper、artifact import、artifact 子进程、依赖安装、candidate 构建或
产品状态修改之前，Phase A 会：

1. 在固定硬上限内下载 index，并在 JSON 解析前校验 bootstrap 内嵌的 digest；
2. 解析严格封闭 schema，检查规范仓库、精确版本、归档名、schema 与边界；
3. 流式计量下载归档，并在解压前校验其精确大小与 SHA-256；
4. 在写入任何成员之前检查每个 tar header、成员类型、路径、大小写冲突键、声明
   模式与固定资源上限；
5. 只解压到新的空安装器 staging 目录，不跟随 link 或 reparse 祖先；
6. 校验原始内嵌 manifest digest 及其封闭 schema；
7. 将完整解压 inventory 与 manifest 逐一比对；
8. 在不导入或执行 artifact 代码的情况下检查所需的 plugin、wheel、lock、
   requirements 与 lifecycle 拓扑。

Artifact 成员名使用 `/` 与封闭的可移植 ASCII 语法。绝对或带盘符路径、`.`、`..`、
反斜杠、冒号、控制字符、末尾点或空格、ASCII 大小写冲突、Windows 设备名、link、
sparse 文件、设备、FIFO、不受支持的 tar 扩展、未声明成员、缺失成员以及固定硬上限
违规都会被拒绝。

只有 Phase A 成功才能进入 Phase B。临时获取与解压路径永远不会成为 marketplace、
active、receipt 或回滚 authority。已处理的结局要么精确删除事务拥有的 staging，
要么报告精确的保留路径。

调用方输入只能通过封闭目标选项集合 `--runtime-root`、`--bin-dir`、
`--marketplace-file`、`--codex-home`、`--data-root`、`--lock-timeout` 进入该边界。
`--option value` 与 `--option=value` 都保留包含空格、撇号和 Unicode 的原生路径。
缩写、重复、位置参数以及 release/artifact 身份选项一律拒绝。Phase B 从自身版本化
lifecycle 位置推导 artifact root，并在 candidate 构建前复查完整 live inventory；
candidate 构建在复制、安装 wheel 或执行其他 helper 之前还会再检查一次。

## 5. 信任边界

用户选择的 bootstrap 字节、规范 GitHub 仓库及其 Release 发布权限、HTTPS/TLS 与
GitHub 交付、`latest` 所使用的规范仓库 Release 列表、受支持的系统 Python、平台
下载器、`uv`、Codex 以及本地账户和文件系统权限共同构成初始信任边界。

版本匹配 bootstrap 固定仓库、版本、归档名、index digest 与 bootstrap schema。
SHA-256 证明获取与解压字节和 bootstrap、index、manifest 固定的字节一致，可检测
损坏、部分替换与跨 Release 混用。动态 `latest` 路径额外信任规范仓库的官方
Release 列表来指出当前 Release；被指出的 Release 随后接受与精确版本完全相同的
固定 Phase A、Phase B 校验。SHA-256 不是独立的数字签名，也不能绝对证明发布
真实性。它不能证明 GitHub 账户从未被入侵，也不能抵御能连贯替换某用户全部
bootstrap、active record、dispatcher、verifier 与 managed runtime 的攻击者。
source commit 和 tree 值是 release builder 检查并记录的发布断言；最终用户安装器
不会从 checkout 重建它们。

本 Release 不添加签名、Sigstore、透明日志验证、第三方镜像或离线全新安装。

## 6. Phase B、managed release 与持久 authority

Phase B 语义校验软件包，创建事务拥有的 candidate，安装 hash 锁定的
wheel-only 依赖与随附的纯 Python 项目 wheel（不运行 sdist 构建后端），并执行
candidate 专属的包、Skill、MCP、receipt 与 runtime 健康检查。candidate 健康检查
不读取公共 active record。

默认 managed-runtime 根目录：

- macOS：`~/.local/share/dev-flow-orchestrator/runtime`
- Windows：`%LOCALAPPDATA%\dev-flow-orchestrator\runtime`

在所选绝对 runtime root 内：

- `releases/<release-id>/` 保存每个 managed release；
- `active.json` 是 active release 的唯一本地选择器；
- `transactions/` 保存有界持久 lifecycle journal；
- `lifecycle/` 保存稳定安装支持文件，包括 update/reinstall 命令驱动与共享
  release resolver；
- `reinstall-command-guard/lifecycle.lock` 在子 bootstrap 使用安装锁期间串行化父级
  reinstall driver；
- `lifecycle.lock` 是安装级锁。

精确 `release-id` 包含版本与已验证的 release 身份；不要手工构造或选择它。managed
release 包含隔离环境、sealed plugin、runtime receipt、完整 installed-content
verifier 与版本化 lifecycle 入口。receipt 绑定 index、archive、manifest、source
断言、wheel、requirements、lock、发行版、Python、plugin、verifier、helper、
owned-file、release 路径与事务身份。

`active.json` 刻意更小。其封闭 schema 只包含单调 generation、release ID、受包含
的绝对 release 路径、receipt digest、dispatcher 协议与提交事务 ID。launcher、
marketplace 数据、receipt 与 helper 不会与它竞争 active 选择器地位。

`lifecycle/installation.json` 中的封闭安装记录是每个生命周期命令执行前都要验证的
digest 固定证据。它记录实际使用的 runtime root、dispatcher 目录、Codex home、
personal marketplace 文件、Controller 任务数据根目录、该根目录下 Dev Flow 自有的
数据条目名称，以及所有稳定生命周期支持文件的 digest。升级、卸载与重装都从这份
证据推导精确路径，因此安装时选择的自定义 data root 会被之后的每个生命周期命令
遵守。只有记录、稳定支持文件与 dispatcher 均匹配固定身份的冻结紧邻前代，才允许
一次性迁移到这份扩展证据 schema；出现漂移或更旧布局时会保留原状。

产品在所选可写 `PATH` 目录中拥有三个小型稳定 dispatcher：

- `dev-flow`
- `dev-flow-mcp`
- `dev-flow-uninstall`

在 Windows 上这些命令安装为 `dev-flow.cmd`、`dev-flow-mcp.cmd` 与
`dev-flow-uninstall.cmd`。

普通 repair、upgrade 与自动回滚复用它们的字节。CLI 与 MCP dispatcher 在调用
active verifier 之前最小化校验 active-record、受包含路径、receipt、协议、Python
与版本化 verifier 证据。verifier 在导入项目代码之前证明完整 installed identity。
personal marketplace 只指向 active managed release 的精确 plugin root。

Controller 任务数据继续保存在 Codex plugin data root 下的 `0.4.0` 命名空间中，
位于 managed releases、lifecycle state 与所有权删除范围之外。

## 7. 激活、锁与终局

全新安装、repair、upgrade、reinstall、迁移、恢复与卸载在 authority 读取和修改时共享
一个安装级生命周期锁。Reinstall 在子 bootstrap 获取同一把锁时释放它；pending journal
阻止无关操作，独立 operation guard 排除第二个 reinstall driver，而且只有携带精确匹配
transaction 授权的子进程可以继续。每个操作创建或恢复一个有界 journal。active 的
创建、替换、恢复与删除使用期望
generation 加 active-record-digest 的 compare-and-swap；generation 单调递增。

candidate 激活顺序：

1. 完成 candidate 专属 staged health；
2. 写入并读回 marketplace 与 Codex plugin；
3. 通过 generation CAS 提交目标 active record；
4. 通过真实公共 `dev-flow` 与 `dev-flow-mcp --stdio` 路径证明启动；
5. 记录终局事务结果。

每个生命周期结果都是以下之一：

- `committed`：请求的 release 或卸载状态是权威的，且其必需读回已成功；
- `rolled_back`：candidate 不是权威，且紧邻的前一 authority（或全新安装失败时
  的“不存在”）已被恢复并证明；
- `partial`：无法精确证明请求的或前一 authority；停止进一步身份特定修改，保留
  不确定内容，journal 记录观察、路径与有界恢复指引。

任何命令都不会带着进行中的 journal、不一致的 plugin/marketplace 状态或未分类的
provisional effect 报告成功。

## 8. 更新、修复与恢复

`dev-flow update` 把当前安装升级到最新正式 Release：

```sh
dev-flow update
```

该命令由稳定 dispatcher 在解析 active release 之前识别，因此 active release 无法
启动时仍然可以执行。它使用与首次安装相同的共享版本解析与规范下载规则解析最新
正式 Release，然后以安装证据中记录的精确路径运行该 Release 的版本化 bootstrap。
现有的 lifecycle lock、事务 journal、制品校验、staged health、active CAS、公共
启动证明与回滚机制负责升级，包括 receipt 身份仍可证明时重建损坏的 active
release。即使 active release 已经是最新版本，Phase B 仍会重新执行 runtime、installed-
content、public startup 与 stable infrastructure 的完整证明。健康 release 会被复用，
不会重建或替换；不存在只校验 receipt 就成功的捷径。解析失败、Release 不存在或
下载失败会在任何产品状态
变化之前以非零状态退出；无法恢复的安装被报告为 `partial`，绝不会被报告为成功。

对同一版本发生漂移的安装做修复复用同一机制：用已安装版本运行首次安装入口
（第 3 节）。健康的 release 只有在完整启动、receipt、ownership 与
installed-content 证明通过之后才会被复用。任何漂移都会从重新获取并重新校验的
同版本制品构建新 candidate。如果该版本的远程 index、archive 或 manifest digest
与 active receipt 不同，修复会以 same-version identity-change 错误失败。

回滚是自动的，并且只在未定 activation 事务期间限于紧邻的前一 authority。active
commit 之前的失败恢复先前外部状态；commit 之后的失败通过 CAS 恢复紧邻的前一
generation、恢复外部状态并重新验证前一公共启动路径。它不需要网络、Git 或
checkout。没有任意历史回滚的公共命令，也没有无界保留策略。

在新的生命周期修改之前，命令会恢复或分类任何非终局事务。它不会无限重试。如果
authority 仍然模糊，事务变为 `partial` 并拒绝新的修改。

## 9. 有界前置版本迁移

自动迁移只识别由冻结前置 fixture 代表的、紧邻之前的合规 checkout 安装器。分类只
依据已安装 plugin 观察、launcher marker、receipt、ownership、marketplace 与事务
状态。更旧、未来、畸形或模糊的布局在身份特定修改之前停止。

迁移从不读取、导入、执行、fetch、pull、reset、clean、接管或删除前置 checkout。
checkout 永远不是回滚输入，成功迁移后仍归用户所有。如果已安装观察无法证明恰好
一个前置 authority，请保留它们并遵循报告的恢复指引。支持更广泛的历史 schema 需要
单独的 OpenSpec change。

legacy source checkout 在迁移过程中始终保持原样并予以保留。

## 10. 验证激活

确认稳定命令能从 `PATH` 解析：

```sh
command -v dev-flow
command -v dev-flow-mcp
command -v dev-flow-uninstall
dev-flow --help
dev-flow web start
dev-flow web status
dev-flow web stop
```

在 Codex 中读回已启用的 personal-marketplace plugin，并确认其路径是 active managed
release 内的精确 plugin root。确认存在一个名为 `dev-flow` 的 Skill 和一个名为
`dev-flow` 的 MCP server。新建 Codex 任务，调用 `$dev-flow`，并让 Codex 调用
`dev_flow_server_info`。

plugin manifest 注册 `./skills/` 与根 `.mcp.json`。sealed plugin 保留精确的
`skills/dev-flow/` 目录树，包括 `implicit_invocation: true` 元数据。
installed-stage validator 在激活前记录成对的 Skill 与 STDIO MCP 证据。Skill 把命令路由到
Controller，Skill 本身不能授权 mutation。

`dev-flow-mcp --stdio` 是长驻协议进程。只通过 MCP client 或 inspector 运行它，
不要作为交互式 shell 命令运行。不支持的 transport 参数必须失败且不打开监听
socket。

## 11. 与源代码无关的卸载

从任意目录运行稳定 dispatcher；不要从 checkout 调用 `uninstall.sh` 或
`uninstall.ps1`：

```sh
dev-flow-uninstall
```

该命令既不需要网络也不需要仓库 checkout。它校验稳定安装证据，在 managed runtime
之外复制并校验一个极小的纯标准库删除驱动，获取同一生命周期锁，并创建或恢复持久
uninstall 事务。它在解析 active release 之前被调度，因此 active release 无法启动
时仍然可以运行；无法证明的内容会被保留并报告，而不是被删除。

卸载只按依赖顺序 compare-and-remove 精确的产品自有 plugin 状态、Dev Flow
personal-marketplace 成员、managed-release 条目、active record、稳定 dispatcher
与 lifecycle 支持。uninstall dispatcher 与 lifecycle 支持最后删除，锁释放后不再
有任何产品修改。被中断的运行可以在 runtime 已被删除后恢复或分类其 journal。

卸载完整保留所有 Dev Flow 用户数据：Controller 任务与历史、状态、证据、锁文件、
Web UI runtime 状态与日志，以及 data-root ownership marker 都原样保留。被修改、
未知、并发、link、reparse、特殊或无法证明的内容会按精确路径保留并报告。卸载还
保留无关 marketplace 与 plugin 条目、无关 launcher、standalone MCP registration
和每个 legacy checkout。它绝不会为了强行完成而扩大为递归删除。

## 12. 带全量数据重置的重装

`dev-flow reinstall` 清空全部 Dev Flow 自有用户数据并安装最新正式 Release：

```sh
dev-flow reinstall
```

与 `update` 一样，它在 active release 解析之前被调度，始终以最新正式 Release 为
目标，并使用相同的规范解析与下载规则。它使用安装级生命周期锁和一个持久的
`reinstall` 事务。

清理严格限定于 digest 固定安装证据所记录的 task-data root，并且只针对其中可证明
属于 Dev Flow 的条目：Controller `0.4.0` 命名空间（任务、历史、状态、证据与锁
文件）、`web-runtime` 目录（状态与日志）以及 data-root ownership marker。数据根
目录首先必须被证明只包含这些自有顶层条目，没有 link、reparse point、特殊文件、
无界 inventory 或未知内容；只要出现任何其他内容，就完整保留数据根目录并报告
`partial`。被证明的数据移动到带有 digest inventory manifest 的事务备份中，目标
Release 通过其版本化 bootstrap 安装。只有 committed 安装报告的 active 身份仍与锁
保护下的 active authority 一致，才会精确删除备份。安装失败或中断时，只要仍能证明
精确回滚，就会校验并恢复之前的数据字节；恢复、清理或 active 身份证明不完整时以
`partial` 结束，报告精确保留路径并以非零状态退出。被中断的重装从自身 journal
继续，而不是开始第二次删除；并发的第二个 reinstall driver 也不能接管该 journal。

用户仓库、工作树、Git 数据、源代码 checkout、无关插件数据和其他任何用户文件都
不在重装删除范围内。重装前请停止 Dev Flow 进程（例如 `dev-flow web stop`），
避免数据移动被占用；被占用或无法证明的移动会安全失败并报告保留内容。

## 13. 故障排查与证据边界

- `DEV_FLOW_SOURCE_ROOT is not supported`：取消该变量并运行官方安装入口，而不是
  checkout 脚本。
- 首次安装的版本、解析或下载错误：停止。产品状态没有被修改；传入已发布的
  `MAJOR.MINOR.PATCH` 或 `latest`。
- Phase A digest、inventory、路径、tar 或资源上限错误：停止；不要执行已解压的
  helper，也不要采用 staging。从规范 Release 页面重新下载 release bootstrap 与
  资产集。
- startup attestation 失败：运行 `dev-flow update`，或用已安装版本重新运行首次
  安装入口；不要替换不同 same-version digest envelope。
- lifecycle lock 或非终局事务：让命令执行有界恢复。如果它报告 `partial`，保留
  列出的路径与观察，并在下一次生命周期修改前遵循精确的恢复指引。
- standalone registration 冲突：把它当作 operator 自有状态检查；bundled
  lifecycle 不会静默接管或删除它。
- 不支持的 MCP transport：使用本地 `--stdio` registration。

原生 Windows 最终制品验证必须在原生 Windows x64 上运行。静态 PowerShell 分析、
模拟 adapter、macOS、WSL 或 Wine 都不是原生 Windows 证据。Release candidate 的
plugin 读回、bundled Skill 发现、STDIO MCP 启动、卸载、更新与重装都必须使用真实
Codex 主机。Promotion 证据需要发布全部六个最终资产并从其精确官方版本专属地址
重新下载的权限。当这些环境或权限不可用时，把门禁记录为未验证；永远不要用单元
测试、确定性 fake 或另一个平台来推断。
