# Dev Flow Orchestrator

兼容模型 0.4.0 用任务范围的自适应保障取代固定的测试与审查循环。每个任务拥有不可变的预检
起点和持续滚动的变更清单。封闭的 `dev-flow-assurance-policy/0.4.0` 仅根据当前契约、
经源码确认的影响闭包和八种封闭风险触发器，推导确有依据的仓库、集成、文档、人工
证据与独立审查义务。`degraded`、`partial` 或未知影响一律保守处理。
`assurance.dispatch` 每次只暴露一个当前可执行义务，记录绝对尝试次数，重启不会重置权限。

索引精确快照包含规范化的 stage 0–3 条目、mode、对象 ID、对象格式和工作树专属 Git
管理目录身份。源码动作必须精确认领控制器观察到的每个变更路径。未认领环境漂移、
未合并 stage、未解决的因果分诊、影响缺口、缺失的必需证据或预算耗尽都会阻止 `DONE`。
独立审查输出结构化的 `introduced`、`affected`、`pre-existing`、`out-of-scope` 或
`unknown` 发现；只有当前阻塞且具有任务因果关系的发现才会安排返工。切片及其治理输入
仍然有效时，可以复用互不相交的证据。

[English](README.md) · [安装说明](INSTALL_CN.md) · [路线图](ROADMAP_CN.md) ·
[架构](ARCHITECTURE_CN.md) · [贡献指南](CONTRIBUTING_CN.md)

**让 Codex 在跨会话、跨仓库开发中不丢状态、不偏离验收标准，并留下可验证的交付
证据。**

Codex 很擅长实现代码，但长时间任务可能在切换会话后丢失进度、逐渐偏离验收标准，
或者在验证不完整时结束。Dev Flow 在 Codex 外增加一个本地工作流控制器，从启动到
交接始终把需求、当前动作、仓库状态和交付证据保存在一起。

![Dev Flow 演示：涉及两个仓库的任务在 Codex 会话中断后恢复，并带着完整验证证据交付](docs/assets/demo.gif)

使用 Dev Flow，你可以：

- 在新 Codex 会话中恢复同一任务，不必重新拼凑上下文；
- 用一个需求协调由 1–8 个 Git 仓库组成的精确集合；
- 让实现始终绑定到明确、稳定的验收标准；
- 要求结构化验证与独立审查证据；
- 为每个未取消任务生成清晰的 `DONE` 或 `INCOMPLETE` Delivery Dossier。

## 60 秒示例

向 Codex 提供一个需求和必须协同的工作树：

```text
使用 $follow-dev-flow 跨下面两个仓库实现用户资料编辑：
- /后端仓库/路径
- /前端仓库/路径

验收标准：
1. 用户可以更新显示名称。
2. 无效名称会被拒绝。
3. 后端、前端和集成测试全部通过。
```

Dev Flow 会把它转化成一条可恢复路径：

```text
需求 -> 影响分析 -> 计划 -> 实施 -> 验证 -> 独立审查 -> Delivery Dossier
```

你可以随时关闭 Codex，再在新会话中通过任务 ID 精确恢复：

```text
使用 $follow-dev-flow 恢复任务 <任务-id>。
```

## 本地只读 Web UI

当前 Dev Flow 发布内置本地任务驾驶舱，它只是同一已安装产品的另一个展示界面，不具有
独立的 WebUI 版本、包、插件、状态命名空间或兼容性线路。通过以下命令启动和管理后台
进程：

```sh
dev-flow web start
dev-flow web status
dev-flow web open
dev-flow web restart
dev-flow web stop
```

`start` 只绑定数字地址 `127.0.0.1`，默认选择临时端口，并打印一条包含浏览器 URL 的
JSON 启动收据。`open` 只重新输出完整 URL，不会自动打开浏览器，可在页面刷新丢失启动
权限后恢复访问。`status`、`restart` 和 `stop` 仅管理与该数据根目录私有运行收据中的
PID、随机实例身份、产品身份、端口及 token 鉴权回环响应同时匹配的进程。原有 `web`
命令继续作为前台兼容模式。256 位进程本地访问令牌位于 URL fragment 中，浏览器将它
读入内存后从可见 URL 移除。服务器不会自动打开浏览器、启用 CORS、加载远程资源、发送
遥测，也不会在受管进程生命周期之外持久化浏览器选择或凭据。
安装后的启动器会自动解析
`<CODEX_HOME>/plugins/data/dev-flow-orchestrator-personal/0.4.0`。直接开发和恢复命令
仍可显式传入精确的 `--data-dir`。

