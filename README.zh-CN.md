# Dev Flow Orchestrator

[English](README.md) | [简体中文](README.zh-CN.md)

面向 Codex 的受控开发工作流，横跨 Git 仓库、`codebase-memory-mcp` 和 OpenSpec。它持久化机器可读的任务状态，确保人工审批明确可见，并在交付前审查已提交、已暂存、未暂存和未跟踪的全部变更。

**第一次使用？** 按顺序做完[配置](#配置)即可——六步，几分钟。[配置项速查](#配置项速查)是所有设置的一屏汇总。再往后是工作原理与设计取舍的讲解。

---

## 配置

下列占位符贯穿全文。请替换成你自己的值，没有任何机制会自动展开它们。

| 占位符 | 含义 | 典型取值 |
| --- | --- | --- |
| `<python>` | Python 3.9+ 解释器的绝对路径 | `/usr/bin/python3`、`C:\Users\me\AppData\Local\Programs\Python\Python312\python.exe` |
| `<plugin-root>` | 插件安装目录 | `~/plugins/dev-flow-orchestrator`、`%USERPROFILE%\.codex\plugins\cache\personal\dev-flow-orchestrator\0.2.0` |
| `<PLUGIN_DATA>` | 插件的私有状态目录 | `~/.codex/plugin-data/dev-flow-orchestrator`、`%USERPROFILE%\.codex\plugin-data\dev-flow-orchestrator` |

所有路径一律用绝对路径。钩子运行时的工作目录不可预测、环境变量也极为精简，相对路径或裸写 `python3` 是"配置完却毫无反应"最常见的原因。

### 1. 安装依赖

| 依赖 | 用于 | 检查方式 |
| --- | --- | --- |
| Python 3.9 或更高 | 全部功能 | `<python> --version` |
| Git | 全部功能 | `git --version` |
| 已启用的 `codebase-memory-mcp` | 仅完整流程（影响分析、工作区发现） | 该 MCP 服务器出现在 Codex 工具列表中 |
| `PATH` 中的 OpenSpec | 仅 OpenSpec 路线 | `openspec --version` |

精简流程只需要 Python 和 Git。本插件有意不捆绑与特定机器相关的 `.mcp.json`，请继续使用你现有的用户级或项目级 MCP 配置。

### 2. 放置插件

将完整的插件目录复制到 `<plugin-root>`——不要只复制单个文件，也不要放进业务仓库。然后在本地市场中注册：

```text
~/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

若 `~/.agents/plugins/marketplace.json` 不存在，把 `templates/personal-marketplace.example.json` 复制过去作为初始内容。若已存在，只把 `templates/marketplace-entry.json` 中的那个对象合并进它的 `plugins` 数组，文件其余部分保持不动。重启桌面应用，从该市场安装插件，然后开启一个新任务。逐文件的精确放置映射和更新（含缓存刷新）流程见 [`INSTALL.md`](INSTALL.md)。

### 3. 注册钩子

钩子是工作流可恢复的关键：它们在会话开始时重新注入当前任务，并拦截绕过控制器的写入和危险 Git 命令。没有钩子，控制器依然能用，但没有任何东西会提醒 Codex 去用它。

**先试试插件自带的注册。** `hooks/hooks.json` 已经基于 `$PLUGIN_ROOT` 写好，如果你的 Codex 版本能发现插件钩子，就无需任何配置。开启一个新任务，查看会话上下文中是否出现 `Dev Flow controller bootstrap:` 段落。出现了就直接跳到第 4 步。

**如果没有出现，改为全局注册。** 创建 `~/.codex/hooks.json`（Windows 为 `%USERPROFILE%\.codex\hooks.json`）。全局注册拿不到 `PLUGIN_ROOT`，也拿不到 `PLUGIN_DATA`，因此两个路径都必须写全，数据目录必须通过命令行的 `--data-dir` 传入：

```json
{
  "description": "Global session recovery and bounded Dev Flow guardrails.",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "<python> <plugin-root>/hooks/dev_flow_hook.py --data-dir <PLUGIN_DATA>",
            "timeout": 10,
            "statusMessage": "Loading the active Dev Flow task"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "<python> <plugin-root>/hooks/dev_flow_hook.py --data-dir <PLUGIN_DATA>",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "^(Bash|bash|shell|exec_command|apply_patch|Edit|edit|Write|write)$",
        "hooks": [
          {
            "type": "command",
            "command": "<python> <plugin-root>/hooks/dev_flow_hook.py --data-dir <PLUGIN_DATA>",
            "timeout": 10,
            "statusMessage": "Checking Dev Flow guardrails"
          }
        ]
      }
    ]
  }
}
```

逐字段说明：

| 字段 | 作用 | 建议 |
| --- | --- | --- |
| `SessionStart.matcher` | 哪些会话事件会重新注入任务上下文 | 保持 `startup\|resume\|clear\|compact`；去掉 `compact` 会导致上下文压缩后丢失任务 |
| `PreToolUse.matcher` | 守卫拦截哪些工具名 | 针对你所用版本工具名的正则。不同 Codex 版本命名不同——若任务活动期间写入没有被拦截，应先放宽这个正则，而不是断定钩子坏了 |
| `command` | 钩子的调用命令 | `<python>`、钩子路径、`--data-dir <PLUGIN_DATA>`，全部用绝对路径。Windows 上用反斜杠并按 JSON 转义（`C:\\Users\\...`） |
| `timeout` | Codex 放弃该钩子前等待的秒数 | `10` 足够。钩子按设计是故障时开放的——超时或出错时它不输出任何内容，而不会卡住你的会话 |
| `statusMessage` | 钩子运行时显示的提示文字 | 纯装饰，可以省略 |

`UserPromptSubmit` 没有 `matcher`——它在每次提交提示词时都会触发。改完这个文件后请开启新任务；Codex 可能还会要求你审查并信任这些钩子，拒绝则等于没有任何守卫。

### 4. 指定数据目录

`<PLUGIN_DATA>` 是插件的私有状态目录，保存你的作用域配置、每个任务的状态以及托管的工作树——它既不在你的仓库里，也不在 `<plugin-root>` 里。控制器按以下顺序解析，命中即止：

| 来源 | 生效范围 | 说明 |
| --- | --- | --- |
| `--data-dir <path>` | 单次调用 | 技能每次都会显式传入。可放在子命令之前或之后 |
| `DEV_FLOW_DATA_DIR` | 单个进程 | 适合作为个人兜底，这样即使忘记 `--data-dir` 也仍会落到正确位置 |
| `PLUGIN_DATA` | 单个进程 | 由 Codex 为插件托管的钩子注入。全局钩子注册**拿不到**这个变量 |
| 平台默认状态目录 | 兜底 | Linux `$XDG_STATE_HOME/dev-flow-orchestrator`（默认 `~/.local/state/...`）、macOS `~/Library/Application Support/dev-flow-orchestrator`、Windows `%LOCALAPPDATA%\dev-flow-orchestrator` |

最后一行是个实实在在的坑：在没设环境变量的情况下漏掉 `--data-dir`，控制器不会报错，而是**静默新建一套空状态**。你的作用域和任务看起来就像凭空消失了。要么每次调用都带上 `--data-dir`，要么把兜底设一次：

```bash
export DEV_FLOW_DATA_DIR="$HOME/.codex/plugin-data/dev-flow-orchestrator"
```

```powershell
setx DEV_FLOW_DATA_DIR "$env:USERPROFILE\.codex\plugin-data\dev-flow-orchestrator"
```

该目录会在首次使用时创建；除通过 `scope` 命令外，请不要预先填充或手工编辑其中任何内容。

### 5. 限定插件生效范围

个人安装对机器上的每个项目都可见。在没有配置的情况下，插件处处生效。作用域用于收窄这一范围：在其之外，钩子不输出任何内容，`start` 也会拒绝该仓库，因此无关会话的表现等同于插件未安装。

作用域保存在 `<PLUGIN_DATA>/config.json`，它是该目录下唯一需要你改动的文件——请通过 `scope` 命令改，而不是用编辑器：

```bash
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --add ~/work
```

```powershell
<python> <plugin-root>\scripts\dev_flow.py scope --data-dir <PLUGIN_DATA> --add D:\projects\my-service
```

生成的文件形如：

```json
{
  "schema_version": 1,
  "scope": {
    "mode": "allowlist",
    "include": ["/home/me/work"],
    "exclude": []
  }
}
```

| 配置项 | 取值 | 默认 | 含义 |
| --- | --- | --- | --- |
| `scope.mode` | `all`、`allowlist` | `all` | `all` 表示除排除项外处处生效；`allowlist` 表示仅在纳入项内生效 |
| `scope.include` | 绝对路径目录列表 | `[]` | 每一项覆盖该目录及其所有子目录 |
| `scope.exclude` | 绝对路径目录列表 | `[]` | 同上，但为排除。在**两种模式**下都生效 |

全部开关及示例：

| 开关 | 示例 | 效果 |
| --- | --- | --- |
| `--add DIR` | `--add ~/work` | 纳入一棵目录树。**第一次** `--add` 会同时把 `mode` 切为 `allowlist`，因为在 `all` 模式下记录纳入项不会产生任何效果 |
| `--add-exclude DIR` | `--mode all --add-exclude ~/work/vendor` | 排除一棵目录树。与 `--mode all` 搭配即是一份纯粹的拒绝列表 |
| `--remove DIR` | `--remove ~/work` | 移除一个纳入项。若该目录从未配置过会明确报错，避免输入错误被吞掉 |
| `--remove-exclude DIR` | `--remove-exclude ~/work/vendor` | 移除一个排除项 |
| `--mode all\|allowlist` | `--mode allowlist` | 直接设定模式 |
| `--clear` | `--clear` | 重置为处处生效。也是 `config.json` 损坏后唯一的恢复手段 |
| `--check [DIR]` | `--check .` | 只读：报告某个目录的判定结果，默认为当前目录 |

四个带 `DIR` 的开关均可重复。路径在存储时会展开并转为绝对路径，因此输入时用 `~` 或相对路径都可以。

**配置中层级最深的目录说了算。** 纳入 `~/work`、排除 `~/work/vendor`、再纳入 `~/work/vendor/mine`，则插件只在第一和第三处生效。完全相同的纳入/排除对，以排除为准。

两个环境变量可在不改动文件的前提下覆盖配置，只作用于单个进程——适合临时会话：

| 变量 | 效果 |
| --- | --- |
| `DEV_FLOW_SCOPE` | 替换纳入目录，**并**强制 `allowlist` 模式 |
| `DEV_FLOW_SCOPE_EXCLUDE` | 替换排除目录，两种模式下均可 |

两者都接受以 `os.pathsep` 分隔的列表（POSIX 用 `:`，Windows 用 `;`），`scope` 会在 `overrides` 字段中回报它们。

### 6. 验证配置

```bash
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --check .
```

配置正确时会输出一行 JSON，退出码为 `0`：

```json
{"changed": false, "check": {"in_scope": true, "matched": "/home/me/work", "mode": "allowlist", "path": "/home/me/work/my-service", "rule": "include"}, "command": "scope", "config_path": "/home/me/.codex/plugin-data/dev-flow-orchestrator/config.json", "effective": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "missing_paths": [], "ok": true, "overrides": {}, "scope": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "summary": "active only inside the included directories"}
```

`check.in_scope` 就是结论；`check.rule` 和 `check.matched` 说明是哪条配置做出的判定（`default` 表示没有规则命中，由模式决定）。`config_path` 用于确认你实际访问到的是哪个数据目录——如果它不是你预期的路径，请先回到第 4 步。

接着确认钩子确实触发：在作用域内的仓库中开启一个新的 Codex 任务，查看注入的 `Dev Flow controller bootstrap:` 段落，其中会写明控制器路径和数据目录。若它没出现，回到第 3 步；若它指向的数据目录你不认识，回到第 4 步。

最后让 Codex 起一个任务。精简流程是成本最低的端到端检验：

```bash
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --flow lite --requirement "修正登录横幅的错别字" --repo <repo-path>
```

## 配置项速查

插件的全部设置，集中一处。

| 设置 | 位置 | 默认 | 生效范围 | 章节 |
| --- | --- | --- | --- | --- |
| 钩子注册 | `<plugin-root>/hooks/hooks.json` 或 `~/.codex/hooks.json` | 插件自带的注册 | 整机 | [第 3 步](#3-注册钩子) |
| `PreToolUse` 匹配器 | 同一个钩子文件 | `^(Bash\|apply_patch\|Edit\|Write)$` | 整机 | [第 3 步](#3-注册钩子) |
| 数据目录 | `--data-dir` | 平台默认状态目录 | 单次调用 | [第 4 步](#4-指定数据目录) |
| `DEV_FLOW_DATA_DIR` | 环境变量 | 未设置 | 单个进程 | [第 4 步](#4-指定数据目录) |
| `PLUGIN_DATA` | 环境变量，由 Codex 注入 | 全局钩子下未设置 | 单个进程 | [第 4 步](#4-指定数据目录) |
| `scope.mode` | `<PLUGIN_DATA>/config.json` | `all` | 整机 | [第 5 步](#5-限定插件生效范围) |
| `scope.include` / `scope.exclude` | `<PLUGIN_DATA>/config.json` | `[]` | 整机 | [第 5 步](#5-限定插件生效范围) |
| `DEV_FLOW_SCOPE` / `DEV_FLOW_SCOPE_EXCLUDE` | 环境变量 | 未设置 | 单个进程 | [第 5 步](#5-限定插件生效范围) |
| `--flow full\|lite` | `start` | `full` | 单个任务，不可更改 | [精简流程](#精简流程) |
| `--protected-branch` | `start` | `main`、`master`、`trunk` | 单个任务，不可更改 | [控制器命令](#控制器命令) |
| `--repo` | `start` | 无（必填） | 单个任务，不可更改 | [控制器命令](#控制器命令) |
| `--task-id` | `start` | 自动生成 | 单个任务 | [控制器命令](#控制器命令) |

流程、受保护分支和仓库集合都没有全局设置：它们在 `start` 时逐任务决定，此后不可更改，以保证记录下来的证据始终指明自己是在哪套规则下产生的。

---

## 工作原理

每个任务在 `start` 时选择两种流程之一。默认的完整流程运行全套流水线。精简流程（`start --flow lite`）适用于作用域内的常规小范围工作——修一个小缺陷、做一处局部调整——而无须承担完整流水线的成本：它直接在用户的检出目录中运行 `preflight -> lite approval -> implement -> verify -> done`，不创建基线工作树，不做影响分析，不使用 OpenSpec，也不使用托管实现工作树或独立审查机制。同时它保留了让工作流可信的关键环节：故障时关闭的预检证据；一个绑定到确切分支、`HEAD` 和工作树快照的显式人工关卡（脏工作树需明确指定 `--allow-dirty`）；每次状态转换时的漂移检测；以及进入 `DONE` 前必须通过且与最终工作树指纹一致的测试记录。详见[精简流程](#精简流程)。

本插件对每个仓库采用双索引模型。基线项目为不可变的分离式分析工作树建立索引，用于影响分析和路线决策；工作区项目为当前代实现工作树建立索引，用于规划、实现、验证和审查发现。Codebase Memory 不会自动在两者之间选择：每次查询都必须传入当前阶段所选项目返回的精确 ID。控制器通过 `show.index_selection` 显示这一选择，归档每一条已被取代的索引记录以便审计并实现 ID 隔离；当必需的工作区索引缺失或过期时，它会阻止后续关卡继续执行。

本插件不会切换或拉取开发者当前的检出目录。预检和显式授权完成后，它会解析已配置远程仓库的默认分支，按需执行获取操作，固定一个不可变的基准提交，并创建分离式分析工作树。随后，直接路线和 OpenSpec 路线都会在隔离的链接工作树中使用独立的任务分支进行实现。现有源分支及其脏状态证据保持可见且不受影响；若要在确切的脏快照上继续操作，必须获得结构化审批。

生命周期钩子会在会话开始和提交提示词时注入插件控制器的绝对路径及私有数据目录路径。主技能每次调用控制器时都会显式传入该数据目录，因为 `PLUGIN_DATA` 属于钩子进程，不会假定其可被后续的 shell 工具继承。

### 边界与限制

钩子提供的是任务级防护措施，而非安全边界。只有在匹配的任务处于活动状态时，它们才会保护可识别的文件写入工具并拦截常见的危险 Git 命令；shell 脚本、嵌套工具、托管工具以及被禁用或不受信任的钩子都可能绕过这些防护。控制器状态、制品哈希、显式审批和最终独立审查仍然是事实依据。安装本插件不会全局限制无关的 Codex 任务。

当 Git 无法可靠提供完整字节内容时，证据流水线会以失败关闭方式终止：它会拒绝带有 `assume-unchanged`/`skip-worktree` 标记的已跟踪条目（包括稀疏检出）、存在脏状态的已初始化子模块，以及 clean/process 内容过滤器（例如 Git LFS）。这些是当前有意保留的限制，系统不会在覆盖不完整时静默降级；继续操作前，请将检出目录恢复为规范状态，或改用单独治理的仓库或流程。

请避免显式指定仅大小写不同于另一任务的工作区路径或分支覆盖值。在不区分大小写的文件系统上，一个尚不存在且仅大小写不同的别名可能通过规划阶段，但随后被 Git 在创建工作树时拒绝；此时控制器会以失败关闭方式终止并要求进行冲突恢复，但当前控制器不会在声明资源时规范化这些别名。

## 控制器命令

插件的全部行为都通过唯一入口 `scripts/dev_flow.py` 完成。技能和钩子不会调用其他任何东西，因此下表即为本插件的完整命令面。

```bash
<python> <plugin-root>/scripts/dev_flow.py [--data-dir <PLUGIN_DATA>] <command> [options]
```

- `--data-dir` 可以放在子命令之前或之后；完整解析顺序见[第 4 步](#4-指定数据目录)。
- 每条命令只向 stdout 输出一个 JSON 对象。任务类命令返回 `ok`、`command`、`task_id`、`revision`、`status`、`flow`、`index_selection` 以及各命令特有的字段；`list` 和 `scope` 返回各自的结构。失败时返回 `{"ok": false, "error": {"code", "message", "details"}}`。
- 退出码：`0` 成功，`2` 可预期的 `FlowError`，`1` 未预期的内部错误，`130` 中断。
- 任务类命令通过位置参数或 `--task` 指定任务 ID。所有会改写状态的命令还必须提供 `--expected-revision N`；版本号过期时以 `REVISION_CONFLICT` 失败，而不会覆盖并发写入者的结果。
- 控制器只负责记录与校验，绝不代为执行你的构建或测试命令。

| 命令 | 流程 | 适用状态 | 用途 |
| --- | --- | --- | --- |
| `start` | 两者 | 创建任务 | 为一个或多个仓库创建 `INTAKE` 任务 |
| `show` | 两者 | 任意 | 输出单个任务的完整快照 |
| `list` | 两者 | 无需任务 | 列出任务摘要 |
| `scope` | 两者 | 无需任务 | 查看或修改插件生效的目录范围 |
| `preflight` | 两者 | `INTAKE`、`PREFLIGHTED` | 记录 Git 身份、远程/基准分支以及精确的工作树指纹 |
| `baseline` | 完整 | `PREFLIGHTED`、`BASELINED` | 固定各仓库的远程基准提交；可选地实体化分析工作树 |
| `record-index` | 完整 | `BASELINED`、`INDEXED` | 记录基线或工作区角色的 codebase-memory 索引来源 |
| `record-artifact` | 两者 | 任意活动状态 | 对不可变文件或确定性目录制品计算哈希并记录 |
| `set-route` | 完整 | `INDEXED`、`IMPACT_REVIEW` | 将 `direct` 或 `openspec` 绑定到当前的影响/索引证据 |
| `approve` | 两者 | 任意活动状态 | 以可审计的说明审批指定关卡 |
| `transition` | 两者 | 任意非终态 | 执行一次受控的状态机转换 |
| `prepare-workspace` | 完整 | `ROUTE_APPROVED`、`WORKSPACE_READY` | 记录可审批的工作区计划，或将其执行为隔离工作树 |
| `record-test` | 两者 | `IMPLEMENTING`、`VERIFYING` | 将具名命令标识与精确的仓库指纹绑定记录 |
| `review-snapshot` | 完整 | `VERIFYING`、`REVIEWING` | 捕获 `base...HEAD`、已暂存、未暂存和未跟踪的审查输入 |
| `cancel` | 两者 | 任意非终态 | 以给定原因取消任务 |

"任意活动状态"指既非终态（`DONE`、`CANCELLED`）也非 `BLOCKED` 的状态；具体的制品类型和关卡还会进一步收窄，详见下文。仅限完整流程的命令在精简任务上会以 `FLOW_MISMATCH` 失败，`approve --gate lite` 在完整任务上同样如此。此外，当任务是在预检阶段被阻塞时，`preflight` 也可从 `BLOCKED` 状态执行。

这十五条中，只有 `scope` 会改变插件自身的行为——它是 `config.json` 的唯一写入者。其余十四条都只操作单个任务的状态，任务结束后不留下任何影响。

### 任务创建与查看

- `start --repo <path> [--repo <path> ...] "<requirement>"` —— 需求也可用 `--requirement` 传入。`--repo` 必填且可重复；仓库集合、需求和流程在创建后不可更改。`--flow full|lite` 选择流水线（默认 `full`）。`--task-id` 可指定稳定的任务 ID 而不使用自动生成值，`--protected-branch` 可重复，用于在默认的 `main`/`master`/`trunk` 之外追加受保护分支。作用域之外的仓库会被 `OUT_OF_SCOPE` 拒绝。
- `show <task>` —— 输出完整任务状态，其中 `index_selection` 指明当前阶段所有查询都必须使用的 codebase-memory 项目。
- `list [--active-only] [--status STATE ...]` —— 按更新时间倒序返回摘要。`--status` 可重复，接受任意状态名。
- `scope [...]` —— 全部开关见[第 5 步](#5-限定插件生效范围)，判定规则见[目录作用域](#目录作用域)。

### 证据记录

- `preflight [--repo ...] [--remote R] [--base B]` —— `--repo` 默认覆盖全部仓库，接受仓库 ID 或路径。当仓库配置无法解析时，可用 `--remote`/`--base` 覆盖解析出的默认值。
- `baseline [--fetch] [--materialize]` —— `--fetch` 执行网络获取，要求 `baseline-fetch` 审批带有 `--allow-fetch`；`--materialize` 在固定的 `base_sha` 上创建或复用分离式分析工作树。
- `record-index [--role baseline|workspace] [--repo ...] [--commit SHA] [--index-id ID] [--receipt FILE] [--metadata-json JSON]` —— `--role` 默认为 `baseline`。`--commit` 对基线索引默认取固定的基准提交，对工作区索引默认取当前 `HEAD`。省略 `--index-id` 需要 `impact-degraded` 审批以及元数据中的失败来源信息；工作区索引要求元数据含 `persistence:false`。
- `record-artifact --path FILE_OR_DIR --kind KIND [--verdict PASS|CONDITIONAL|FAIL] [--metadata-json JSON]` —— `--artifact` 是 `--path` 的等价别名。已识别的制品类型与阶段绑定：`impact`（位于 `INDEXED`/`IMPACT_REVIEW`，记录后会清除已有的路线审批）、`direct-contract`/`openspec-plan`（位于 `PLANNING`）、`review-report`（位于 `REVIEWING`，此时 `--verdict` 必填且必须与报告正文的 `Verdict:` 行一致）。`workspace-plan` 与 `review-snapshot` 由控制器生成，在此处会被 `RESERVED_ARTIFACT_KIND` 拒绝；其他类型作为自由形式的证据记录。
- `record-test --name NAME --command CMD --exit-code N [--repo ...] [--output FILE]` —— 命令字符串只被记录，绝不执行。该记录绑定当前计划（完整流程）或精简审批，以及记录时刻的仓库指纹，因此之后任何改动都会使其失效。
- `review-snapshot [--repo ...]` —— `--repo` 必须覆盖任务中的全部仓库。

### 决策与流转

- `set-route direct|openspec --reason "..."` —— 路线也可用 `--route` 传入。
- `approve --gate GATE --note "..." [--artifact-sha256 SHA] [--accept-conditional] [--allow-fetch] [--allow-dirty]` —— 完整任务的关卡为 `baseline-fetch`、`impact-degraded`、`route`、`workspace`、`plan` 和 `review`，精简任务的关卡为 `lite`。绑定证据的关卡要求 `--artifact-sha256` 指向任务上已记录的制品。`--accept-conditional` 仅用于 `review`，`--allow-fetch` 仅用于 `baseline-fetch`，`--allow-dirty` 仅用于 `baseline-fetch` 和 `lite`；用于其他关卡会报 `INVALID_ARGUMENT`。`FAIL` 的审查结论无法被审批通过。
- `transition STATE [--note "..."]` —— 目标状态也可用 `--to` 传入。允许的边包括所在流程的下一个状态、其返工边（完整流程可退回 `PLANNING`、`IMPLEMENTING` 或 `INDEXED`；精简流程可退回 `IMPLEMENTING` 或 `PREFLIGHTED`），以及 `BLOCKED`/`CANCELLED`。转入 `BLOCKED`、`CANCELLED`、重新规划和重新评估影响时必须提供 `--note`。被阻塞的任务只能恢复到被阻塞前的状态。每次转换都会重新校验目标状态的守卫条件，因此工作树漂移、缺失的工作区索引、过期的审查快照和非当前的测试记录都会在此处故障关闭。
- `prepare-workspace [--repo ...] [--branch B] [--path P] [--workspace-path REPO=PATH ...] [--workspace-branch REPO=BRANCH ...] [--dry-run | --execute]` —— 默认为 `--dry-run`，记录一份确定性的 `workspace-plan` 制品；`--execute` 严格执行最近一份已获 `workspace` 审批的计划。`--path` 只在选定单个仓库时有效，其余情况请使用可重复的 `REPO=...` 覆盖参数。分支默认为 `codex/<task-id>`。
- `cancel --reason "..."` —— 结束非终态任务的推荐方式。`DONE` 任务无法被取消。

## 精简流程

目录作用域决定插件在*哪里*生效；流程决定该作用域内的任务需要运行*多少*流水线。精简任务的状态机为 `INTAKE -> PREFLIGHTED -> IMPLEMENTING -> VERIFYING -> DONE`：

```bash
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --flow lite --requirement "fix ..." --repo <path>
```

- 流程与需求和仓库集合一样，在 `start` 时选定且不可更改。当精简变更超出其作用范围时，应取消该任务并以完整任务替代；不支持原地升级。
- 精简关卡（`approve --gate lite`）用一次显式决策取代基线、路线、工作区、计划和审查关卡：在已记录的确切检出目录中就地工作。它会绑定每个仓库的分支、`HEAD` 和工作树指纹；每次重新执行 `preflight` 都会清除该审批，进入实现阶段时还会重新验证这三项实时状态。
- 仅限完整流程的命令和关卡（`baseline`、`record-index`、`set-route`、`prepare-workspace`、`review-snapshot`，以及计划/路线/审查审批）在精简任务中会以 `FLOW_MISMATCH` 失败；反之，精简关卡在完整任务中也会如此。
- 测试记录绑定当前精简审批，而非计划哈希。进入 `DONE` 前，每个仓库仍须具备一条当前有效且通过的测试结果，其指纹必须与最终工作树一致。
- 仅当精简任务处于 `IMPLEMENTING` 或 `VERIFYING` 状态时，钩子才允许向源检出目录写入文件；命令防护措施保持不变（禁止 `git reset --hard`、`clean`、`pull`、切换分支或在受保护分支上提交）。提交和推送仍是需要单独显式授权的操作。
- 精简任务不记录由控制器绑定的 Codebase Memory 索引；`show.index_selection.selected_role` 为 `none`，临时查询不纳入证据链。

## 目录作用域

[第 5 步](#5-限定插件生效范围)已覆盖开关和文件格式，本节说明判定是如何解析的。

如果没有配置文件，插件会在所有位置激活，这与原有行为一致。钩子和控制器在每次事件时都会读取该作用域，因此改动会在下一次 Codex 事件时生效，无需重装插件。

有两项有意设置的例外，用于防止作用域本身成为故障来源。首先，如果当前目录位于某个活动任务的仓库或工作区内，即使作用域排除了该目录，钩子仍会在此处保持启用，因此在任务执行期间缩小作用域不会静默丢失该任务的检查点或防护措施；注入的检查点会说明这一情况。其次，如果配置不可读或控制器无法导入，系统会故障时开放到全局激活，因为故障时关闭会隐藏工作流，而不是限制其作用域。

作用域不仅用于减少干扰，也会强制执行约束：`start` 会以 `OUT_OF_SCOPE` 拒绝作用域之外的仓库，并指出配置文件路径。但它仍然只是一种作用域机制，而不是安全边界——[边界与限制](#边界与限制)中所述的约束同样适用。

每次调用 `scope` 还会返回 `effective`、`summary` 和 `missing_paths`，后者列出已配置但已不存在的目录，是排查"项目搬家导致作用域失效"最快的手段。

## 源码布局

请相对于插件根目录将文件保存在以下位置：

```text
dev-flow-orchestrator/
├── .codex-plugin/plugin.json        # 必需的插件清单
├── INSTALL.md                        # 精确的个人/仓库安装位置映射
├── hooks/
│   ├── hooks.json                   # Codex 生命周期钩子注册
│   └── dev_flow_hook.py             # 状态注入和尽力而为的防护措施
├── scripts/
│   └── dev_flow.py                  # 持久化状态机和 Git 控制平面
├── skills/
│   ├── follow-dev-flow/             # 主工作流入口
│   ├── analyze-change-impact/       # 基于 codebase-memory 的影响分析
│   └── review-dev-flow-change/      # 独立的完整变更审查
├── templates/project/AGENTS.md      # 可复制到目标仓库的可选策略
├── templates/marketplace-entry.json # 用于合并到本地市场的条目
├── templates/personal-marketplace.example.json # 完整的首个市场配置示例
└── tests/                            # 离线单元测试
```

不要将钩子或辅助脚本分别复制到各个业务仓库中。应将整个插件目录作为一个整体安装。每个目标仓库只需在 `AGENTS.md` 中保留项目专属指导；当选择 OpenSpec 路线时，由 `openspec init`/`openspec update` 生成当前的 Codex OpenSpec 技能。

## 开发验证

在此目录中运行：

```bash
python3 -m unittest discover -s tests -v
```

然后使用 `skill-creator/scripts/quick_validate.py` 验证三个技能目录，并使用 `plugin-creator/scripts/validate_plugin.py` 验证此插件根目录。

## 安装位置

每个文件的精确目标位置、`<PLUGIN_DATA>` 下的运行时数据布局，以及已安装副本的更新流程，请参阅 [`INSTALL.md`](INSTALL.md)。个人使用时，请将整个目录放到个人市场条目所引用的插件位置。对于仓库市场，请将其放在 `<marketplace-root>/plugins/dev-flow-orchestrator/`，并让该市场条目指向 `./plugins/dev-flow-orchestrator`。

安装或更新插件后，请启动一个新的 Codex 任务，以加载新的技能和钩子。Codex 提示时，请审查并信任所捆绑的钩子。
