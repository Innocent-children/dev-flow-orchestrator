# 安装 Dev Flow Orchestrator

[English](INSTALL.md)

本指南说明 `0.6.8` 版本的版本化 release artifact 生命周期。它无需克隆或保留本仓库，
即可把正式 `dev-flow` Codex Skill 作为 bundled plugin 安装，并安装本地 STDIO MCP
服务器。持久化 Controller 模型和任务数据命名空间继续为 `0.4.0`。

## 1. 支持的安装与注册模式

使用所选精确 GitHub Release 附带的 `install.sh` 或 `install.ps1` 资产。不要从仓库
checkout 调用安装器，也不要设置 `DEV_FLOW_SOURCE_ROOT`；checkout 驱动的生命周期
调用会在任何产品修改之前被拒绝。

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
- 一个已经位于 `PATH` 上的可写绝对目录。

原生 Windows 安装需要 Windows 10 22H2 x64 或 Windows 11 x64、64 位 CPython
3.10–3.14、`uv`、Codex、PowerShell 5.1 或 PowerShell 7、
`Invoke-WebRequest`，以及一个已经位于 `PATH` 上的可写绝对目录。Windows Server
与 POSIX compatibility layer 不在受支持客户端声明范围内。

Git、仓库 clone 和 `.git` 不是最终用户前提。Release production 使用精确且干净的
Git tag，但任何 checkout 都不会成为已安装权威。用户选择的安装根可以包含空格、
撇号和 Unicode。

## 3. 精确版本安装

在 macOS 上，从所选版本的专属 release 地址下载 bootstrap；若本地策略要求，先进行
检查，再执行该下载资产：

```sh
VERSION=0.6.8
INSTALLER="${TMPDIR:-/tmp}/dev-flow-install-${VERSION}.sh"
curl -fL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v${VERSION}/install.sh" \
  -o "$INSTALLER"
sh "$INSTALLER"
```

在原生 Windows 上：

```powershell
$Version = '0.6.8'
$Installer = Join-Path $env:TEMP "dev-flow-install-$Version.ps1"
Invoke-WebRequest -UseBasicParsing `
  -Uri "https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v$Version/install.ps1" `
  -OutFile $Installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Installer
```

`latest` 下载路由可以帮助用户选择版本，但 bootstrap 本身与版本匹配。开始执行后，
它只构造 `releases/download/v<version>/` 下的 URL；生产接口不提供 repository、
mirror 或 origin override。

## 4. Release 资产与 Phase A 验证

每个 `MAJOR.MINOR.PATCH` release 发布以下一套身份匹配的资产：

- `dev-flow-orchestrator-<version>.tar.gz`；
- `release-index.json`；
- `install.sh`；
- `install.ps1`。

平台中立的 archive 包含一个顶层目录，内部有完整 sealed `plugin/**` tree、恰好一个
`dev_flow_orchestrator-<version>-py3-none-any.whl`、
`runtime-requirements.txt`、生成它所用的 `uv.lock`、版本化 `lifecycle/**` helper
和 `release-manifest.json`。Plugin tree 包含 `.codex-plugin/plugin.json`、
`.mcp.json`、`skills/dev-flow/**`、plugin-side CLI 资产与 installed-validation 资产。
Manifest inventory 覆盖除自身以外的每个后代；`release-index.json` 固定 manifest 的
原始 UTF-8 字节。

两个 bootstrap 内嵌逐字节相同的标准库 Phase A verifier。在执行任何 artifact helper、
artifact import、artifact subprocess、依赖安装、candidate 构建或产品状态修改之前，
Phase A 会：

1. 在固定 hard cap 下下载 index，并在 JSON parse 之前验证 bootstrap 内嵌的 digest；
2. 解析严格的闭合 schema，检查规范 repository、精确 version、archive name、schema
   和边界；
3. 以 streaming size accounting 下载 archive，并在解压前验证精确 size 与 SHA-256；
4. 在写入任何 member 前检查每个 tar header、member type、path、case-collision key、
   declared mode 和固定资源边界；
5. 仅解压到全新、空的 installer-owned staging directory，并且不跟随 link 或
   reparse ancestor；
