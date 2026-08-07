# 安装 Dev Flow Orchestrator

Dev Flow 兼容模型 0.4.0 是一次干净的协议切换。已安装控制器必须使用精确的
`<PLUGIN_DATA>/0.4.0` 目录。可以为操作者参考保留 `<PLUGIN_DATA>/0.2.0` 字节，但
0.4.0 模型运行时不会发现、加载、迁移、修复或修改它们；显式提供的 0.2 schema 或状态不受支持。

启动任务前由用户自行准备每个 Git 工作树。准入为每个规范根目录和工作树专属 Git
管理目录创建一个活动租约；不同任务的不同 linked worktree 可以共享 Git 公共目录。
源码动作期间提交精确的 `dev-flow-task-change-claims/0.4.0`。执行
`assurance.execute` 时只遵循 `current_obligation` 及其证据契约，不得重建 binding、
plan ID、finding、计数器或审查结论。

[English](INSTALL.md)

本指南从本地 Codex 市场安装当前 Dev Flow Orchestrator 发布，并验证已安装的启动器、Hook、技能和控制器路径。

安装后的核心使用兼容模型 0.4.0，在由用户预先准备的一到八个 Git 工作树组成的精确规范集合上运行一个本地任务，并始终将一个当前动作投影给一个 Codex 执行器。它不会创建或切换分支/工作树、发布 Git 更改、协调并行 Agent、调用外部 CI/PR/Release 系统，也不会复用未变更仓库成员的部分保障。

## 快速安装

在支持的 macOS 主机上，使用一条命令从公共仓库安装：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

该脚本检查 macOS、Git、Python 3.9–3.14 和 Codex CLI；克隆或快进 `$HOME/plugins/dev-flow-orchestrator`；验证完整候选版本；保留其他个人市场条目，同时替换任何 Dev Flow 条目；在插件未安装时完成安装、存在旧版本时完成升级，或通过重新安装修复当前版本；并打印包含执行类型、版本、本次涉及目录和第一个提示的安装收据。如果您不想将远程脚本直接传递给 `sh`，请在运行前查看 [`scripts/install.sh`](scripts/install.sh)。

安装器会选择 `PATH` 中第一个可写的绝对目录，并在其中创建带所有权标记的 `dev-flow`
启动器，因此无需修改 shell 启动文件即可立即使用该命令。安装器拒绝覆盖该路径上的非
Dev Flow 文件。需要指定目录时，可将 `DEV_FLOW_BIN_DIR` 设置为一个可写的 `PATH`
目录。卸载器使用相同的选择规则，并且只删除包含精确 Dev Flow 所有权标记的启动器。

标准输出连接交互式终端时，成功收据会使用霓虹终端配色。重定向输出、`TERM=dumb` 或设置 `NO_COLOR` 时，同一收据会自动改为不含 ANSI 颜色代码的纯文本。

安装程序将 `main` 视为其不可配置的权威源引用。全新安装会显式选择 `main`。现有源只有在其来源与配置的仓库 URL 匹配、附加分支为干净的 `main`，且当前提交等于或可以快进到获取的 `main` 提交时才会继续。快进拒绝覆盖与传入 `main` 冲突的被忽略本地路径，但保留无关的被忽略内容。它拒绝其他分支、分离 HEAD、报告的本地更改、本地领先历史、分歧或非 Git 路径（不切换、重置、储藏、清理或覆盖签出）。

一键安装器会自动卸载并重新安装已有插件。如果 Codex 因存在活动的 Dev Flow 任务而拒绝卸载，请完成或明确取消这些任务，然后重新运行同一命令。其余部分手动记录相同过程并提供完整的安装接受检查。

## 启动本地只读 Web UI

已安装的 0.4.1 插件已经包含 Web UI；无需单独安装，也没有单独版本。安装后的启动器会
自动选择 Codex 插件数据中当前兼容性模型对应的目录：

```sh
dev-flow web start
```

