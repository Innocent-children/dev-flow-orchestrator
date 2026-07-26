FAIL

### 一、总体结论

不建议当前版本直接用于生产仓库或多人并行开发。建议修复 P1 问题后，再以受控试点方式使用。

整体阶段判断：**实验性后期 / 可用 Beta**，尚未达到稳定或生产级。

结论依据：

- 插件清单、Skill 目录、默认 `hooks/hooks.json`、跨平台 CI、状态机、Git mutation 隔离和权限控制整体设计完整，明显强于普通实验脚本。
- 未发现 P0 级任意命令执行、无范围递归删除或直接数据丢失漏洞。
- 但存在 4 个必须优先修复的 P1：活动任务归属歧义、状态/事件半提交、敏感 remote URL/命令落盘、Hook 重复注册。
- Windows Hook 入口 `%PLUGIN_ROOT%\hooks\dev_flow_hook.cmd` 在包含 `%NAME%` 的合法路径中已实际复现启动失败。
- 当前发布候选验证无法完成：顶层空 `.agents` 目录导致候选快照失败；同时当前 HEAD 又包含 3 个陈旧 Windows 交接文件。
- 项目自己的跨平台 OpenSpec 验收清单仍有多项未完成，因此原生 Windows/macOS/Linux 支持声明缺乏同一候选摘要上的完整发布证据。

审核基线：

- 分支：`main`
- HEAD：`0976fc88080c514dd72f9da4fe1016e638bc15bc`
- Git tree：`d1a6f668a730631a39843561a329c3fa6cc8a778`
- 从干净 HEAD 导出的 canonical digest：`5504e80d19ab28429c2f84e65c59670661b628256dc18b56f6e90acc0804fd0d`，45 个路径
- 没有提供独立 review manifest/base commit，因此本次以整个当前产品快照为审核边界。
- 未修改任何项目代码。

验证结果：

- 聚焦测试：97 通过，3 个平台条件跳过。
- `audit_runtime_imports.py`：通过。
- `validate_package.py`：通过。
- `openspec validate ... --strict`：通过语法/结构校验。
- `run_bundled_validators.py --snapshot-only`：失败，原因为 `unexpected path outside canonical allowlist: .agents`。
- 完整 `tests.test_dev_flow` 未在本次审核时间窗口内跑完；macOS/Linux 原生运行和真实 Codex-host Hook 加载没有现场证据。

