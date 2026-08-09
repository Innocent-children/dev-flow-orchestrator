# 安装 Dev Flow Orchestrator

[English](INSTALL.md)

本指南安装带本地 MCP-first 接口的 `0.5.0`。持久化模型和任务数据命名空间仍为 `0.4.0`。

## 1. 支持的注册模式

Bundled Codex 插件/MCP 安装是唯一受支持模式。manifest 引用根 `.mcp.json`；
安装器不提供 standalone 注册。若已存在独立管理的 standalone 注册，安装会在
修改源码、runtime、marketplace、插件或 launcher 前停止，并提示人工检查。
卸载时无法证明属于 bundled 安装的注册会被保留。

## 2. 要求

Bundled macOS 安装要求 macOS、Git、`uv`、支持插件和 MCP server 的 Codex、一个已在 `PATH` 中且可写的绝对目录，以及 64 位 CPython 3.10、3.11、3.12、3.13 或 3.14。

Windows 预览安装要求 Windows 10 22H2 x64 或 Windows 11 x64、Git for Windows、`uv`、Codex、64 位 CPython 3.10–3.14，以及 Windows PowerShell 5.1 或 PowerShell 7。发布候选只有取得原生 Windows 证据后才能视为在 Windows 已验证。Windows Server 和 POSIX 兼容层不在支持承诺范围。

## 3. 在 macOS 上 Bundled 安装

一行安装：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

先审阅再本地安装：

```sh
git clone --branch main --single-branch \
  https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
sh "$HOME/plugins/dev-flow-orchestrator/scripts/install.sh"
```

显式位置示例：

```sh
DEV_FLOW_SOURCE_ROOT="$HOME/plugins/dev-flow-orchestrator" \
DEV_FLOW_RUNTIME_HOME="$HOME/.local/share/dev-flow-orchestrator/runtime" \
DEV_FLOW_BIN_DIR="$HOME/.local/bin" \
sh scripts/install.sh
```

`DEV_FLOW_BIN_DIR` 必须已在 `PATH` 中。安装器不会修改 shell profile 或无关配置。

## 4. 安装器执行内容

安装器依次：

1. 校验预期 origin、已附着的 `main`、干净 checkout、ignored path 安全，并只允许 fast-forward 更新；
2. 在执行候选运行时代码前校验候选内容；
3. 检查是否存在重复启用的 standalone `dev-flow` 注册；
4. 查找受支持的 64 位 Python，并要求 `uv`；
5. 导出精确 `uv.lock` 并安装到源码和任务数据之外的临时虚拟环境；
6. 构建并安装项目 wheel，再检查 import、initialization、instructions、恰好十一个工具的目录和一次读取调用；
7. 写入包含 release、source commit、Python 身份、架构、lock digest、launcher 身份和激活时间的 runtime receipt；
8. 原子发布版本化 runtime 与 `dev-flow-mcp` launcher；
9. 保留无关 marketplace 条目并激活插件。

Runtime 构建失败不会替换先前的版本化 runtime 或 launcher。只有 receipt 仍与已验证 source commit、dependency lock、launcher 和 interpreter digest 匹配时才复用 runtime 版本。

默认托管 runtime：macOS 为 `~/.local/share/dev-flow-orchestrator/runtime`，Windows 为 `%LOCALAPPDATA%\dev-flow-orchestrator\runtime`。任务数据仍位于 Codex 插件数据根目录的 `0.4.0` 命名空间，与 runtime 分离。

## 5. 验证 Bundled 激活

确认命令已在 `PATH`：

```sh
command -v dev-flow-mcp
dev-flow-mcp --http
```

第二条命令必须以 `MCP_RUNTIME_UNAVAILABLE` 失败，且不得打开监听 socket。在 Codex 中检查已启用插件并确认只有一个 `dev-flow` server。让 Codex 调用 `dev_flow_server_info`；它应报告 release `0.5.0`、model `0.4.0`、STDIO transport、六种 workflow 和 catalog digests。然后列出工具并确认恰好十一个 `dev_flow_*` 工具。

服务器是长生命周期 STDIO 协议进程，因此除非使用 MCP client 或 inspector，不要在交互终端直接运行 `dev-flow-mcp --stdio`。

## 6. Standalone 注册

先安装或构建托管 runtime 和 PATH launcher，但不要启用 bundled plugin。注册同一命令：

```sh
codex mcp add dev-flow -- dev-flow-mcp --stdio
codex mcp list --json
```

切换到 bundled 模式前先移除：