命令会启动受管后台进程并打印一条严格 JSON 收据。打开收据中的 `url`：它使用数字地址
`127.0.0.1`、默认临时端口和 fragment 中的进程本地令牌。若要指定固定本地端口，可在
`start` 或 `restart` 后添加 `--port <端口>`。使用 `dev-flow web status`、
`dev-flow web open`、`dev-flow web restart` 和 `dev-flow web stop` 进行管理；`open` 只重新输出完整启动 URL，不会
自动打开浏览器。原有 `web` 形式继续作为可用 Ctrl-C 停止的前台模式。产品刻意不提供
host、代理、远程访问或长期凭据选项。

初始清单和存储任务详情不会调用 Git。只有在需要当前仓库健康和动作就绪度时才选择
**Observe live**。停止或重启服务器会取消任何活动的实时捕获。该访问机制
是本地 capability 安全，而不是多用户认证：不得分享启动 URL、通过代理暴露端口，或
削弱 Host、Origin、Fetch Metadata、CSP、bearer token、no-CORS 和 loopback 检查。

## 1. 要求

此版本支持：

- macOS；
- Git；
- Python 3.9–3.14；
- 具备 `codex plugin` 命令和 `SessionStart`、`UserPromptSubmit` 和 `PreToolUse` Hook 支持的 Codex。

检查主机：

```sh
sw_vers
git --version
python3 --version
codex plugin --help
```

运行时代码仅使用 Python 的标准库。请勿为此插件安装 Python 或 Node 依赖集。OpenSpec、代码库内存和独立审查员是可选的工作流功能，并具有明确的回退行为。

## 2. 将源放入个人市场

这些示例将 `$HOME/plugins/dev-flow-orchestrator` 作为市场源：

```text
$HOME/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

通过 SSH 克隆：

```sh
mkdir -p "$HOME/plugins"
git clone --branch main --single-branch \
  git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

HTTPS 替代方案：

```sh
mkdir -p "$HOME/plugins"
git clone --branch main --single-branch \
  https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

经过审查的本地候选版本可以放在相同路径。将其保留为一个完整的候选树，以便包标识、工作流、技能、Hook、源和文档来自同一快照。

验证候选版本：

```sh
cd "$HOME/plugins/dev-flow-orchestrator"
python3 -I -S scripts/validate_package.py
python3 -m json.tool .codex-plugin/plugin.json
```

清单名称为 `dev-flow-orchestrator`，候选验证涵盖 `lite`、`feature`、`bugfix`、`investigation`、`refactor` 和 `full` 的目录条目。

对于新的个人市场：

```sh
mkdir -p "$HOME/.agents/plugins"
cp \
  "$HOME/plugins/dev-flow-orchestrator/templates/personal-marketplace.example.json" \
  "$HOME/.agents/plugins/marketplace.json"
```

如果 `~/.agents/plugins/marketplace.json` 已存在，请保留它并将来自 `templates/marketplace-entry.json` 的对象合并到其 `plugins` 数组中。确保恰好有一个名为 `dev-flow-orchestrator` 的条目。

```sh
python3 -m json.tool "$HOME/.agents/plugins/marketplace.json"
```

## 3. 安装 0.4.0

```sh
codex plugin list
codex plugin add dev-flow-orchestrator@personal
codex plugin list
```

结果中恰好包含一个已启用的 `dev-flow-orchestrator@personal`。

启动一个新的 Codex 任务。打开 `/hooks`，确认 Hook 源是已安装插件快照，审查当前定义，并信任它。验证 `SessionStart`、`UserPromptSubmit` 和 `PreToolUse` 是否已启用。源代码检出测试无法确定已安装的 Hook 或技能拾取。

## 4. 替换安装

Codex 安装一个不可变的缓存快照。插件、Python 包和 lock 元数据共享一个
`RELEASE_VERSION`；运行时协议与持久化任务使用独立治理的 `MODEL_VERSION` `0.4.0`。
仅发布补丁不会改变状态命名空间、schema、工作流身份或活动任务。

1. 获取完整的已审查候选版本。
2. 将市场源树替换为一个候选版本。
3. 删除已安装的快照：

   ```sh
   codex plugin remove dev-flow-orchestrator@personal
   ```

4. 安装候选版本：

   ```sh
   codex plugin add dev-flow-orchestrator@personal
   ```

5. 启动一个新的 Codex 任务并验证已安装的版本和 Hook 源。

替换安装操作基于当前的 0.4.0 产品模型和状态命名空间。在替换已安装快照之前，完成或明确取消活动任务。

## 5. 数据目录和控制器定位器

任务状态必须保留在任务中的每个目标仓库之外。Hook 注入一个完整的定位器，其中包含已安装的 Python 启动器、已安装的 CLI 和确切的 `<PLUGIN_DATA>/0.4.0` 状态目录：

```text
<ctl> = <exact Hook-injected locator>
```

对已安装任务使用该定位器不变。不要重新构造其路径或附加另一个 `--data-dir`。

对于单独的直接 CLI 冒烟测试，选择目标仓库外的一个明确数据目录。这里的 `--data-dir` 表示确切目录，不会附加 `0.4.0`：

```sh
SOURCE_ROOT="$HOME/plugins/dev-flow-orchestrator"
DATA_DIR="/absolute/path/to/independent-dev-flow-0.4.0-state"