任务清单和普通详情只从已持久化的 0.4.0 模型状态推导，因此仓库不可用时仍可立即查看，
且不会运行 Git。只有在需要当前动作就绪度或仓库健康时，才对选中的任务使用
**Observe live**。实时观察复用现有的有界只读聚合快照，全进程只允许一个捕获，并且
不会创建任务 binding，也不会改变控制器或仓库状态。

## 一条命令安装

当前 Dev Flow 发布支持 macOS，并要求 Git、Python 3.9–3.14 以及支持插件和 Hook
的 Codex：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

安装器会检查环境、克隆或更新源码、校验软件包、在 `PATH` 中现有的可写目录安装自有的
`dev-flow` 启动器、安全合并 personal marketplace 条目、
在插件未安装时完成安装、存在旧版本时完成升级，或通过重新安装修复当前版本。随后输出
包含执行类型、版本、本次涉及目录和第一条 Prompt 的安装收据。安装器默认自动选择目录；
需要指定一个已在 `PATH` 中的可写目录时可设置 `DEV_FLOW_BIN_DIR`。安装器以 `main` 为权威
源码 ref：首次安装会显式选择
`main`；已有源码必须具有预期的 origin、干净且已附着的 `main`，并且只能快进到本次
抓取的提交。其他分支、本地超前或分叉历史以及 Git 报告的本地改动都会停止安装，安装器
不会自动 switch、reset、stash 或 clean。快进也会拒绝覆盖发生路径冲突的 ignored 本地
内容，同时保留无关的 ignored 内容。如果你希望执行前检查所有步骤，请先阅读
[scripts/install.sh](scripts/install.sh)，或者使用[手动安装指南](INSTALL.md)。

标准输出连接交互式终端时，成功收据会使用霓虹终端配色。重定向输出、`TERM=dumb` 或
设置 `NO_COLOR` 时，同一收据会自动改为不含 ANSI 颜色代码的纯文本。

安装后新建 Codex 任务，在 `/hooks` 中检查并信任已安装 Hook，然后尝试：

```text
使用 $follow-dev-flow 在当前仓库启动一个 lite 任务：
<你的需求>
```

## 为什么不只用 Prompt、AGENTS.md 或 OpenSpec？

这些工具解决交付中的不同问题，并且可以组合使用。下表描述的是各自的主要职责，
不是性能评测：

| 交付问题 | 直接使用 Codex | `AGENTS.md` | OpenSpec | Dev Flow |
|---|---|---|---|---|
| 跨会话状态 | 对话/任务上下文 | 仓库级指导 | 带版本的变更工件 | 持久化控制器任务 |
| 多仓库协调 | 由 Prompt 定义 | 不是主要职责 | 规格范围 | 不可变的 1–8 仓库集合 |
| 验收标准 | 由 Prompt 定义 | 仅提供指导 | 规格工件 | 稳定 ID 与运行时证据绑定 |
| 验证 | 由 Agent 执行 | 可以规定命令 | 规格/变更校验 | 逐仓库与集成覆盖 |
| 最终交付记录 | 对话总结 | 无 | 变更归档 | 带新鲜度和缺口的 Delivery Dossier |

Dev Flow 不会替代指导文件或规格。它提供运行时状态、转换规则和证据链，把它们连接到
明确的交付结果。

## 它防止的三类常见交付失败

| 场景 | 需求 | 常见失败方式 | Dev Flow 执行路径 | 交付结果 |
|---|---|---|---|---|
| 跨会话恢复 | 关闭 Codex 后继续实现功能 | 新会话基于过期或残缺上下文重新推断进度 | 保存契约、工件、决策和权威下一动作；通过任务 ID 恢复 | 从已记录状态继续，并拒绝过期 binding |
| 多仓库变更 | 用一个需求同时修改 API 和前端 | 只验证一个仓库，遗漏另一个仓库或二者集成 | 启动时绑定精确仓库集合，要求成员结果与集成结果 | Dossier 展示每个成员和组合行为的证据 |
| 验证失败返工 | 测试或审查失败后修复 | 非正式重试后直接宣称完成 | 进入有界返工，并要求新的验证/审查证据 | 只有当前证据完整时才为 `DONE`，否则明确为 `INCOMPLETE` |

