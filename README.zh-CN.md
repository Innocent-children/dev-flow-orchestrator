# Dev Flow Orchestrator

[English](README.md) · [安装说明](INSTALL.md) · [Architecture](ARCHITECTURE.md) ·
[贡献指南](CONTRIBUTING.md)

Dev Flow Orchestrator 是一个面向 macOS Codex 的 plugin，用于执行边界明确、可恢复的
软件开发工作。产品只有一个 plugin identity、一个 V4 runtime，以及一个负责所有
task state transition 的 controller。

当前 runtime 按 greenfield 方式设计：

- task state 只使用 schema v4，并保存在目标 repository 之外；
- workflow 深度、repository topology 和 workspace strategy 相互独立；
- `full@4` 与 `lite@4` 都支持单 repository 和多 repository；
- 每个 node 都明确声明 action、authority、write set、effect、failure 和 recovery；
- CLI、MCP、Hook 与 Skill 都只是同一个 controller 的薄 adapter；
- runtime Python code 只使用标准库。

当前 release 只在当前 macOS host 验证，不声明 native Windows 或 Linux 支持。

## 四条路径

repository 数量不会把 `lite@4` 自动升级为 `full@4`。

| Workflow | Topology | 路径 |
|---|---|---|
| `full@4` | 单 repository | preflight → baseline → impact → route → workspace → planning → plan approval → implement → verify → review → finalize |
| `full@4` | 多 repository | full-only gate → 共享 repository plan/lease/result/barrier/integration → implement → verify → review → finalize |
| `lite@4` | 单 repository | preflight → implement → verify |
| `lite@4` | 多 repository | preflight → 共享 repository plan/lease/result/barrier/integration → implement → verify |

`in-place`、`branch` 和 `worktree` 是明确输入的 workspace strategy，不负责选择
workflow。Lite 没有 workflow entry approval；如果后续共享 repository node 自己
声明了额外 authority，它仍与 Full 使用同一种准确 confirmation。

## 目录范围

当前版本没有全局 include directory、exclude directory 或 allowlist 配置。task
scope 就是通过可重复 `--repo` 明确传入的 repository path 集合。Hook 根据这些
repository root 以及已经创建的 workspace root 查找当前 task。

## 环境要求

- macOS；
- Git；
- Python 3.9–3.14；
- 支持 plugin 与 `UserPromptSubmit` Hook 的 Codex。

不需要安装 `pip`、`npm` 或其他 runtime dependency。

## 安装

[INSTALL.md](INSTALL.md) 给出了 source 放置、personal marketplace、原 identity
替换、Hook、optional MCP 与 acceptance 的完整步骤。

常用的 SSH 安装流程：

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"

mkdir -p "$HOME/.agents/plugins"
cp \
  "$HOME/plugins/dev-flow-orchestrator/templates/personal-marketplace.example.json" \
  "$HOME/.agents/plugins/marketplace.json"

codex plugin add dev-flow-orchestrator@personal
codex plugin list
```

如果 marketplace 文件已经存在，必须把 `templates/marketplace-entry.json` 合并到
现有 `plugins` array，不能覆盖文件。最终只保留一个已安装的
`dev-flow-orchestrator`。默认 personal marketplace 会被 Codex 自动发现。

旧 popup 版本即使替换 source 后仍可能留在 installed cache。升级时必须按
[INSTALL.md](INSTALL.md) 执行 atomic cachebuster/remove/reinstall，并启动新的
Codex session。cutover 不会把旧 authority record 迁移为 conversation
confirmation evidence。uninstall 默认只删除 package，保留 external task、
confirmation 与 audit data。

## 在 Codex 中使用

公开 Skill 是 `follow-dev-flow`：

```text
使用 $follow-dev-flow，以 lite@4 在以下 repository 开始需求：
/path/to/service
/path/to/client