"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" --help
```

对该任务的每个命令使用相同的精确目录。控制器使用私有目录/文件、任务锁、修订比较和交换、确定性重放以及原子替换。直接状态编辑、符号链接状态路径、格式错误的记录和数据/仓库树重叠会失败关闭。

## 6. 验证 0.4.0 CLI 合约

在一次性初始化的 Git 仓库中创建一个任务：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --repo /absolute/path/to/disposable-repository \
  --requirement "Installation smoke"
```

响应包含修订版零的任务状态和最小合约。保存其 `task_id`，然后请求投影：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" next <task-id>
```

第一个 0.4.0 操作是 `task.preflight`。每个 `apply`（包括 preflight）都需要精确返回的对象作为 `projection.action.binding`。复制新的绑定为严格 JSON；不要重建或重用它：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action task.preflight \
  --payload-json '{}' \
  --binding-json '<projection.action.binding JSON>'
```

使用每个 apply 返回的新投影进行下一步操作：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action implementation.record \
  --payload-json '{"summary":"installation smoke implementation"}' \
  --binding-json '<fresh implementation binding JSON>'
```

运行证明烟雾测试要求的命令。仅在它成功退出后记录 `passed: true`。最小合约标准 ID 是 `requirement`：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action verification.record \
  --payload-json '{"passed":true,"command":"git -C /absolute/path/to/disposable-repository status --short","coverage":{"schema":"dev-flow-verification-coverage/0.4.0","criteria":{"requirement":"proven"},"repositories":{"<repository-id>":{"command":"git -C /absolute/path/to/disposable-repository status --short","passed":true}},"integration":{"command":"git -C /absolute/path/to/disposable-repository status --short","passed":true}},"summary":"member and integration checks passed"}' \
  --binding-json '<fresh verification binding JSON>'
```

从其新投影中完成：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action delivery.finalize.success \
  --payload-json '{"summary":"installation smoke completed","remaining_risks":{},"handoff":"inspect the generated dossier"}' \
  --binding-json '<fresh finalization binding JSON>'
```

最终投影报告 `done: true`，状态为 `DONE` 和紧凑的档案摘要。检查完整的账本和档案工件：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" show <task-id>
```

上面的一个参数 `--repo` 路径创建了一个单成员精确仓库集。它使用 `dev-flow-agent/0.4.0`，一个聚合仓库集快照，`dev-flow-verification-coverage/0.4.0`，作用域资源和 `dev-flow-delivery-dossier/0.4.0`，就像所有更大的集合一样。

为了对较大的集合进行烟雾测试，准备两个到八个初始化的、非裸的本地 Git 工作树根目录并重复 `--repo`：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --repo /absolute/path/to/disposable-api \
  --repo /absolute/path/to/disposable-client \
  --requirement "Repository-set installation smoke"