6. 验证内嵌 manifest 的原始 digest 及其闭合 schema；
7. 将完整 extracted inventory 与 manifest 比较；
8. 在不导入或执行制品代码的情况下检查所需 plugin、wheel、lock、requirements 与
   lifecycle topology。

Artifact member name 使用 `/` 和闭合 portable ASCII grammar。Absolute 或
drive-qualified path、`.`、`..`、backslash、colon、control、trailing dot/space、
ASCII case collision、Windows device name、link、sparse file、device、FIFO、
不支持的 tar extension、未声明 member、缺失 member 和固定 hard-cap 违规都会被拒绝。

只有成功的 Phase A 才能进入 Phase B。临时 acquisition/extraction path 永远不会成为
marketplace、active、receipt 或 rollback authority。已处理结果会精确删除 transaction
自有 staging，或者报告其精确保留路径。

调用者输入只能通过闭合的 destination option 集合跨越该边界：`--runtime-root`、
`--bin-dir`、`--marketplace-file`、`--codex-home`、`--data-root` 和
`--lock-timeout`。`--option value` 与 `--option=value` 两种形式都能原样保留包含空格、
撇号和 Unicode 的原生路径。缩写、重复 option、位置参数以及 release/artifact 身份
option 都会被拒绝。Phase B 从自身的版本化 lifecycle 位置推导 artifact root，并在
构建 candidate 前重新核对完整 live inventory；candidate 构建还会在复制、安装 wheel
或执行另一 helper 前再次核对。

## 5. 信任边界

用户选择执行的 bootstrap 字节、规范 GitHub 仓库及其 Release 发布权限、HTTPS/TLS
与 GitHub delivery、受支持的系统 Python、平台 downloader、`uv`、Codex，以及本地
账户和文件系统权限，共同构成初始信任边界。

Bootstrap 固定 repository、version、archive name、index digest 与 bootstrap schema。
SHA-256 确认获取和解压的字节与 bootstrap、index 和 manifest 固定的字节一致。它能
检测损坏、局部替换和跨 release 混用。SHA-256 不是独立数字签名，也不是发布真实性的
绝对证明。它不能证明 GitHub 账户从未被攻破，也不能抵御可一致替换一个用户的
bootstrap、active record、dispatcher、verifier 与 managed runtime 的攻击者。Source
commit 与 tree 是 release builder 检查并记录的 publication assertion；最终用户安装器
不会从 checkout 重建它们。

本版本不增加签名、Sigstore、transparency-log verification、third-party mirror 或
offline fresh install。

## 6. Phase B、managed release 与持久权威

Phase B 对 package 做 semantic validation，创建 transaction-owned candidate，安装
要求哈希且仅使用 wheel 的依赖和随附的 pure-Python 项目 wheel，不运行 sdist build
backend，并执行 candidate-specific package、Skill、MCP、receipt 与 runtime health
check。Candidate health 不使用公共 active record。

默认 managed-runtime root 为：

- macOS：`~/.local/share/dev-flow-orchestrator/runtime`
- Windows：`%LOCALAPPDATA%\dev-flow-orchestrator\runtime`

在所选绝对 runtime root 内：

- `releases/<release-id>/` 包含每个 managed release；
- `active.json` 是 active release 的唯一本地 selector；
- `transactions/` 包含有界、持久的 lifecycle journal；
- `lifecycle/` 包含稳定安装支持；
- `lifecycle.lock` 是 installation-wide lock。

精确 `release-id` 包含版本与经验证的 release identity；不要手动构造或选择它。
Managed release 包含隔离 environment、sealed plugin、runtime receipt、完整 installed-
content verifier 与版本化 lifecycle entry point。Receipt 绑定 index、archive、manifest、
source assertion、wheel、requirements、lock、distribution、Python、plugin、verifier、
helper、owned-file、release-path 与 transaction identity。

`active.json` 有意保持更小。其闭合 schema 包含单调递增 generation、release ID、
contained 的绝对 release path、receipt digest、dispatcher protocol 和提交该状态的
transaction ID。Launcher、marketplace data、receipt 和 helper 不会与它竞争 active
selector 权威。

