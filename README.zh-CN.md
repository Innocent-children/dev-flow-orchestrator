# Dev Flow Orchestrator

[English](README.md) | [简体中文](README.zh-CN.md)

面向 Codex 的受控开发工作流，横跨 Git 仓库、`codebase-memory-mcp` 和 OpenSpec。它在原生 Windows、macOS 和 Linux 上保持同一套状态机、审批与证据语义，持久化机器可读的任务状态，确保人工审批明确可见，并在交付前审查已提交、已暂存、未暂存和未跟踪的全部变更。

受支持的运行时为原生 Windows、macOS 和 Linux，须配备 Python 3.9–3.14，以及真正支持 `git worktree` 的 Git。控制器和钩子运行时只使用 Python 标准库；Windows 无需 POSIX 兼容层。

**第一次使用？** 按顺序做完[配置](#配置)即可——六步，几分钟。[配置项速查](#配置项速查)是所有设置的一屏汇总。再往后是工作原理与设计取舍的讲解。

---

## 配置

下列占位符贯穿全文。请替换成你自己的值，没有任何机制会自动展开它们。

| 占位符 | 含义 | 典型取值 |
| --- | --- | --- |
| `<python>` | Python 3.9–3.14 解释器的绝对路径 | `/usr/bin/python3`、`C:\Users\me\AppData\Local\Programs\Python\Python314\python.exe` |
| `<plugin-root>` | 插件安装目录 | `~/plugins/dev-flow-orchestrator`、`%USERPROFILE%\.codex\plugins\cache\personal\dev-flow-orchestrator\0.3.0` |
| `<PLUGIN_DATA>` | 插件的私有状态目录 | `~/.codex/plugin-data/dev-flow-orchestrator`、`%USERPROFILE%\.codex\plugin-data\dev-flow-orchestrator` |

手工调用控制器或配置全局钩子时，应使用解释器、handler 和数据目录的绝对路径。钩子运行时的工作目录不可预测，环境也有意保持精简，因此相对路径或依赖 `PATH` 的裸解释器名常会造成看似毫无反应的配置失败。插件自带的钩子是例外：它使用 Codex 注入的 `PLUGIN_ROOT`/`PLUGIN_DATA` 和随包的跨平台启动命令；工作流技能随后会保留注入的解释器、控制器和数据目录参数，而不会重建启动命令。

### 1. 安装依赖

| 依赖 | 用于 | 检查方式 |
| --- | --- | --- |
| Python 3.9–3.14 | 全部功能；运行时只使用 Python 标准库 | `<python> --version` |
| 支持 `git worktree` 的原生 Git | 仓库证据和托管工作树 | `git --version` |
| 已启用的 `codebase-memory-mcp` | 仅完整流程（影响分析、工作区发现） | 该 MCP 服务器出现在 Codex 工具列表中 |
| `PATH` 中的 OpenSpec | 仅 OpenSpec 路线 | `openspec --version` |

精简流程只需要受支持版本的 Python 和 Git；完整流程还需要 codebase-memory，只有 OpenSpec 路线需要 OpenSpec。本插件有意不捆绑 Python、Git、OpenSpec、POSIX 兼容层或与特定机器相关的 `.mcp.json`；请自行安装前两项，并继续使用现有的用户级或项目级 MCP 配置。Python 3.9 与 3.14 会在 Windows、macOS、Linux 上运行完整验证，3.10–3.13 至少在 Linux 上验证；新 Python 小版本只有进入该原生矩阵后才会被声明为受支持。

### 2. 放置插件

将完整的插件目录复制到 `<plugin-root>`——不要只复制单个文件，也不要放进业务仓库。然后在本地市场中注册：

```text
~/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

若 `~/.agents/plugins/marketplace.json` 不存在，把 `templates/personal-marketplace.example.json` 复制过去作为初始内容。若已存在，只把 `templates/marketplace-entry.json` 中的那个对象合并进它的 `plugins` 数组，文件其余部分保持不动。重启桌面应用，从该市场安装插件，然后开启一个新任务。完整的包放置映射和更新（含缓存刷新）流程见 [`INSTALL.md`](INSTALL.md)。

### 3. 注册钩子

钩子是工作流可恢复的关键：它们在会话开始时重新注入当前任务，并拦截绕过控制器的写入和危险 Git 命令。没有钩子，控制器依然能用，但没有任何东西会提醒 Codex 去用它。

**先试试插件自带的注册。** Codex 会按官方默认位置发现 `hooks/hooks.json`；插件清单不会加入不受支持的 `hooks` 字段。每个 handler 都同时提供 POSIX `command` 和 Windows `commandWindows`，且两者都会调用 `hooks/dev_flow_hook.py`：

- macOS/Linux 的 `command` 通过 `python3 "$PLUGIN_ROOT/hooks/dev_flow_hook.py"` 启动；
- Windows 的 `commandWindows` 调用随包的 `hooks/dev_flow_hook.cmd`。该 shim 先尝试受支持的 `py -3`，再依次尝试明确的 `py -3.14` 至 `py -3.9`，最后尝试 `python`，并保留 stdin、stdout 和退出码；
- 两条路径最终都运行同一个 `hooks/dev_flow_hook.py`，由 Codex 注入真实的 `PLUGIN_ROOT` 和 `PLUGIN_DATA`，因此 handler 语义一致。

如果没有 Windows 启动器能提供 Python 3.9–3.14，该 shim 会输出不产生变更的诊断。开启一个新任务，查看会话上下文中是否出现 `Dev Flow controller bootstrap:` 段落。它提供的控制器前缀由当前 `sys.executable`、`PLUGIN_ROOT` 下的控制器绝对路径和显式 `--data-dir <PLUGIN_DATA>` 组成；工作流技能会原样复用，而不会重建为 `python3`。出现了就直接跳到第 4 步。

**如果没有出现，改为全局注册。** 创建 `~/.codex/hooks.json`（Windows 为 `%USERPROFILE%\.codex\hooks.json`）。全局注册拿不到 `PLUGIN_ROOT`，也拿不到 `PLUGIN_DATA`，因此两个平台的解释器、handler 和数据目录都必须写成绝对路径，并在命令行中显式传入 `--data-dir`：

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
            "command": "\"<absolute-posix-python>\" \"<absolute-plugin-root>/hooks/dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "commandWindows": "\"<absolute-windows-python>\" \"<absolute-plugin-root>\\hooks\\dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
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
            "command": "\"<absolute-posix-python>\" \"<absolute-plugin-root>/hooks/dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "commandWindows": "\"<absolute-windows-python>\" \"<absolute-plugin-root>\\hooks\\dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "^(Bash|apply_patch|Edit|Write)$",
        "hooks": [
          {
            "type": "command",
            "command": "\"<absolute-posix-python>\" \"<absolute-plugin-root>/hooks/dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "commandWindows": "\"<absolute-windows-python>\" \"<absolute-plugin-root>\\hooks\\dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
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
| `PreToolUse.matcher` | 守卫拦截哪些规范工具名 | 保持 `^(Bash\|apply_patch\|Edit\|Write)$`；包验证器会检查这项契约 |
| `command` | macOS/Linux 上的钩子调用 | 使用受支持解释器、handler 和数据目录的绝对路径，并为每条路径加引号 |
| `commandWindows` | 原生 Windows 上的钩子调用 | 用 Windows 解释器和绝对路径调用同一个 Python handler；JSON 字符串中的反斜杠须双写（`C:\\Users\\...`） |
| `timeout` | Codex 放弃该钩子前等待的秒数 | `10` 足够。钩子按设计是故障时开放的——超时或出错时它不输出任何内容，而不会卡住你的会话 |
| `statusMessage` | 钩子运行时显示的提示文字 | 纯装饰，可以省略 |

`UserPromptSubmit` 没有 `matcher`——它在每次提交提示词时都会触发。`SessionStart` 始终注入完整的可恢复检查点。仅当当前 Codex 会话中的内容发生变化时，提示词才会接收一行精简检查点，其中包含任务、revision、流程、状态、剩余流程、索引、下一步动作和精简恢复命令。尽力写入的标记以 `sha256(session_id)` 分键，且只保存精简内容摘要；缺少 session ID，或标记读取、写入、损坏出现任何问题时，钩子都会继续输出而非错误抑制，从而保持故障时开放。命令守卫会以等价方式识别直接调用的 `git`/`git.exe`、绝对 Git 路径、受支持的 POSIX shell、`cmd.exe /c`、Windows PowerShell 和 `pwsh -Command` 包装；已识别但无法安全解析的包装载荷会带诊断拒绝。随包的 Windows shim 用于插件托管的自动发现；全局注册既拿不到 `PLUGIN_ROOT`，也拿不到 `PLUGIN_DATA`，因此应按上例使用经过验证的绝对解释器。改完这个文件后请开启新任务；Codex 可能还会要求你审查并信任这些钩子，拒绝则等于没有任何守卫。

### 4. 指定数据目录

`<PLUGIN_DATA>` 是插件的私有状态目录，保存你的作用域配置、每个任务的状态以及托管的工作树——它既不在你的仓库里，也不在 `<plugin-root>` 里。控制器按以下顺序解析，命中即止：

| 来源 | 生效范围 | 说明 |
| --- | --- | --- |
| `--data-dir <path>` | 单次调用 | 技能每次都会显式传入。可放在子命令之前或之后 |
| `DEV_FLOW_DATA_DIR` | 单个进程 | 适合作为个人兜底，这样即使忘记 `--data-dir` 也仍会落到正确位置 |
| `PLUGIN_DATA` | 单个进程 | 由 Codex 为插件托管的钩子注入。全局钩子注册**拿不到**这个变量 |
| 平台默认状态目录 | 兜底 | Windows `%LOCALAPPDATA%\dev-flow-orchestrator`（另有基于主目录的本地应用数据兜底）、macOS `~/Library/Application Support/dev-flow-orchestrator`、Linux `$XDG_STATE_HOME/dev-flow-orchestrator`（默认 `~/.local/state/dev-flow-orchestrator`） |

显式参数或环境变量只有空白字符时会被视为未设置，绝不会相对于当前工作目录解析。最后一行是个实实在在的坑：在没设环境变量的情况下漏掉 `--data-dir`，控制器不会报错，而是**静默新建第二套空状态**。你的作用域和任务看起来就像凭空消失了。要么每次调用都带上 `--data-dir`，要么在每个控制器进程中设置 `DEV_FLOW_DATA_DIR`。下面的示例只影响当前 shell；如需持久生效，请按照正常的 shell 配置或环境管理策略，把等价赋值加入相应配置。

Bash（macOS/Linux）：

```bash
export DEV_FLOW_DATA_DIR="$HOME/.codex/plugin-data/dev-flow-orchestrator"
```

PowerShell（Windows）：

```powershell
$env:DEV_FLOW_DATA_DIR = "$env:USERPROFILE\.codex\plugin-data\dev-flow-orchestrator"
```

命令提示符（Windows）：

```bat
set "DEV_FLOW_DATA_DIR=%USERPROFILE%\.codex\plugin-data\dev-flow-orchestrator"
```

该目录会在首次使用时创建；除通过 `scope` 命令外，请不要预先填充或手工编辑其中任何内容。POSIX 上，控制器管理的目录保持 `0700`，状态、配置、事件、锁、回执和临时文件保持 `0600`。Windows 上，控制器通过标准库 Win32 绑定校验实际所有者和继承 DACL；遇到 null、不可读、所有者异常或写权限过宽的安全描述符时，会阻止变更。POSIX mode 位不被当作 Windows ACL。

活动任务及其状态目录只能留在创建它们的平台上。不要跨操作系统复制或同步 `<PLUGIN_DATA>`、链接工作树、锁/隔离文件或执行中的任务；应在来源主机完成或取消任务，再在目标主机创建新任务。普通源码提交当然可以通过 Git 迁移。

### 5. 限定插件生效范围

个人安装对机器上的每个项目都可见。在没有配置的情况下，插件处处生效。作用域用于收窄这一范围：在其之外，钩子不输出任何内容，`start` 也会拒绝该仓库，因此无关会话的表现等同于插件未安装。

作用域保存在 `<PLUGIN_DATA>/config.json`，它是该目录下唯一需要你改动的文件——请通过 `scope` 命令改，而不是用编辑器。

Bash（macOS/Linux）：

```bash
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --add ~/work
```

PowerShell（Windows）：

```powershell
& "<python>" "<plugin-root>\scripts\dev_flow.py" scope --data-dir "<PLUGIN_DATA>" --add "D:\projects\my-service"
```

命令提示符（Windows）：

```bat
"<python>" "<plugin-root>\scripts\dev_flow.py" scope --data-dir "<PLUGIN_DATA>" --add "D:\projects\my-service"
```

生成的文件形如：

```json
{
  "schema_version": 2,
  "scope": {
    "mode": "allowlist",
    "include": ["/home/me/work"],
    "exclude": []
  },
  "risk_policy": {
    "schema": "dev-flow-risk-policy/v1",
    "protected_paths": [
      ".github/workflows/**",
      "**/alembic/**",
      "**/api/**",
      "**/auth/**",
      "**/migrations/**",
      "**/schema/**",
      "**/schemas/**",
      "**/security/**",
      "**/*.graphql",
      "**/*.proto",
      "**/*.sql",
      "**/*.tf",
      "deploy/**",
      "docker-compose*.yml",
      "docker-compose*.yaml",
      "Dockerfile*",
      "infra/**",
      "infrastructure/**",
      "k8s/**",
      "terraform/**"
    ]
  }
}
```

| 配置项 | 取值 | 默认 | 含义 |
| --- | --- | --- | --- |
| `scope.mode` | `all`、`allowlist` | `all` | `all` 表示除排除项外处处生效；`allowlist` 表示仅在纳入项内生效 |
| `scope.include` | 绝对路径目录列表 | `[]` | 每一项覆盖该目录及其所有子目录 |
| `scope.exclude` | 绝对路径目录列表 | `[]` | 同上，但为排除。在**两种模式**下都生效 |
| `risk_policy.protected_paths` | 仓库相对 POSIX glob | 上述内置公共契约/鉴权/schema/迁移/基础设施集合 | 声明路径或实时变更路径命中任一规则时必须使用完整流程 |

全部开关及示例：

| 开关 | 示例 | 效果 |
| --- | --- | --- |
| `--add DIR` | `--add ~/work` | 纳入一棵目录树。**第一次** `--add` 会同时把 `mode` 切为 `allowlist`，因为在 `all` 模式下记录纳入项不会产生任何效果 |
| `--add-exclude DIR` | `--mode all --add-exclude ~/work/vendor` | 排除一棵目录树。与 `--mode all` 搭配即是一份纯粹的拒绝列表 |
| `--remove DIR` | `--remove ~/work` | 移除一个纳入项。若该目录从未配置过会明确报错，避免输入错误被吞掉 |
| `--remove-exclude DIR` | `--remove-exclude ~/work/vendor` | 移除一个排除项 |
| `--mode all\|allowlist` | `--mode allowlist` | 直接设定模式 |
| `--clear` | `--clear` | 将作用域重置为处处生效，并把受保护路径恢复为内置默认值。也是 `config.json` 损坏后唯一的恢复手段 |
| `--add-protected-path GLOB` | `--add-protected-path "config/security/**"` | 添加仓库相对受保护模式；可重复 |
| `--remove-protected-path GLOB` | `--remove-protected-path "Dockerfile*"` | 移除一条完全匹配的已配置模式；可重复，输入错误会失败 |
| `--reset-protected-paths` | `--reset-protected-paths` | 只恢复内置受保护路径集合，不改目录作用域 |
| `--check [DIR]` | `--check .` | 只读：报告某个目录的判定结果，默认为当前目录 |

四个带 `DIR` 的开关均可重复。路径在存储时会展开并转为绝对路径，因此输入时用 `~` 或相对路径都可以。

受保护模式会规范化为仓库相对 POSIX glob，支持字面字符、`*`、`?` 和独占完整路径段的 `**`。绝对路径、盘符路径、NUL 字节、空/`.`/`..` 路径段、方括号字符类，以及嵌在其他字符中的 `**` 都会被拒绝。

**配置中层级最深的目录说了算。** 纳入 `~/work`、排除 `~/work/vendor`、再纳入 `~/work/vendor/mine`，则插件只在第一和第三处生效。完全相同的纳入/排除对，以排除为准。

两个环境变量可在不改动文件的前提下覆盖配置，只作用于单个进程——适合临时会话：

| 变量 | 效果 |
| --- | --- |
| `DEV_FLOW_SCOPE` | 替换纳入目录，**并**强制 `allowlist` 模式 |
| `DEV_FLOW_SCOPE_EXCLUDE` | 替换排除目录，两种模式下均可 |

两者都接受以 `os.pathsep` 分隔的列表（POSIX 用 `:`，Windows 用 `;`），`scope` 会在 `overrides` 字段中回报它们。

### 6. 验证配置

以下是 Bash、PowerShell 和命令提示符都可采用的单行参数序列；请使用该 shell 对应的绝对路径拼写：

```text
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --check .
```

配置正确时会输出一行 JSON，退出码为 `0`：

```json
{"changed": false, "check": {"in_scope": true, "matched": "/home/me/work", "mode": "allowlist", "path": "/home/me/work/my-service", "rule": "include"}, "command": "scope", "config_path": "/home/me/.codex/plugin-data/dev-flow-orchestrator/config.json", "effective": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "missing_paths": [], "ok": true, "overrides": {}, "scope": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "summary": "active only inside the included directories"}
```

`check.in_scope` 就是结论；`check.rule` 和 `check.matched` 说明是哪条配置做出的判定（`default` 表示没有规则命中，由模式决定）。`config_path` 用于确认你实际访问到的是哪个数据目录——如果它不是你预期的路径，请先回到第 4 步。

接着确认钩子确实触发：在作用域内的仓库中开启一个新的 Codex 任务，查看注入的 `Dev Flow controller bootstrap:` 段落，其中会写明控制器路径和数据目录。若它没出现，回到第 3 步；若它指向的数据目录你不认识，回到第 4 步。

最后让 Codex 起一个任务。精简流程是成本最低的端到端检验。

以下是跨平台参数形式：

```text
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --workspace-strategy in-place --change-category docs --target-path docs/login-banner.md --requirement "修正登录横幅的错别字" --repo <repo-path>
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
| `risk_policy.protected_paths` | `<PLUGIN_DATA>/config.json` | 内置完整流程路径集合 | 整机；逐任务固化快照 | [第 5 步](#5-限定插件生效范围) |
| `DEV_FLOW_SCOPE` / `DEV_FLOW_SCOPE_EXCLUDE` | 环境变量 | 未设置 | 单个进程 | [第 5 步](#5-限定插件生效范围) |
| `--flow full\|lite` | `start` | 由 `--workspace-strategy` 推导；仅作可选兼容一致性断言 | 单次 `start` 调用 | [精简流程](#精简流程) |
| `--workspace-strategy in-place\|branch\|worktree` | `start` | 无（必填） | 单个任务，不可更改 | [工作原理](#工作原理) |
| `--change-category` | `start` | 精简流程必填 | 单个任务，不可更改的声明 | [精简流程](#精简流程) |
| `--target-path` | `start` | 精简流程必填 | 单个任务，不可更改的声明 | [精简流程](#精简流程) |
| `--protected-branch` | `start` | 始终包含 `main`、`master`、`trunk`；重复参数只会追加 | 单个任务，不可更改 | [控制器命令](#控制器命令) |
| `--repo` | `start` | 无（必填） | 单个任务，不可更改 | [控制器命令](#控制器命令) |
| `--task-id` | `start` | 自动生成 | 单个任务 | [控制器命令](#控制器命令) |

工作方式、受保护分支和仓库集合都没有全局设置：它们在 `start` 时逐任务决定，此后不可更改。流程由工作方式推导并以不可更改的形式记录，以保证证据始终指明自己是在哪套规则下产生的。

---

## 工作原理

每个新任务都必须先用中文让用户选择工作方式，再执行 `start` 或任何分支/工作树操作：

- **使用当前分支（精简流程）**：传入 `--workspace-strategy in-place`，由控制器推导 `lite`；
- **新建并切换分支（精简流程）**：先展示当前分支、`HEAD`、状态、目标分支和确切的本地 `git switch -c <branch>` 操作，获得批准并完成新建/切换后，再用 `--workspace-strategy branch` 启动，由控制器推导 `lite`；该选择不授权 `fetch` 或 `pull`；
- **创建独立工作树（完整流程）**：传入 `--workspace-strategy worktree`，由控制器推导 `full`，仍须在后续批准确定性的工作区计划。

新调用只需传 `--workspace-strategy`。`--flow` 仅为旧调用方保留为可选兼容一致性断言：匹配值可接受，不匹配值会失败，不能覆盖由工作方式推导出的流程。内部流程 ID 保持 `full`/`lite` 兼容，对用户显示为**完整流程**和**精简流程**。

精简流程适用于常规小范围工作，直接在用户选定的检出分支中运行 `preflight -> lite approval -> implement -> verify -> done`，不创建基线工作树，不做影响分析，不使用 OpenSpec，也不使用托管实现工作树或独立审查机制。schema-v2 精简任务必须只有一个仓库，至少声明一个低风险 `--change-category`（`internal`、`tests` 或 `docs`），并提供至少一个不命中受保护策略的确切仓库相对 `--target-path`。`public-api`、`schema`、`auth`、`migration`、`infrastructure`、`cross-repo`、多仓库，以及缺失或未知声明都会以 `LITE_REQUIRES_FULL` 故障关闭。

Schema-v2 状态确认默认要求显式确认，只有五条精确自动白名单：完整流程最后一个必需基线 `record-index`（`BASELINED -> INDEXED`）、完整流程 `WORKSPACE_READY -> PLANNING`、完整与精简流程的 `IMPLEMENTING -> VERIFYING`，以及完整流程 `review-snapshot`（`VERIFYING -> REVIEWING`）。不能根据命令名或主观安全性推广这份白名单；`DONE` 和 `CANCELLED` 永远显式。

其他 `transition` 或 `cancel` 必须先执行 `--preview`，展示中文`当前状态 → 目标状态`、动作、副作用和目标之后的全部剩余主流程；获得批准后，再把确切返回的 `intent_id` 传给 `--confirm-intent`。intent 会绑定任务、revision、流程、状态边、动作和实时证据；任何漂移都返回 `INTENT_STALE`，必须重新预览。预检保留独立的两阶段协议：`--preview` 不做完整指纹，只绑定确切状态决策和轻量 observation；`--confirm-preview` 才捕获完整证据。决策漂移会使该 token 过期。仅 observation 漂移返回 `PREFLIGHT_EVIDENCE_REFRESH_REQUIRED`；检查并明确接受刷新后的证据后，可用同一 token 加 `--accept-evidence-refresh` 重试。

会推进状态的 `baseline`、`set-route`、路线审批和 `prepare-workspace --execute` 仍是显式领域动作。路线审批同时推进任务时，会以不同 event ID 记录彼此独立的 `gate_approved` 与 `state_transitioned` 审计事实，并共享 transaction/revision/intent；任何一个事实都不能替代另一个。

本插件对每个仓库采用双索引模型。基线项目为不可变的分离式分析工作树建立索引，用于影响分析和路线决策；工作区项目为当前代实现工作树建立索引，用于规划、实现、验证和审查发现。Codebase Memory 不会自动在两者之间选择：每次查询都必须传入当前阶段所选项目返回的精确 ID。控制器通过 `show.index_selection` 显示这一选择，归档每一条已被取代的索引记录以便审计并实现 ID 隔离；当必需的工作区索引缺失或过期时，它会阻止后续关卡继续执行。

控制器本身不会切换或拉取开发者当前的检出目录。只有当用户在 `start` 前明确选择“新建并切换分支”时，主技能才会在展示确切本地操作后单独征求批准；切换完成后，精简任务把该分支作为不可漂移的预检证据。完整流程仍通过批准后的隔离链接工作树实现，不触碰源分支。受控 fetch 只使用已批准的有效 URL 和确切 refspec，并禁用仓库 hook、自定义 upload-pack/传输命令、credential/askpass helper、prune 及自动维护。

选择 OpenSpec 路线时，用户对人类可读制品语言的明确选择优先。用户未明确指定时，先跟随目标仓库现有 OpenSpec 制品的主导语言，再参考其他人类可读制品；信号冲突或无法判断时，必须先停下来询问。工具要求的标识符和固定语法保持不变。

生命周期钩子会在会话开始时注入完整上下文，并在精简检查点内容发生变化的提示词提交时保留确切的解释器、控制器绝对路径和私有数据目录参数；相同内容只会在同一会话内被抑制。主技能每次调用控制器时都会保留这组有序前缀；它不会把解释器替换成针对平台的猜测，也不会假定 `PLUGIN_DATA` 能传入后续执行工具。

### 边界与限制

钩子提供的是任务级防护措施，而非安全边界。只有在匹配的任务处于活动状态时，它们才会保护可识别的文件写入工具并拦截常见的危险 Git 命令；shell 脚本、嵌套工具、托管工具以及被禁用或不受信任的钩子都可能绕过这些防护。控制器状态、制品哈希、显式审批和最终独立审查仍然是事实依据。安装本插件不会全局限制无关的 Codex 任务。

当 Git 无法可靠提供完整字节内容时，证据流水线会以失败关闭方式终止：它会拒绝带有 `assume-unchanged`/`skip-worktree` 标记的已跟踪条目（包括稀疏检出）、存在脏状态的已初始化子模块，以及 clean/process 内容过滤器（例如 Git LFS）。这些是当前有意保留的限制，系统不会在覆盖不完整时静默降级；继续操作前，请将检出目录恢复为规范状态，或改用单独治理的仓库或流程。

当前证据契约版本是 `2`（`evidence_contract_version: 2`）。仓库指纹不会强行伪造 `core.fileMode`、`core.symlinks` 或 `core.ignoreCase`，而是由主机能力探测记录真实的 Git/文件系统配置，并为每个已跟踪条目绑定原始路径、index mode/object/stage、工作树类型和磁盘字节摘要。不同平台可以有不同能力表达，但每种配置都必须携带已跟踪字节清单；观察不完整或存在歧义时，关卡会被阻塞，而不会宣称已经完整覆盖。

重复的测试与审查指纹保持完全相同的 v2 语义 payload 和哈希，但在每个任务中只保存一份 `task-local-json-v1` blob。状态中的条目是存储 locator，而非证据记录，因此会刻意省略 `evidence_contract_version`；当前控制器只有在完整校验 blob 后才接受其中的 v2 payload，旧控制器则会故障关闭，而不会信任一个未经校验的 locator。旧的 inline v2 指纹仍可读取。

新任务使用任务状态 schema v2，其中确认契约和风险评估都是必填安全字段。当前控制器仍可读取并完成 schema-v1 任务；它们保留旧的直接 `transition`/`cancel` 行为和逐状态边人工提示，无法使用 v2 的 `--preview`/`--confirm-intent`。不要把 v1 状态手工改写成 v2，也不要伪造 intent 或风险快照。反过来，只理解 schema v1 的旧控制器会拒绝 schema-v2 任务，而不会静默丢弃这些安全字段。

旧的 v1 证据不满足当前 v2 证据契约与能力配置摘要，会被下游关卡有意视为过期。任务继续前，必须在同一主机上用兼容的当前版本重新生成所需的预检、基线/工作区索引、计划绑定、测试记录和审查快照。若任务已经越过控制器允许刷新所需证据的状态，就不能原地迁移；应取消并新建任务，不能手工修改证据。缺少启动时 `branch_binding` 的旧 `branch` 工作方式任务仍可查看，但会在预检和精简关卡故障关闭；应取消并新建任务，不能人工伪造批准证据。不要给旧证据重新贴标签，也不要把基线 codebase-memory 项目当作工作区项目复用。反过来，使用不理解当前能力配置的旧版插件指向已经由本版本处理过的数据目录也不安全：应重装支持同一证据契约的版本，再重新生成失效证据。旧状态可读不代表语义兼容，更换平台也不是证据迁移路径。

控制器在写入或输出任务状态、事件记录、变更/隔离证据、可预期错误或 CLI JSON 前，会对已识别的带凭据 URL、敏感命名字段和命令行选项、授权值及类似凭据的诊断文本执行结构化脱敏；运行所需的路径、分支名、需求文本和控制器签发的预览令牌会保留精确值。加载仍含已识别敏感材料的旧状态时会在任务锁内执行一次性清理重写，即使首次读取来自 `show` 或 `list` 也一样；这次清理不新增工作流事件，也不表示可以手工编辑状态。

路径与工作区所有权检查会规范化 `/` 与 `\`、盘符与 UNC 拼写、大小写行为、Unicode 规范化及 symlink/junction 别名。尚不存在的目标会绑定到最近的现有祖先，以便探测文件系统行为。能力无法安全测量或身份存在歧义/冲突时，会在分配所有权前故障关闭；应避免仅大小写不同的工作区路径和分支覆盖值，也不要依赖特定平台才接受的别名。

控制器在受保护变更期间拥有其启动的子进程：中断时先请求平台对应的终止，再按需升级并等待回收，确认静止后才释放锁。如果改变 Git 的子进程超时或无法证明已经静止，控制器会在仍持锁时写入持久化 `mutation-quarantine.json`；此后所有状态变更都会被阻止。不要删除或编辑该文件，也不要直接重试原操作。先只读检查报告的进程和仓库证据，再执行 `recover-quarantine --task <task-id> --expected-revision <revision>`；该命令会证明子进程已消失、校验记录的 Git/文件系统后置条件及当前证据契约，然后归档隔离记录。子进程仍存活或无法验证、revision 漂移或后置条件漂移时，恢复仍会故障关闭。

控制器的每个状态文件都通过带回滚证据的原子替换写入。如果这次写入在清理之前被打断——`SIGKILL`、断电，或钩子在超时点被杀死——目标文件旁会残留一个 `.<name>.rollback-<suffix>` 文件，此后针对该文件的所有写入都会以 `ATOMIC_RECOVERY_REQUIRED` 故障关闭，并在 `details.rollback_candidates` 中列出残留路径。这是有意为之：控制器不会覆盖一个上次替换结果无法说明的目标文件。但它并非死路，手工删除也依然不是出路。执行 `recover-atomic-write` 可只读列出全部候选；加 `--apply` 只清除可证明安全的证据，即与已提交目标逐字节相同的副本，或从未提交过新文件时留下的空占位文件。内容与目标不一致意味着这是一个关于已提交状态的决定，因此会继续阻塞，并同时给出两侧的摘要（大小、SHA-256 与 schema 字段），直到你对某个 `--path` 明确选择 `--resolve keep-current` 或 `--resolve restore-rollback`，并用 `--rollback-sha256` 证明确实查看过该文件。该命令绝不替你做选择。

## 控制器命令

插件的全部行为都通过唯一入口 `scripts/dev_flow.py` 完成。技能和钩子不会调用其他任何东西，因此下表即为本插件的完整命令面。

以下为 Bash、PowerShell 和命令提示符通用的单行参数顺序；实际执行时，工作流应使用钩子注入的绝对解释器、控制器和 `--data-dir` 前缀：

```text
<python> <plugin-root>/scripts/dev_flow.py [--data-dir <PLUGIN_DATA>] <command> [options]
```

- `--data-dir` 可以放在子命令之前或之后；完整解析顺序见[第 4 步](#4-指定数据目录)。
- 每条命令只向 stdout 输出一个 JSON 对象。任务类命令返回稳定的 `status`/`flow` ID，同时返回 `status_name`、`flow_name`、`workspace_strategy_name` 和含中文当前/剩余状态的 `workflow`，并保留 `index_selection` 及命令特有字段；`list` 和 `scope` 返回各自的结构。失败时返回 `{"ok": false, "error": {"code", "message", "details"}}`。
- 控制器的命令、参数、help、稳定 ID、JSON 字段、错误码和首方 `error.message` 保持英文；hook/skill 提示以及 `*_name`、工作流名称和选择标签等展示字段使用中文。自动化应根据 `error.code` 分支，不应解析 message 文本。
- 退出码：`0` 成功，`2` 可预期的 `FlowError`，`1` 未预期的内部错误，`130` 中断。
- 任务类命令通过位置参数或 `--task` 指定任务 ID。所有会改写状态的命令还必须提供 `--expected-revision N`；版本号过期时以 `REVISION_CONFLICT` 失败，而不会覆盖并发写入者的结果。
- 控制器只负责记录与校验，绝不代为执行你的构建或测试命令。

| 命令 | 流程 | 适用状态 | 用途 |
| --- | --- | --- | --- |
| `start` | 两者 | 创建任务 | 为一个或多个仓库创建 `INTAKE` 任务 |
| `show` | 两者 | 任意 | 输出精简、分区或完整任务快照 |
| `recover-quarantine` | 两者 | 存在活动隔离记录 | 证明受中断子进程已消失、校验部分后置条件并归档持久化隔离记录 |
| `recover-atomic-write` | 两者 | 无需任务 | 列出并清理原子状态写入被中断后残留的回滚证据 |
| `list` | 两者 | 无需任务 | 列出任务摘要 |
| `scope` | 两者 | 无需任务 | 查看或修改插件生效的目录范围 |
| `preflight` | 两者 | `INTAKE`、`PREFLIGHTED` | 先预览唯一状态边，再用确认令牌记录 Git 身份、远程/基准分支和工作树指纹 |
| `baseline` | 完整 | `PREFLIGHTED`、`BASELINED` | 固定各仓库的远程基准提交；可选地实体化分析工作树 |
| `record-index` | 完整 | `BASELINED`、`INDEXED`（基线）；`WORKSPACE_READY`、`PLANNING`、`IMPLEMENTING`、`VERIFYING`（工作区） | 记录基线或工作区角色的 codebase-memory 索引来源 |
| `record-artifact` | 两者 | 任意活动状态 | 对不可变文件或确定性目录制品计算哈希并记录 |
| `set-route` | 完整 | `INDEXED`、`IMPACT_REVIEW` | 将 `direct` 或 `openspec` 绑定到当前的影响/索引证据 |
| `approve` | 两者 | 任意活动状态 | 以可审计的说明审批指定关卡 |
| `transition` | 两者 | 任意非终态 | 执行一次受控的状态机转换 |
| `prepare-workspace` | 完整 | `ROUTE_APPROVED`、`WORKSPACE_READY` | 记录可审批的工作区计划，或将其执行为隔离工作树 |
| `record-test` | 两者 | `IMPLEMENTING`、`VERIFYING` | 将具名命令标识与精确的仓库指纹绑定记录 |
| `review-snapshot` | 完整 | `VERIFYING`、`REVIEWING` | 捕获 `base...HEAD`、已暂存、未暂存和未跟踪的审查输入 |
| `cancel` | 两者 | 任意非终态 | 以给定原因取消任务 |

"任意活动状态"指既非终态（`DONE`、`CANCELLED`）也非 `BLOCKED` 的状态；具体的制品类型和关卡还会进一步收窄，详见下文。仅限完整流程的命令在精简任务上会以 `FLOW_MISMATCH` 失败，`approve --gate lite` 在完整任务上同样如此。此外，当任务是在预检阶段被阻塞时，`preflight` 也可从 `BLOCKED` 状态执行。

这十七条中有三条不针对单个任务：`scope` 是 `config.json` 的唯一写入者；`recover-atomic-write` 处理控制器已拥有文件上那次被中断的写入；`list` 跨任务列出摘要。其余十四条针对单个任务的状态。加载旧状态时，`show` 或 `list` 还可能执行上文所述的一次性敏感信息清理。

### 任务创建与查看

- `start --repo <path> [--repo <path> ...] --workspace-strategy MODE [--change-category CATEGORY ...] [--target-path PATH ...] "<requirement>"` —— 需求也可用 `--requirement` 传入。`--repo` 必填且可重复；`--workspace-strategy` 同样必填，以证明启动前已经明确选择工作方式：`in-place` 和 `branch` 推导 `lite`，`worktree` 推导 `full`。Schema-v2 精简任务还必须只有一个仓库，重复声明的类别只能取 `internal`/`tests`/`docs`，重复声明的确切仓库相对目标路径不能命中受保护 glob。仅限完整流程的类别为 `public-api`、`schema`、`auth`、`migration`、`infrastructure`、`cross-repo`；缺失或未知声明会故障关闭到完整流程。完整任务也可以记录同样的声明，但不会因此被拒绝。任务会保存规范化值及其确切风险策略快照和摘要。可选的 `--flow` 仅作兼容一致性断言；匹配值可接受，不匹配值会失败而不能覆盖工作方式。仓库集合、需求、推导出的流程、工作方式和风险声明在创建后不可更改。`branch` 会记录用户批准并在 `start` 前完成切换后得到的确切分支和 `HEAD`，并拒绝符号本地分支、受保护分支以及可解析出的远端默认/基准分支。首次全仓库预检确认前，分支和 `HEAD` 都必须保持不变；此后分支永久锁定，而新的 `HEAD` 只能通过新的全仓库预览/确认对和精简审批采纳。控制器的 `start` 本身不执行 Git 切换。`--task-id` 可指定稳定任务 ID；`--protected-branch` 可重复追加，始终只会扩展而永不替换默认的 `main`、`master`、`trunk` 保护集合。受保护名称禁止 branch 模式绑定和直接提交，但显式选择 `in-place` 时仍可在本地编辑。作用域之外的仓库会被 `OUT_OF_SCOPE` 拒绝。
- `show <task> [--compact | --section SECTION ...]` —— 为兼容保留完整状态作为默认输出。`--compact` 只返回流程进度（含 `workflow.remaining`）与任务计数；可重复的 `--section` 只返回指定任务分区。mutation receipt 已含下一 revision/status/workflow 时直接使用；恢复或冲突时用 compact show，关卡缺字段时用 sectioned show。
- `recover-quarantine <task> --expected-revision N` —— 子进程静止性检查失败后，证明记录的进程/进程组已经消失，校验变更的平台和仓库后置条件，并归档持久化隔离记录。该命令绝不会终止进程，也不会把超时当作已经恢复。
- `recover-atomic-write [--path FILE] [--apply] [--resolve keep-current|restore-rollback] [--rollback-sha256 SHA]` —— `ATOMIC_RECOVERY_REQUIRED` 的唯一受支持出路。不带参数时只读列出数据目录下的全部回滚候选，并给出两侧的大小、SHA-256 和 schema 摘要；`--apply` 只清除可证明安全的证据；`--path` 接受被阻塞的目标文件或它的某个回滚文件，与 `--resolve` 搭配时必填。该命令不接受任务 ID，也不需要 `--expected-revision`——残留的回滚文件恰好会阻塞版本检查所需的那次状态写入；它改为持有被中断写入者本应持有的锁。它有意独立于 `recover-quarantine`：后者同样通过原子写入提交任务状态，残留会一并阻塞它，而残留也可能落在不属于任何任务的 `config.json` 或 `workspace-registry.json` 上。
- `list [--active-only] [--status STATE ...]` —— 按更新时间倒序返回摘要。`--status` 可重复，接受任意状态名。
- `scope [...]` —— 目录作用域和受保护路径的全部开关见[第 5 步](#5-限定插件生效范围)，生效范围判定规则见[目录作用域](#目录作用域)。它是配置 schema v2 的唯一写入者。

### 证据记录

- `preflight [--repo ...] [--remote R] [--base B] --preview`，随后以相同参数执行 `--confirm-preview TOKEN [--accept-evidence-refresh]` —— 预览不提交任务状态，也不计算完整工作树指纹，只返回确切来源/目标决策、中文剩余流程、轻量 observation 和 token；`changes_status` 为真时先确认这一条边。confirm 阶段才捕获完整指纹并记录证据。决策漂移返回 `PREFLIGHT_PREVIEW_STALE`，必须重新预览并确认状态边。仅 observation 漂移返回 `PREFLIGHT_EVIDENCE_REFRESH_REQUIRED`，其中带有当前证据和可复用 token；检查并明确接受后，用同一 token 加 `--accept-evidence-refresh` 重试。`--repo` 默认覆盖全部仓库，接受仓库 ID 或路径。只选择部分仓库的一对预览/应用可以记录证据，但绝不改变状态；任何预检状态转换都必须最后执行一次覆盖全部仓库的预览/确认并捕获每个仓库的完整证据。任务进入 `PREFLIGHTED` 后，重新预检也必须覆盖全部仓库。
- `baseline [--fetch] [--materialize]` —— 每次调用（包括裸 `baseline`，以及不获取网络内容的 `--materialize`）都要求当前有效的 `baseline-fetch` 审批。`--fetch` 执行受约束且不调用外部 helper 的网络获取，并额外要求该审批带有 `--allow-fetch`；若批准的预检快照存在未提交改动，还必须带有 `--allow-dirty`。`--materialize` 在固定的 `base_sha` 上创建或复用分离式分析工作树。
- `record-index [--role baseline|workspace] [--repo ...] [--commit SHA] [--index-id ID] [--receipt FILE] [--metadata-json JSON]` —— `--role` 默认为 `baseline`。基线索引可在 `BASELINED`/`INDEXED` 记录；工作区索引可在 `WORKSPACE_READY`/`PLANNING`/`IMPLEMENTING`/`VERIFYING` 记录。`--commit` 对基线索引默认取固定的基准提交，对工作区索引默认取当前 `HEAD`。只有基线角色省略 `--index-id` 时，才可依赖 `impact-degraded` 审批和元数据中的失败来源信息；工作区索引必须提供成功且非空的 `--index-id`，并在元数据中显式写入 `persistence:false`。
- `record-artifact --path FILE_OR_DIR --kind KIND [--verdict PASS|CONDITIONAL|FAIL] [--metadata-json JSON]` —— `--artifact` 是 `--path` 的等价别名。已识别的制品类型与阶段绑定：`impact`（位于 `INDEXED`/`IMPACT_REVIEW`，记录后会清除已有的路线审批）、`direct-contract`/`openspec-plan`（位于 `PLANNING`）、`review-report`（位于 `REVIEWING`，此时 `--verdict` 必填且必须与报告正文的 `Verdict:` 行一致）。`workspace-plan` 与 `review-snapshot` 由控制器生成，在此处会被 `RESERVED_ARTIFACT_KIND` 拒绝；其他类型作为自由形式的证据记录。
- `record-test --name NAME --command CMD --exit-code N [--repo ...] [--output FILE]` —— 命令字符串只被记录，绝不执行。该记录绑定当前计划（完整流程）或精简审批，以及记录时刻的仓库指纹，因此之后任何改动都会使其失效。完整指纹在每个任务内只保存一次，位置为 `artifacts/fingerprints/<fingerprint-sha256>.json`；状态仅保留经过校验的精简引用，响应则是 compact receipt。
- `review-snapshot [--repo ...]` —— `--repo` 必须覆盖任务中的全部仓库。它复用同一份任务内指纹 blob，并只返回指向 manifest 的 compact receipt，不再内联完整快照。

### 决策与流转

- `set-route direct|openspec --reason "..."` —— 路线也可用 `--route` 传入。
- `approve --gate GATE --note "..." [--artifact-sha256 SHA] [--accept-conditional] [--allow-fetch] [--allow-dirty]` —— 完整任务的关卡为 `baseline-fetch`、`impact-degraded`、`route`、`workspace`、`plan` 和 `review`，精简任务的关卡为 `lite`。绑定证据的关卡要求 `--artifact-sha256` 指向任务上已记录的制品。`--accept-conditional` 仅用于 `review`，`--allow-fetch` 仅用于 `baseline-fetch`，`--allow-dirty` 仅用于 `baseline-fetch` 和 `lite`；用于其他关卡会报 `INVALID_ARGUMENT`。`FAIL` 的审查结论无法被审批通过。
- `transition STATE [--note "..."] [--preview | --confirm-intent INTENT]` —— 目标状态也可用 `--to` 传入。允许的边包括所在流程的下一个状态、其返工边（完整流程可退回 `PLANNING`、`IMPLEMENTING` 或 `INDEXED`；精简流程可退回 `IMPLEMENTING` 或 `PREFLIGHTED`），以及 `BLOCKED`/`CANCELLED`。转入 `BLOCKED`、`CANCELLED`、重新规划和重新评估影响时必须提供 `--note`。Schema-v2 任务中，不在精确自动白名单内的每条边都先用 `--preview`，再以 `--confirm-intent` 应用未变化的返回 intent；`DONE` 和 `CANCELLED` 永远显式。被阻塞的任务通常只能恢复到被阻塞前的状态，但 `lite-risk` 阻塞必须取消/替换，不能恢复。每次转换都会重新校验目标状态的守卫和实时证据，因此工作树漂移、缺失的工作区索引、过期的审查快照和非当前的测试记录都会在此处故障关闭。
- `prepare-workspace [--repo ...] [--branch B] [--path P] [--workspace-path REPO=PATH ...] [--workspace-branch REPO=BRANCH ...] [--dry-run | --execute]` —— 默认为 `--dry-run`，记录一份确定性的 `workspace-plan` 制品；`--execute` 严格执行最近一份已获 `workspace` 审批的计划。`--path` 只在选定单个仓库时有效，其余情况请使用可重复的 `REPO=...` 覆盖参数。分支默认为 `codex/<task-id>`。
- `cancel --reason "..." [--preview | --confirm-intent INTENT]` —— 结束非终态任务的推荐方式。Schema-v2 取消永远先预览，再应用确切的已确认 intent；schema-v1 任务保留人工提示后的旧直接调用。`DONE` 任务无法被取消。

## 精简流程

目录作用域决定插件在*哪里*生效；流程决定该作用域内的任务需要运行*多少*流水线。精简任务的状态机为 `INTAKE -> PREFLIGHTED -> IMPLEMENTING -> VERIFYING -> DONE`：

下面是 Bash、PowerShell 和命令提示符通用的单行参数序列：

```text
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --workspace-strategy in-place --change-category internal --target-path src/component.py --requirement "fix ..." --repo <path>
```

- 工作方式在 `start` 时选定并唯一推导不可更改的流程；它本身也与需求、仓库集合一样不可更改。精简流程可记录“使用当前分支” (`in-place`) 或“启动前新建并切换分支” (`branch`)；任务开始后两者都禁止再次切换分支。它还保存规范化的低风险类别/目标声明和确切受保护策略快照。
- 精简关卡（`approve --gate lite`）用一次显式决策取代完整流程的六个关卡（`baseline-fetch`、`impact-degraded`、`route`、`workspace`、`plan`、`review`）：在已记录的确切检出目录中就地工作。它会绑定每个仓库的分支、`HEAD` 和工作树指纹；每次重新执行 `preflight` 都会清除该审批，进入实现阶段时还会重新验证这三项实时状态。
- 仅限完整流程的命令（`baseline`、`record-index`、`set-route`、`prepare-workspace`、`review-snapshot`）以及全部六个完整流程关卡，在精简任务中都会以 `FLOW_MISMATCH` 失败；反之，精简关卡在完整任务中也会如此。
- 测试记录绑定当前精简审批，而非计划哈希。进入 `DONE` 前，每个仓库仍须具备一条当前有效且通过的测试结果，其指纹必须与最终工作树一致。
- Schema-v2 在进入 `VERIFYING` 或 `DONE` 前，会重新分类自获批预检 `HEAD` 以来的每一条实时变更路径，包括已提交、已暂存、未暂存和未跟踪路径。受保护路径、声明目标之外的变更，或不可读/有歧义的证据会让只读 `--preview` 返回 `required_flow: full`；任何实际应用该推进的尝试都会持久化为 `BLOCKED`，并记录 `blocked.phase: lite-risk` 和 `required_flow: full`。控制器不会改动检出目录；应显式预览/确认取消，再创建 worktree/完整流程替代任务，绝不原地修改流程。
- 精简流程中只有 `IMPLEMENTING -> VERIFYING` 是自动状态边。`PREFLIGHTED -> IMPLEMENTING`、返工、`DONE` 和 `CANCELLED` 都必须使用 schema-v2 intent 协议。
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
├── .gitattributes                    # canonical 候选的 LF 检出策略
├── .github/workflows/
│   └── cross-platform.yml            # Windows/macOS/Linux 原生验证矩阵
├── .codex-plugin/plugin.json        # 必需的插件清单
├── INSTALL.md                        # 精确的个人/仓库安装位置映射
├── hooks/
│   ├── hooks.json                   # POSIX/Windows 成对的钩子注册
│   ├── dev_flow_hook.cmd            # 原生 Windows 启动 shim
│   └── dev_flow_hook.py             # 共享的状态注入和防护逻辑
├── scripts/
│   ├── dev_flow.py                  # 稳定 CLI 门面与有序运行时加载器
│   ├── dev_flow_parts/              # 十个不可拆分安装的控制器实现部件
│   ├── audit_runtime_imports.py      # 标准库依赖与隔离启动审计
│   ├── candidate_identity.py         # canonical-v1 身份与确定性 handoff
│   ├── validate_package.py          # 清单、默认钩子和包清单检查
│   ├── run_bundled_validators.py    # 官方 validators 与双层候选摘要
│   ├── windows_native_validation.py # Windows 原生证据 runner
│   └── windows_native_validation.cmd # runner 的 Windows Python 启动器
├── skills/
│   ├── follow-dev-flow/             # 主工作流入口
│   ├── analyze-change-impact/       # 基于 codebase-memory 的影响分析
│   └── review-dev-flow-change/      # 独立的完整变更审查
├── templates/marketplace-entry.json # 用于合并到本地市场的条目
├── templates/personal-marketplace.example.json # 完整的首个市场配置示例
└── tests/                            # 可移植的离线单元测试
```

不要将钩子或辅助脚本分别复制到各个业务仓库中。应将整个插件目录作为一个整体安装。每个目标仓库只需在 `AGENTS.md` 中保留项目专属指导；当选择 OpenSpec 路线时，由 `openspec init`/`openspec update` 生成当前的 Codex OpenSpec 技能。

## 开发验证

在插件源码根目录中运行。以下五条均为单行参数序列，可用于 Bash、PowerShell 或命令提示符；`<python>` 始终替换成受支持解释器的实际命令或绝对路径：

```text
<python> -m unittest discover -s tests -v
<python> scripts/audit_runtime_imports.py
<python> scripts/validate_package.py
<python> scripts/run_bundled_validators.py --require-available
openspec validate complete-cross-platform-support --strict
```

这些检查依次覆盖完整单元测试、运行时仅标准库/隔离启动、插件清单与官方默认 `hooks/hooks.json` 发现及包内引用、三个随包技能与插件清单的官方 validators、以及严格 OpenSpec 变更校验。`scripts/audit_runtime_imports.py` 会解析所有随包运行时导入，并用隔离的 `-I -S` 启动控制器、钩子和 Windows 原生 runner；`scripts/validate_package.py` 独立验证默认钩子，因为 `.codex-plugin/plugin.json` 必须省略官方 plugin validator 尚不支持的 `hooks` 字段。

`scripts/run_bundled_validators.py` 会在候选快照前后记录摘要，并尝试从 Codex home 自动发现官方 skill/plugin validators。必需 CI 会从固定的 `openai/codex` commit 取得这两个官方脚本，同时校验 Git blob ID 与 SHA-256，并用 `--require-available` 失败关闭。若本地开发环境中的脚本不存在或其依赖不能导入，省略严格参数的诊断运行会输出 JSON `status: "unavailable"`，使其余检查仍可继续，但这**不等于**官方 validator 已通过。最终交付必须在 validators 确实可用的环境中运行：

```text
<python> scripts/run_bundled_validators.py --require-available
```

如需显式定位，可设置 `DEV_FLOW_SKILL_VALIDATOR`、`DEV_FLOW_PLUGIN_VALIDATOR` 和（必要时）`DEV_FLOW_VALIDATOR_PYTHON`。`--require-available` 会把任何 `unavailable` 当作失败，因此 handoff 不能用默认的软诊断替代真实通过记录。

每个必需的 CI job 都会使用真实 Git，在其检出的确切 `github.sha` 上运行同一套完整验证：Python 3.9 和 3.14 覆盖原生 Windows、macOS、Linux，3.10–3.13 另在 Linux 覆盖。模拟 Windows 分支或仅启动 `commandWindows` 仍不足以声明完整 Windows 插件支持。发布前还必须在真实 Windows Codex 主机上，从已确认的本地市场安装候选插件并开启新任务；安装/来源路径须覆盖空格、Unicode、`&` 和括号，并记录默认发现 `hooks/hooks.json`、选择 `commandWindows`、真实 `PLUGIN_ROOT`/`PLUGIN_DATA` 注入、bootstrap/checkpoint 拾取，以及良性命令放行和受保护 Git 变更拒绝。没有这份实机 smoke 证据时，不得对外声明 Windows 支持已经完成验证。

### 跨主机 Windows 原生自测

跨主机绑定使用 `dev-flow-canonical-v1`，而不是本机完整快照摘要。canonical v1 按精确 UTF-8 POSIX 路径和原始文件字节哈希显式包清单，不纳入时间戳、所有者和可执行位，只从 canonical 摘要排除 OpenSpec 进度，并拒绝意外路径、符号链接和 reparse point，同时断言已发布的双文件黄金向量。`scripts/run_bundled_validators.py` 同时输出 `canonical_candidate_sha256` 与模式敏感的 `host_local_snapshot_sha256`；只有前者可跨操作系统比较。

实现、文档、工作流和 cachebuster 全部冻结后，在精确候选根目录生成保字节 handoff。两个输出文件必须尚不存在、父目录必须已存在，且必须位于候选根目录之外。

macOS/Linux Bash：

```bash
mkdir -p "$HOME/dev-flow-windows-handoff"
"<python>" scripts/windows_native_validation.py prepare --candidate-root . --archive "$HOME/dev-flow-windows-handoff/dev-flow-candidate.zip" --manifest "$HOME/dev-flow-windows-handoff/dev-flow-candidate.json"
```

命令输出中的 `candidate_sha256` 就是 `<canonical-sha256-from-prepare>`，必须原样保留为 64 位小写十六进制值。不要解压，也不要经过文本转换；直接把 ZIP 和 JSON 传到 Windows。ZIP 是确定性的 `ZIP_STORED`，外部 manifest 会绑定归档文件、精确成员集合、成员哈希和 canonical 摘要。

在 Windows 上准备一个普通可写目录，并让它同时通过本地路径和已存在的 UNC 共享访问。两条路径必须指向同一个目录，且都不能是盘符根或共享根。例如管理员已经把 `C:\dev-flow-share-parent` 共享为 `DevFlowNative`，则使用子目录 `C:\dev-flow-share-parent\test-root` 和 `\\localhost\DevFlowNative\test-root`。runner 不会创建或删除共享。

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "C:\dev-flow-share-parent\test-root" | Out-Null
New-Item -ItemType Directory -Force "C:\dev-flow-windows-handoff" | Out-Null
& ".\scripts\windows_native_validation.cmd" run --archive "C:\dev-flow-windows-handoff\dev-flow-candidate.zip" --manifest "C:\dev-flow-windows-handoff\dev-flow-candidate.json" --expected-canonical "<canonical-sha256-from-prepare>" --local-root "C:\dev-flow-share-parent\test-root" --unc-root "\\localhost\DevFlowNative\test-root" --code-page 936 --report "C:\dev-flow-windows-handoff\windows-native-report.json"
```

Windows 命令提示符：

```bat
scripts\windows_native_validation.cmd run --archive "C:\dev-flow-windows-handoff\dev-flow-candidate.zip" --manifest "C:\dev-flow-windows-handoff\dev-flow-candidate.json" --expected-canonical "<canonical-sha256-from-prepare>" --local-root "C:\dev-flow-share-parent\test-root" --unc-root "\\localhost\DevFlowNative\test-root" --code-page 936 --report "C:\dev-flow-windows-handoff\windows-native-report.json"
```

`936` 是文档默认的非 UTF-8 代码页；如主机不支持，可改为另一个已安装的 legacy code page。报告路径必须是新文件，父目录须已存在，并位于候选及两条测试根路径之外。runner 会先验证 manifest、archive、成员路径与字节，使用二进制写入而非 `extractall`，证明本地/UNC 身份一致后才创建一个随机 sentinel 子目录。它只使用隔离控制器状态和仓库级 Git 配置，把 `chcp` 限定在子 `cmd.exe`，并且只清理 sentinel 完全匹配的自有子目录。它不会安装插件、复用活动 `<PLUGIN_DATA>`、修改机器/全局 Git 配置、发布、推送、创建/删除共享或覆盖报告。`--keep-owned-fixture-on-failure` 只保留该自有子目录，并强制结果为 `incomplete`。

请把新生成的 `windows-native-report.json` 原样返回审查。有效报告必须绑定相同的 expected/observed canonical 摘要，legacy code page 与 UNC/长路径/真实 worktree 检查均为 `passed`，cleanup 也为 `passed`。macOS/Linux 只能验证 prepare 和故障关闭逻辑，绝不能生成 Windows native `passed`。

项目内自测与真实 Windows Codex-host pickup smoke 是两个不同流程。运行自测不授权发布、原生 CI dispatch 或市场安装；这些动作仍需分别显式批准。获准发布时，`.github/workflows/cross-platform.yml` 要求传入已评审的 canonical 摘要，每个 Windows/macOS/Linux job 都校验其 64 位小写格式、canonical 黄金向量与本地摘要一致性；普通 push/pull request 检查不构成发布授权。

仅在 CI 中执行命令不足以证明 Windows 上的 Codex 集成。对外发布 Windows 支持前，必须在真实 Windows Codex 主机上，从已确认的本地市场安装带 cachebuster 的候选插件并开启新任务；证明默认发现 `hooks/hooks.json`、选择 `commandWindows`，观察真实的 `PLUGIN_ROOT`/`PLUGIN_DATA`，并完整走通包含空格、Unicode、`&` 和括号的安装路径。还须针对同一候选摘要记录 bootstrap/checkpoint 拾取、良性命令放行和受保护 Git 变更拒绝。没有这份真实主机 smoke 证据，就不能宣称 Windows 支持已经完成验证。

## 安装位置

完整的包放置映射、`<PLUGIN_DATA>` 下的运行时数据布局，以及已安装副本的更新流程，请参阅 [`INSTALL.md`](INSTALL.md)。个人使用时，请将整个目录放到个人市场条目所引用的插件位置。对于仓库市场，请将其放在 `<marketplace-root>/plugins/dev-flow-orchestrator/`，并让该市场条目指向 `./plugins/dev-flow-orchestrator`。

安装或更新插件后，请启动一个新的 Codex 任务，以加载新的技能和钩子。Codex 提示时，请审查并信任所捆绑的钩子。活动任务状态仍只属于创建它的主机；重装插件不代表可以把执行中的状态目录复制到另一操作系统。