```

准入规范并排序精确集合，并拒绝重复或重叠的根目录、共享 Git 公共目录、非工作树根目录和数据目录重叠。调用者顺序没有意义，且启动后成员关系是不可变的。保存返回的成员 ID。`dev-flow-agent/0.4.0` 投影中的 `repository_set` 携带聚合快照摘要，并且每次 apply 仍使用其单个新鲜操作绑定。

在 `verification.record` 处，覆盖精确标准和成员集合以及一个集成结果。顶层命令必须等于 `integration.command`，顶层 `passed` 必须等于每个成员和集成结果的合取：

```sh
<ctl> apply <task-id> \
  --action verification.record \
  --payload-json '{"passed":true,"command":"./verify-integration.sh","coverage":{"schema":"dev-flow-verification-coverage/0.4.0","criteria":{"requirement":"proven"},"repositories":{"<api-repository-id>":{"command":"./verify-api.sh","passed":true},"<client-repository-id>":{"command":"./verify-client.sh","passed":true}},"integration":{"command":"./verify-integration.sh","passed":true}},"summary":"all member and integration checks passed"}' \
  --binding-json '<fresh verification binding JSON>'
```

完成生成一个聚合 `dev-flow-delivery-dossier/0.4.0`。它包括规范清单、每个成员基线/最终摘要、变更成员诊断、作用域资源、验证尝试、当前成员/集成证明和聚合新鲜度。在任务达到终端状态之前，对任何成员的更改会使当前聚合绑定和保证失效；获取一个新操作并重新运行完整集合所需的确保。任务为终端后不会重新打开：后续成员漂移只会使现有档案过时，进一步交付工作需要一个新的任务。

## 7. 从明确的合同开始

正常的 `feature`、`bugfix`、`investigation`、`refactor` 和 `full` 任务使用结构化的初始合同：

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" start \
  --workflow feature \
  --repo /absolute/path/to/repository \
  --requirement "Deliver observable behavior" \
  --contract-json '{"schema":"dev-flow-delivery-contract/0.4.0","revision":1,"summary":"Deliver observable behavior","acceptance_criteria":[{"id":"C1","statement":"The behavior is observable"}],"scope":["implementation and focused verification"],"constraints":[],"risks":[],"non_goals":[],"open_questions":[]}'
```

该对象具有完全记录的字段，正数修订版本 `1`，至少一个唯一标识的标准，并且文本/列表内容有限。省略该对象将使用从需求推导出的最小合同。在此命令中重复 `--repo` 以将相同的显式合同绑定到更大的精确仓库集；工作流选择并不意味着仓库数量。

当规划动作声明基于仓库的资源时，每个项目都具有返回的 `repository_id`、相对 `path`、`role` 和 `normalizer`。未知或省略的 ID、转义路径、跨根解析和重复的作用域键均被拒绝。

## 8. 修改范围或记录豁免

在预检后可以进行合同修订。提供完整的下一个合同修订版本、原因和操作者标签：

```sh
<ctl> revise-contract <task-id> \
  --contract-json '{"schema":"dev-flow-delivery-contract/0.4.0","revision":2,"summary":"Revised scope","acceptance_criteria":[{"id":"C1","statement":"Revised observable condition"}],"scope":["revised work"],"constraints":[],"risks":[],"non_goals":[],"open_questions":[]}' \
  --reason 'accepted scope correction' \
  --actor-label 'operator'
```

控制器捕获一个涵盖新合同中每个成员的聚合 `revision-source` 快照，并重新进入工作流声明的影响或实现节点。修订不能更改仓库成员资格。

仅作为明确决定记录标准豁免：

```sh
<ctl> decide <task-id> \
  --decision-json '{"id":"waive-C1-r1","kind":"criterion-waiver","subject":"C1","outcome":"waived","rationale":"accepted bounded exception","actor_label":"operator"}'
```

对于不可用的独立审查，`kind` 是 `assurance-waiver`，`subject` 是确切的审查节点 ID（官方工作流使用 `review`），并且 `outcome` 为 `waived`。决策 ID 对任务是唯一的，并且 `(kind, subject)` 对每份合同摘要只能接受一次。后续合同修订会使早期豁免成为历史。

