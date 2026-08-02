# Dev Flow Orchestrator

[English](README.md) · [安装说明](INSTALL.md) · [路线图](ROADMAP_CN.md) ·
[架构](ARCHITECTURE.md) · [贡献指南](CONTRIBUTING.md)

Dev Flow Orchestrator V6 是面向 Codex 的本地优先交付控制器。它把一项软件需求
转化为可恢复、以证据为支撑的任务，并且每次只投影一个权威的下一动作。Codex
执行实际工作；控制器保存交付契约、工作流状态、决策、类型化工件、保障证据和最终的
Delivery Dossier。

## 当前产品

V6 在一个 Git 仓库内提供完整的个人交付能力：

- 带版本的结构化交付契约，包含稳定的验收标准 ID、范围、约束、风险、非目标与
  未决事项；
- 六个官方工作流：`lite`、`feature`、`bugfix`、`investigation`、`refactor`
  和 `full`；
- 追加式契约修订，以及可归责的验收标准豁免或审查保障豁免；
- 带生产者元数据、契约绑定、仓库快照、输入血缘、摘要值和派生新鲜度的类型化工件；
- 有界验证与审查返工，以及明确的 `DONE` 和 `INCOMPLETE` Dossier 结果；
- 可选的 OpenSpec、codebase-memory 和 `independent-review`（独立审查）driver
  路径，并显式记录降级或不可用结果；
- 通过同一个控制器和任务 ID 跨 Codex 会话恢复。

受支持的执行边界是一个任务、一个仓库、该仓库的当前工作树和一个 Codex 执行者。
控制器不会创建或切换 branch/worktree，不会协调并行 Agent，也不会跨仓库运行。
只要传入的路径是一个已初始化、非裸 Git 工作树的精确根目录，脏工作树和
detached `HEAD` 都可以使用。

## 运行要求

- macOS；
- Python 3.9–3.14；
- Git，以及已经存在 `HEAD` 提交的目标工作树；
- 支持插件和 Hook 的 Codex。

运行时代码只使用 Python 标准库。OpenSpec、codebase-memory 和独立审查者是可选的
工作流能力；缺失时必须显式记录，不能静默提高保障等级。

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

只有 `~/.agents/plugins/marketplace.json` 不存在时才执行 `cp`。如果文件已经存在，
请把 `templates/marketplace-entry.json` 合并到它的 `plugins` 数组中。安装后新建
Codex 任务，打开 `/hooks`，检查并信任已安装的 Hook 定义。升级、V5 数据保留与
回滚检查、已安装验收、排错和卸载请参阅 [INSTALL.md](INSTALL.md)。

## 选择工作流

日常使用通过 `$follow-dev-flow` 完成。

| 工作流 | 交付路径 | 保障预算 |
|---|---|---|
| `lite` | 预检 → 实施 → 验证 → Dossier | 2 次验证尝试 |
| `feature` | 影响分析 → 仓库内计划 → 实施 → 文档 → 验证 → 独立审查 → Dossier | 2 次验证与 2 次审查尝试 |
| `bugfix` | 问题诊断 → 仓库内修复计划 → 实施 → 文档 → 回归验证 → 独立审查 → Dossier | 2 次验证与 2 次审查尝试 |
| `investigation` | 影响分析 → 调查报告 → 验证 → Dossier | 2 次验证尝试；不虚构实施工件 |
| `refactor` | 结构影响 → 带不变量的计划 → 实施 → 文档 → 验证 → 独立审查 → Dossier | 2 次验证与 2 次审查尝试 |
| `full` | 完整影响分析与规划 → 实施 → 文档 → 验证 → 独立审查 → Dossier | 3 次验证与 3 次审查尝试 |

每个官方工作流都从有界、只读的 Git 预检开始，允许在每个未完成阶段显式取消，
并通过 Delivery Dossier 收尾每个未取消结果。启动新的 V6 任务时，也可以传入有效的
线性 workflow-v1 JSON 或 YAML 文件绝对路径；所选定义和适配器身份会固定到该任务。

## 启动与恢复

要求 Codex 使用明确的仓库、工作流和交付契约启动任务：