需求：
<内容>
```

```text
使用 $follow-dev-flow 恢复 task <task-id>。
```

辅助 Skill：

- `analyze-change-impact`：只读、经过 source 确认的影响分析；
- `review-dev-flow-change`：使用全新 context 的独立只读 implementation review。

Skill 使用 Hook 注入的准确 CLI locator；启用 MCP 时也可以使用 current MCP tool。
两种 transport 相互独立。

## CLI

同一个 task 的所有 command 必须使用同一个明确的 data directory：

```sh
PLUGIN_ROOT=/path/to/dev-flow-orchestrator
DATA_DIR="$HOME/Library/Application Support/dev-flow-orchestrator"

"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" --help
```

data directory 不得放在目标 repository 内。

### 创建 task

单 repository `lite@4`：

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --workspace-strategy in-place \
  --repo /path/to/project \
  --requirement "更新边界明确的功能"
```

多 repository `lite@4`：

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --workspace-strategy branch \
  --repo /path/to/service \
  --repo /path/to/client \
  --requirement "更新共享 contract 和两个 consumer"
```

完整路径使用 `--workflow full`。`--task-id` 是 optional；不传时由 controller
生成。

### 查看与推进

```sh
# 完整 state
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" show <task-id>

# 紧凑 agent-v1 projection
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" next <task-id> \
  --session-id <hook-injected-session-id>

# 在 revision 0 记录 Git preflight evidence
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" preflight <task-id> --expected-revision 0

# 应用准确的 current action
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --expected-revision <revision> \
  --action <action-id> \
  --payload-json '{"field":"value"}' \
  --session-id <hook-injected-session-id>
```

### 持久 conversation confirmation

如果 `next` 返回的 `required_authority` 是 `task-revision+<grant>`，第一次准确的
`apply` 只验证 current task、revision、action、payload、role 与 scope，然后创建
或重新读取一个 private、durable confirmation request。它返回 `PENDING`，不会
修改 workflow state、执行 Git 或 dispatch external effect。request 没有时间
timeout。

agent 必须展示 bounded request、要求用户输入一种准确回复，然后结束当前 turn。
后续真实的 `UserPromptSubmit` event 接受：

- 只有在 current session 与 repository context 中恰好存在一个无歧义 request 时，
  才接受裸 `同意` 或 `approve`；
- 使用 `同意 <request-id>` 或 `approve <request-id>` 指定展示过的准确 request；
- `拒绝` / `deny` 及其 request-ID 形式使用相同的歧义规则。

带额外说明的 prompt 不会决定 request。Hook 只记录 conversation decision，不会
应用 action。下一个 turn 必须先重新读取 `next`；只有仍然 current 的
`CONFIRMED` request 才允许对同一个 revision、action、payload 与 scope 进行一次
准确 retry。pending 或 ambiguous request 继续等待；denial 对该准确 binding 为
terminal。不得 polling、auto-confirm、在 pending 时 retry、伪造 reply 或手工调用
Hook。

不存在 public confirmation/authority issuer、caller approval boolean、caller
`--actor`、raw-prompt input 或 serialized record。`session_id`、`turn_id`、local
account，以及 controller-derived cwd/eligible-task 与 prompt digest，是 configured
Codex conversation channel 的 correlation 与 audit evidence；不会保留 raw cwd 或
raw prompt。这些 evidence 不是独立的 operating-system 或 authenticated-human
identity proof。
`--session-id` 与 optional `--request-turn-id` 只用于 routing，不授予 authority，
也不得由 caller 编造。

每次成功 mutation、lost response 或 revision conflict 后都重新读取 `next`。不得
直接修改持久化 task 或 confirmation JSON。

### 多 repository 执行

Full 在自己的 full-only gate 后进入共享 repository kernel；Lite
multi-repository 在 preflight 后直接进入。二者使用完全相同的共享 node：

1. `repository.plan.record` 记录准确的 repository ID set、controller-derived
   owner、pinned Git HEAD、dependency DAG、concurrency 与 retry 上限；
2. `repository.lease.issue` 创建绑定一个 owner 与 pinned HEAD 的 ready、bounded
   lease；
3. `repository.result.accept` 将 `PASS` 或 `FAIL` 的 result digest 绑定到一个
   repository lease 与 attempt；
4. `repository.barrier.close` 只在所有 repository 通过后关闭 barrier；
5. `repository.integration.record` 绑定 integration result；
6. 明确请求 `repository.cancel` 时撤销 active lease。

repository ID 可从 `show` 读取。ordering 与 CAS 由 controller 管理。

### Effect recovery

workspace Git effect 使用 durable journal：

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" effect-inspect <task-id>

"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" effect-recover <task-id> \
  --execution-id <sha256> \
  --mode <settle|abandon|reattach|compensate> \
  --session-id <hook-injected-session-id>
```

