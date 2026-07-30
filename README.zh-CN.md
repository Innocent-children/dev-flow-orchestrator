# Dev Flow Orchestrator

[English](README.md) · [安装说明](INSTALL.md) ·
[贡献指南](CONTRIBUTING.md)

Dev Flow Orchestrator 是一个面向 macOS Codex 的 plugin，用于执行受控、可恢复的
软件交付。它把 workflow state 保存在项目 repository 之外，将 state 或 Git
变更约束为明确的 controller action，并保留中断后安全恢复所需的 evidence。

产品只有一个 plugin identity：`dev-flow-orchestrator`，并且只有一个当前
runtime：

- 所有 task 使用 task schema v4；
- `lite@4` 用于边界明确的单 repository 工作；
- `full@4` 用于完整的单 repository 或多 repository 工作。

## 环境要求

- macOS；
- Git；
- Python 3.9 或更高版本；
- 支持 plugin 的 Codex 版本。

runtime Python code 只使用标准库。本 release 不声明 native Windows 或 Linux
支持。

## 它负责什么

controller 是 workflow transition 和持久化 task state 的唯一 authority，负责：

- intake、影响分析、route 选择、planning、implementation、focused
  verification 与 independent review；
- 单 repository 和多 repository 的 repository set；
- baseline capture、隔离 worktree planning 与 repository ownership；
- gated action 执行前的明确 approval；
- 有边界的 worker assignment 与 changed-path enforcement；
- action journal、receipt、reconciliation、quarantine 与 recovery；
- `codebase-memory` discovery evidence，以及彼此分离的 baseline/current
  workspace project identity；
- 面向当前 actionable frontier 的紧凑 CLI 和 MCP projection。

所有 Git 变更都具有确定性并受 gate 约束。plugin 不会隐式获得 stash、reset、
clean、commit、push、force-push、rebase 或 merge authority。

## Workflow profile

controller 会直接解析一个已安装 bundle，并在 task 的第一个 revision 中固定其
SHA-256 identity。

| Workflow | Repository profile | 适用场景 |
|---|---|---|
| `lite@4` | 单 repository | 具有明确 target path 的内部、test 或 documentation 小范围工作 |
| `full@4` | 单 repository | 完整交付流程，通常使用隔离 worktree |
| `full@4` | 多 repository | 协同 planning、lease、result、barrier 与 integration |

`in-place` 和 `branch` workspace strategy 会选择 lite flow，`worktree` 会选择
full flow。多 repository task 使用 full flow。

## 安装

[INSTALL.md](INSTALL.md) 提供完整的新安装、原 identity 替换、MCP 配置、
troubleshooting 和验收步骤。下面是使用 `personal` marketplace 的直接安装方式。

先获取 source：

```sh
mkdir -p "$HOME/plugins"
git clone https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

使用 SSH：

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

如果 `~/.agents/plugins/marketplace.json` 尚不存在，可以使用 package 内的完整
template：

```sh
mkdir -p "$HOME/.agents/plugins"
cp \
  "$HOME/plugins/dev-flow-orchestrator/templates/personal-marketplace.example.json" \
  "$HOME/.agents/plugins/marketplace.json"
```

如果该文件已经包含其他 plugin，不要覆盖；把
`templates/marketplace-entry.json` 中的 object 合并到现有 `plugins` array。

注册 marketplace 并安装：

```sh
python3 -m json.tool "$HOME/.agents/plugins/marketplace.json"
codex plugin marketplace add "$HOME"
codex plugin add dev-flow-orchestrator@personal
codex plugin list
```

预期只有一条对应记录：

```text
dev-flow-orchestrator@personal  installed, enabled
```

安装后新建 Codex session。随后确认 Hook 已 pickup；如果需要类型化 MCP tool，
在 plugin 设置中启用默认 disabled 的 `dev-flow-macos`，再次新建 session，并
确认发现六个 MCP tool。最后在真实项目中新建 task 并完成一个 workflow action。

如果已经安装，应先用同一个 `dev-flow-orchestrator@personal` identity 执行
`codex plugin remove`，替换 source 后再执行 `codex plugin add`。不要安装第二个
plugin instance。

## 在 Codex 中使用

公开入口是随 package 提供的 `follow-dev-flow` Skill。典型请求如下：

```text
使用 $follow-dev-flow 在当前 repository 开始以下需求：
<需求内容>
```

```text
使用 $follow-dev-flow 恢复 task <task-id>。
```

```text
使用 $review-dev-flow-change 独立 review 已完成的 implementation。
```

Skill 会向 controller 查询当前 node，只加载绑定的 playbook section，对需要确认
的 action 先执行 preview，并在同一个 task revision 上应用已确认的 intent。

package 还包含两个辅助 Skill：

- `analyze-change-impact`：只读的影响与依赖分析；
- `review-dev-flow-change`：全新 context 中独立、只读的 implementation review。

## CLI

CLI 是完整的本地 operation 与 recovery surface。package launcher 会选择受支持
的 Python interpreter：

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py --help
```