```sh
codex mcp remove dev-flow
```

Standalone provisioning 在此版本中不受支持。已有 standalone 注册仍归操作者所有，
产品不会静默接管或删除。

## 7. Windows 预览

在正常原生 PowerShell 会话运行：

```powershell
git clone --branch main --single-branch `
  https://github.com/Innocent-children/dev-flow-orchestrator.git `
  "$HOME\plugins\dev-flow-orchestrator"
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$HOME\plugins\dev-flow-orchestrator\scripts\install.ps1"
```

安装器使用 literal path，校验 x64 进程与解释器，构建
`venv\Scripts\python.exe`，并在可写绝对 PATH 目录中创建自有
`dev-flow-mcp.cmd` 和 `dev-flow.cmd`。后者复用现有 CLI，支持 `--help` 以及
`web start|status|stop`。它不使用 POSIX 工具。

## 8. 审批与剩余边界

MCP annotations 是描述，不是强制机制。每项审批都应保留用户权威。在 host 支持时，对读取工具单独审批，并把 mutation 审批限定到 `dev-flow` server、确切工具和当前任务。不要授予通用 shell 或 blanket mutation 审批。

`0.5.0` 移除旧 fail-open Hook 及其 pre-tool 数据目录 guard。剩余保护来自 Controller 校验、Store locks、revision CAS、精确 bindings、仓库权限、host 审批和用户复核。不得把 tool annotations 描述成替代安全边界。

## 9. 修复与升级

重新运行同一安装器。它只接受干净权威 checkout，获取 `refs/heads/main` 并仅进行 fast-forward 更新。它绝不 stash、reset、clean、rebase、switch branch 或覆盖 ignored collision。本地改动、本地独有 commit、detached/非预期 branch、非预期 origin 或 divergence 都会在激活前停止。

托管 runtime 由 release、source commit 和 lock digest 进行内容寻址。保留先前已验证 runtime 目录，确保构建失败不会破坏最后可用 runtime。插件激活错误会附明确的重试恢复方法，并且绝不报告为成功。

## 10. 卸载

macOS：

```sh
sh "$HOME/plugins/dev-flow-orchestrator/scripts/uninstall.sh"
```

两种形式都会保留源码 checkout。`--keep-source` 继续作为兼容参数被接受，并用于明确表达这一意图：

```sh
sh "$HOME/plugins/dev-flow-orchestrator/scripts/uninstall.sh" --keep-source
```

Windows：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$HOME\plugins\dev-flow-orchestrator\scripts\uninstall.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$HOME\plugins\dev-flow-orchestrator\scripts\uninstall.ps1" -KeepSource
```

卸载器可以在各组件现有检查允许时移除 Dev Flow 插件条目、自有 launcher、personal marketplace 条目和托管 runtime。它们会分别报告每个组件，并返回明确的 `partial` 结果，因为源码 checkout 会保留。这并不为 runtime 移除建立精确所有权或独立安全性；DFO-AUDIT-010 仍未关闭。

破坏性源码移除已禁用，因为现有安装尚无可验证、与 receipt 绑定的精确所有权 manifest。receipt 会给出所保留源码的词法绝对路径，并保留 Controller 任务数据和无关 marketplace/MCP/插件配置。在执行任何手工操作前，应检查并备份 checkout，再独立确认所有权。`--keep-source` 和 `-KeepSource` 的源码保留行为与默认调用相同。

## 11. 故障排查

- `Python ... required`：把 `DEV_FLOW_PYTHON` 指向已验证的 64 位 CPython 3.10–3.14。
- `uv is required`：安装 `uv` 后重试；依赖绝不会安装到系统或用户 Python。
- `PATH has no writable absolute directory`：将 `DEV_FLOW_BIN_DIR` 设为已在 `PATH` 中的安全目录。
- `standalone ... conflicts`：bundled 安装器不管理 standalone 注册；请检查并保留
  现有注册，人工解决冲突后再重试。
- transport 选项触发 `MCP_RUNTIME_UNAVAILABLE`：使用本地 `--stdio`；尚未实现远程 transport。
- mutation 完成状态不确定：调用 `dev_flow_get_task` 和 `dev_flow_get_next_action`，不得盲目重放 mutation。
- 存储任务可见但 next action 失败：在规范路径恢复每个不可变成员 worktree 后重试读取。

只读 Web UI 仍可通过 `dev-flow web start` 在 `127.0.0.1` 使用；它不能替代 MCP health 检查，也没有 mutation 权威。