recovery 会先验证 execution、journal binding、evidence 与 selected mode，并把
evidence digest 绑定到 confirmation request。可执行 mode 使用与 `apply` 相同的
durable request、后续 prompt decision、fresh projection 和 exact-retry
lifecycle；retry 会在与 live dispatch 相同的 per-execution fence 内重新读取并再次
证明 outcome。proof 发生变化或无法证明时，只返回 bounded operator intervention，
不会 settle 或 abandon effect。reattach 或 compensation 不可用时，controller 会在
请求 confirmation 之前直接返回 intervention。conversation agreement 不能证明
effect absence、settlement、receipt validity、reattachment 或 compensation；
recovery 也不会猜测结果或重新 dispatch uncertain effect。

## Codex integration

### Hook

packaged Hook 为 scope 内 task 注入准确的 controller/data-directory locator 和
current `agent-v1` projection，并明确标记注入的
`conversation_routing={session_id,request_turn_id}` 只用于 correlation，不是
authority。收到 `UserPromptSubmit` 时，它向 controller 的 confirmation observer
转发 bounded `session_id`、`turn_id`、`cwd` 与准确 prompt evidence；controller
根据 canonical cwd 推导 eligible active-task set，之后由 Hook 注入 refreshed
projection。Hook 不会选择或应用 action、dispatch effect 或写 task state。
malformed event 与 Hook 内部错误 fail open，但 guarded operation 保持 unapplied。

### MCP

optional `dev-flow-macos` MCP server 默认 disabled。启用后只公开：

- `task-start`
- `task-show`
- `task-next`
- `task-preflight`
- `action-apply`
- `effect-inspect`
- `effect-recover`

所有 mutation tool 与 CLI 调用同一个 controller method。

## Architecture

```text
src/dev_flow_orchestrator/
  product.py             唯一四 profile product matrix
  model.py               immutable schema-v4 value
  workflow.py            full、lite 与共享 repository node contract
  repository_kernel.py   pure DAG/lease/result/barrier logic
  engine.py              pure eligibility 与 mutation planning
  authority.py           durable conversation confirmation evidence
  controller.py          唯一 state writer 与 effect coordinator
  store.py               private lock/CAS/atomic persistence
  journal.py             durable effect outcome 与 recovery
  git_client.py          bounded Git read 与 workspace effect
  cli.py                 JSON CLI adapter
  mcp.py                 stdio MCP adapter
  hook.py                advisory、fail-open Hook

scripts/                 固定 public bootstrap 与 validator
skills/                  public workflow 与只读 guidance
hooks/hooks.json         Codex Hook registration
.mcp.json                optional macOS MCP registration
```

这些 direct Python module 就是完整的 runtime 与 workflow definition。

## Safety boundary

- state 为 private，并位于目标 repository 之外；
- 每次 mutation 都使用 revision CAS 与 atomic replace；
- external effect 使用 plan → dispatch → receipt → commit；
- uncertain effect 会 quarantine，并保证 single-dispatch；
- Git subprocess 使用 argument vector 与 bounded output；
- Hook 只提供 advisory，不具备写 task state 的 authority；
- confirmation data 只允许 local account 访问，并位于 repository 之外；
- unsafe permission、symlink、corruption、lock/write failure 或 capacity
  exhaustion 会让 guarded authority fail closed，且不会 automatic repair；
- Codex host 自己的 sandbox、filesystem 和 tool permission prompt 属于另一个
  boundary，本 plugin 不会 suppress 或 auto-confirm；
- 不提供自动 stash、reset、clean、commit、push、rebase、merge 或 force-push。

## 开发

见 [CONTRIBUTING.md](CONTRIBUTING.md)。本 repository 禁止 full test discovery，只
运行直接覆盖当前改动的 focused test module。

## License

见 [LICENSE](LICENSE)。
