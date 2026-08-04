# 架构

[English](ARCHITECTURE.md)

Dev Flow Orchestrator 0.2.0 是一个仅使用 Python 标准库的包，包含一个控制器状态变更边界、一个只追加的交付账本和声明式工作流定义。它支持在由用户预先准备的一到八个本地 Git 工作树组成的精确规范集合上执行一个任务，并始终只有一个当前动作和一个 Codex 执行器。

## 依赖方向

```text
CLI ─┐
Hook ┴─> Controller ─┬─> Engine ─> Delivery ─> Model
                    │       └────> Workflow ─> Product
                    ├─> Store ───> Engine
                    │      └─────> Filesystem primitives
                    ├─> Workflows ─> yaml_subset
                    └─> GitClient (bounded, read-only)
```

领域层 (`model.py`, `product.py`, `snapshot.py`, `workflow.py`, `delivery.py` 和 `engine.py`) 不执行任何文件系统、进程、环境或网络 I/O。
`workflows.py` 加载打包或选择的定义。`GitClient` 是唯一的目标仓库检查端口，为每个任务成员串行调用。
驱动程序是 Codex 在控制器外执行的指令；运行时仅验证并记录其声明的结果。

## 模块所有权

| 模块 | 所有者 |
|---|---|
| `product.py` | 0.2.0 任务/工作流/目录/记录/工件/投影的身份，六个官方工作流 ID，以及权威的 1–8 仓库拓扑能力 |
| `model.py` | 不可变的任务值和规范的仓库成员资格、规范 JSON、稳定错误、零修订初始化、收据 |
| `snapshot.py` | 聚合仓库集快照和嵌套成员工作区快照验证、查找和摘要处理 |
| `workflow.py` | `dev-flow-workflow/0.2.0` 验证，节点/工件/输入/重做/取消合同，图安全，所选定义身份 |
| `delivery.py` | 交付合同验证、摘要和封印、决策、动作绑定、输入解析、新鲜度、覆盖范围、档案生成 |
| `engine.py` | 负载验证、动作规划、账本记录、保障路由、修订重放、转换验证、投影和任务视图 |
| `workflows.py` | 官方目录解析和绝对自定义定义加载 |
| `yaml_subset.py` | 严格 JSON/YAML 子集解析并限制错误 |
| `git_client.py` | 内容敏感的只读仓库和资源快照 |
| `store.py` | 私有任务路径、锁、修订 CAS、重放验证、原子替换 |
| `controller.py` | 应用协调和创建后的所有状态变更 |
| `cli.py` | 严格的 argv/JSON 接口，每个命令一个 JSON 响应 |
| `hook.py` | 活动任务查找、精确定位器注入以及出错时放行的数据路径防护 |

## 当前产品身份

`PRODUCT_IDENTITY` 封闭了完整的当前权威：任务、记录、工件、动作绑定、仓库集快照、嵌套工作区快照、工作流、代理、验证覆盖范围、交付档案、数据命名空间和 1–8 的仓库拓扑。如果存储的产品身份与当前不符，则拒绝该任务。

| 表面 | 当前身份边界 |
|---|---|
| 产品版本 | `0.2.0`，任务身份，数据命名空间 `0.2.0` 和精确拓扑权威 |
| 工作流语言 | `dev-flow-workflow/0.2.0`，版本 `0.2.0` |
| 所选工作流 | 选择器、模式和规范所选文档的摘要 |
| 官方目录 | 排序后官方 ID 的摘要；目录身份与任务所选工作流是独立的 |
| 记录、工件和绑定 | 每个值的当前规范模式和摘要封印 |
| Agent 投影 | `dev-flow-agent/0.2.0`，带有一个 `repository_set` 和一个当前动作 |
| 验证覆盖范围 | 精确 `schema: dev-flow-verification-coverage/0.2.0`，包含 `criteria`, `repositories`, 和 `integration` |
| 仓库快照 | `dev-flow-repository-set-snapshot/0.2.0`，每个成员包含一个 `dev-flow-workspace-snapshot/0.2.0` |
| 交付档案 | `dev-flow-delivery-dossier/0.2.0` |

0.2.0 Hook 和控制器使用 `<PLUGIN_DATA>/0.2.0` 来存储当前任务状态。

## 仓库集边界