```text
使用 $follow-dev-flow 在下面的仓库启动 feature 任务：
/仓库/绝对路径

为下面的工作创建结构化交付契约：
<要交付的工作>
```

契约 schema 为 `dev-flow-delivery-contract/v1`。它仅包含 `schema`、`revision`、
`summary`、`acceptance_criteria`、`scope`、`constraints`、`risks`、
`non_goals` 和 `open_questions`，初始契约修订为 `1`。快速启动 `lite` 任务时，
省略 `--contract-json` 会从非空需求生成一个有界的最小契约。

保存返回的任务 ID。随后这样恢复：

```text
使用 $follow-dev-flow 恢复任务 <task-id>。
```

当前目录位于任务仓库内时，已安装 Hook 会重新接入任务。Hook 注入的 locator 已经
包含已安装 launcher、CLI 和精确的 V6 数据目录。Skill 通过 `next` 获取新的
`dev-flow-agent-v2` 投影，执行其中唯一的动作，再通过 `apply --binding-json` 原样
传回 `projection.action.binding`。binding 固定任务修订、契约、输入、源码前驱和
起始工作区快照；过期工作会被拒绝，并返回新投影。

## 证据、决策与完成

workflow-v2 工件声明一种工作区角色：

- `context` 记录只读分析；
- `produces-source` 消费固定的源码前驱，并记录后继工作树快照；
- `verifies-source` 必须精确观察最新的源码权威。

输入血缘使用 `governing`、`source-predecessor` 或 `causal`。治理型仓库资源参与
新鲜度计算；报告型资源只保留来源。OpenSpec 的 proposal、design 和 spec 文件属于
治理资源。`tasks.md` 会以原始报告进度记录一次，并以 `openspec-tasks-v1` 语义
normalizer 再记录一次；后者只忽略复选框状态。

验证必须把每项验收标准报告为 `proven` 或 `unverified`。只有当前显式的
`criterion-waiver` 决策才能派生 `waived`。审查批准要求独立保障。独立审查不可用时，
自审可以记录发现，但不能宣称批准；只有精确约束当前审查节点的
`assurance-waiver` 才能让不可用结果走成功路径。否则，有界返工最终生成
`INCOMPLETE` Dossier。

后续契约修订会记录完整替代契约、理由和操作主体标签。同一条记录把当前工作树捕获为
新契约的 `revision-source`，并让工作流回到已声明的影响分析或实施入口。更早的工件
继续作为不可变历史证据保留，不能满足修订后的范围。

`show <task-id>` 暴露完整的只读 ledger 和 Dossier。终态 Dossier 包含有效契约、
验收覆盖、当前验证、审查保障、文档证据、决策、工件来源与新鲜度、仓库快照、
剩余风险、结果和移交建议。

## 状态、安全与兼容性

- 控制器是唯一任务状态写入者。状态使用锁、修订 compare-and-swap、确定性重放和
  原子替换。
- 任务状态位于目标仓库之外。已安装的 V6 Hook 使用 `<PLUGIN_DATA>/v6`，并保护
  插件数据根目录，避免常见 shell 和编辑操作直接写入。
- 仓库快照有边界限制、内容敏感并且只读。控制器不会自动执行 stash、reset、clean、
  commit、checkout、rebase、merge、push、force-push，也不会删除用户工作。
- Hook 是内部错误时放行的操作护栏。工作流校验和状态转换权威仍属于控制器。
- V5 任务数据原样保存在 `<PLUGIN_DATA>/v5`。V6 不读取也不迁移这些数据。检查或恢复
  V5 任务必须使用保留的 V5 软件包快照及其 V5 控制器 locator。

## 更多文档

- [INSTALL.md](INSTALL.md)：安装、V5 到 V6 升级与回滚检查、已安装验收和排错。
- [ARCHITECTURE.md](ARCHITECTURE.md)：契约、workflow-v2、binding、血缘、重放、
  投影和模块职责。
- [ROADMAP_CN.md](ROADMAP_CN.md)：已交付的阶段 1 能力与后续产品阶段。
- [CONTRIBUTING.md](CONTRIBUTING.md)：聚焦校验与贡献规则。
- [LICENSE](LICENSE)：许可证条款。