仅在明确用户指令下取消，且当前节点位于所选工作流的 `cancel.stages` 声明中：

```sh
<ctl> cancel <task-id> --reason 'operator requested cancellation'
```

六个官方工作流在其正常非终止阶段的严格多数声明中取消。交付终结者从不暴露取消。

### 恢复用错误仓库集启动的任务

Hook 匹配仅证明当前路径属于活动任务声明的仓库集中。它并不能证明这些仓库可以满足接受的需求。当 `$follow-dev-flow` 确认有效合同和源之间的语义不匹配时，必须：

1. 停止投影的工作流动作而不更改成员；
2. 识别确切的任务和不匹配项，说明任务仍处于活动状态，并请求明确的取消授权，除非当前请求已为此任务提供该授权；
3. 授权后，为确切任务调用 `<ctl> cancel`；以及
4. 仅在投影包含 `done: true`、`status: CANCELLED` 和 `current_node: cancelled` 后报告完成。

如果没有授权，或者当取消不可用或无法捕获完整的仓库集时，任务保持活动状态。恢复声明的成员、完成必需的终结器或执行报告的操作者动作；不要替换不可变的成员资格或启动隐式的替换任务。

## 9. 验证已安装的 Hook 和 Skill pickup

1. 在任意成员中启动一个新的 Codex 任务，该成员属于一个已初始化的精确仓库集，包括较大集合中的次要成员。不选择模糊的活动任务匹配。
2. 打开 `/hooks`；确认源是已安装的不可变快照并信任该定义。
3. 调用 `$follow-dev-flow` 并启动正式工作流。
4. 确认注入的上下文名称为 Dev Flow 0.4.0，包括已安装的启动器和 CLI，选择 `<PLUGIN_DATA>/0.4.0`，并以每个方向的精确 `repository_set` 投射 `dev-flow-agent/0.4.0`。
5. 确认 `$follow-dev-flow` 在每次应用时传递确切的当前操作绑定，并使用 `show` 检查终端交付档案。
6. 确认针对插件数据根目录的常见 shell/edit 尝试被拒绝，而正常的仓库工作保持可用。

已安装发布证据涵盖了所有六个正式工作流，并记录了安装的快照身份、任务 ID、仓库基线、可选驱动状态、验证/审查路径、合同修订恢复、有限耗尽和 Dossier 0.4.0 结果。任何依赖于真实新 Codex 任务加载 Hook 或 Skill 的条件，在验证环境无法观察到时仍需手动进行安装 pickup 检查。

捆绑的 `scripts/validate_installed_stage1.py` 运行器将其生成的驱动有效载荷标记为控制器合同模拟。一个已验证的发布门将该已安装控制器证据与从实际 OpenSpec、代码库内存和独立审查执行中捕获的 `--external-evidence` 结合起来。仅运行控制器矩阵报告 `execution_ok: true` 并保持发布门处于 `unverified` 状态。

## 10. 故障排除

`Python handler does not exist`
: 市场源或已安装快照不完整。确认 `scripts/dev_flow.py` 和 `scripts/dev_flow_python_launcher` 一起存在。

`Python 3.9-3.14 was not found`
: 安装一个受支持的 Python 或将 `DEV_FLOW_PYTHON` 设置为一个已验证的绝对解释器路径。

`ARGUMENT_INVALID` 提及 `--data-dir`
: 将所需的全局 `--data-dir` 放在子命令之前。已安装任务使用完整的 Hook 定位器。

`ACTION_BINDING_INVALID` 或 `ACTION_BINDING_STALE`
: 获取一个新的 `next` 投影并提交其完整绑定。永远不要合成、修剪或重用绑定。

`REVISION_CONFLICT`
: 另一个突变推进了任务。阅读 `error.details.projection`，然后运行 `next` 并重新评估新投影的操作。

`WORKSPACE_CHANGED`
: 上下文或验证操作观察到了与其绑定的起始聚合快照不同的工作树。恢复预期的快照或获取新的操作；源更改仅属于声明的源生成操作。