当前插件的 manifest/Skill 基本布局符合[官方插件结构说明](https://developers.openai.com/plugins/build/plugins)；默认 Hook 位置也符合规范。但官方 Hook 文档明确说明多个来源的匹配 Hook 都会运行，而不是按优先级互相覆盖，[同一事件的 command Hook 还可能并发执行](https://learn.chatgpt.com/docs/hooks)。

---

### 二、问题清单

#### P0：严重问题

未发现已确认的 P0 问题。

#### P1-1：同一源码仓库可同时归属多个活动任务，Hook 任意选择“最新”任务

- **严重级别**：P1，确定存在。
- **位置**：[dev_flow.py:1026](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:1026)、[dev_flow.py:6254](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:6254)、[dev_flow.py:6389](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:6389)、[dev_flow_hook.py:173](D:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py:173)。
- **原因**：`start` 只检查单次请求内部的重复 Git common directory，以及 task-id 冲突；不检查其他非终态任务是否已经占用相同源码仓库。Hook 扫描所有状态后，按 `updated_at/revision` 返回最新匹配项。
- **触发场景**：分别以不同 task-id 对同一仓库启动两个 full/lite/in-place/branch 任务，或两个进程并发启动。
- **影响**：Hook 的写权限和命令策略取决于偶然被选中的任务。一个处于 `IMPLEMENTING` 的 lite 任务可能放开另一个 full 任务认为应只读的源码；检查点、审批和变更也可能归到错误任务。
- **修复建议**：
  1. 在数据根建立跨任务 repository claim，以 canonical root、filesystem identity 和 Git common directory 为键。
  2. 在同一全局锁内完成“检查活动 claim + 创建任务 + 写 claim”。
  3. full worktree 任务可按明确规则共享源码只读基线；lite/in-place/branch 对同一 checkout 应互斥。
  4. Hook 遇到多个匹配任务必须报告歧义并拒绝策略相关写操作，不能自动选择最新者。

```python
matches = find_active_tasks_for_cwd(cwd, data_dir)
if len(matches) > 1:
    return _deny(
        "Multiple active Dev Flow tasks own this checkout; "
        "resolve or cancel the conflicting tasks first."
    )
task = matches[0] if matches else None
```

#### P1-2：`state.json` 与 `events.jsonl` 不是原子事务，会产生半提交

- **严重级别**：P1，已通过故障注入确认。
- **位置**：[dev_flow.py:1627](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:1627)、[dev_flow.py:3374](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:3374)。
- **原因**：`_commit_state()` 先原子替换 `state.json`，然后追加 `events.jsonl`，最后才完成 mutation intent。事件追加失败时没有回滚或可恢复 outbox。
- **触发场景**：磁盘满、ACL 改变、杀进程、事件文件损坏、杀毒软件占用；故障注入 `_append_event()` 抛出 `OSError` 时，状态已从 revision 1 前进到 2，但没有对应事件。
- **影响**：CLI 返回失败，实际状态却已转换；重试可能得到 `TASK_EXISTS`、`REVISION_CONFLICT` 或错误状态。审计链缺事件，恢复逻辑也无法确认调用方是否应重试。
- **附加缺陷**：`os.write()` 没有处理短写返回值。
- **修复建议**：使用 durable outbox/journal。事件先作为 `pending_event` 与新状态一起原子写入；随后按 `event_id` 幂等刷新到 JSONL；加载或下一次 mutation 自动恢复未刷新事件。JSONL 追加必须循环处理短写。
- **验证**：在 journal 写入、state replace、event append、fsync、intent completion 每一点注入异常和进程终止。

#### P1-3：凭据化 remote URL 和完整命令被写入状态、隔离文件及错误输出

- **严重级别**：P1，确定存在。
- **位置**：[dev_flow.py:1789](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:1789)、[dev_flow.py:5226](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:5226)、[dev_flow.py:5373](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:5373)、[dev_flow.py:7028](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:7028)、[dev_flow.py:7878](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:7878)、[dev_flow.py:8388](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:8388)、[dev_flow.py:4333](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:4333)。
- **原因**：`git remote get-url` 的原值被存入 preflight state，并进入审批摘要；mutation quarantine 记录完整 `command`；失败详情记录完整命令和 stderr。
- **触发场景**：remote 使用 `https://user:token@host/repo.git`、带签名查询参数的 URL，或测试命令包含 token/header。
- **影响**：凭据可能出现在 `state.json`、`mutation-quarantine.json`、CLI JSON、终端日志、备份或支持包中。0600/DACL 能降低本机横向读取风险，但不能解决日志和备份泄露。
- **修复建议**：
  - 持久化 `redacted_remote_url` 和完整 URL 的 SHA-256，不保存 userinfo、密码或敏感 query。
  - 执行 fetch 时重新读取实际 URL，并以摘要绑定审批。
  - quarantine 保存结构化操作类型及脱敏参数，不保存完整命令。
  - 对 stderr 和错误详情应用统一 secret scrubber。
  - 文档明确禁止把凭据放进 task requirement、approval note 或命令行参数。

#### P1-4：文档鼓励全局 Hook 回退，但没有防止插件 Hook 与全局 Hook 同时加载

- **严重级别**：P1，确定存在。
- **位置**：[README.md:48](D:/PycharmProjects/dev-flow-orchestrator/README.md:48)、[README.md:54](D:/PycharmProjects/dev-flow-orchestrator/README.md:54)、[hooks.json:4](D:/PycharmProjects/dev-flow-orchestrator/hooks/hooks.json:4)。
- **原因**：文档要求 bundled Hook 不出现时，复制同一组三类 Hook 到用户全局配置；没有要求后续恢复插件 Hook 时移除全局条目，也没有检测或去重机制。
- **触发场景**：首次拒绝信任 bundled Hook 后添加全局配置；升级、重新信任或重新安装后 bundled Hook 开始工作。
- **影响**：同一 SessionStart、UserPromptSubmit、PreToolUse 被执行两次；重复上下文、额外延迟。若全局和插件版本不同，两个并发 Hook 可能使用不同数据目录或给出冲突策略；任何一个 deny 都可能阻塞操作。
- **修复建议**：
  - 文档明确要求 bundled/global 二选一。
  - 增加 `doctor hooks` 或安装检查命令，扫描已知 Hook 来源并报告重复 handler。
  - 回退说明必须包含恢复 bundled 后删除全局条目的步骤。
  - 版本升级测试应模拟旧全局 Hook 与新插件 Hook 并存。

#### P2-1：Windows Hook 启动器因 `call` 二次解析 `%PLUGIN_ROOT%`

- **严重级别**：P2，已实际复现。
- **位置**：[dev_flow_hook.cmd:6](D:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.cmd:6)、[dev_flow_hook.cmd:24](D:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.cmd:24)、[hooks.json:11](D:/PycharmProjects/dev-flow-orchestrator/hooks/hooks.json:11)、[README.md:52](D:/PycharmProjects/dev-flow-orchestrator/README.md:52)。
- **原因**：`call py ... "%PLUGIN_ROOT%\..."` 会让 CMD 对展开后的命令再次进行百分号变量替换。
- **触发场景**：插件安装目录包含合法名称 `%DEV_FLOW_TEST_TOKEN%`。实测真实路径 `plugin-%DEV_FLOW_TEST_TOKEN%` 被改写成 `plugin-expanded`，Python 返回“找不到文件”，退出码 2。
- **影响**：Hook 完全不运行，而 handler 又是 fail-open，用户可能只看到 guardrail 消失。
- **修复建议**：不要对 `.exe` 启动器使用 `call`；先用 `where` 解析并验证实际 `.exe`，再直接调用。加入 `%VAR%`、`^`、`&`、圆括号、中文和空格组合路径测试。

#### P2-2：Unix Hook 固定使用 `python3`，与声明的 3.9–3.14 契约不一致

- **严重级别**：P2，确定存在。
- **位置**：[hooks.json:10](D:/PycharmProjects/dev-flow-orchestrator/hooks/hooks.json:10)、[hooks.json:23](D:/PycharmProjects/dev-flow-orchestrator/hooks/hooks.json:23)、[hooks.json:36](D:/PycharmProjects/dev-flow-orchestrator/hooks/hooks.json:36)。
- **原因**：Windows shim 会验证并枚举受支持版本；macOS/Linux 直接使用 PATH 上的 `python3`。
- **触发场景**：`python3` 指向 3.8 或 3.15，但主机另有 `python3.12`；或 GUI 启动 Codex 时 PATH 中没有 `python3`。
- **影响**：bundled Hook 启动失败或使用未支持版本，与 README 的运行时声明不一致。
- **修复建议**：提供 POSIX launcher，验证 `python3` 后再枚举 `python3.14` 至 `python3.9`；失败时输出可见诊断。不要把单纯提高 Hook timeout 当作修复。

#### P2-3：每次 Hook 都全量扫描历史任务，固定 10 秒且失败时放行

- **严重级别**：P2，潜在高风险，需要规模验证。
- **位置**：[dev_flow.py:1026](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:1026)、[dev_flow_hook.py:1390](D:/PycharmProjects/dev-flow-orchestrator/hooks/dev_flow_hook.py:1390)、[hooks.json:12](D:/PycharmProjects/dev-flow-orchestrator/hooks/hooks.json:12)、[README.md:112](D:/PycharmProjects/dev-flow-orchestrator/README.md:112)。
- **原因**：每次 Hook 新建 Python 进程，遍历所有 `tasks/*/state.json`，对每个仓库执行多次路径规范化/身份判断；进程内缓存不能跨 Hook 复用。
- **触发场景**：积累数千任务、UNC/网络路径离线、杀毒扫描慢、路径解析阻塞。
- **影响**：超过 10 秒时 Hook 无输出，检查点和 guardrail 同时失效。文档中“10 秒足够”没有基准数据支持。
- **修复建议**：维护 `cwd/common-dir identity → active task` 的持久化索引；终态转换时清理；全扫描仅作为索引重建回退。增加 10/1,000/10,000 任务基准和慢路径模拟。

#### P2-4：发布候选不是封闭清单，并已包含陈旧交接产物

- **严重级别**：P2，确定存在。
- **位置**：[candidate_identity.py:32](D:/PycharmProjects/dev-flow-orchestrator/scripts/candidate_identity.py:32)、[candidate_identity.py:175](D:/PycharmProjects/dev-flow-orchestrator/scripts/candidate_identity.py:175)、[validate_package.py:102](D:/PycharmProjects/dev-flow-orchestrator/scripts/validate_package.py:102)、[validate_package.py:485](D:/PycharmProjects/dev-flow-orchestrator/scripts/validate_package.py:485)、[INSTALL.md:231](D:/PycharmProjects/dev-flow-orchestrator/INSTALL.md:231)。
- **原因**：候选 allowlist 按整个 `scripts/`、`tests/` 等目录放行；package validator 只验证必需路径和冲突，不拒绝额外嵌套文件。
- **触发场景**：`tests/secret.txt`、`scripts/debug.log`、旧 ZIP 或临时二进制被误提交。
- **影响**：
  - 当前 HEAD 的 45 个 canonical 路径中，有 3 个是 `tests/windows_test/dev-flow-candidate.zip/json/run.txt`。
  - 旧 JSON 记录的是 42 路径、旧 digest `61e362...`；新的候选会把旧 ZIP 再打进新 ZIP。
  - 与文档“handoff 输出必须位于 candidate 外部”冲突。
  - 当前工作区又因空 `.agents` 目录被 snapshot validator 拒绝，而 `validate_package.py` 仍通过，两个发布检查器语义不一致。
- **修复建议**：共享一份精确 release inventory；删除或移出陈旧交接产物；对额外文件和目录统一 fail closed；明确将顶层 `.agents` 排除或拒绝，并让 package/canonical validator 采用同一规则。

#### P2-5：取消和卸载没有处理外部状态、linked worktree 与全局配置

- **严重级别**：P2，确定存在。
- **位置**：[dev_flow.py:12301](D:/PycharmProjects/dev-flow-orchestrator/scripts/dev_flow.py:12301)、[INSTALL.md:160](D:/PycharmProjects/dev-flow-orchestrator/INSTALL.md:160)。
- **原因**：`cancel` 只写 `CANCELLED` 状态；安装文档有更新和任务升级说明，但没有卸载/清理章节。
- **触发场景**：取消 full task、卸载插件、移动安装目录、停止使用全局 fallback Hook。
- **影响**：遗留 worktree、Git common-dir metadata、分支、workspace registry、PLUGIN_DATA；全局 Hook 继续指向已删除脚本，后续每次请求都执行失败。
- **修复建议**：增加只读 `uninstall-plan/doctor`；列出活动任务、脏 worktree、全局 Hook、marketplace 条目和数据目录。删除必须单独显式授权，只允许用 `git worktree remove` 清理已验证为本插件所有且干净的精确路径，禁止盲目递归删除。

#### P2-6：跨平台支持声明先于项目自己的发布证据闭环

- **严重级别**：P2，需要验证。
- **位置**：[README.md:7](D:/PycharmProjects/dev-flow-orchestrator/README.md:7)、[README.md:474](D:/PycharmProjects/dev-flow-orchestrator/README.md:474)、[tasks.md:41](D:/PycharmProjects/dev-flow-orchestrator/openspec/changes/complete-cross-platform-support/tasks.md:41)、[tasks.md:60](D:/PycharmProjects/dev-flow-orchestrator/openspec/changes/complete-cross-platform-support/tasks.md:60)。
- **原因**：README 开头直接声明 Windows/macOS/Linux 为 supported runtime；同一 README 后面又要求发布前完成真实 Windows Codex-host smoke。OpenSpec 4.4–6.6 多项仍未勾选。
- **触发场景**：用户只阅读开头支持声明并部署到 Windows/UNC/特殊路径。
- **影响**：当前仓库无法证明发布候选已经通过同一 digest 上的完整矩阵、真实 Hook discovery、`commandWindows` 选择和 Windows host smoke。
- **修复建议**：在证据闭环前将措辞改为“目标支持/验证中”；完成同一 canonical digest 的 native CI、Windows report 和真实 Codex host smoke 后再恢复正式支持声明。

#### P2-7：CI 的部分供应链依赖仍使用可变标签或无哈希安装

- **严重级别**：P2，安全加固项。
- **位置**：[cross-platform.yml:59](D:/PycharmProjects/dev-flow-orchestrator/.github/workflows/cross-platform.yml:59)、[cross-platform.yml:62](D:/PycharmProjects/dev-flow-orchestrator/.github/workflows/cross-platform.yml:62)、[cross-platform.yml:67](D:/PycharmProjects/dev-flow-orchestrator/.github/workflows/cross-platform.yml:67)、[cross-platform.yml:153](D:/PycharmProjects/dev-flow-orchestrator/.github/workflows/cross-platform.yml:153)。
- **原因**：`checkout@v4`、`setup-python@v5`、`setup-node@v4` 是可变 major tag；PyYAML 和全局 npm 安装只有版本约束，没有包哈希/锁定完整性。
- **触发场景**：上游标签移动、发布账户或依赖供应链受损。
- **影响**：发布验证过程本身可能被替换。项目已经对 Codex validator 源码做 blob/SHA-256 校验，这使其他未固定部分更显不一致。
- **修复建议**：所有 Action 使用完整 commit SHA；Python 使用带 hash 的 requirements；npm 使用 lockfile/受审核 tarball integrity。

#### P3-1：候选发布依赖硬链接，不支持部分合法文件系统

- **严重级别**：P3，兼容性风险。
- **位置**：[candidate_identity.py:280](D:/PycharmProjects/dev-flow-orchestrator/scripts/candidate_identity.py:280)、[candidate_identity.py:311](D:/PycharmProjects/dev-flow-orchestrator/scripts/candidate_identity.py:311)。
- **原因**：exclusive-create 通过 `os.link(temp, destination)` 实现。
- **触发场景**：FAT/exFAT、禁止硬链接的 SMB 共享、容器挂载或特殊企业文件系统。
- **影响**：即使目标目录可写，handoff 仍失败。
- **修复建议**：提供不覆盖的原子发布回退，或在 preflight 明确检测硬链接能力并给出可操作错误；增加无硬链接文件系统模拟测试。

#### P3-2：版本和进度文档陈旧

- **严重级别**：P3，确定存在。
- **位置**：[plugin.json:3](D:/PycharmProjects/dev-flow-orchestrator/.codex-plugin/plugin.json:3)、[INSTALL.md:105](D:/PycharmProjects/dev-flow-orchestrator/INSTALL.md:105)、[README.md:20](D:/PycharmProjects/dev-flow-orchestrator/README.md:20)、[tasks.md:43](D:/PycharmProjects/dev-flow-orchestrator/openspec/changes/complete-cross-platform-support/tasks.md:43)。
- **原因**：manifest 已是 `0.3.0`，安装路径和 cachebuster 说明仍写 `0.2.0`；多项已经实现的 CI/候选功能在 OpenSpec 中仍未勾选。
- **触发场景**：升级本地 marketplace 或执行发布清单。
- **影响**：用户可能形成错误的缓存版本预期；发布审核无法区分“尚未实现”和“已实现但未验收”。
- **修复建议**：版本号由 manifest 单一来源生成/校验；为 README、INSTALL、OpenSpec 增加版本一致性测试。

---

### 三、执行流程检查

实际链路如下：

```text
marketplace 安装
  → 读取 .codex-plugin/plugin.json
  → 加载 skills/
  → 默认发现 hooks/hooks.json
  → 用户信任 Hook
  → Codex 注入 PLUGIN_ROOT / PLUGIN_DATA
  → Windows 调用 dev_flow_hook.cmd；Unix 调用 python3 dev_flow_hook.py
  → Hook 从 stdin 读取 Codex JSON
  → 解析 cwd / tool / tool_input
  → 扫描 PLUGIN_DATA/tasks 找活动任务
  → SessionStart/Prompt 注入上下文
     或 PreToolUse 返回 allow/deny
  → Skill 引导调用 scripts/dev_flow.py
  → controller 加锁、读取 revision、执行状态转换
  → Git mutation 写 quarantine intent、创建 worktree/执行 Git
  → 写 state.json、追加 events.jsonl、完成 intent
  → 测试、独立 review、finalize/cancel
```

关键异常点：

- **可能重复执行**：bundled Hook 与全局 Hook 并存；同事件 command Hook 可能并发。
- **隐含条件**：用户信任 Hook、GUI PATH 中存在受支持 Python、所有调用始终使用同一 `PLUGIN_DATA`、同一 checkout 只有一个活动任务。
- **失败后不易恢复**：状态已写但事件未写；Hook 超时/异常静默放行；cancel 不清理 linked worktree。
- **可能污染外部状态**：PLUGIN_DATA、workspace registry、Git worktree metadata、任务分支、全局 `~/.codex/hooks.json`、marketplace 条目。
- **文档不一致**：0.3.0 与 0.2.0；handoff 必须在候选外部但仓库跟踪旧 handoff；“10 秒足够”缺少规模证据；支持声明早于自定义验收清单完成。

---

### 四、安全检查

- **Shell 引用**：POSIX `$PLUGIN_ROOT` 已加双引号；Windows `commandWindows` 也引用了 wrapper 路径。但 wrapper 内的 `call` 造成二次 `%...%` 展开，不能认为对全部 Windows 合法路径安全。
- **命令注入**：生产代码未发现 `shell=True`、`os.system()`、`eval()` 或 `source` 用户输入。Git/subprocess 基本都使用参数数组，这是明显优点。
- **用户输入拼接**：remote/base/refspec 有格式校验；Git fetch 使用显式 refspec、禁用 ext protocol、credential helper、hooks 和递归 submodule。主要问题不是注入，而是完整命令和 remote URL 被持久化。
- **路径限制**：源码、worktree、Git common directory、case/Unicode/symlink/reparse identity 检查较强；但活动任务之间缺少同等级别的 repository ownership claim。
- **误删/覆盖**：未发现无边界 `rm -rf`。`shutil.rmtree` 主要用于受控 probe、review 临时目录和 sentinel-owned Windows fixture；整体删除策略较谨慎。
- **临时文件**：大多使用同目录 `mkstemp`、fsync、私有权限和原子替换；优于常见实现。候选发布对硬链接能力有额外假设。
- **敏感信息**：remote URL、完整 command、stderr、requirement/approval note 都可能进入本地状态或终端。必须增加脱敏和使用说明。
- **不可信仓库代码**：worktree 创建和 fetch 主动禁用了 Git hooks，这是优点。但后续用户批准的测试/build 自然可能执行仓库代码；Hook 本身只是一层可绕过 guardrail，README 已正确说明它不是安全边界。
- **Hook 信任**：用户不信任、超时或异常时均 fail-open。对于“工作流约束”可以接受，但不能把 Hook 描述成强安全控制。

---

### 五、兼容性检查

- **macOS**：Python/pathlib/Git 逻辑基本可移植；主要风险是 GUI PATH 中 `python3` 不存在或版本不受支持。需要 APFS 大小写/Unicode normalization 原生测试。
- **Linux**：Hook 命令只用简单 POSIX 双引号，Bash/Zsh/Dash 均可；同样受固定 `python3` 和 O(N) 扫描影响。
- **Windows**：Python 版本探测较完整，但 CMD `call` 二次展开已确认。ACL、Job Object、UNC 和 code page 有大量专项代码，但当前仓库没有同一候选摘要上的完整 native report/host smoke。
- **Git Bash**：若 Codex 仍选择 `commandWindows`，由 CMD 运行；手工从 Git Bash 调用时要避免混用 `/c/...` 与 Windows `PLUGIN_DATA`。不应把 Git Bash 状态与 native/WSL 状态混用。
- **WSL**：应视作独立 Linux 主机；不能复用 Windows 的活动状态、locks、worktrees 或路径。文档已有“状态 host-local”原则，但可更明确写出 WSL。
- **PowerShell**：全局 Hook 示例使用绝对路径且 JSON 反斜杠正确；实际 Hook 不是由 PowerShell 解析，而是 `commandWindows`/CMD。
- **特殊路径**：空格和中文处理总体较好；`%NAME%` 已确认失败。还应测试 `&()^!`、尾随点/空格、NFC/NFD。
- **Git Worktree**：单任务内部支持充分，能识别 common directory、别名和路径重叠；跨任务 claim 是主要缺口。
- **非 Git 目录**：`start` 会拒绝；Hook 在无活动任务且范围外基本表现为未安装，行为合理。
- **首次运行**：依赖 Hook 信任、正确的 `PLUGIN_DATA` 和 Python discovery。
- **重复运行**：相同 task-id 会拒绝，但相同 repo 的不同 task-id会被允许，这是错误。
- **升级**：schema/evidence 迁移说明较详细，但文档版本陈旧，旧全局 Hook 可能遗留。
- **卸载**：缺少官方清理流程，linked worktree、数据和全局 Hook 不会自动消失。

---

### 六、测试建议

优先增加以下自动化测试：

| 类别 | 必须覆盖的场景 |
|---|---|
| 正常执行 | 实际解析并运行打包后的 POSIX/Windows Hook；full/lite 完整状态链 |
| 重复执行 | 相同 task-id；同一 repo 不同 task-id；终态后重新启动 |
| 并发执行 | 两进程同时 `start` 同一 repo；同 task revision 竞争；全局与 bundled Hook 并发 |
| 执行中断 | state replace、event append、fsync、intent completion 每一点 kill/fault injection |
| 文件不存在 | 缺 state、events、hooks.json、handler、Python、workspace registry |
| 配置不完整 | 缺 `PLUGIN_ROOT`、`PLUGIN_DATA`、损坏 JSON、错误 scope、错误 schema |
| 特殊路径 | 空格、中文、NFC/NFD、`%VAR%`、`&()^!`、UNC、长路径 |
| Hook 重复注册 | 两个相同版本；旧全局版与新插件版；不同 data-dir；不同 deny 结果 |
| Git Worktree | 同 common-dir 多任务；源 checkout 与 linked worktree 别名；branch/in-place/full 混合 |
| 路径差异 | `C:\`/`c:\`、反斜杠/斜杠、UNC、本地别名、WSL `/mnt/c`、POSIX symlink |
| 敏感信息 | 带 `user:token@` 的 remote、Authorization header、stderr secret 均不得落盘 |
| 发布候选 | `tests/secret.txt`、旧 ZIP、空 `.agents`、额外目录必须得到一致处理 |
| 卸载/升级 | 旧全局 Hook、旧 schema、活动/终态任务、脏/干净 worktree 的清理计划 |
| 性能 | 10、1,000、10,000 个任务；离线 UNC/慢 `resolve`；确保 Hook 在预算内完成 |

CI 应保留现有 Windows/macOS/Linux × Python 3.9–3.14 矩阵，并补充：

- 真正调用 `hooks.json` 中的平台命令，而不只是直接导入 handler。
- Windows native Codex host smoke。
- 同一 canonical digest 上的交接包、native report、CI 和安装验证。
- fault-injection 测试独立 job，避免普通单元测试超时后只留下不完整日志。

---

### 七、修复顺序

1. **立即修复 P1**
   - repository claim 与 Hook 歧义处理；
   - state/event durable outbox；
   - remote URL/command/stderr 脱敏；
   - bundled/global Hook 二选一和重复检测。

2. **一起修复跨平台 Hook**
   - 移除 Windows `call` 二次解析；
   - 增加 POSIX Python 版本探测；
   - 同时补特殊字符路径和真实平台命令测试。

3. **收紧发布候选**
   - 删除/移出旧 Windows handoff；
   - 建立精确 inventory；
   - 统一 package/canonical validator 对 `.agents` 和额外文件的处理；
   - 修正 0.2.0/0.3.0 文档。

4. **补状态生命周期**
   - 优化活动任务索引；
   - 增加 uninstall-plan、worktree 清理和旧全局 Hook 检测；
   - 这部分可能影响现有状态兼容，必须提供只读迁移预览和回滚方案。

5. **完成发布验证**
   - 固定 CI Action/依赖；
   - 全量测试；
   - native Windows/macOS/Linux CI；
   - Windows Codex-host smoke；
   - 确认所有结果绑定同一 canonical digest；
   - 更新 OpenSpec 任务状态后再宣称稳定跨平台支持。

修复完成后的最低验收门槛应是：完整测试通过、故障注入通过、重复 Hook 检测通过、跨任务并发测试通过、凭据脱敏测试通过、所有内置/官方 validator 通过，并取得同一候选摘要上的原生平台及真实 Codex-host 证据。