
Let me start by reading the project's key entry files and configuration in parallel:
Now let me read the core implementation files in parallel:
Let me read the critical sections of the large controller and other scripts:
Let me read more critical files - skills, tests, CI config, and more of the controller:
Let me read the test files, reference documents, and more controller code:
Let me read key sections of the controller for atomic writes, locking, and the command dispatch:
Let me read a few more critical sections and then read the reference files:
Let me read a few more important files for the audit:
Let me read a few more critical sections:
Let me do final verifications on critical code paths:
以下是对 **dev-flow-orchestrator** Codex 插件的完整代码审核报告。

---

## 一、总体结论

**整体评价**：这是一个设计精良、工程化水平很高的 Codex 插件。核心控制器（12,813 行纯标准库 Python）实现了一个完整的、带防护栏的开发工作流状态机，包括原子写入回滚、文件锁、子进程隔离（mutation containment）、双索引模型、两阶段预检协议等。代码在防御性编程方面做得非常出色——mutation quarantine、rollback evidence、POSIX/Windows 双平台文件锁、Windows ACL 校验等都是少见的高质量标准。

**当前阶段**：**可用 → 接近生产级**。核心状态机、原子写入、文件锁和突变隔离机制已达到生产级质量。存在一些需要修复的问题，但不影响基本功能可用性。

**建议**：**建议修改后使用**。虽然不存在必须立即修复的 P0 安全问题，但以下 P1 问题建议在正式推广前修复。

---

## 二、问题清单

### P0：严重问题

无确定的 P0 级别问题。

> **需要验证**：`_mutation_gate_code`（行 3738-3778）通过 `sys.executable -I -S -c` 执行嵌入代码，以 JSON 参数传递实际命令。Gate 子进程运行 `subprocess.run(command, ...)`（`command` 为 list，非 shell 字符串），此处不存在命令注入风险。但 `sys.executable` 本身可被调用方控制的环境变量（如 `__PYVENV_LAUNCHER__` 或虚拟环境路径）影响——如果 hook 使用了被污染的 Python 解释器启动，gate 子进程会继承同一解释器。由于控制器仅依赖标准库且 gate 使用 `-I -S` 隔离模式，此风险极低。

---

### P1：高优先级

#### 问题 1：Hook 与 Controller 之间存在大量重复的常量定义