`REPOSITORY_IDENTITY_MISMATCH`, `REPOSITORY_INVALID`,
`REPOSITORY_GIT_IDENTITY_DUPLICATE`, 或 `REPOSITORY_OVERLAP`
: 持久化成员缺失或已移动，不再为其精确的规范 Git 工作树根目录，或现在与另一个成员冲突。依赖仓库的进展记录不包含部分证据。在每个确切的持久化根目录下恢复所有成员，解决身份冲突，并请求一个新的投影。使用 `show` 进行只读存储账本诊断。

`ARTIFACT_INPUT_MISSING` 或 `RESOURCE_BINDING_MISSING`
: 无法解析所需的当前工件或声明的仓库资源。检查 `show`、新鲜度原因和当前资源路径；必要时生成上游替换工件。

`DELIVERY_NOT_READY`
: 成功完成缺乏新鲜通过验证、完整覆盖或所需的独立审查/豁免。遵循投影的重做或决策路径。

`WORKFLOW_IDENTITY_MISMATCH`
: 所选工作流模式、选择器或规范定义与任务的固定身份不同。恢复在任务创建时使用的精确定义或启动新任务。

`STATE_INVALID`
: 存储的 0.4.0 状态未能通过模式、封印、身份、账本或重放验证。保留它用于诊断，不要编辑它。确认每个命令都使用了任务的确切控制器定位器和数据目录。

Codex 显示沙盒或权限提示
: 这是主机拥有的权限。控制器既不抑制也不自动确认主机权限提示。

多个插件行
: 删除重复安装并仅安装一个 `dev-flow-orchestrator@personal`。

## 11. 移除

完成或明确取消活动的 Dev Flow 任务后，运行一键卸载器：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/uninstall.sh | sh
```

它会移除自有的 PATH 启动器、已安装的 Codex 插件、personal marketplace 中的
`dev-flow-orchestrator` 条目和安装器管理的源码 checkout。只有源码具有预期插件身份、
origin、已附着的 `main`，并且
不存在 Git 报告的改动、ignored 路径或仅存在于本地的提交时，才允许删除源码。任何预检
失败都会在移除插件或修改 marketplace 之前停止。使用 `--keep-source` 可以移除插件和
marketplace 条目，同时保留包含本地工作的源码 checkout：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/uninstall.sh | sh -s -- --keep-source
```

等价的仅移除插件手动命令为：

```sh
codex plugin remove dev-flow-orchestrator@personal
```

自动或手动移除都不会删除外部任务数据。数据删除仍是独立的操作。除非明确意图删除且已评估可恢复性，否则保留活动的 0.4.0 任务。

## Windows 集成预览

在装有 64 位 CPython 3.9–3.14、Git for Windows、Codex 插件/Hook 支持以及 Windows
PowerShell 5.1 或 PowerShell 7 的 Windows 10 22H2 x64 或 Windows 11 x64 客户端上，
先检查签出内容，再执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

安装器把 `main` 作为权威来源。它只接受预期 origin、干净且附加的 `main`，以及等于或
可仅快进到已获取提交的历史；绝不切换、重置、stash、clean 或合并分歧工作。它先验证
候选版本，再原子更新个人市场，并安装、修复或升级插件。

安装不会建立 Hook 信任。请启动新的 Codex 会话，打开 `/hooks`，检查精确的已安装 Hook
定义及源码并予以信任。Hook guard 很有用，但不是完整的 PowerShell 或操作系统强制边界。

在注入的 Controller locator 后追加 `web start --port 0`，即可启动受管的本地只读 Web UI。
使用同一 locator 执行 `web open`、`web status`、`web restart` 或 `web stop`。它只绑定
数字地址 `127.0.0.1`，使用 fragment token 权限，并且不修改任务或仓库。

卸载时始终保留外部 Controller 任务数据：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1 -KeepSource
```

Windows ARM64、32 位 Python、Windows Server、WSL 执行、UNC/SMB/NAS 和映射网络
仓库、`\\wsl$`、历史任务迁移及跨操作系统任务转移均不受支持。在记录 Windows 11 与
Windows 10 22H2 发布证据之前，客户端支持仍为预览。