## Dev Flow 控制什么

Dev Flow 0.4.0 在由一至八个本地 Git 工作树组成的精确规范集合中提供完整的个人交付能力：

- 带版本的结构化交付契约，包含稳定的验收标准 ID、范围、约束、风险、非目标与
  未决事项；
- 六个官方工作流：`lite`、`feature`、`bugfix`、`investigation`、`refactor`
  和 `full`；
- 追加式契约修订，以及可归责的验收标准豁免或审查保障豁免；
- 带生产者元数据、契约绑定、逐仓库快照、聚合仓库集合绑定、输入血缘、摘要值和
  派生新鲜度的类型化工件；
- 自适应保障义务、绝对执行与源码返工预算，以及明确的 `DONE` 和 `INCOMPLETE` Dossier 结果；
- 可选的 OpenSpec、codebase-memory 和 `independent-review`（独立审查）driver
  路径，并显式记录降级或不可用结果；
- 可以从任意成员仓库通过同一个控制器和任务 ID 跨 Codex 会话恢复。

受支持的执行边界是一个任务、一个不可变仓库集合、一个当前动作和一个 Codex
执行者。仓库拓扑与工作流深度彼此独立：所有官方工作流都可绑定一个成员或最多八个
成员的精确集合。所有工作树由用户提前准备并持续拥有。控制器不会创建或切换
branch/worktree，不会协调并行 Agent、提交或发布 Git 变更、调度外部 CI，也不会
创建 PR。只有当证据的治理输入与影响闭包仍然有效，并且能够证明与后续任务自有改动
切片不相交时，控制器才会复用等价切片证据。产品没有外部发布 effect；任何 CI、PR 或
release 后续操作都由用户拥有并在 Dev Flow 之外完成。只要每个传入路径都是已初始化、
非裸 Git 工作树的精确根目录，脏工作树和 detached `HEAD` 都可以使用。

## 运行要求

- macOS；
- Python 3.9–3.14；
- Git，以及一至八个已经存在 `HEAD` 提交的目标工作树；
- 支持插件和 Hook 的 Codex。

运行时代码只使用 Python 标准库。OpenSpec、codebase-memory 和独立审查者是可选的
工作流能力；缺失时必须显式记录，不能静默提高保障等级。

## 手动安装

不使用一键安装器时，首次创建个人 marketplace：

```sh
mkdir -p "$HOME/plugins"
git clone --branch main --single-branch \
  git@github.com:Innocent-children/dev-flow-orchestrator.git \
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
Codex 任务，打开 `/hooks`，检查并信任已安装的 Hook 定义。替换安装、已安装验收、
排错和卸载请参阅 [INSTALL.md](INSTALL.md)。

## 一条命令卸载

完成或取消活动的 Dev Flow 任务后运行：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/uninstall.sh | sh
```

卸载器会移除自有的 PATH 启动器、Codex 插件、personal marketplace 中的对应条目和
安装器管理的干净源码 checkout。如果源码存在本地改动、ignored 路径、仅本地提交、
非预期 origin 或不同分支，
卸载器会拒绝删除。外部 Dev Flow 任务数据始终保留。如需保留源码 checkout，请传入
`--keep-source`：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/uninstall.sh | sh -s -- --keep-source
```

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

每个官方工作流都从覆盖完整仓库集合的有界、只读 Git 预检开始，并通过一个聚合
Delivery Dossier 0.4.0 收尾每个未取消结果。`dev-flow-workflow/0.4.0` 定义通过 `cancel.stages`
声明可取消阶段；官方工作流在大多数正常非终态阶段允许取消，并排除所有
`delivery.finalize` 阶段。自定义工作流必须是以绝对路径选择的有效 `dev-flow-workflow/0.4.0`
JSON 或 YAML 文档，其身份绑定 selector、schema 与规范化文档。仓库数量不会选择或
改变工作流。

如果 Codex 确认已接受的需求无法由任务的不可变仓库集合满足，它会停止当前投影动作，
并明确指出该确切任务仍处于活动状态。取消该任务仍需要用户的显式授权；只有控制器返回
`done: true`、`status: CANCELLED` 和 `current_node: cancelled` 后，Codex 才会报告
任务已经结束。取消失败或当前阶段不可取消时，不会替换成另一个仓库，也不会宣称任务已
进入终态。

## 启动与恢复

要求 Codex 使用明确的工作流、交付契约和一个或多个用户预备仓库根目录启动任务：

```text
使用 $follow-dev-flow 在下面两个预备工作树上启动一个 feature 任务：
/API仓库/绝对路径
/客户端仓库/绝对路径