`start` 接受一到八个重复的 `--repo` 值。控制器将每个值解析为现有非裸 Git 工作树的确切规范根目录，拒绝重复根目录、重叠根目录、共享 Git 公共目录和数据目录重叠，然后按规范路径和仓库 ID 对生成的 `{id, path}` 记录进行排序。调用者顺序无语义意义。
`TaskState.repositories` 是唯一持久化的成员资格权威；其派生的 `repository_set_id` 并不是第二个可变副本。在修订零之后不能添加、移除、替换、移动或重新排序成员。

每个成员工作树都由用户准备并拥有。控制器不创建或切换分支/工作树，发布 Git 更改，运行并行代理，或操作外部 CI、PR 或发布系统。一个 Codex 在完整集合上执行投影动作。Hook 可以从任意成员根目录发现任务，但拒绝模糊匹配。缺少或移动的成员会阻止所有依赖仓库的突变操作，且无部分证据；存储的账本检查在精确持久化根恢复之前始终可用。

## 交付合同和账本

任务创建以原子方式写入修订版零状态，包含不可变的原始 `dev-flow-delivery-contract/0.2.0` 和一个空记录元组。显式合同恰好包含：

```json
{
  "schema": "dev-flow-delivery-contract/0.2.0",
  "revision": 1,
  "summary": "交付请求的行为",
  "acceptance_criteria": [
    {"id": "C1", "statement": "可观察的验收条件"}
  ],
  "scope": ["包含的工作"],
  "constraints": [],
  "risks": [],
  "non_goals": [],
  "open_questions": []
}
```

仅要求启动推导出有界最小修订版一合同。每次后续成功的变异恰好追加一个密封的 `dev-flow-record/0.2.0`；类型化输出使用密封的 `dev-flow-artifact/0.2.0` 描述符。每次变异精确增加任务修订一次，保留：

```text
任务修订 == 记录数量
```

第一个非取消记录是完整不可变仓库集的预检。入口阶段显式声明的取消可能是唯一的任务记录。工作流操作、合同修订、决策和取消共享同一账本。回放在状态被接受之前验证记录密封、工作流转换、固定定义身份、只追加历史和每个修订一个记录不变量。

合同修订在预检后可用。其记录包含完整的下一个合同、原因、行动者标签、转换，以及作为新合同 `revision-source` 艺术品公开的安全当前快照。这始终是一个聚合快照和一条记录；没有成员单独提交。工作流的 `revision_target` 选择重新进入（计划工作流使用 `impact`，`lite` 使用 `implement`）。此修订源是跨越合同摘要的唯一源桥。

决策记录保持任务唯一 ID 和绑定种类、主题、结果、理由、行动者标签和有效合同。标准宽免针对确切的验收 ID。保障宽免针对确切的工作流节点，其处理程序为 `review.record`（官方节点 ID 为 `review`）。每个合同摘要接受一个 `(种类, 主题)` 对。

## 工作流定义

官方定义使用 `dev-flow-workflow/0.2.0`，版本为 `0.2.0`。目录包括 `bugfix`、`feature`、`full`、`investigation`、`lite` 和 `refactor`。自定义工作流通过绝对 JSON/YAML 路径选择，并通过与官方定义相同的 0.2.0 工作流验证和选定身份计算。

一个 `dev-flow-workflow/0.2.0` 文档声明 `entry`、`revision_target`、`nodes` 和一个非空、唯一的 `stages` 列表共享的 `cancel` 操作。只有当前节点出现在该列表中时才可取消。官方工作流列出正常多数非终止阶段并省略每个 `delivery.finalize` 节点。每个非终止节点有一个正常目标。仅 `verification.record` 和 `review.record` 可添加有限失败路径和耗尽路径。

### 节点合同

| 字段 | 规则 |
|---|---|
| `action_id` | 通过投影选择的唯一动作 |
| `handler` | `preflight`、`artifact.record`、`verification.record`、`review.record` 或 `delivery.finalize` |
| `target` | 正常 `{node, status}` 转换 |
| `payload` | 精确所需的字段到类型映射；未知或缺失字段失败 |
| `artifact` | 0.2.0 工作流动作节点所需 `{type, workspace, inputs}` 声明 |
| `rework` | 仅保障的 `{failure, max_attempts, exhausted}` 合同 |
| `finalize` | 在 `delivery.finalize` 节点上为 `success` 或 `incomplete` |
| `driver` | 不透明的能力元数据，包括可选回退和生成的艺术品 |
| `effect` | 预检使用 `git.inspect-repository`；其他地方为 `none` |
| `writes` | 如果存在，必须等于处理程序派生的 0.2.0 记录写集 |
| `terminal` | `true` 定义无动作汇 |