产品在所选可写 PATH 目录中拥有三个小型稳定 dispatcher：

- `dev-flow`
- `dev-flow-mcp`
- `dev-flow-uninstall`

在 Windows 上，这些命令分别安装为 `dev-flow.cmd`、`dev-flow-mcp.cmd` 和
`dev-flow-uninstall.cmd`。

普通修复、升级与自动回滚复用这些字节。CLI 与 MCP dispatcher 在调用 active verifier
之前，最小验证 active-record、contained-path、receipt、protocol、Python 和版本化
verifier 证据。Verifier 在导入项目代码前检查完整 installed identity。Personal
marketplace 只指向 active managed release 内的精确 plugin root。

Controller task data 继续位于 `0.4.0` namespace 下的 Codex plugin data root 中，
不属于 managed release、lifecycle state 或 ownership removal。

## 7. 激活、锁与终态

Fresh install、repair、upgrade、migration、recovery 与 uninstall 共用一把
installation-wide lifecycle lock。每个命令在读取 active 或 transaction authority
之前获取锁，并持有至持久终态。每次 operation 创建或恢复一个有界 journal。Active
创建、替换、恢复与删除使用 expected generation 加 active-record-digest CAS；generation
单调递增。

Candidate activation 按以下顺序进行：

1. 完成 candidate-specific staged health；
2. provisional 配置 marketplace 与 Codex plugin，并将它们读回；
3. 通过 generation CAS 提交 target active record；
4. 通过真实公共 `dev-flow` 和 `dev-flow-mcp --stdio` 路径证明启动；
5. 记录 transaction 终态。

每个 lifecycle result 都属于以下一种：

- `committed`：请求的 release 或 uninstall 状态具有权威，且所需 read-back 成功；
- `rolled_back`：candidate 不具有权威，且 immediate previous authority（对于失败的
  fresh install 则是无权威状态）已经恢复并证明；
- `partial`：无法精确证明请求状态或 previous authority；进一步 identity-specific
  mutation 停止，不确定内容予以保留，journal 记录 observations、paths 与有界 recovery
  guidance。

命令不会在 journal 仍为 in-progress、plugin/marketplace state 不一致或存在未分类的
provisional effect 时报告成功。

## 8. 修复、升级、回滚与恢复

Repair 重新运行与已安装版本匹配的 bootstrap。对于 `0.6.8`，使用第 3 节中完全相同
的命令，并设置 `VERSION=0.6.8`。只有 complete startup、receipt、ownership 与
installed-content attestation 都通过时才会复用健康 release。任一 drift 都会从重新
获取并重新验证的同版本 artifact 构建新 candidate。若该版本远端 index、archive 或
manifest digest 与 active receipt 不同，repair 会以 same-version identity-change 错误
失败。

Upgrade 运行目标版本的 bootstrap。例如，把第 3 节中的 `VERSION` 或 `$Version` 设置
为所需的 `MAJOR.MINOR.PATCH`；不要让旧版本的 lifecycle helper 获取目标版本。

Rollback 是自动的，并且仅限当前激活 transaction 尚未终结时的 immediate previous
authority。Active commit 前失败会恢复 previous external state。Commit 后失败会通过
CAS 恢复 immediate previous generation，恢复 external state，并重新验证 previous
public startup path。它不需要网络、Git 或 checkout。没有面向任意历史版本的公共
rollback 命令，也没有无限 retention policy。

在开始新的 lifecycle mutation 前，命令会恢复或分类任何 non-terminal transaction，
不会无限重试。若 authority 仍有歧义，transaction 进入 `partial`，新 mutation 被拒绝。

## 9. 有界 predecessor migration

自动 migration 只识别 frozen predecessor fixture 所表达的紧邻 conforming checkout-
based installer。它仅从 installed plugin observation、launcher marker、receipt、
ownership、marketplace 和 transaction state 分类 identity。更旧、未来、畸形或歧义
layout 会在 identity-specific mutation 前停止。

Migration 永远不会读取、导入、执行、fetch、pull、reset、clean、纳入 ownership 或
删除 predecessor checkout。Checkout 绝不是 rollback input，成功迁移后仍归用户所有。
若 installed observation 不能精确证明一个 predecessor authority，应保留原状并遵循
报告的 recovery guidance。支持更广泛的历史 schema 需要单独的 OpenSpec change。