如果直接调用已安装副本，请把 `.` 替换为该 plugin root。

### 配置 plugin 生效目录

没有 scope 配置时，plugin 默认在所有目录生效。排除一个目录及其所有子目录：

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --mode all --add-exclude /path/to/excluded-directory
```

只允许指定目录：

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --mode allowlist \
  --add /path/to/project-a \
  --add /path/to/project-b
```

查看或修改配置：

```sh
# 查看当前 scope。
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py scope

# 检查一个目录是否生效。
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --check /path/to/project

# 取消一个排除目录。
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --remove-exclude /path/to/excluded-directory

# 恢复默认的全目录 scope 和 protected-path policy。
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py scope --clear
```

include 和 exclude 规则都递归覆盖子目录。匹配层级最深的目录优先；同一目录同时
匹配 include/exclude 时，exclude 优先。

### 直接创建 task

`--repo` 必填且可以重复，路径必须指向 Git repository。

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py start \
  --repo /path/to/project \
  --workspace-strategy worktree \
  --requirement "实现指定需求"
```

对于边界明确的 lite 工作，应声明精确的 repository-relative target path：

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py start \
  --repo /path/to/project \
  --workspace-strategy in-place \
  --change-category docs \
  --target-path README.md \
  --target-path docs/usage.md \
  --requirement "更新用户文档"
```

多 repository task 需要重复传入 `--repo`：

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py start \
  --repo /path/to/service \
  --repo /path/to/client \
  --workspace-strategy worktree \
  --requirement "修改共享 contract 和两端 implementation"
```

### 查看和恢复 task

```sh
# 列出 task。
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py list

# 获取紧凑 agent projection。
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  show --task <task-id> --profile agent-v1

# 查看某个 command 的完整帮助。
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py <command> --help
```

不要直接编辑持久化 task JSON。必须通过 CLI 或 MCP action 操作，从而保持
revision、approval、evidence 和 recovery invariant。

## State 与配置

task state 不会写入目标 repository。data directory 按以下顺序解析：

1. 明确传入的 `--data-dir`；
2. `DEV_FLOW_DATA_DIR`；
3. Codex 提供的 `PLUGIN_DATA`；
4. `~/Library/Application Support/dev-flow-orchestrator`。

创建、查看和恢复同一个 task 时必须使用同一个 data directory。`scope` 配置也
保存在该 data directory。

## Codex integration

### Hook

lifecycle Hook 会在 session 启动和 compact 时恢复 task context，注入有边界的
worker assignment，检查 worker result，并为 Bash 或文件编辑工具提供 guardrail。
Hook 内部错误 fail open；controller 仍是唯一 workflow state machine。

### MCP

随 package 提供的 macOS MCP profile 是 optional，并且默认 disabled。启用后，
它通过 package launcher 启动 `scripts/dev_flow_mcp.py`，并公开：

- `task-next`；
- `node-description`；
- `evidence-read`；
- `action-preview`；
- `action-apply`；
- `worker-result`。

MCP disabled 或不可用时，Skill 仍可使用 Hook 注入的 CLI locator。

## Architecture

```text
.codex-plugin/plugin.json       plugin identity 与 Codex interface
.mcp.json                       optional macOS MCP profile
hooks/                          lifecycle 与 tool guardrail Hook
scripts/dev_flow.py             CLI controller 与 sealed V4 registry
scripts/dev_flow_mcp.py         类型化 stdio MCP facade
scripts/dev_flow_parts/         只使用标准库的 runtime module
skills/                         公开 orchestration 与只读 Skill
workflows/catalog.json          full@4 与 lite@4 catalog
workflows/activation.json       三个受支持 activation profile
workflows/bundles/              package-owned graph、schema 与 playbook byte
workflows/provenance/           V4 runtime inventory 与 genesis
templates/                      本地 marketplace 示例
```

目标 repository 不能覆盖 package 内的 workflow definition 或 handler。

## Recovery

中断的 effect 必须先检查，再决定是否修改：

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  action-recovery-inspect --help
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  action-recovery-preview --help
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  action-recovery-apply --help
```

如果 trusted host authority 无法证明安全结果，recovery 会返回有边界的
`UNRESOLVED` operator-intervention packet 并停止。它不会推断 settlement、
重新 dispatch effect 或伪造 approval。

## 开发与验证

贡献规则见 [AGENTS.md](AGENTS.md) 和 [CONTRIBUTING.md](CONTRIBUTING.md)。

使用 `codebase-memory` 进行 discovery，再回到 source 确认重要结论；从 OpenSpec
获取当前 JSON instruction；只运行直接覆盖改动的最小 focused tests。本
repository 禁止运行完整 unittest discovery。

## License

见 [LICENSE](LICENSE)。