顶层 `cancel.stages` 列表只能包含声明的非终止节点 ID。其共享操作使用 `artifact.record`、精确的 `reason: string` 载荷和 `CANCELLED` 终止目标。

载荷类型为 `string`、`boolean`、`integer`、`object` 和 `sha256`。验证需要一个预检条目、唯一动作 ID、可达节点、有效终止档案路径和带有 `CANCELLED` 的取消目标。删除所有有限保障失败边必须留下无环图，因此每个可能的重做循环消耗一个声明的尝试预算。

### 艺术品血统

每个 `dev-flow-workflow/0.2.0` 艺术品声明一个工作区角色：

- `context`：只读分析，不能授权工作树更改；
- `produces-source`：精确地固定一个 `source-predecessor`，然后原子记录后续快照；
- `verifies-source`：验证、审查和最终确定观察最新的源权威。

输入边携带不同语义：

- `governing` 选择其类型的最新当前艺术品并传播替换或资源陈旧性；
- `source-predecessor` 识别由源生成动作有意消耗的源权威；
- `causal` 保留促使重做的失败验证或审查，而不使该地址失败成为当前完成证明。

艺术品封装包含类型、模式和摘要、生产者动作/节点和尝试、有效合同修订/摘要、工作区角色、观察到的仓库快照、解析的输入记录/艺术品摘要、绑定资源和有界正文内容。控制器推导来源字段；操作载荷不提供这些。

### 仓库资源和新鲜度

每个基于仓库的观察使用 `dev-flow-repository-set-snapshot/0.2.0`。它包装每个规范仓库的一个完整验证 `dev-flow-workspace-snapshot/0.2.0`；其聚合摘要覆盖集 ID、有序 ID 和完整的嵌套快照。一个成员集包含一个嵌套成员并使用相同的封装器。两步捕获必须作为一个整体稳定，否则变异不记录任何内容。

源生成计划载荷可声明相对于仓库的资源。每个项目需要 `repository_id`：

```json
{
  "items": [
    {"repository_id": "repo-api", "path": "openspec/changes/example/proposal.md", "role": "governing", "normalizer": "none"},
    {"repository_id": "repo-api", "path": "openspec/changes/example/tasks.md", "role": "governing", "normalizer": "openspec-tasks/0.2.0"},
    {"repository_id": "repo-docs", "path": "openspec/changes/example/tasks.md", "role": "reported", "normalizer": "none"}
  ]
}
```

资源身份是 `(repository_id, path, role, normalizer)`。未知成员 ID、绝对或逃逸路径、跨根解析和重复作用域键失败；不同成员中的等效相对路径保持独立。`governing` 摘要参与艺术品新鲜度，即使对于 Git 清洁文件也如此。`reported` 摘要保留来源。`openspec-tasks/0.2.0` 仅标准化 Markdown 任务复选框标记；文本、排序和测试义务仍为治理字节。

新鲜度源自不可变历史加上当前安全任务快照。对于仓库集，任何成员中的漂移保守地使聚合源、验证、审查和档案证据陈旧。当前核心不重用未更改成员的保障。合同变更、缺失或替换输入、更改治理资源、更新源生成器、工作区漂移和被取代的艺术品类型产生明确陈旧原因。陈旧证据仍可见，但不包括在当前覆盖率和成功最终确定中。

## 动作绑定和状态变更边界

`next` 在工作开始前解析输入并发出一个密封的
`dev-flow-action-binding/0.2.0`，其中包含：

- 任务 ID 和任务修订；
- 操作和节点 ID；
- 有效的合同修订和摘要；
- 类型化的输入记录、记录摘要、工件摘要、快照摘要和边类型；
- 当声明时的源前驱；
- 起始聚合仓库集快照摘要；
- 绑定摘要。

每个 `apply` 必须返回带有 `--binding-json` 的确切对象。控制器加载状态和固定的定义，验证操作/载荷，捕获请求的资源和应用时间快照，锁定并重新加载，执行修订 CAS，验证绑定和谱系，附加一个密封记录，验证重放，并原子性地替换状态。

```text
next → 固定操作绑定 → 执行一个操作 → 使用绑定进行应用
     → 快照/谱系/CAS 验证 → 附加记录 → 新鲜投影
```

上下文和验证操作要求当前快照的每个成员等于绑定的起始快照。源生成操作可以更改用户拥有的工作树的任意子集，并将一个完整的前驱快照链接到一个完整的后继快照。并发推进返回 `REVISION_CONFLICT`，并带有 `error.details.projection`；调用者获取新的 `next` 操作，并且不重放过时的工作。