为下面的工作创建结构化交付契约：
<要交付的工作>
```

CLI 每个成员重复一次 `--repo`。只传一次会通过同一准入与证据路径创建一成员仓库集合：

```text
<ctl> start --requirement <需求> --workflow feature \
  --repo /API仓库/绝对路径 \
  --repo /客户端仓库/绝对路径 \
  --contract-json <json对象>
```

调用顺序不表示优先级。创建任务前，控制器会规范化完整集合，并拒绝缺失、裸仓库、
重复、共享 Git identity、互相包含、不安全或与数据目录重叠的根目录。成员集合在任务
生命周期内不可变；需要改变仓库集合时必须新建任务。

契约 schema 为 `dev-flow-delivery-contract/0.4.0`。它仅包含 `schema`、`revision`、
`summary`、`acceptance_criteria`、`scope`、`constraints`、`risks`、
`non_goals` 和 `open_questions`，初始契约修订为 `1`。快速启动 `lite` 任务时，
省略 `--contract-json` 会从非空需求和完整仓库集合生成一个有界的最小契约。

保存返回的任务 ID。随后这样恢复：

```text
使用 $follow-dev-flow 恢复任务 <task-id>。
```

当前目录位于任意成员仓库内时，已安装 Hook 会重新接入同一任务；检查成员下的嵌套
路径时，同一任务只返回一次，多个活动任务仍保持显式歧义。Hook 注入的 locator 已经
包含已安装 launcher、CLI 和精确的 0.4.0 数据目录。Skill 通过 `next` 获取一个带
`repository_set` 摘要的 `dev-flow-agent/0.4.0` 投影，执行其中唯一的当前动作，再通过
`apply --binding-json` 原样传回 `projection.action.binding`。binding 固定任务修订、
契约、输入、源码前驱和聚合起始快照；过期工作会被拒绝，并返回新投影。一成员集合在
`repository_set.repositories` 中只有一个条目，其余结构完全相同。

## 证据、决策与完成

`dev-flow-workflow/0.4.0` 工件声明一种工作区角色：

- `context` 记录只读分析；
- `produces-source` 消费固定的源码前驱，并记录后继工作树快照；
- `verifies-source` 必须精确观察最新的源码权威。

输入血缘使用 `governing`、`source-predecessor` 或 `causal`。治理型仓库资源参与
新鲜度计算；报告型资源只保留来源。每项仓库资源必须带显式 `repository_id`，因此不同
成员中的相同相对路径仍保持独立。OpenSpec 的 proposal、design 和 spec 文件属于
治理资源。`tasks.md` 会以原始报告进度记录一次，并以 `openspec-tasks/0.4.0` 语义
normalizer 再记录一次；后者只忽略复选框状态。

验证对所有集合大小统一使用 `dev-flow-verification-coverage/0.4.0` 契约，包含精确的
当前 `schema`、`criteria`、`repositories` 和 `integration` 对象：每个成员和集成命令都必须存在，
顶层命令必须等于集成命令，顶层 `passed` 必须是所有成员与集成结果的合取。验证必须
把每项验收标准报告为
`proven` 或 `unverified`。只有当前显式的 `criterion-waiver` 决策才能派生 `waived`。
审查批准要求独立保障。独立审查不可用时，
自审可以记录发现，但不能宣称批准；只有精确约束当前审查节点的
`assurance-waiver` 才能让不可用结果走成功路径。否则，有界返工最终生成
`INCOMPLETE` Dossier。

后续契约修订会记录完整替代契约、理由和操作主体标签。同一条记录把完整当前仓库集合
捕获为新契约的聚合 `revision-source`，并让工作流回到已声明的影响分析或实施入口。
修订不能添加、删除、重排或移动成员。更早的工件继续作为不可变历史证据保留，不能
满足修订后的范围。

`show <task-id>` 暴露完整的只读 ledger 和 Dossier。终态
`dev-flow-delivery-dossier/0.4.0` 包含有效契约、仓库集合身份与规范成员清单、验收覆盖、
当前结构化验证、审查保障、文档证据、决策、工件来源与新鲜度、逐成员基线/最终摘要、
变更成员诊断、带仓库范围的资源、剩余风险、结果、移交建议，以及每次当前或已过期的
验证和审查尝试。
若某个成员当前无法抓取，`show` 仍返回已存 ledger 和 Dossier；
`current_snapshot` 与 `artifact_freshness` 此时不可用，`snapshot_error` 会指出
被阻塞的成员。

## 状态与安全

- 控制器是唯一任务状态写入者。状态使用锁、修订 compare-and-swap、确定性重放和
  原子替换。
- 任务状态位于每个目标仓库之外。已安装的 Dev Flow 0.4.0 Hook 使用 `<PLUGIN_DATA>/0.4.0`，并保护
  插件数据根目录，避免常见 shell 和编辑操作直接写入。
- 仓库快照有边界限制、内容敏感并且只读；仓库集合以全有或全无方式捕获。规范成员
  缺失或移动时，依赖仓库的进度会停止且不修改 ledger；恢复同一精确根目录后再重试，
  控制器不会替换成其他工作树。控制器不会自动执行 stash、reset、clean、
  commit、checkout、rebase、merge、push、force-push，也不会删除用户工作。
- Hook 是内部错误时放行的操作护栏。工作流校验和状态转换权威仍属于控制器。
- 所有集合大小统一使用 `dev-flow-repository-set-snapshot/0.4.0`、
  `dev-flow-agent/0.4.0`、带仓库范围的资源、结构化成员/集成验证与 Delivery Dossier 0.4.0。
  每个聚合快照按规范顺序嵌套每位成员的一个 `dev-flow-workspace-snapshot/0.4.0` 值。

## 更多文档

- [INSTALL.md](INSTALL.md)：安装、替换、已安装验收和排错。
- [ARCHITECTURE.md](ARCHITECTURE.md)：契约、`dev-flow-workflow/0.4.0`、binding、血缘、重放、
  投影和模块职责。
- [ROADMAP_CN.md](ROADMAP_CN.md)：已交付的阶段 1 能力与后续产品阶段。
- [CONTRIBUTING.md](CONTRIBUTING.md)：聚焦校验与贡献规则。
- [docs/PROMOTION.md](docs/PROMOTION.md)：可直接使用的 About、Release、社区发布
  文案和推广检查清单。
- [LICENSE](LICENSE)：许可证条款。

## 原生 Windows 集成预览

当前候选版本为 Windows 10 22H2 x64 和 Windows 11 x64 客户端提供同一产品的原生
集成：`.cmd` Hook 启动器、成对的 `commandWindows` 定义、兼容 PowerShell 5.1/7
的生命周期脚本、同一个 Controller 与只读 Web UI，以及聚焦的 Windows 自动化。
它要求受支持的 64 位 CPython 3.9–3.14、Git for Windows、Codex 插件/Hook 支持、
PowerShell 和普通本地仓库。

在已检查的签出中执行 `powershell -ExecutionPolicy Bypass -File
.\scripts\install.ps1`。安装插件不会自动信任命令 Hook。请启动新的 Codex 会话，打开
`/hooks`，审查精确的已安装定义并予以信任，然后再依赖自动任务恢复或 guardrail。

Windows ARM64、32 位 Python、Windows Server、WSL 执行、UNC/SMB/NAS 和映射网络
仓库、`\\wsl$`、历史迁移及跨操作系统任务转移均不在边界内。托管 Windows Server CI
只属于实现证据；在记录的 Windows 11 完整旅程与 Windows 10 22H2 smoke 通过之前，
公开的客户端支持声明仍为预览。