- **严重级别**：P1
- **涉及文件**：
  - [dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L20-L105)
  - [dev_flow.py](file:///d:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py#L48-L108)
- **问题原因**：Hook 中复制了 Controller 的 `STAGES`、`LITE_STAGES`、`STATE_NAMES_ZH`、`FLOW_NAMES_ZH`、`WORKSPACE_STRATEGY_NAMES_ZH`、`DEFAULT_PROTECTED_BRANCHES`、`NEXT_ACTIONS`、`LITE_NEXT_ACTIONS`、`PENDING_GATES`、`LITE_PENDING_GATES` 等常量。Hook 仅在少数场景（`in_configured_scope`、`load_active_task`）导入 Controller，其余场景使用自己的副本。
- **触发场景**：任何人修改 Controller 中的状态机定义（例如增加新状态、修改中文名称）而忘记同步更新 Hook 中的常量。
- **影响**：Hook 会向 AI 代理注入**错误的**当前状态中文名、下一步动作建议、待审批 Gate 名称。AI 代理可能因此尝试无效的状态转换，或向用户展示不一致的信息。由于 Controller 才是最终的状态机执行者（通过 `command_transition` 校验），错误的上下文信息不会导致状态损坏，但会严重破坏用户体验和工作流效率。
- **推荐方案**：Hook 应当始终从 Controller 导入这些常量，而不是维护副本。具体做法是将这些常量抽取到一个独立的轻量级模块（例如 `scripts/constants.py`），Hook 和 Controller 都从该模块导入。这样在 `_import_controller()` 中导入常量模块（而非整个 12,813 行的 Controller）也不会带来性能问题。
- **代码示例**：创建 `scripts/constants.py`，将 `STAGES`、`STATE_NAMES_ZH` 等常量移入；然后在 Hook 和 Controller 中 `from constants import STAGES, STATE_NAMES_ZH, ...`。

---

#### 问题 2：Hook 导入 12,813 行的 Controller 仅用于 scope 解析，影响启动性能

- **严重级别**：P1
- **涉及文件**：
  - [dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L142-L145) `_import_controller()`
  - [dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L163) `from dev_flow import evaluate_scope, resolve_scope`
  - [dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L180) `from dev_flow import find_active_task_for_cwd, load_state`
- **问题原因**：`in_configured_scope()` 和 `load_active_task()` 通过 `_import_controller()` 将 `scripts/` 目录加入 `sys.path` 并导入完整的 `dev_flow` 模块。`dev_flow.py` 长 12,813 行，导入时会执行大量模块级代码（包括 15 个函数定义、ctypes 结构体定义、正则编译、全局字典构建等）。Codex 在每次 SessionStart、UserPromptSubmit 和每次 Bash/Edit/Write 工具调用前都会触发 Hook，这意味着 Controller 模块可能被重复导入（取决于 Hook 进程模型）。
- **触发场景**：Codex 在每个用户提示和每次工具调用时触发 Hook。如果 Controller 导入耗时显著（在低配机器或网络文件系统上），会导致可感知的延迟。
- **影响**：Hook 响应延迟增加，影响 Codex 会话的交互体验。此外，`sys.path.insert(0, ...)` 是全局副作用，如果 Hook 进程被复用，可能影响其他模块的导入。
- **推荐方案**：将 `evaluate_scope`、`resolve_scope`、`find_active_task_for_cwd`、`load_state` 及其依赖抽取到独立的轻量模块（如 `scripts/scope.py` 和 `scripts/task_lookup.py`），确保这些模块不依赖 `dev_flow.py` 的其他重型依赖。这同时也解决了问题 1 的常量重复问题。

---

#### 问题 3：`find_active_task_for_cwd` 在大量任务时的 O(n) 扫描可能超时

- **严重级别**：P1
- **涉及文件**：[dev_flow.py](file:///d:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py#L1026-L1060)
- **问题原因**：`find_active_task_for_cwd()` 遍历 `tasks_dir.glob("*/state.json")` 并逐个加载+校验每个 state.json，然后按 `updated_at` 和 `revision` 排序取最大值。当任务目录中存在大量历史任务（已完成或已取消）时，扫描所有 state.json 并逐个反序列化的开销不可忽略。由于 Codex 可能为每次 Hook 调用执行此扫描（取决于工作目录），这可能导致 Hook 超时。
- **触发场景**：用户长期使用插件，积累了数百个任务后，Hook 的 SessionStart 响应时间逐渐增长。Codex 的 Hook 超时机制会终止超时的 Hook，导致状态上下文被静默丢弃。
- **影响**：Hook 超时后静默失败（fail-open），AI 代理收不到当前任务的状态信息，无法正确引导工作流。用户可能困惑为什么工作流状态"消失"了。
- **推荐方案**：
  1. 在 tasks 目录下维护一个轻量索引文件（如 `active-tasks.json`），由 Controller 在创建/完成任务时原子更新。
  2. 在扫描时跳过 `status` 为 `DONE` 或 `CANCELLED` 的任务（当前已跳过，在第 1042-1043 行），但优化方案是添加提前退出：如果当前目录已经匹配到活动任务，不需要继续扫描剩余任务。
  3. 可考虑在扫描中设置总时间限制，超时则返回 `None`（符合现有 fail-open 设计）。
- **注意**：当前代码在第 1042-1043 行**已经**过滤终端状态，但仍在遍历所有文件后才过滤。可优化为在 `load_state` 内部检查 `status`。

---

#### 问题 4：`_same_path` 对不存在的路径使用 fallback 比较可能产生误判

- **严重级别**：P1
- **涉及文件**：[dev_flow.py](file:///d:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py#L721-L751)
- **问题原因**：当两个路径都不存在时，`_same_path` 回退到 `_filesystem_identity` 比较。`_filesystem_identity` 查找最近的已存在祖先目录来获取文件系统标识（device/inode 或 volume_serial/file_index）。如果两个不存在的路径共享同一个最近祖先但实际目标是不同文件系统的挂载点，它们会被**错误地判断为相同**。
- **触发场景**：在多挂载点环境中（例如 `/home` 和 `/data` 是不同的文件系统），如果两个不存在的路径都在 `/home/user/` 下，但其中一个实际应该解析到 `/data` 的 bind mount，`_same_path` 可能返回 `True`（因为 `_nearest_existing_path` 对两者都返回 `/home/user`）。
- **影响**：路径身份校验（preflight 指纹比较、scope 解析去重、capability profile 路径匹配）可能出现误判。最坏情况下，preflight 确认阶段的跨仓库指纹校验（行 7537-7562）可能接受不一致的仓库状态。
- **推荐方案**：当两个路径都不存在时，不应仅依赖文件系统身份，还应比较规范化路径字符串和 `suffix_parts`。实际上，当前代码已经同时检查 `normalized` 字符串、`ancestor_identity` + `suffix_parts`、和 `anchor` + `parts`，但 `ancestor_identity` 可能相同而 suffix 不同。需要验证三个匹配路径中是否至少有一个是可靠的。建议增加：当两个路径都不存在时，至少需要 `normalized` 字符串完全相等才认为"same"。

---

### P2：中优先级

#### 问题 5：`_raw_cmd_prefix_payload` 对外层引号的启发式剥离可能误剥离

- **严重级别**：P2
- **涉及文件**：[dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L989-L1001)
- **问题原因**：第 999-1000 行的逻辑 `if len(payload) >= 2 and payload[0] == payload[-1] == '"': payload = payload[1:-1]` 假设如果 `/c` 后的 payload 以双引号开头和结尾，就是 cmd.exe 的 `/s /c` 外层包装。但 cmd.exe 的 `/s` 行为是：如果命令以 `"` 开头，则剥离最外层引号。如果 payload 恰好是一个以引号开头和结尾的单一命令（如 `"C:\Program Files\Git\bin\git.exe"` 后面无参数），剥离后会丢失引号，导致 `_cmd_segments` 后续分词错误。
- **触发场景**：Codex 生成命令 `cmd /s /c ""C:\Program Files\Git\bin\git.exe" status"` 时正确处理。但如果用户自定义命令为 `cmd /c ""some tool.exe""` （工具本身被引号包围且无参数），外层引号被误剥离后剩余 `some tool.exe`（含空格），导致分词错误。
- **影响**：cmd.exe payload 解析失败，Hook 可能无法识别其中的 git 子命令，从而遗漏本应阻止的危险操作。由于 Hook 设计为 fail-open（解析失败时仅返回空结果），这不会阻塞合法操作但会遗漏保护。
- **推荐方案**：增加更精确的 cmd.exe `/s` 行为模拟：检查剥离外层引号后的第一个 token 是否仍被引号包围（表示 cmd.exe 实际执行的是带空格的路径）。如果是，说明确实是一层 `/s` 包装；如果不是（即无空格或已被剥到无引号），则不该剥离。

---

#### 问题 6：`_write_targets` 从 patch 内容提取路径的可靠性有限

- **严重级别**：P2
- **涉及文件**：[dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L121-L124) `_PATCH_PATH` 和 [dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L502-L511)
- **问题原因**：`_PATCH_PATH` 正则表达式仅匹配 `*** Add File:`、`*** Update File:`、`*** Delete File:` 和 `*** Move to:` 模式。不同的 diff/patch 格式（如 unified diff 的 `--- a/file` 和 `+++ b/file`、git format-patch 的 `diff --git a/file b/file`）不会被识别。此外，正则表达式可能匹配到补丁注释或上下文中的类似文本。
- **触发场景**：AI 代理生成的 patch 使用了非标准格式，Hook 无法提取文件路径，导致 `targets` 为空列表。此时 `_write_denial_reason` 回退到仅检查 `workdir`（行 533）。
- **影响**：如果 `workdir` 恰好在允许写入的 workspace 内但实际 patch 目标指向了不允许的路径（例如通过 `..` ），则写入保护被绕过。但由于 `_path()` 在第 514 行已经调用 `resolve(strict=False)` 规范化路径，`..` 遍历会被消解。
- **推荐方案**：
  1. 扩展 `_PATCH_PATH` 支持更多 patch 格式（unified diff 的 `+++ b/`、`--- a/`）。
  2. 当 `targets` 为空时，不应仅依赖 `workdir` 判断，应在 deny reason 中明确说明"无法解析 patch 目标路径"并要求用户确认。

---

#### 问题 7：Windows `dev_flow_hook.cmd` 的 Python 版本探测范围有限且诊断消息可能过时

- **严重级别**：P2
- **涉及文件**：[dev_flow_hook.cmd](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.cmd)
- **问题原因**：探测顺序为 `py -3` → `py -3.14` … `py -3.9` → `python`。当 Python 3.15 发布后，`py -3`（Python Launcher 的默认）可找到 3.15，但如果系统没有安装 Python Launcher，手动探测只覆盖到 3.14。诊断消息 `"Python 3.9–3.14"` 在 3.15 时代会过时。
- **触发场景**：Windows 用户安装了 Python 3.15 但没有 Python Launcher（`py` 命令），且 `python` 命令不存在或指向 Python 2.x。
- **影响**：Hook 静默退出（exit 0），Codex 会话中不显示任何 dev-flow 状态信息。用户可能困惑为什么插件"不工作"。
- **推荐方案**：
  1. 探测循环使用动态上限：`for /L %%v in (14,-1,9) do py -3.%%v ...`（当前已是硬编码，可接受，但需定期维护）。
  2. 诊断消息改为 `"Python 3.9 or later"` 而非 `"Python 3.9–3.14"`，避免版本号过时。
  3. 在 `python` 回退之后，增加最终 `where python 2>nul || echo No Python found` 的诊断。

---

#### 问题 8：`build_bootstrap_context` 和 `build_context` 硬编码中文指令，不可定制

- **严重级别**：P2
- **涉及文件**：[dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L354-L424)
- **问题原因**：bootstrap context（第 363-365 行）和 active-task context（第 403-413 行）包含硬编码的中文行为指令，如"必须用中文询问用户选择……"、"必须先用中文展示……"。这些指令在非中文项目中可能不合适，且无法通过配置覆盖。
- **触发场景**：非中文用户安装了此插件，Hook 在每次 SessionStart 时注入中文指令到 AI 代理的上下文中。
- **影响**：AI 代理可能被中文指令干扰，在英文项目中输出中英文混排的内容。用户体验下降。
- **推荐方案**：将行为指令语言与 `LANG`/`LC_ALL` 环境变量或插件配置关联，默认使用英文指令，中文指令仅当环境指示为中文 locale 时注入。或者通过 `config.json` 的 `locale` 字段配置。

---

#### 问题 9：`_cmd_segments` 在非严格模式下不检测 `%VAR%` 和 `!VAR!` 动态扩展

- **严重级别**：P2
- **涉及文件**：[dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L585-L633) 和 [dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L760-L806)
- **问题原因**：`_payload_has_dynamic_expansion` 仅在 `strict=True` 时被调用（第 951 行）。当以非严格模式（`strict=False`）解析 cmd.exe payload 时，`%VAR%` 和 `!VAR!`（延迟扩展）不会触发检测，cmd.exe 的分词器也不处理这些扩展语法。`%VAR%` 会被当作普通 token 的一部分。
- **触发场景**：Codex 生成的命令中包含 `%USERPROFILE%` 或 `!PATH!` 等动态扩展，Hook 在非严格 POSIX 解析路径下未能识别这些扩展。
- **影响**：Hook 的 git 子命令检测可能无法正确识别嵌入在动态扩展后的命令。但由于 `_git_invocations` 的双解析策略（POSIX + cmd），大多数情况 cmd 路径会捕获。且由于 fail-open 设计，不会阻塞合法操作。
- **推荐方案**：在 `_cmd_segments` 内部直接检测 `%` 字符（不在引号内时），如果发现则标记为"存在动态扩展"。

---

### P3：低优先级

#### 问题 10：探针目录在进程被 SIGKILL 时可能残留

- **涉及文件**：[dev_flow.py](file:///d:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py#L556-L603) `_probe_filesystem_case_sensitive` 和 [dev_flow.py](file:///d:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py#L606-L647) `_probe_filesystem_unicode_distinct`
- **说明**：探针在 `finally` 块中清理临时目录，但 SIGKILL 绕过了 finally。残留的 `.dev-flow-case-*` 和 `.dev-flow-unicode-*` 目录不会影响功能但会污染文件系统。由于探针只在首次调用时（缓存命中后不再创建）执行，影响极小。

#### 问题 11：锁文件残留

- **涉及文件**：[dev_flow.py](file:///d:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py#L2614-L2647) `_file_lock`
- **说明**：`state.lock`、`task-namespace.lock`、`workspace-registry.lock`、`config.lock` 是 1 字节的持久化文件。进程崩溃时文件锁通过 OS 自动释放，但锁文件本身保留在磁盘上。这不会影响功能（每次获取锁时重新打开文件），但大量残留文件在目录列表中显得混乱。可考虑在 `_file_lock` 的 `finally` 中尝试删除锁文件。

#### 问题 12：`_render` 函数 500 字符截断可能丢失信息

- **涉及文件**：[dev_flow_hook.py](file:///d:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py#L249)
- **说明**：对于路由描述、审批备注等可能很长的字段，500 字符截断可能丢失关键信息。

#### 问题 13：Skill 文件内容较简略

- **涉及文件**：`skills/analyze-change-impact/SKILL.md`（39 行）、`skills/review-dev-flow-change/SKILL.md`（52 行）
- **说明**：相比 `skills/follow-dev-flow/SKILL.md` 及其丰富的 references，另外两个 skill 文件相当简短，高度依赖 AI 代理的推理能力而非提供具体指导。

---

## 三、执行流程检查

### 完整执行链路

```
1. Codex 加载插件
   └─ 读取 .codex-plugin/plugin.json（无 hooks 字段）
   └─ 通过默认约定发现 hooks/hooks.json
   └─ 通过 skills 字段发现 skills/ 目录

2. SessionStart / UserPromptSubmit Hook 触发
   └─ Codex 执行: python3 "$PLUGIN_ROOT/hooks/dev_flow_hook.py"（POSIX）
      或 "%PLUGIN_ROOT%\hooks\dev_flow_hook.cmd"（Windows）
   └─ [cmd] 探测 Python 版本 → 调用 dev_flow_hook.py
   └─ [py] main(): 从 stdin 读取 JSON payload
   └─ [py] handle(): 解析 event, plugin context, cwd, tool_input
   └─ [py] load_active_task(): 扫描 tasks/*/state.json
       └─ 内部调用 _import_controller() → import dev_flow
   └─ [py] in_configured_scope(): 检查 scope 配置
       └─ 内部调用 _import_controller() → import dev_flow
   └─ [py] 如无活动任务且在 scope 外: return None（静默跳过）
   └─ [py] SessionStart/UserPromptSubmit:
       ├─ 有任务 → build_context(task) → 注入状态 checkpoint
       └─ 无任务 → build_bootstrap_context() → 注入启动指令
   └─ [py] 输出 JSON → stdout

3. PreToolUse Hook 触发（Bash/apply_patch/Edit/Write）
   └─ [py] handle():
   └─ [py] apply_patch / Edit / Write:
       └─ 检查写入目标是否在允许的路径内
   └─ [py] Bash:
       └─ command_denial_reason(): 检查 git 命令
       └─ _git_invocations(): 双解析（POSIX + cmd）
       └─ 阻止 force-push/reset --hard/clean/pull/switch/worktree add
       └─ 阻止对受保护分支的 commit/push
   └─ 返回 deny 决策或 None（放行）

4. AI 代理使用 Skill 与 Controller 交互
   └─ Skill 指示 ai 调用: python scripts/dev_flow.py <command>
   └─ Controller CLI → main() → build_parser() → command_*()
   └─ command_preflight(): 两阶段协议（--preview → --confirm-preview <token>）
   └─ command_transition(): 状态转换 + 乐观锁（expected_revision）
   └─ 所有写操作通过 _atomic_write_bytes() + _file_lock()
   └─ 子进程通过 _mutation_gate_command() 隔离
```

### 可能重复执行的步骤

| 步骤 | 说明 |
|------|------|
| `_import_controller()` | `in_configured_scope()` 和 `load_active_task()` 各自独立调用。如果两者在同一个 `handle()` 调用中都被触发，Controller 会被导入两次（但第二次导入是 Python 缓存的 no-op，开销在于 `sys.path.insert`）。 |
| `load_state()` for `find_active_task_for_cwd` | 扫描所有非终端任务（即使已找到匹配），缺少提前退出。 |
| Hook 整体执行 | SessionStart 和 UserPromptSubmit 都会注入完整上下文。如果两者紧邻触发（例如用户在新会话中立即提交 prompt），上下文信息会重复出现。这是 Codex 框架行为，非插件问题。 |

### 依赖隐含条件的步骤

| 步骤 | 隐含条件 |
|------|----------|
| `resolve_data_dir()` | 依赖 `PLUGIN_DATA` 环境变量由 Codex 正确设置。如果 Codex 未设置此变量，回退到 `DEV_FLOW_DATA_DIR` 或平台默认路径。首次使用时默认路径可能不存在（`resolve_data_dir` 不创建目录）。 |
| `_file_lock()` | 依赖 `fcntl`（POSIX）或 `msvcrt`（Windows）可用。两者都是标准库模块，在受支持平台上始终可用。但在极端的嵌入式 Python 或无标准库环境中可能不可用，此时锁定失败（fail-closed）。 |
| `_mutation_gate_command()` | 依赖当前 Python 解释器支持 `-I`（隔离模式）和 `-S`（禁用 site-packages）。这两个选项在 Python 3.4+ 中可用。Python 3.4 之前的版本没有 `-I` 标志。 |
| `_controller_prefix()` | 使用 `sys.executable` 作为 Python 解释器路径。如果 Hook 进程的 `sys.executable` 为空（极罕见，如嵌入 Python），命令构造会失败。 |

### 失败后无法恢复的步骤

| 步骤 | 恢复难度 |
|------|----------|
| `_atomic_write_bytes()` 留下 rollback evidence | **可恢复**：`recover-atomic-write` 命令可恢复。但当 rollback 文件存在时，后续写操作被阻止（需要手动干预）。 |
| `_atomic_write_bytes()` 的 post-check 失败且恢复也失败 | **需要手动恢复**：状态文件可能处于中间态。`ATOMIC_RECOVERY_UNCERTAIN` 错误提供了 rollback 路径。 |
| `_begin_mutation_intent()` 写入 quarantine 后子进程未启动 | **自动恢复**：`_abandon_unstarted_mutation_intent()` 在 spawn 失败时回退 quarantine。 |
| 子进程被终止但 quarantine 证据也写入失败 | **部分恢复**：quarantine 文件持久化了 PID 和命令信息。用户可根据 quarantine 内容手动判断是否需要回滚。 |

### 可能污染用户仓库或全局配置的步骤

| 步骤 | 风险 |
|------|------|
| `command_preflight()` 的 `_preflight_repo()` | 在源仓库中执行 `git fetch` 和 `git rev-parse` 等只读操作，不修改用户仓库。 |
| `command_prepare_workspace()` 的 workspace 创建 | **会修改**：创建 git worktree、新建分支或在当前分支上操作。这些是预期行为，但需要用户明确确认。 |
| `_run()` with `mutation=True` | **会修改**：执行 git commit、merge、branch 等操作。通过 mutation gate 隔离，并在 `mutation-quarantine.json` 中记录证据。 |
| `config set` 写入 `config.json` | 修改 `data_dir/config.json`，**不会**修改用户仓库内的配置。 |
| Hook 的 `_import_controller()` | 修改 `sys.path`，这是进程级全局副作用。如果 Hook 进程被 Codex 复用，可能影响后续 Hook 调用或其他插件。 |

### 与文档描述不一致的行为

| 文档描述 | 实际行为 | 文件 |
|----------|----------|------|
| README 描述插件 "best-effort Codex tool guardrails" | 正确，Hook 在所有异常路径上都 fail-open | 一致 |
| INSTALL.md 描述安装步骤 | 正确 | 一致 |
| `plugin.json` 中 `version: "0.3.0"` | 与代码中的 `SCHEMA_VERSION = 1` 不一致——`SCHEMA_VERSION` 是状态文件 schema 版本，与插件版本独立，这是正确的 | 设计如此 |
| Skill 中描述 `codebase-memory selection: explicit project parameter; never automatic` | Hook 注入的 index selection context 正确反映了这一点 | 一致 |

---

## 四、安全检查

### Shell 参数引用

- ✅ **POSIX**: `_quote()` 使用 `shlex.quote()`，这是 Python 标准库中最安全的 Shell 引用方法。
- ✅ **Windows**: `_quote()` 实现了完整的 Windows 命令行转义（反斜杠+双引号），正确处理了路径中的空格和特殊字符。
- ✅ **Controller CLI**: `_controller_prefix()` 正确引用了 `sys.executable` 和 controller 路径。
- ⚠️ **`_cmd_shell_payload`**: 第 838 行 `" ".join(parts)` 在拼接 cmd.exe payload 时未重新引用包含空格的参数——但这仅用于检查（inspection），不用于执行，因此安全。

### 用户输入直接拼接到命令

- ✅ **Mutation gate**: 命令作为 JSON 编码的 list 传递给 gate 子进程，gate 使用 `subprocess.run(command_list)` 而非 `shell=True`，无命令注入风险。
- ✅ **Controller 所有子进程**: 全部使用 `subprocess.Popen(list, shell=False)`（默认）。
- ✅ **Hook 的 `_controller_prefix()`**: 路径通过 `_quote()` 处理后拼接到命令行字符串中，但此字符串随后通过 `subprocess` 以 list 形式执行（在 Controller 中），不会经过 shell 解析。

### 文件路径规范化和范围限制

- ✅ **`_path()`**: 在所有输入路径上调用 `expanduser()` + `resolve(strict=False)`，规范化 `..` 和符号链接。
- ✅ **`_within()`**: 使用 `Path.relative_to()` 检查路径是否在父目录内，正确处理了 `..` 遍历。
- ✅ **Scope 检查**: `evaluate_scope()` 在解析后的路径上使用 `_within()` 进行比较。
- ⚠️ **`resolve(strict=False)`**: 对于不存在的路径，`resolve(strict=False)` 不会解析不存在的中间组件。这意味着 `/a/b/../c` 中如果 `b` 不存在，`..` 不会被消解。但在当前使用场景中，路径通常指向已存在的文件和目录。

### 误删、覆盖或修改用户文件的风险

- ✅ **原子写入**: `_atomic_write_bytes()` 在替换前创建 rollback 证据，替换后验证权限和父目录 fsync。
- ✅ **Rollback 检测**: 下次写入前检查是否存在未清理的 rollback 证据，防止级联损坏。
- ✅ **乐观锁**: `expected_revision` 机制防止基于过期状态的操作。
- ⚠️ **`command_prepare_workspace()` 的 workspace 操作**: 这是唯一可能修改用户仓库的命令（创建分支、worktree 等）。但这些操作需要用户明确确认（通过 Skill 中的中文指令），且有状态机保护。

### 不安全的 eval、source、通配符或递归删除

- ✅ 代码中无 `eval()` 或 `exec()` 调用。
- ✅ 无 `source` 或 `.`（shell source）调用。
- ✅ `shutil.rmtree` 仅用于清理已知的临时目录（探针目录），且被 `FileNotFoundError` 保护。
- ✅ Hook 积极阻止 `eval`/`source`/`.` 等动态命令（`_inspect_tokens` 中的 `ambiguous_commands`，行 880-883）。

### 临时文件安全

- ✅ **`tempfile.mkstemp`**: 所有临时文件使用 `mkstemp` 创建，参数 `prefix` 限制在同一目录下（原子替换要求）。
- ✅ **权限**: POSIX 上设置 `0o600`，Windows 上校验 ACL（`_verify_windows_private_path`）。
- ⚠️ **可预测的临时目录前缀**: 探针目录使用 `.dev-flow-case-` 和 `.dev-flow-unicode-` 前缀，可能在多用户系统中暴露信息。但由于使用 `mkdtemp` 添加了随机后缀，且目录权限为 `0o700`，风险极低。

### 敏感信息是否写入日志、状态文件或 Git

- ✅ **`LC_ALL=C`**: Controller 子进程设置 `LC_ALL=C` 和 `LANG=C`，避免 locale 差异导致的不确定性。
- ✅ **Git 环境清理**: Controller 清理了 `GIT_ASKPASS`、`GIT_SSH` 等凭据相关的环境变量。
- ⚠️ **stderr 哈希化**: Controller 在错误详情中包含 `stderr_sha256`（而非纯文本 stderr），减少了敏感信息泄露风险——但这仅在 `COMMAND_FAILED` 错误中，其他错误可能包含完整的 stderr。
- ⚠️ **Quarantine 文件**: `mutation-quarantine.json` 记录了执行的命令（包括参数），可能包含敏感信息（如文件路径、分支名称）。但 quarantine 文件存储在 `data_dir/tasks/<id>/` 下，权限为 `0o600`，仅当前用户可读。

### Hook 是否可能执行仓库中的不可信代码

- ✅ Hook 本身不执行仓库中的代码——它仅导入 Plugin 自己的 `scripts/dev_flow.py`。
- ✅ PreToolUse hook 仅检查命令字符串，不执行任何代码。
- ✅ Mutation gate 子进程使用 `-I -S` 隔离模式，不加载 site-packages 或用户配置。
- ⚠️ **理论风险**: 如果仓库中包含一个名为 `dev_flow.py` 的文件且 `sys.path` 被污染，Hook 的 `import dev_flow` 可能导入错误的模块。但 `_import_controller()` 使用 `sys.path.insert(0, str(scripts_dir))` 确保 Plugin 的 scripts 目录在最前面。然而，如果 Python 的当前工作目录恰好在 `sys.path` 中（Python 默认行为），且仓库根目录中恰有 `dev_flow.py`……实际上，Python 3.x 默认不在 `sys.path` 中包含当前目录（而是包含脚本所在目录），因此这个风险极低。

---

## 五、兼容性检查

### macOS

- ✅ `resolve_data_dir()` 使用 `~/Library/Application Support/dev-flow-orchestrator`（macOS 标准）。
- ✅ `fcntl.lockf` 在 macOS 上可用。
- ✅ POSIX 进程组管理在 macOS 上可用。
- ⚠️ macOS 的 `shlex` 行为可能与 Linux 略有不同（特别是在处理非 ASCII 字符时），但核心功能不受影响。
- ⚠️ macOS 文件系统默认不区分大小写（APFS 可配置），`_probe_filesystem_case_sensitive` 会正确检测。

### Linux

- ✅ `resolve_data_dir()` 使用 `$XDG_STATE_HOME/dev-flow-orchestrator` 或 `~/.local/state/dev-flow-orchestrator`。
- ✅ `fcntl.lockf` 在所有 Linux 发行版上可用。
- ✅ POSIX 进程组管理在 Linux 上可用。
- ✅ CI 矩阵测试了 Python 3.9-3.14 在 Linux 上。

### Windows、Git Bash、WSL 和 PowerShell

- ✅ **原生 Windows**: `commandWindows` 使用 `.cmd` shim，探测 Python 并调用 Hook。
- ✅ **Windows ACL**: `_verify_windows_private_path()` 实现了完整的 ACL 校验（owner、DACL、Everyone/Users 拒绝）。
- ✅ **Windows 文件锁**: `msvcrt.locking` 实现字节范围锁。
- ✅ **Windows Job Objects**: `_windows_kill_on_close_job` 用于子进程隔离和终止。
- ⚠️ **Git Bash**: Git Bash 是 POSIX 环境，Hook 会使用 `python3` 命令（而非 `.cmd`）。如果 Git Bash 的 `python3` 在 PATH 中，工作正常。如果未安装，Hook 失败（但 fail-open）。
- ⚠️ **WSL**: WSL 本质是 Linux，使用 POSIX 路径。但如果 Codex 运行在 Windows 端而仓库在 WSL 端（`\\wsl$\` 路径），可能出现路径不兼容。Controller 的 `_filesystem_identity` 可能无法正确处理 WSL 跨文件系统路径。
- ⚠️ **PowerShell**: `_powershell_segments` 和 `_payload_has_dynamic_expansion` 支持 PowerShell 的 tokenization，但阻止了 `Invoke-Expression`（`iex`）、encoded commands 和 `-File` 参数调用。

### 不同 Shell（Bash、Zsh、Dash）

- ✅ `_posix_segments` 使用 Python 的 `shlex` 模块，遵循 POSIX shell 分词规则。Bash、Zsh 和 Dash 在基本分词上兼容。
- ⚠️ Zsh 和 Bash 有一些 `shlex` 不支持的扩展语法（如 Zsh 的 `=(...)` 进程替换、Bash 的 `<<<` here-string），但这些不影响 git 子命令的识别。
- ⚠️ Dash（Debian/Alpine 的 `/bin/sh`）不支持 `[[` 和某些 Bash 扩展——但 `shlex` 主要处理分词，不影响。

### 路径中包含空格、中文或特殊字符

- ✅ **空格**: `_quote()` 正确处理了 Windows 和 POSIX 路径中的空格。
- ✅ **中文**: `_json_bytes` 使用 `ensure_ascii=False`，JSON 输出中保留中文。状态文件名限制为 ASCII（`TASK_ID_RE`），避免文件系统编码问题。
- ✅ **特殊字符**: `_quote()` 的 Windows 实现正确处理了 `&|()<>^` 等 cmd.exe 特殊字符。
- ⚠️ **`_filesystem_identity`**: Unicode 规范化探针正确处理了 NFC/NFD 差异。但某些文件系统（如 macOS 的 HFS+）强制 NFD 规范化，可能导致 `_same_path` 在规范化后正确匹配。

### Git 仓库、Git Worktree 和非 Git 目录

- ✅ **Git 仓库**: Controller 在所有 git 操作前执行 `_validate_repo()` 验证。
- ✅ **Git Worktree**: `command_prepare_workspace()` 完整支持 worktree 创建、管理和清理。双索引模型（baseline index vs workspace index）正确分离了不同 worktree 的数据。
- ✅ **非 Git 目录**: Hook 的 `load_active_task()` 在非 Git 目录中和谐降级（返回 None → 如无 scope 配置则跳过）。
- ⚠️ **Git 子模块**: Controller 的 `_git` helper 使用 `git -C`，不处理子模块（除非显式配置为独立 repository）。

### 首次运行、重复运行、升级和卸载场景

- ✅ **首次运行**: `_ensure_private_dir` 创建缺失的目录，`load_config` 对缺失的 config 使用默认值。
- ✅ **重复运行**: 乐观锁（`expected_revision`）和文件锁（`_file_lock`）防止并发修改。`_atomic_write_bytes` 的 rollback 证据检测防止脏状态。
- ✅ **升级**: Schema version 检查（`SCHEMA_VERSION = 1`）在 `load_state` 和 `load_config` 中验证，拒绝不兼容的版本。Evidence contract version 检查类似。
- ⚠️ **卸载**: 没有自动清理逻辑。`data_dir` 中的状态文件、锁文件、任务目录会在卸载后残留。这不影响系统其他部分，但占用磁盘空间。可考虑在 INSTALL.md 中说明清理步骤。
- ⚠️ **Hook 升级**: 如果升级了 Hook 脚本但保留了旧的 Controller 模块，Hook 的 `_import_controller()` 可能导入旧版本。但由于 Hook 和 Controller 在同一 Plugin 目录中，通常一起升级。

---

## 六、测试建议

### 现有测试覆盖评估

现有测试（7,217 行 test_dev_flow.py + 1,438 行 test_hooks.py + 366 行 test_packaging.py + 463 行 test_candidate_identity.py）覆盖了：
- Controller 状态机的核心转换和错误路径
- Hook 的命令解析和 guardrail 逻辑
- 打包验证（manifest、hooks、skills）
- 候选身份（canonical identity）的确定性和跨平台一致性

CI 矩阵覆盖了 Linux（3.9-3.14）、macOS（3.9/3.14）、Windows（3.9/3.14）。

### 需要补充的测试用例

#### 1. 重复执行测试

```python
# tests/test_idempotency.py
def test_duplicate_hook_registration():
    """验证 hooks.json 中每个事件类型不会因用户配置重复加载。"""
    # 模拟 plugin.json 无 hooks 字段 + hooks/hooks.json = 仅注册一次
    
def test_double_session_start_context_injection():
    """验证连续两次 SessionStart Hook 不会重复注入上下文。"""
    
def test_concurrent_controller_lock():
    """验证两个进程同时获取同一个 task 的锁时，一个等待、一个超时。"""
    # 启动两个子进程，同时执行 dev_flow.py transition --task test-1 --expected-revision 0 --to BASELINED
    # 期待一个成功、一个 LOCK_TIMEOUT
```

#### 2. 并发执行测试

```python
# tests/test_concurrency.py
def test_concurrent_state_mutation_different_tasks():
    """不同 task 的并发写入不互相阻塞。"""
    
def test_concurrent_task_creation():
    """并发创建 task 时 task-namespace.lock 正常工作。"""
    
def test_concurrent_workspace_registry():
    """并发 workspace 操作时 workspace-registry.lock 正常工作。"""
```

#### 3. 执行中断测试

```python
# tests/test_interruption.py
def test_atomic_write_interrupted():
    """在 atomic write 的 replace 阶段模拟崩溃，然后验证 rollback 证据被检测。"""
    # 使用 mock 或临时文件注入
    
def test_mutation_quarantine_on_child_crash():
    """子进程被 SIGKILL 后，quarantine 证据正确写入。"""
    
def test_mutation_quarantine_recovery_blocks_next_mutation():
    """quarantine 存在时，下一次 mutation 被阻止。"""
```

#### 4. 文件不存在和配置不完整

```python
# tests/test_edge_cases.py
def test_hook_without_plugin_root():
    """PLUGIN_ROOT 不存在时 Hook 输出诊断信息（fail-open）。"""
    
def test_hook_without_plugin_data():
    """PLUGIN_DATA 不存在时 Hook 输出诊断信息（fail-open）。"""
    
def test_empty_tasks_directory():
    """tasks 目录为空时 find_active_task_for_cwd 返回 None。"""
    
def test_corrupted_state_json():
    """state.json 内容不是合法 JSON 时 load_state 返回 TASK_NOT_FOUND。"""
    
def test_missing_controller():
    """scripts/dev_flow.py 不存在时 Hook 输出诊断信息。"""
```

#### 5. 路径包含空格和中文

```python
# tests/test_path_edge_cases.py
def test_scope_with_spaces_in_path():
    """路径包含空格时 evaluate_scope 正常工作。"""
    
def test_scope_with_chinese_path():
    """路径包含中文时 evaluate_scope 正常工作。"""
    
def test_task_directory_with_special_chars():
    """data_dir 路径包含特殊字符时 task 创建和读取正常工作。"""
```

#### 6. Hook 重复注册

```python
# tests/test_hook_registration.py
def test_hooks_json_structure():
    """验证 hooks.json 结构符合 Codex 插件规范。"""
    
def test_no_duplicate_event_registration():
    """验证 plugin.json 未定义 hooks 字段，仅 hooks.json 注册。"""
    
def test_command_and_command_windows_paired():
    """验证每个 hook 条目同时有 command 和 commandWindows。"""
```

#### 7. Git Worktree

```python
# tests/test_worktree.py  
def test_worktree_prepare_and_cleanup():
    """完整的 worktree 创建→使用→清理生命周期。"""
    
def test_worktree_detection_in_scope():
    """Hook 能正确识别 worktree 目录是否在 scope 内。"""
    
def test_worktree_baseline_index():
    """baseline index 在工作树环境中正确指向源仓库。"""
```

#### 8. Windows 和 Unix 路径差异

```python
# tests/test_cross_platform_paths.py
def test_windows_path_case_insensitivity():
    """Windows 不区分大小写的文件系统上 _same_path 正确工作。"""
    
def test_posix_path_case_sensitivity():
    """Linux 区分大小写的文件系统上 _same_path 正确工作。"""
    
def test_windows_unc_path():
    """UNC 路径（\\server\share）的处理。"""
```

#### 9. 自动化执行方案

```yaml
# .github/workflows/test-enhanced.yml 的补充
jobs:
  edge-cases:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ["3.9", "3.14"]
    steps:
      - run: python -m pytest tests/test_concurrency.py -v
      - run: python -m pytest tests/test_interruption.py -v
      - run: python -m pytest tests/test_path_edge_cases.py -v
      # 在 Windows 上额外运行 UNC 路径测试
      - if: runner.os == 'Windows'
        run: python -m pytest tests/test_windows_paths.py -v
```

---

## 七、修复顺序

### 第一阶段：必须优先修复（1-2 周）

| 优先级 | 问题 | 修改文件 | 验证方法 |
|--------|------|----------|----------|
| 1 | **P1-1: 消除 Hook/Controller 常量重复** | 新建 `scripts/constants.py`，修改 `dev_flow.py` 和 `dev_flow_hook.py` 从 constants 导入 | 运行全部现有测试，确认无回归；手动触发 SessionStart Hook 验证上下文输出与 Controller 一致 |
| 2 | **P1-2: 拆分 Controller 导入** | 新建 `scripts/scope.py` 和 `scripts/task_lookup.py`，将 `evaluate_scope`/`resolve_scope`/`find_active_task_for_cwd`/`load_state` 移到 `task_lookup.py` | 运行 `test_hooks.py` 和 `test_dev_flow.py`；验证 Hook 响应时间无明显增加 |
| 3 | **P1-3: 优化 find_active_task_for_cwd** | 修改 `dev_flow.py`（或新的 `task_lookup.py`），添加提前退出和/或轻量索引 | 创建 500+ 个已完成任务后测量 Hook 响应时间 |

### 第二阶段：一起修改（2-3 周）

| 优先级 | 问题 | 修改文件 |
|--------|------|----------|
| 4 | **P1-4: 修复 `_same_path` 不存在路径误判** | `dev_flow.py` `_same_path()` |
| 5 | **P2-5: `_raw_cmd_prefix_payload` 引号剥离** | `dev_flow_hook.py` `_raw_cmd_prefix_payload()` |
| 6 | **P2-6: `_write_targets` patch 路径解析** | `dev_flow_hook.py` `_PATCH_PATH` 正则和 `_write_targets()` |
| 7 | **P2-7: Windows cmd Python 版本探测** | `dev_flow_hook.cmd` |
| 8 | **P2-8: 中文指令可配置化** | `dev_flow_hook.py` `build_bootstrap_context()` / `build_context()`，或新建 `config.json` `locale` 字段 |
| 9 | **P2-9: `_cmd_segments` 非严格模式扩展检测** | `dev_flow_hook.py` `_cmd_segments()` |

### 第三阶段：低优先级优化（后续迭代）

| 优先级 | 问题 |
|--------|------|
| 10 | P3-10: 探针目录残留清理 |
| 11 | P3-11: 锁文件清理 |
| 12 | P3-12: `_render` 截断长度 |
| 13 | P3-13: Skill 文件内容增强 |

### 可能引入兼容性风险的修改

| 修改 | 风险 | 缓解措施 |
|------|------|----------|
| 拆分 `constants.py` | 如果其他项目直接 `from dev_flow import STAGES`，导入会失败 | 在 `dev_flow.py` 中保留 `from constants import *` 的 re-export |
| 拆分 `task_lookup.py` | Hook 的 `_import_controller()` 路径变更 | Hook 内部 fallback 可同时尝试新旧路径 |
| `_same_path` 逻辑修改 | 可能使某些之前"相同"的路径变为"不同" | 充分测试跨平台、跨文件系统场景 |
| 中文指令可配置化 | 现有依赖中文指令的 Skill 可能受影响 | 保持中文为默认语言，仅增加可切换选项 |

### 修改完成后的验证清单

1. **运行全部现有测试**：`python -m pytest tests/ -v`
2. **运行打包验证器**：`python scripts/run_bundled_validators.py`
3. **运行运行时导入审计**：`python scripts/audit_runtime_imports.py`
4. **手动测试 Hook 响应**：在空白会话中触发 SessionStart，验证上下文注入正确
5. **手动测试 PreToolUse guardrails**：在有活动任务时尝试 force-push、reset --hard 等被阻止的命令
6. **跨平台 CI 通过**：GitHub Actions matrix 全部绿色
7. **在真实 Codex 会话中完成一次 full flow 和一次 lite flow**：端到端验证
8. **验证卸载后无残留副作用**：删除插件后检查 `data_dir` 状态

---

> **审核声明**：以上问题中，P1-1（常量重复）和 P1-2（Controller 导入过重）是通过代码阅读和架构分析确定的**结构性缺陷**，有明确的触发条件和可验证的影响。P2-5 到 P2-9 是基于输入空间分析的**潜在风险**，在实际使用中触发概率较低但理论上可能发生。所有 P0 级别的安全审查均未发现确定的可利用漏洞——该插件在安全性方面的工程投入明显高于同类项目。