整个 migration 期间，legacy source checkout 都保持不变并予以保留。

## 10. 验证激活

确认稳定命令可以从 `PATH` 解析：

```sh
command -v dev-flow
command -v dev-flow-mcp
command -v dev-flow-uninstall
dev-flow --help
dev-flow web start
dev-flow web status
dev-flow web stop
```

在 Codex 中读回已启用的 personal-marketplace plugin，确认其路径是 active managed
release 内的精确 plugin root。确认一个名为 `dev-flow` 的 Skill 与一个名为
`dev-flow` 的 MCP server。启动新的 Codex 任务、调用 `$dev-flow`，并让 Codex 调用
`dev_flow_server_info`。

Plugin manifest 注册 `./skills/` 和根 `.mcp.json`。Sealed plugin 保留精确的
`skills/dev-flow/` 目录树，包括带有 `implicit_invocation: true` 的 metadata。
installed-stage validator 在激活前记录配对的 Skill 与 STDIO MCP 证据。Skill 负责把
命令路由到 Controller；Skill 本身不能授权 mutation。

`dev-flow-mcp --stdio` 是长期运行的 protocol process。只能通过 MCP client 或
inspector 运行，不要将其作为交互式 shell 命令执行。不支持的 transport flag 必须失败，
且不能打开监听 socket。

## 11. 与源码无关的卸载

从任意目录运行稳定 dispatcher；不要再从 checkout 调用 `uninstall.sh` 或
`uninstall.ps1`：

```sh
dev-flow-uninstall
```

该命令既不需要网络，也不需要仓库 checkout。它验证稳定安装证据，把最小标准库 removal
driver 复制到 managed runtime 之外并验证副本，获取同一把 lifecycle lock，并创建或
恢复持久 uninstall transaction。

Uninstall 按顺序 compare-and-remove 精确的 product-owned plugin state、Dev Flow
personal-marketplace member、managed-release entry、active record、稳定 dispatcher
与 lifecycle support。Uninstall dispatcher 与 lifecycle support 最后移除，释放锁之后
不再执行产品修改。中断后的重跑无需已删除的 runtime 即可恢复或分类 journal。

Changed、unknown、concurrent、linked、reparse、special 或无法证明的内容会被保留，并
以精确路径报告。Uninstall 保留 Controller task data、无关 marketplace/plugin entry、
无关 launcher、standalone MCP registration 与每个 legacy checkout。它绝不会为了强行
完成而扩大为递归删除。

## 12. 故障排查与证据限制

- `DEV_FLOW_SOURCE_ROOT is not supported`：取消设置该变量，并运行精确版本的 release
  bootstrap，而不是 checkout script。
- Phase A digest、inventory、path、tar 或 resource-limit 错误：停止；不要执行已解压
  helper 或采用 staging。从规范 release 页面重新下载精确 release bootstrap 与资产集。
- startup attestation 失败：重新运行与 active version 匹配的 bootstrap；不要替换成
  digest envelope 不同的同版本资产。
- lifecycle lock 或 non-terminal transaction：让命令执行有界恢复。若其报告
  `partial`，在下一个 lifecycle mutation 前保留列出的 path 与 observation，并遵循
  精确 recovery guidance。
- standalone registration 冲突：把它作为 operator-owned state 检查；bundled
  lifecycle 不会静默采用或删除它。
- 不受支持的 MCP transport：使用本地 `--stdio` registration。

原生 Windows final-artifact 验证必须在原生 Windows x64 上运行。静态 PowerShell
分析、模拟 adapter、macOS、WSL 或 Wine 都不是原生 Windows 证据。Release-candidate
plugin read-back、bundled Skill discovery、STDIO MCP startup 与 uninstall 必须使用
真实 Codex host。Promotion evidence 需要有权限发布全部四个最终资产，并从精确的官方
版本专属地址重新下载。若这些环境或权限不可用，应把该门禁记录为未验证；绝不能从单元
测试、deterministic fake 或其他平台推断。