## 保障和交付档案

验证记录 `passed`、非空命令、摘要以及每个当前标准的覆盖情况（作为 `proven` 或 `unverified`）。当前标准豁免派生出 `waived`。成功覆盖仅包含已证明或已豁免的标准。

覆盖始终使用 `dev-flow-verification-coverage/0.2.0` 合同，具有精确的 `schema`、`criteria`、`repositories` 和 `integration` 字段。
仓库映射完全覆盖规范成员 ID；每个成员和集成结果仅包含非空的 `command` 和布尔值 `passed`。顶层命令等于集成命令，顶层 `passed` 等于所有成员和集成结果的合取。命令成功但存在未验证、未豁免的标准是良好结构化的失败保障尝试，并消耗有限的返工路径。

审查记录结果（`approved`、`changes-requested` 或 `unavailable`）和保障（`independent` 或 `self`）。独立批准成功。不可用审查仅在对该审查节点具有精确当前保障豁免时才成功。其他结果遵循有限返工或耗尽路径。尝试按节点 ID 和有效合同摘要计数，因此合同修订为其新作用域启动完整的声明预算。

`delivery.finalize` 在纯领域层内生成权威的
`dev-flow-delivery-dossier/0.2.0` 内容。它包含集合身份、规范成员基线/最终摘要、变更成员诊断、范围资源、所有验证和审查尝试、当前结构化验证，以及聚合新鲜度。成功的最终化需要完整集合的新鲜通过证据、完整当前覆盖情况，以及任何声明的审查输入包含独立批准或精确豁免。耗尽路径生成一个聚合 `INCOMPLETE` 档案，其中包含未解决的成员/集成详情、覆盖情况和保留的失败保障。

## Agent 投影和任务视图

`next` 返回紧凑的 `dev-flow-agent/0.2.0` JSON，每个集合大小有一个 `repository_set` 和一个当前操作（此处缩写）：

```json
{
  "schema": "dev-flow-agent/0.2.0",
  "task_id": "task-example",
  "revision": 3,
  "workflow": {"id": "lite", "version": "0.2.0", "schema": "dev-flow-workflow/0.2.0"},
  "status": "VERIFYING",
  "current_node": "verify",
  "contract": {"revision": 1, "digest": "<sha256>", "summary": "...", "criterion_ids": ["C1"]},
  "repository_set": {
    "id": "<derived-set-id>",
    "digest": "<aggregate-snapshot-digest>",
    "repositories": [
      {"id": "repo-api", "path": "/absolute/api", "snapshot": {"digest": "<sha256>"}},
      {"id": "repo-client", "path": "/absolute/client", "snapshot": {"digest": "<sha256>"}}
    ]
  },
  "freshness": {},
  "action": {
    "action_id": "verification.record",
    "payload": {"passed": "boolean", "command": "string", "coverage": "object", "summary": "string"},
    "inputs": [],
    "binding": {"schema": "dev-flow-action-binding/0.2.0", "digest": "<sha256>"},
    "retry_budget": {"attempts_used": 0, "max_attempts": 2, "remaining": 2},
    "verification_coverage": {"fields": ["criteria", "repositories", "integration"]}
  },
  "dossier": null,
  "done": false
}
```

单成员任务使用此确切封装，其中 `repository_set.repositories` 中有一个项目。

终端投影将 `action` 设置为 `null`、`done` 设置为 `true`，并公开紧凑的档案摘要。`show` 返回完整的只读任务状态、有效合同、当前聚合快照、工件新鲜度和档案摘要；完整档案内容仍存在于其账本工件中。如果实时聚合捕获失败，则存储的状态和档案仍然可用，而当前快照和新鲜度为 `null` 且 `snapshot_error` 标识被阻塞的成员。

## 持久化和公开引导

```text
<PLUGIN_DATA>/
  0.2.0/
    tasks/<task-id>/state.json
    locks/<task-id>.lock
```

私有目录和文件使用仅本地账户权限。状态路径不能与目标仓库重叠。符号链接和格式错误的状态失败关闭；写入使用任务锁和原子替换。

`scripts/dev_flow_python_launcher` 选择支持的解释器并运行固定的 CLI 或 Hook 引导。Hook 注册 `SessionStart`、`UserPromptSubmit` 和 `PreToolUse`，注入确切安装的 0.2.0 定位器和新鲜投影，并保护对插件数据根目录的直接写入。Hook 内部错误失败开放且从不修改任务状态。
