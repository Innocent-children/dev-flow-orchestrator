# Dev Flow Orchestrator

[English](README.md) · [安装说明](INSTALL.md) · [架构](ARCHITECTURE.md) ·
[贡献指南](CONTRIBUTING.md)

Dev Flow Orchestrator 是一款适用于 macOS 版 Codex 的开发流程插件。它把一次软件
需求保存成可暂停、可恢复的任务，按照清晰的阶段推进，并且每次只给 Codex 一个明确
的下一步。

代码修改和验证仍由 Codex 完成；插件负责安排执行顺序并记录每个阶段的结果。随插件
提供的标准工作流 `lite` 包含仓库预检、实现和验证，也可以通过工作流文件编排适合
项目的执行步骤。

## 它能做什么

- 通过任务 ID，在后续 Codex 会话中继续开发任务。
- 每次专注一个阶段，不必从聊天记录中重新整理进度。
- 开始实现前检查目标 Git 仓库。
- 记录实际执行的验证命令，只有验证通过后才完成任务。
- 把工作流状态保存在目标仓库之外。
- 按需加入代码影响分析、实现审查或自定义工作流。

每个任务对应一个 Git 仓库。

## 运行要求

- macOS；
- Python 3.9–3.14；
- Git，目标路径必须是至少已有一个提交的工作树根目录；
- 支持插件和 Hook 的 Codex。

插件运行时只使用 Python 标准库，不需要额外安装 Python 包。随插件提供的 Skills
使用外部 `codebase-memory-mcp` 集成来发现代码。

## 安装

首次创建个人 marketplace 时：

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"

cd "$HOME/plugins/dev-flow-orchestrator"
python3 -I -S scripts/validate_package.py

mkdir -p "$HOME/.agents/plugins"
cp templates/personal-marketplace.example.json \
  "$HOME/.agents/plugins/marketplace.json"

codex plugin add dev-flow-orchestrator@personal
```

只有 `~/.agents/plugins/marketplace.json` 不存在时才执行上面的 `cp` 命令。如果文件
已经存在，请把 `templates/marketplace-entry.json` 合并到原有 `plugins` 数组中。

安装完成后，新建一个 Codex 任务，打开 `/hooks`，检查并信任已安装的 Hook 定义。
HTTPS 克隆、已有 marketplace 配置、升级、验收、排错和卸载说明请参阅
[INSTALL.md](INSTALL.md)。

## 启动和继续任务

日常使用只需要 `$follow-dev-flow`。

提供仓库路径、工作流和需求来启动任务：

```text
使用 $follow-dev-flow，在下面的仓库中以 lite 工作流启动任务：
/仓库/绝对路径

需求：
<要完成的工作>
```

保存返回的任务 ID。之后可以这样继续：

```text
使用 $follow-dev-flow 继续任务 <task-id>。
```

当前目录位于任务仓库内时，已安装的 Hook 会帮助 Codex 重新接入进行中的任务。Skill
会按照下一阶段继续工作、记录结果，直到任务完成。

## `lite` 工作流

`lite` 是随插件提供的标准工作流：

```text
preflight → implement → verify → done
任一未完成阶段 ── cancel ──→ cancelled
```

| 阶段 | 说明 |
|---|---|
| `preflight` | 插件执行受时间和输出量限制的只读 Git 检查，并记录仓库的起始状态。 |
| `implement` | Codex 完成需求并记录实现摘要。 |
| `verify` | Codex 执行相关检查，记录命令和结果；只有验证通过后任务才会完成。 |

preflight 要求传入非裸 Git 工作树的精确根目录，并且已经存在 `HEAD` 提交。有未提交
改动的工作树和 detached `HEAD` 都可以使用。

需要停止未完成的任务时，应明确要求 Codex 取消任务并说明原因。`lite` 的每个未完成
阶段都可以取消。

## 更多能力

插件还提供两个辅助 Skill：

- `$analyze-change-impact` 分析改动可能影响的范围，并在源码中确认重要结论；
- `$review-dev-flow-change` 独立、只读地审查实现结果。

除了 `lite`，也可以传入 JSON 或 YAML 工作流文件的绝对路径。自定义工作流使用运行时
提供的步骤类型，还可以加入 `tool: openspec` 之类的 driver 元数据，告诉 Codex 某个
阶段应使用什么工具。任务启动后会绑定所选工作流，因此在任务结束前应保持该文件可用
且内容不变。

工作流格式、支持的 handler、payload 契约和扩展方式请参阅
[工作流定义](ARCHITECTURE.md#workflow-definitions)。

## 状态与安全

- 任务状态保存在插件数据目录中，不会写入目标仓库。状态目录和仓库必须位于彼此分离
  的目录树中。
- 状态更新使用文件锁和原子替换。不要手工修改任务状态文件。
- Git preflight 只读取仓库。控制器不会自动执行 stash、reset、clean、commit、
  checkout、merge 或 push。
- `$follow-dev-flow` 会在取消任务，以及执行 `stash`、`reset`、`clean`、
  `force-push`、`rebase`、`merge`、`commit` 或 `push` 前要求明确授权。

Hook 会恢复任务上下文，并为常用的 shell 和编辑工具保护插件数据路径。它是操作护栏，
不是安全沙箱：如果 Hook 无法处理某个事件，它不会阻止宿主继续操作。工作流校验和状态
推进仍由控制器负责。

## CLI 与更多文档

随插件提供的 CLI 包含 `start`、`show`、`next`、`apply`、`cancel` 和 `list`。直接
使用 CLI 时必须明确传入 `--data-dir`，并通过随插件提供的 Python launcher 启动；同一
任务的所有命令都要使用相同的数据目录。完整命令行示例见
[安装说明](INSTALL.md#7-verify-the-cli-package)。

- [INSTALL.md](INSTALL.md)：安装、升级、验收和排错。
- [ARCHITECTURE.md](ARCHITECTURE.md)：工作流格式、任务投影、状态和模块边界。
- [CONTRIBUTING.md](CONTRIBUTING.md)：开发与校验说明。
- [LICENSE](LICENSE)：许可证条款。
