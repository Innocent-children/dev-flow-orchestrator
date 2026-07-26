I'll start by reading the whole project to build an accurate picture before judging anything.

# Dev Flow Orchestrator — 代码审核报告

> 审核基于 `main @ 0976fc8` 的实际代码，非文档推断。已实际执行：`validate_package.py`（通过）、`audit_runtime_imports.py`（通过）、`run_bundled_validators.py`、`tests/test_hooks|test_packaging|test_cross_platform_safety|test_candidate_identity|test_mutation_gate_crash`（97 passed / 3 skipped）、canonical 摘要重算。`tests/test_dev_flow.py`（84 例）在报告完成时仍在运行，未见失败输出。

---

## 一、总体结论

这是我审过的**工程完整度最高的一类插件**：控制器全程 `subprocess` 列表调用、无 `shell=True`、无 `eval`、无字符串拼接命令；Git 环境变量白名单剥离、`--upload-pack` / `credential.helper` / `protocol.*` 全部钉死；状态写入是带 rollback 证据的原子替换；跨进程锁有 POSIX/Windows 双后端并且**有真实多进程竞争测试**；路径身份比较处理了大小写、Unicode NFC、UNC/映射盘、reparse point。文档与代码的一致性也远高于平均水平。

但它同时存在几个真实的、可复现的缺陷，其中两个会直接影响"能不能在真实项目里用"。

**结论：**

* **不建议直接按现状发布/使用。** 建议修复后使用。
* **必须立即修复：** `P1-1`（全量指纹的性能与竞态，中大型仓库下功能性不可用）、`P1-2`（PreToolUse matcher 与 handler 工具名不一致，部分工具面守卫完全失效）、`P1-3`（Git remote URL 中的凭据未脱敏即落盘并打印到 stdout）、`P1-4`（仓库内提交的陈旧交付物污染 canonical 身份，发布证据链自相矛盾）、`P1-5`（对用户源仓库的 worktree/分支残留没有任何回收路径）。
* **当前阶段判定：`可用`（偏上），距离 `稳定` 还差 P1 清单；不是 `生产级`。** 理由：单仓库/小仓库 + lite 流程的路径证据充分、测试覆盖好；但 full 流程在真实规模仓库上的性能与生命周期回收未经证实，且发布证据链目前是矛盾的。

**明确不是问题的（避免误伤）：** 没有命令注入、没有路径穿越、没有不安全临时文件（全部 `tempfile.mkstemp` 同目录 + 0600）、没有 `extractall`、没有递归删除用户目录、`--data-dir` 前后置都正确（`default=argparse.SUPPRESS` 规避了 argparse 子解析器覆盖默认值的经典坑，已实测验证）、锁顺序无环（`namespace → task → registry` 单向）、`_claim_workspace_plan` 两处调用点都正确传了 `registry_locked=True`，不存在 POSIX `fcntl` 同文件重入误释放。

---

## 二、问题清单

### P0：严重问题

**本次审核未发现 P0。** 不存在任意命令执行、数据丢失或插件完全不可用的确定性缺陷。

---

### P1：高优先级

---

#### P1-1　全量工作树 SHA-256 被反复重算，中大型仓库下 `review-snapshot` / `transition` 实质不可用

**级别：** P1（性能 + 并发竞态导致的功能不可用）

**位置：**
* [scripts/dev_flow.py:4885](scripts/dev_flow.py:4885) `_tracked_worktree_manifest`：对**每一个 tracked 文件**做 `_sha256_file`
* [scripts/dev_flow.py:5916](scripts/dev_flow.py:5916) `_fingerprint_repo`：调用 `_fingerprint_repo_once` **两次**并要求 sha256 完全相等
* [scripts/dev_flow.py:11637](scripts/dev_flow.py:11637)、[:11676](scripts/dev_flow.py:11676)、[:11678](scripts/dev_flow.py:11678) `_write_review_repo`：单个仓库调用 `_fingerprint_repo` **三次**
* [scripts/dev_flow.py:11777](scripts/dev_flow.py:11777) `_latest_passing_test_is_current`、[:12066](scripts/dev_flow.py:12066) `_review_is_current`：被 `_transition_guard` 在 `REVIEWING/FINALIZING/DONE` 目标上调用

**原因：**
`_fingerprint_repo` 是"两次独立观测必须一致"的 fail-closed 设计。但它的成本不是常数——`_tracked_worktree_manifest` 对整棵工作树逐文件 `_sha256_file`。于是：

* 一次 `_fingerprint_repo` = **2 遍全树哈希**
* 一次 `review-snapshot` 单仓库 = `_fingerprint_repo` × 3 = **6 遍全树哈希**，外加 `capture_sections()` 执行两次（每次 3 个 `git diff --binary --full-index`）
* 一次 `transition --to DONE` = `_review_is_current` + `_latest_passing_test_is_current` = 每仓库 **4 遍全树哈希**

**触发场景（具体）：**
一个 40k 文件 / 2 GB 的仓库上执行 `review-snapshot`：需要读取约 12 GB。在 Windows + 实时杀毒扫描下，这是数分钟到数十分钟。更糟的是竞态：在这段时间内，只要 IDE 保存缓存、语言服务器写索引、构建 watcher 落盘、或 `.git` 内部产生任何被 tracked 的变化，第 1 遍与第 2 遍的 sha256 就不同 → `WORKTREE_CHANGED` / `REVIEW_SNAPSHOT_CHANGED`，整个命令失败。用户重试仍然会撞上同样的窗口。

**影响：**
full 流程在真实规模仓库上无法完成 `VERIFYING → REVIEWING → FINALIZING → DONE`，且失败是 fail-closed 的，没有降级路径。这不是"慢一点"，是"过不去"。

**修改方案（保持现有设计）：**

1. **用 Git 自己的哈希代替自算哈希。** `_tracked_worktree_manifest` 已经从 `ls-files --stage` 拿到了 `index_oid`；工作树侧的内容摘要可以用一次 `git diff-files --raw -z`（列出 index 与 worktree 不一致的条目）+ 仅对这些差异条目做 `_sha256_file`。绝大多数文件是干净的，成本从 O(全树) 降到 O(变更集)。
2. **同一次命令内缓存指纹。** 引入按 `(resolved_repo, 观测世代)` 的进程内缓存，让 `_write_review_repo` 的 before/middle/final 与 `_transition_guard` 的两个 `is_current` 复用同一次捕获，而不是各自重算。
3. **保留双观测语义，但降低其代价。** 双观测的目的是"证明捕获期间树没变"。可以用一个廉价的前后置探针（`git status --porcelain -z --ignored=no` + `rev-parse HEAD` + `ls-files --stage` 的摘要）夹住昂贵的一次全量捕获，而不是把昂贵捕获做两遍。

```python
# 示意：仅对 worktree 与 index 不一致的 tracked 条目做全量哈希
def _dirty_tracked_paths(repo: Path) -> set[bytes]:
    raw = _git_evidence(repo, "diff-files", "--raw", "-z", "--", text=False)
    # -z --raw: ":mode mode oid oid status\0path\0" 交替
    fields = raw.split(b"\0")
    return {fields[i + 1] for i in range(0, len(fields) - 1, 2) if fields[i]}

# visit() 内：
if stat.S_ISREG(metadata_value.st_mode):
    item["worktree_type"] = "file"
    item["sha256"] = (
        _sha256_file(target) if path_bytes in dirty else f"index:{item['index_oid']}"
    )
```

**需要验证：** 修改后必须重跑 `tests/test_dev_flow.py` 中所有依赖 `fingerprint.sha256` 稳定性的用例，因为指纹口径变化会使所有既有证据失效——这属于 `EVIDENCE_CONTRACT_VERSION` 需要 bump 的变更。

---

#### P1-2　`hooks.json` 的 PreToolUse matcher 与 hook 支持的工具名不一致，`exec_command` / `shell` 守卫是死代码

**级别：** P1

**位置：**
* [hooks/hooks.json:32](hooks/hooks.json:32)　`"matcher": "^(Bash|apply_patch|Edit|Write)$"`
* [hooks/dev_flow_hook.py:1432](hooks/dev_flow_hook.py:1432)　`if tool_name not in {"bash", "exec_command", "shell"}: return None`
* [scripts/validate_package.py:263](scripts/validate_package.py:263)　**强制**该 matcher 必须逐字符等于上述字符串
* [tests/test_hooks.py:1319](tests/test_hooks.py:1319)　`test_unified_exec_cmd_alias_is_guarded` 实际用 `tool_name: "Bash"` + `tool_input.cmd`，测的是 **input key** 别名，不是 **tool name** 别名

**原因：**
handler 明确支持三个命令类工具名（`bash` / `exec_command` / `shell`），但 matcher 只放行 `Bash`。任何以 `exec_command` 或 `shell` 命名的工具调用根本不会触发 hook，handler 里那两个分支永远不会被执行。而 `validate_package.py` 把 matcher 锁死为"契约"，使这个不一致无法通过配置修复。

**触发场景：**
Codex 在某个版本把命令工具命名为 `shell`（这正是 handler 里写这两个别名的原因）。此时 `git reset --hard`、`git clean`、`git pull`、受保护分支的 `commit`/`push` 守卫**全部静默失效**，用户看不到任何差别——hook 是 fail-open 的，不会报错。

**影响：**
命令守卫在特定 Codex 版本/工具面上完全失效。由于 hook 本身以"静默不输出"表示放行，这个失效**无法被用户察觉**。这与 README「hooks 会拦截危险 Git 命令」的承诺不符。

**修改方案：**
matcher 与 handler 的工具名集合必须来自同一个来源。

```json
"matcher": "^(Bash|Shell|shell|exec_command|apply_patch|Edit|Write)$"
```

同步修改 [scripts/validate_package.py:263](scripts/validate_package.py:263) 的断言，并把它改成**从 `dev_flow_hook` 导入名单再生成正则**，而不是硬编码字符串比较：

```python
from importlib import util as _util
# 校验 matcher 覆盖 handler 实际处理的每一个工具名（大小写不敏感）
required = {"bash", "exec_command", "shell", "apply_patch", "edit", "write"}
missing = [n for n in required if re.match(matcher, n, re.I) is None
                              and re.match(matcher, n.capitalize()) is None]
```

同时补一个**真正**测 tool_name 别名的用例（见第六节 T-3）。

---

#### P1-3　Git remote URL 中的凭据未脱敏，原样写入 `state.json` 并打印到 stdout

**级别：** P1（敏感信息泄露）

**位置：**
* [scripts/dev_flow.py:5226](scripts/dev_flow.py:5226) `_remote_url` → `git remote get-url`
* [scripts/dev_flow.py:5373](scripts/dev_flow.py:5373) 写入 `preflight["remote_url"]`
* [scripts/dev_flow.py:7824](scripts/dev_flow.py:7824)、[:7927](scripts/dev_flow.py:7927) 进入 `preflight_remote_evidence`（被哈希并作为 gate 证据）
* [scripts/dev_flow.py:6463](scripts/dev_flow.py:6463) `command_show` 返回**完整 state**，包含 `remote_url`
* [scripts/dev_flow.py:8404](scripts/dev_flow.py:8404) `REMOTE_URL_UNAVAILABLE` 的 `details` 也可能带出

**原因：** 全链路没有任何 redaction。

**触发场景：**
用户的仓库 remote 是 `https://x-access-token:ghp_XXXXXXXX@github.com/org/repo.git`（GitHub Actions 检出、`gh auth setup-git` 的某些配置、企业内网 token URL、以及大量 CI 镜像仓库都是这个形态）。执行 `preflight --confirm-preview` 后：

1. token 明文写入 `<PLUGIN_DATA>/tasks/<id>/state.json`（0600，尚可）；
2. `show` / `preflight` / `baseline` 的 **stdout JSON 单行**包含该 token → 直接进入 Codex 的模型上下文、会话记录、任何终端回显与日志采集；
3. `_preflight_remote_evidence` 把它纳入 gate 哈希，意味着"脱敏"会破坏既有证据，事后补救成本更高。

**影响：** 长期有效的 Git 凭据被写入持久文件并广播到 LLM 上下文/日志。这是本次审核中唯一的真实凭据泄露路径。

**修改方案：**
在 `_remote_url` 出口做一次规范化脱敏，同时保留可比较的身份（因为 `REMOTE_URL_CHANGED` 检测依赖它）。

```python
_CREDENTIAL_URL = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^/@]*@)")

def _redact_remote_url(value: str | None) -> str | None:
    if not value:
        return value
    match = _CREDENTIAL_URL.match(value)
    if match is None:
        return value
    return f"{match.group('scheme')}<redacted>@{value[match.end():]}"

def _remote_url(repo: Path, remote: str | None) -> str | None:
    if not remote:
        return None
    return _redact_remote_url(_git_optional(repo, "remote", "get-url", "--", remote))
```

`baseline --fetch` 处（[:8453](scripts/dev_flow.py:8453)）当前直接把记录值传给 `git fetch`，脱敏后必须改为**重新读取实时 URL**、并断言其脱敏形态等于记录值，再用实时值发起 fetch：

```python
live_url = _git_optional(path, "remote", "get-url", "--", remote)
if _redact_remote_url(live_url) != preflight.get("remote_url"):
    raise FlowError("REMOTE_URL_CHANGED", ...)
_git_mutating(path, ..., "--", live_url, fetch_refspec)
```

此改动改变证据内容，需要 bump `EVIDENCE_CONTRACT_VERSION`，并在 README「Boundaries」中说明。

---

#### P1-4　仓库内提交了陈旧的 Windows 交付物，污染 canonical 身份且与文档规则矛盾

**级别：** P1（发布证据链自相矛盾 + 包污染）

**位置：**
* `tests/windows_test/dev-flow-candidate.zip`（ZIP_STORED，含 42 个成员，是本插件旧版本的完整副本）
* `tests/windows_test/dev-flow-candidate.json`（`path_count: 42`，`sha256: 61e36202…`）
* `tests/windows_test/run.txt`（一条含具体本机路径的命令行）
* [scripts/candidate_identity.py:39](scripts/candidate_identity.py:39)　`tests` 在 `_ALLOWED_TOP_LEVEL_DIRECTORIES` 中 → 这三个文件**计入** canonical 摘要
* [README.md:441](README.md:441)、[INSTALL.md:231](INSTALL.md:231)　明文规定："Both output paths must be new … and they must be **outside the candidate root**"

**原因：** handoff 的产物被提交进了 candidate root 自身，形成自指。

**实测证据（clean `git archive HEAD` 导出后计算）：**

| | 提交的清单声称 | 当前树实际 |
|---|---|---|
| `path_count` | 42 | **45** |
| `canonical_sha256` | `61e36202c7a4…3c1a48` | **`5504e80d19ab…04fd0d`** |

zip 内部不含 `tests/windows_test/`，证明它是加入这些文件之前的快照。

**触发场景：**
授权 release dispatch 时向 `.github/workflows/cross-platform.yml` 提供 `61e362…`（唯一被评审过的摘要）→ 每个矩阵 job 断言本地 canonical 摘要 → **全部失败**。反过来，若提供 `5504e8…`，就等于把"一个包含 1 MB 陈旧自身副本的树"当成发布主体。日常 push/PR 因为 `DEV_FLOW_REVIEWED_CANONICAL` 为空而不比较，所以这个矛盾**在 CI 里是隐形的**。

**影响：**
1. 发布通道被堵死或被错误放行；
2. 每个用户安装时多拿 ~1 MB 的旧版自身副本（`INSTALL.md` 的逐文件放置表里也没有这三个文件，安装说明与实际包内容不一致）；
3. `run.txt` 泄露了作者机器的具体路径与共享名。

**修改方案：**
```bash
git rm -r --cached tests/windows_test && rm -rf tests/windows_test
```
并在 `.gitignore` 增加 `tests/windows_test/`，同时在 [scripts/candidate_identity.py:58](scripts/candidate_identity.py:58) 的 `_EXCLUDED_ANYWHERE` 或新增的排除规则中显式拒绝 handoff 产物落在 candidate 内（fail-closed 更好：遇到 `*.zip` + 同名 `*.json` 于 candidate 内直接报错，坐实文档承诺）。重算并重新评审 canonical 摘要后再更新 `.codex-plugin/plugin.json` 的 cachebuster。

---

#### P1-5　对用户源仓库的 worktree/分支残留没有任何回收路径，claim 永久占用

**级别：** P1（污染用户仓库 + 卸载残留）

**位置：**
* [scripts/dev_flow.py:10541](scripts/dev_flow.py:10541)、[:10551](scripts/dev_flow.py:10551)　`git worktree add`（在**用户源仓库**中注册 linked worktree，并可能创建 `codex/<task-id>` 分支）
* [scripts/dev_flow.py:2953](scripts/dev_flow.py:2953)　`_state_workspace_claims`：遍历 `tasks/*/state.json` 生成 claim，**不过滤 `DONE`/`CANCELLED`**
* [scripts/dev_flow.py:9901](scripts/dev_flow.py:9901)　`RETIRED_WORKSPACE_REUSE`：退役的 path/branch 永久不可复用
* [scripts/dev_flow.py:12301](scripts/dev_flow.py:12301)　`command_cancel`：只改状态，不动文件系统
* 命令表（17 个）中**没有任何** cleanup / release / prune 命令
* [skills/follow-dev-flow/references/recovery.md:107](skills/follow-dev-flow/references/recovery.md:107)　明确写"cleanup needs a separate explicit decision"——但这个 decision 没有可执行的落点

**原因：** 生命周期只设计了"创建 + 冻结"，没有设计"释放"。

**触发场景：**
1. 用户跑 3 个 full 任务（含 1 次 impact reassessment），全部走到 `DONE`；
2. 源仓库 `.git/worktrees/` 里留下 4 条 linked worktree 注册、4 个 `codex/*` 本地分支；
3. `<PLUGIN_DATA>/workspaces/` 里留下 4 棵检出树；
4. 用户手工 `git worktree remove` + `git branch -D` 清理干净；
5. 之后用 `--workspace-path` 指定同一路径 / `--branch` 指定同一分支名开新任务 → `WORKSPACE_CLAIM_*` / `RETIRED_WORKSPACE_REUSE`，**永久拒绝**，即使物理上已经没有冲突。
6. 卸载插件、删掉 `<PLUGIN_DATA>` 后，用户仓库里的 worktree 注册变成指向不存在路径的孤儿条目，需要用户自己 `git worktree prune`。

**影响：** 插件在用户的源仓库里留下不可自动清理的状态，且自身的 claim 表单调增长、永不释放。这正好命中审核目标第 7 条（卸载/升级/配置变更后的无效状态残留）。

**修改方案（保持现有设计，最小增量）：**

1. **新增 `release-workspace <task> --expected-revision N [--repo …] [--remove-worktree]`**：
   * 前置：任务处于 `DONE`/`CANCELLED`；
   * 校验目标路径确实是本任务 claim 的 linked worktree、common dir 匹配、`status --porcelain --ignored` 为空；
   * 可选执行 `git worktree remove`（经 `_git_mutating` 走 mutation gate）与 `git branch -d`（只允许 fast-forward 安全删除）；
   * 把 workspace 记录移入 `workspace_history` 并标记 `released_at`，同时从 registry 删除 claim。
2. **`_state_workspace_claims` 跳过已释放条目**：只有 `released_at` 为空的 workspace/history 记录才产生 claim。**注意**：不要单纯按 `status in TERMINAL_STATES` 跳过——那会让"任务完成但 worktree 还在"的路径被别的任务抢占，反而更危险。必须以显式 release 为准。
3. **`cancel` 的响应中列出所有 retained paths**（recovery.md 已经这么要求了，但代码没实现），并附上 `release-workspace` 的建议命令。

---

### P2：中优先级

---

#### P2-1　`.cmd` 启动器以 LF 行尾发布，Windows 批处理行为需验证

**级别：** P2　**（需要验证）**

**位置：** [.gitattributes:4-5](.gitattributes:4)　`*.bat text eol=lf` / `*.cmd text eol=lf`；实测 `hooks/dev_flow_hook.cmd` 与 `scripts/windows_native_validation.cmd` 工作区字节均为 **LF only**。

**原因：** `eol=lf` 同时作用于仓库和检出，Windows 上拿到的批处理文件没有 CRLF。

**触发场景：** `hooks/dev_flow_hook.cmd:9-15` 是一个 `for %%V in (…) do ( … goto run_py_version )` —— 从 `FOR` 括号块内 `goto` 跳出，正是 cmd.exe 对 LF-only 批处理最容易出问题的模式（cmd.exe 逐字节读取并按偏移量重新定位标签）。

**影响：** 若行为异常，捆绑注册路径下的 Windows hook 直接失效（用户表现为"看不到 bootstrap 块"，会被 README 引导去做全局注册，问题被掩盖）。

**验证方法（必须实机做，不能靠推断）：** 在真实 Windows 上分别用 LF 版和 CRLF 版执行
```bat
set PLUGIN_ROOT=C:\path\with space\dev-flow-orchestrator
echo {"hook_event_name":"SessionStart"} | hooks\dev_flow_hook.cmd --data-dir "C:\tmp\dd"
```
并强制走 `run_py_version` 分支（临时把 `py -3` 探测改成必失败）。

**修改方案：** 若验证有问题，把 `.gitattributes` 改为 `*.cmd text eol=crlf` / `*.bat text eol=crlf`，并在 `validate_package.py` 增加"`.cmd` 必须是 CRLF"的断言。注意这会改变 canonical 摘要。

---

#### P2-2　显式 `--data-dir` 时不会回退到脚本自身目录，外来 `PLUGIN_ROOT` 会使 hook 降级

**级别：** P2

**位置：** [hooks/dev_flow_hook.py:1298-1326](hooks/dev_flow_hook.py:1298)

**原因：** `_resolve_plugin_context` 里，只要 `PLUGIN_ROOT` 是非空字符串就走 `else` 分支，`fallback_root` 完全不被使用。

**触发场景：** 用户按 README 做全局注册（传 `--data-dir`），但会话环境里恰好存在**另一个插件**或旧安装留下的 `PLUGIN_ROOT`。该路径下没有 `scripts/dev_flow.py` → `problems` 非空 → 每次事件只输出 `Dev Flow hook diagnostic: … PLUGIN_ROOT does not contain scripts/dev_flow.py`，而 hook 明明可以从 `__file__` 推出正确的 root。

**影响：** 守卫与上下文注入全部失效，且诊断信息把用户引向一个错误的排查方向。

**修改方案：**
```python
    else:
        try:
            supplied_root = Path(raw_root).expanduser()
            ...
            if root is not None and not controller.is_file():
                if fallback_root is not None:               # 新增
                    root = fallback_root.resolve(strict=False)
                    controller = root / "scripts" / "dev_flow.py"
                    if not controller.is_file():
                        problems.append("neither PLUGIN_ROOT nor the hook path contains scripts/dev_flow.py")
                        controller = None
                else:
                    problems.append("PLUGIN_ROOT does not contain scripts/dev_flow.py")
                    controller = None
```

---

#### P2-3　`--data-dir` 允许相对路径，与「必须绝对」的文档不符

**级别：** P2

**位置：** [hooks/dev_flow_hook.py:1333](hooks/dev_flow_hook.py:1333)　`if not data_dir_from_cli and not supplied_data_dir.is_absolute():`；[scripts/dev_flow.py:285](scripts/dev_flow.py:285)　`Path(candidate).expanduser().resolve(strict=False)`

**原因：** 命令行来源的 `--data-dir` 被显式豁免了绝对路径校验，`resolve_data_dir` 也会把相对路径按 CWD 解析。

**触发场景：** 用户在 `~/.codex/hooks.json` 里写 `--data-dir ".dev-flow"`。每个仓库目录下都会生成一套独立的 `config.json` / `tasks/`，用户看到的现象是"任务莫名消失"——正是 README step 4 警告过的失败模式，但代码在这条路径上没有拦截。

**影响：** 静默的数据目录分裂。

**修改方案：** 移除 `data_dir_from_cli` 豁免（命令行来源同样要求绝对），并在 `resolve_data_dir` 中对**显式传入**的相对路径抛 `INVALID_ARGUMENT`（环境变量与默认值保持现状）。

---

#### P2-4　mutation gate 对子进程 stderr 零容忍，任何 warning 变成需人工恢复的 quarantine

**级别：** P2

**位置：** [scripts/dev_flow.py:3864-3877](scripts/dev_flow.py:3864)　`if returncode != 0 or stderr or not stdout.startswith(envelope): raise MUTATION_GATE_PROTOCOL_FAILED`；调用方 [:4250](scripts/dev_flow.py:4250) 把它升级为 `MUTATION_QUARANTINED`

**原因：** gate 子进程（`sys.executable -I -S -c …`）**任何**写到 stderr 的字节都被判定为协议失败。

**触发场景：** Python 在特定环境下向 stderr 输出非致命信息——例如 `PYTHONWARNINGS` 被设为 `always`、`sitecustomize` 缺失告警、Windows Store Python 的重定向提示、某些 conda shim 的 banner。此时一次完全正常的 `git worktree add` / `git fetch` 会被判为 quarantine。

**影响：** 用户被推入 `recover-quarantine` 流程（需要 `--expected-revision`、需要人工检查进程与仓库状态），而实际上根本没有发生任何异常。`-I -S` 降低了概率，但没有消除。

**修改方案：** 收紧到"stdout 必须以信封开头且信封可解析"，把 stderr 作为**诊断字段**而非失败条件：

```python
if returncode != 0 or not stdout.startswith(_MUTATION_GATE_ENVELOPE):
    raise FlowError("MUTATION_GATE_PROTOCOL_FAILED", ...,
                    details={..., "gate_stderr_sha256": _sha256_bytes(stderr)})
# 信封解析成功后，把非空 stderr 记入 envelope["gate_stderr_sha256"] 供审计
```
信封本身已经有 `version` + 私有前缀 + base64 双通道，stdout 侧的完整性足以认证；stderr 不承载协议语义。

---

#### P2-5　`windows_native_validation.py` 在 `finally` 中 `return`

**级别：** P2

**位置：** [scripts/windows_native_validation.py:1211](scripts/windows_native_validation.py:1211)

**原因：** `finally` 块内的 `return 2` 会吞掉一切正在传播的异常。

**触发场景：** 实测在 Python 3.14 下运行测试即产生 `SyntaxWarning: 'return' in a 'finally' block`（CI 的 Windows/Linux 3.14 job 都会打印）。运行期上，若 try 体内抛出 `KeyboardInterrupt` / `SystemExit`（不被那三个 `except` 捕获），它会被静默丢弃并返回 2。

**影响：** 中断被伪装成普通失败；CI 日志噪音；PEP 765 之后的 Python 版本可能升级为错误。

**修改方案：**
```python
    report_write_failed = False
    ...
    finally:
        ...
        try:
            write_report_exclusive(report_path, report)
        except NativeValidationError as exc:
            print(json.dumps({"code": exc.code, "result": "incomplete"}, sort_keys=True))
            report_write_failed = True
    if report_write_failed:
        return 2
    print(...)
    return 0 if report["result"] == "passed" else 2
```

---

#### P2-6　canonical allowlist 拒绝任意未知顶层目录，普通开发树无法运行发布校验

**级别：** P2

**位置：** [scripts/candidate_identity.py:32-58](scripts/candidate_identity.py:32)

**原因：** `_EXCLUDED_TOP_LEVEL` 只列了 `.codex .git .idea .pytest_cache htmlcov openspec work`，其余任何顶层条目直接 `CandidateIdentityError`。

**触发场景（实测）：** 本次审核在当前工作树上运行 `scripts/run_bundled_validators.py`，结果：
```
{"detail":"unexpected path outside canonical allowlist: .agents","event":"validation_error"}
{"error_count":2,"event":"bundled_validation_summary","status":"failed"}
```
`.venv`、`.vscode`、`.claude`、`node_modules` 会有完全相同的结果。

**影响：** "fail-closed 保护发布身份"是对的，但它同时让**日常开发中无法运行该校验**，而 README 把它列为常规开发验证步骤之一（[README.md:431](README.md:431)）。开发者会养成跳过它的习惯。

**修改方案：** 保持 canonical 计算的严格性不变，但给命令行加一层可用性：
* `run_bundled_validators.py` 在遇到 allowlist 违例时，把违例路径列表作为**结构化诊断**输出（当前只输出第一条 message），并明确提示"这些路径不属于发布包，请在干净导出上重跑"；
* 增加 `--candidate-root` 参数（当前只有 `windows_native_validation.py prepare` 有），让开发者可以指向 `git archive` 导出的干净目录；
* 在 `_EXCLUDED_TOP_LEVEL` 中补充 `.venv`、`venv`、`.vscode`、`.claude`、`node_modules`、`.mypy_cache`、`.ruff_cache`——这些**确定**不是发布内容，排除它们不削弱 fail-closed 语义。

---

#### P2-7　捆绑注册与全局注册可能同时生效，文档没有去重指引

**级别：** P2　**（需要验证）**

**位置：** [README.md:52-54](README.md:52)（"First try the bundled registration … If it does not appear, register the hooks globally instead"）、[hooks/hooks.json](hooks/hooks.json)、`~/.codex/hooks.json`

**原因：** README 把两条路径描述为"先试 A，不行再用 B"，但没有说明**如果 A 后来生效了会怎样**，也没有给出检测/清理手段。

**触发场景：** 用户在 Codex 不支持 `hooks/hooks.json` 发现的版本上加了全局注册；之后 Codex 升级并恢复插件级 hook 发现 → 两份注册同时激活。

**影响（实际评估）：** 不会破坏状态——hook 对 `SessionStart`/`UserPromptSubmit` 是纯只读的上下文注入，`PreToolUse` 的 deny 是幂等的。真实代价是：**每次 prompt 注入两份约 20 行的中英混排 checkpoint**（token 成本翻倍），每次工具调用起两个 Python 进程（延迟翻倍），以及用户看到重复内容后的困惑。

**验证方法：** 升级到当前 Codex，同时保留两处注册，启动新任务，数上下文里 `Dev Flow controller bootstrap:` / `Dev Flow active-task checkpoint:` 块出现几次。

**修改方案：** 在 README step 3 增加一段明确的排他说明与自检：
> 两种注册**互斥**。如果你添加了 `~/.codex/hooks.json` 之后又在会话上下文里看到两个 `Dev Flow controller bootstrap:` 块，说明捆绑注册也生效了——删除 `~/.codex/hooks.json` 中的三个 handler，保留捆绑注册。

并在 hook 里做防御：`build_context`/`build_bootstrap_context` 输出中带一个稳定的 `instance_key`（`sha256(controller_path + data_dir)` 前 8 位），使重复注入在视觉上可辨识。

---

#### P2-8　`check-ref-format` 在控制器 CWD 而非目标仓库中执行

**级别：** P2

**位置：** [scripts/dev_flow.py:9842](scripts/dev_flow.py:9842)、[:5271](scripts/dev_flow.py:5271)、[:5283](scripts/dev_flow.py:5283)　`_run(["git", "check-ref-format", ...])`，没有 `-C repo`

**原因：** 遗漏了仓库定位参数。

**触发场景：** 控制器进程的 CWD 不在任何 Git 仓库内（hook 注入的调用完全可能如此）。`check-ref-format` 的大部分校验不依赖仓库，但 `--branch` 形式在解析 `@{-1}` 这类 revision 简写时需要仓库上下文；此外若 CWD 恰好在**另一个**仓库内，判定会受那个仓库的配置影响。

**影响：** 分支名合法性判定在边界输入上不确定。风险低但确实存在。

**修改方案：** 三处都改为 `_run(["git", "-C", str(repo), "check-ref-format", ...])`。`_workspace_plan` 里 `source_repo` 已在作用域内。

---

#### P2-9　PreToolUse 的环境诊断返回了非法字段

**级别：** P2

**位置：** [hooks/dev_flow_hook.py:1345-1358](hooks/dev_flow_hook.py:1345)　`_environment_diagnostic` 对 `PreToolUse` 也返回 `hookSpecificOutput.additionalContext`

**原因：** `additionalContext` 是 `SessionStart`/`UserPromptSubmit` 的字段；`PreToolUse` 的输出契约是 `permissionDecision` + `permissionDecisionReason`。

**触发场景：** 全局注册缺少 `PLUGIN_DATA` 且未传 `--data-dir` 时，每次 Bash/Edit/Write 调用都会输出一个宿主可能直接丢弃的对象。

**影响：** 用户在最需要看到诊断的场景下**看不到诊断**（fail-open 是对的，但静默失败让配置错误难以定位）。测试 `test_pre_tool_use_missing_environment_is_diagnostic_not_denial` 只断言"不是 deny"，无法发现这一点。

**修改方案：** `PreToolUse` 分支改为不输出任何 JSON（真正静默 fail-open），把诊断留给 `SessionStart`/`UserPromptSubmit`——它们本来就会在同一个会话里先触发。或者，如果 Codex 支持，用 `systemMessage` 字段。

---

#### P2-10　原子写的固定开销与不可回收的临时文件

**级别：** P2

**位置：** [scripts/dev_flow.py:1381](scripts/dev_flow.py:1381) `_atomic_write_bytes`

**原因：** 每次状态写入都要：复制旧文件 → fsync → 对旧文件和副本各做一次完整 SHA-256 → 写新文件 → fsync → `os.replace` → fsync 父目录 → 删副本 → 再 fsync 父目录。

**影响与场景：**
1. 每次 mutation 固定付出 2 次全文件哈希 + 最多 4 次 fsync。对 `state.json` 量级可接受，但 mutation intent 在一次命令内可能写 3–5 次（`_begin/_update × 2/_complete`），成本叠加。
2. 若进程在 `mkstemp` 之后、`finally` 的 `temporary.unlink()` 之前被 SIGKILL，会留下 `.state.json.<8随机字符>` 临时文件。它**不匹配** `.state.json.rollback-*` glob，因此既不会阻塞后续写入，也**不会**被 `recover-atomic-write` 报告或清理——静默垃圾累积。

**修改方案：**
1. 副本完整性校验用"复制时增量计算摘要 + 复制后对源文件再算一次"即可，省掉对副本的第二次读盘：`shutil.copyfileobj` 换成手写循环，边写边喂 `hashlib`。
2. `recover-atomic-write` 的只读报告中增加 `orphan_temporaries` 一节：扫描 `.{name}.*` 中既不是 rollback 也不对应任何活跃写入的候选，`--apply` 时一并清除（这些文件**从未** commit 过，删除是无条件安全的）。

---

### P3：低优先级

* **P3-1　单文件 12812 行的控制器。** [scripts/dev_flow.py](scripts/dev_flow.py) 承担了：路径身份探测、Windows 安全描述符、跨平台文件锁、Windows Job 对象、进程组管理、原子写、mutation gate 协议、Git 证据采集、workspace 注册表、17 个命令、argparse 构建。职责边界清晰（函数命名极好），但任何修改都要在一个文件里翻上万行。建议按 `identity/ locking/ atomicity/ process/ gitevidence/ commands/` 拆包——`scripts/__init__.py` 已经是导入边界，拆分不影响 `audit_runtime_imports.py` 的 stdlib-only 断言。
* **P3-2　文档版本与清单版本不一致。** `.codex-plugin/plugin.json` 是 `0.3.0`，而 [INSTALL.md:105](INSTALL.md:105) 说"helper preserves the `0.2.0` base version"，[README.md:20](README.md:20) 与 [README.zh-CN.md:18](README.zh-CN.md:18) 的示例路径也是 `…\dev-flow-orchestrator\0.2.0`。建议在 `validate_package.py` 增加"文档中出现的 base version 必须等于 manifest version"的检查。
* **P3-3　`hooks.json` 的 POSIX 命令硬编码 `python3`。** [hooks/hooks.json:10](hooks/hooks.json:10)。控制器侧已经正确地用 `sys.executable`（[hooks/dev_flow_hook.py:345](hooks/dev_flow_hook.py:345) 有很好的注释说明为什么），但 hook 自身的启动仍依赖 PATH 上有 `python3`。在只装了 `python` 的环境（部分 conda/pyenv 配置）会静默失效。可参照 Windows 的做法加一个 `hooks/dev_flow_hook.sh` 探测 shim。
* **P3-4　每次 prompt 注入约 20 行上下文。** `build_context` 的中文确认规则块占绝大部分。这些规则更适合放在 SKILL.md（只在技能激活时加载），checkpoint 只保留状态与命令前缀。
* **P3-5　死别名。** [scripts/dev_flow.py:3780](scripts/dev_flow.py:3780) `_WINDOWS_MUTATION_GATE_CODE = _MUTATION_GATE_CODE` 与 [:3796](scripts/dev_flow.py:3796) `_windows_mutation_gate_command`（直接转调）。注释说是给测试用的，但会让读者以为存在 Windows 专用实现。
* **P3-6　`load_active_task` 用异常做控制流。** [hooks/dev_flow_hook.py:183-190](hooks/dev_flow_hook.py:183)：`cwd.relative_to(data_dir / "tasks")` 在正常情况下必然抛 `ValueError` 并被外层 `except Exception` 吞掉。结果正确，但可读性差且掩盖真实错误。改用 `_within()` 显式判断。
* **P3-7　`_MUTATION_GATE_CODE` 是内联源码字符串。** 无语法高亮、无 lint、无类型检查覆盖。可以改为一个真实的 `hooks/_gate.py` 文件并用 `sys.executable -I -S <path>` 调用（`audit_runtime_imports.py` 也就能审计它了）。

---

## 三、执行流程检查

### 完整链路

```
① 安装
   marketplace.json → <plugin-root>/  (完整目录，含 .codex-plugin/plugin.json，无 hooks 字段)

② Hook 注册（两条互斥路径）
   A. 捆绑：Codex 发现 hooks/hooks.json → 注入 PLUGIN_ROOT + PLUGIN_DATA
      POSIX:   python3 "$PLUGIN_ROOT/hooks/dev_flow_hook.py"
      Windows: "%PLUGIN_ROOT%\hooks\dev_flow_hook.cmd"  → 探测 py -3 → py -3.14..3.9 → python
   B. 全局：~/.codex/hooks.json，无 PLUGIN_ROOT/PLUGIN_DATA，靠绝对路径 + --data-dir argv

③ Hook 触发（SessionStart / UserPromptSubmit / PreToolUse）
   stdin JSON → main() → _cli_data_dir(argv) 覆盖 PLUGIN_DATA
   → _resolve_plugin_context → in_configured_scope（失败即 fail-open）
   → load_active_task（sys.path 注入 scripts/，import dev_flow）
   → 注入 checkpoint 或 bootstrap；PreToolUse 时做写/命令守卫

④ 控制器调用
   <interpreter> <controller> --data-dir <PLUGIN_DATA> <cmd> --expected-revision N
   → _locked_state: _task_lock(state.lock) → load_state → _check_revision
     → (可选) _workspace_registry_lock
   → 命令逻辑（Git 证据 / 指纹 / 计划 / 审批）
   → _commit_state: _atomic_write_json(state.json) → _append_event → _complete_mutation_intent

⑤ 变更型 Git 子进程
   _run(mutation=True) → 必须持锁 → _begin_mutation_intent 先落 quarantine 文件
   → Popen(gate: python -I -S -c CODE, argv=json(command))
   → POSIX: start_new_session；Windows: kill-on-close Job
   → 写 b"G" 放行 → 读 DEV_FLOW_GATE_V1: 信封 → 证明子进程静默 → 更新 intent
```

### 可能被重复执行的步骤

| 步骤 | 重复风险 | 现状 |
|---|---|---|
| Hook 注入 | **是**（双注册，见 P2-7） | 无副作用，但上下文/进程翻倍 |
| `preflight --preview` | 是 | 无状态副作用，token 是内容哈希，天然幂等 |
| `prepare-workspace --dry-run` | 是 | 相同参数返回相同 plan hash，但**每次都 +1 revision** 并清掉旧 workspace 审批（recovery.md 已说明） |
| `record-index` / `record-artifact` | 是 | 追加 + 归档旧记录，不覆盖 |
| `transition` 同状态 | 是 | 显式返回 `unchanged: true`，不改 revision ✔ |
| `git fetch` / `worktree add` | **否** | mutation intent 在 Popen 之前落盘，重复执行会撞上 quarantine 或 `WORKSPACE_COLLISION` ✔ |

### 依赖隐含条件的步骤

1. **`load_active_task` 依赖 `sys.path` 注入成功。** [hooks/dev_flow_hook.py:142](hooks/dev_flow_hook.py:142) 把 `<root>/scripts` 插到 `sys.path[0]`。这会让**任何**名为 `dev_flow` 的第三方模块（或用户 CWD 下的同名文件，若 CWD 在 path 上）优先/次优先被导入。目前 `scripts/` 只有本插件文件，风险低，但这是一个隐式全局副作用。
2. **`_controller_prefix` 依赖 `sys.executable` 非空。** 在被冻结/嵌入的解释器下 `sys.executable` 可能是宿主可执行文件，注入的命令前缀会是错的。
3. **`branch` 策略依赖用户在 `start` **之前**已经完成 `git switch -c`。** 控制器只做绑定校验（[scripts/dev_flow.py:6291](scripts/dev_flow.py:6291)），从不执行切换。这是正确设计，但完全依赖 skill 层遵守。
4. **Windows 权限校验依赖 `ctypes` + advapi32 可用。** 在受限环境下 `_verify_windows_private_path` 抛错会阻断所有 mutation。

### 失败后无法自动恢复的步骤

| 步骤 | 失败后果 | 恢复手段 |
|---|---|---|
| 原子写被 SIGKILL 打断 | 该文件后续所有写入 `ATOMIC_RECOVERY_REQUIRED` | `recover-atomic-write`（设计完备）✔ |
| mutation 子进程无法证明静默 | 全任务 mutation 阻塞 | `recover-quarantine`（设计完备）✔ |
| `_commit_state` 中 `_append_event` 失败 | 状态已提交、事件日志缺失、intent 未清 | 走 quarantine 恢复；事件日志**永久缺一条**，无补写路径 |
| gate 子进程 stderr 非空（P2-4） | 正常操作被误判为 quarantine | 只能人工 `recover-quarantine` |
| worktree/分支创建成功但状态未提交 | 孤儿 worktree | recovery.md 描述了"采纳未记录 worktree"，但要求 `--ignored` 状态完全干净，否则永久拒绝 |
| DONE/CANCELLED 后的 claim（P1-5） | path/branch 永久不可复用 | **无** |

### 可能污染用户仓库或全局配置的步骤

* **会污染用户源仓库：** `git worktree add`（写 `.git/worktrees/<name>/`）、`git worktree add -b`（创建 `codex/<task-id>` 分支）、`git fetch`（写 `refs/remotes/<remote>/<base>` 与 objects）。三者都无回收路径（P1-5）。
* **不会污染的：** 所有 `git -c key=value` 都是**单次调用**参数，从不写入仓库/全局配置；`core.hooksPath=<devnull>` 同理；`chcp` 只在子 `cmd.exe` 内生效（windows_native_validation）。全局 Git 配置、系统设置、PATH 均不被触碰。✔
* **`<PLUGIN_DATA>` 之外唯一被创建的目录**是用户显式用 `--workspace-path` 指定的位置，且 `_workspace_plan` 有 6 层隔离断言（不得是 data root 的祖先、不得落在 `tasks/`/`analysis/`、不得与任何已配置源仓库重叠）。✔

### 与文档描述不一致的行为

| 文档声称 | 实际代码 |
|---|---|
| hooks 拦截危险 Git 命令 | `exec_command`/`shell` 工具名永不触发（P1-2） |
| handoff 输出必须在 candidate root **之外** | `tests/windows_test/` 就在里面（P1-4） |
| 显式值"whitespace-only 视为未设置，绝不解析为当前目录" | 非空**相对**路径确实按 CWD 解析（P2-3） |
| INSTALL.md 的逐文件放置表 = 包内容 | 表中没有 `tests/windows_test/*`、`tests/test_hooks.py` 之外的若干测试文件 |
| INSTALL/README：base version `0.2.0` | manifest `0.3.0`（P3-2） |
| `cancel` "Report all retained paths" (recovery.md:107) | `command_cancel` 不返回任何 retained paths |

---

## 四、安全检查

| 检查项 | 结论 | 依据 |
|---|---|---|
| **Shell 参数引用** | ✔ 无问题 | 全部 `subprocess` 列表调用，无 `shell=True`。`_quote`（[hooks/dev_flow_hook.py:317](hooks/dev_flow_hook.py:317)）仅用于**显示**给用户的命令串，且实现了正确的 Windows 反斜杠-引号规则；skill 文档明确要求执行时保留三个独立 argv 而非重解析该串。 |
| **用户输入拼接进命令** | ✔ 无问题 | 唯一接近的是 `git fetch -- <remote_url> <refspec>`（[:8453](scripts/dev_flow.py:8453)），已有 `--` 分隔符、refspec 由 `_approved_fetch_refspec` 模板生成并与审批哈希绑定。分支名过 `git check-ref-format --branch`。 |
| **路径规范化与范围限制** | ✔ 优秀 | `_filesystem_identity` / `_is_within` 用**稳定卷+文件 ID** 而非文本前缀比较，正确处理映射盘、UNC、junction、per-directory 大小写敏感、NFC/NFD。`_workspace_plan` 有 6 层隔离断言。canonical 路径校验拒绝 `..`、绝对路径、盘符、反斜杠。 |
| **误删/覆盖用户文件** | ✔ 无问题 | `shutil.rmtree` 仅 3 处：两处是自建的能力探测临时目录（[:593](scripts/dev_flow.py:593)、[:637](scripts/dev_flow.py:637)、[:4453](scripts/dev_flow.py:4453)），一处是失败时清理**自己刚建的** snapshot 目录（[:11929](scripts/dev_flow.py:11929)）。`unlink` 全部作用于控制器自有的 rollback/quarantine/temp 文件。控制器从不删除用户仓库文件。 |
| **`eval` / `source` / 通配符 / `rm -rf`** | ✔ 无 | 无 `eval`/`exec`。`glob` 仅用于 `tasks/*/state.json` 与 `.{name}.rollback-*`（文件名固定，无 glob 元字符风险）。 |
| **临时文件安全** | ⚠ 基本安全，有残留 | 全部 `tempfile.mkstemp(dir=<目标同目录>)` + 立即 `fchmod(0o600)` / Windows DACL 校验，无可预测名、无 `/tmp` 竞态。但见 P2-10：被 SIGKILL 杀掉时留下不可回收的 `.{name}.<rand>`。 |
| **敏感信息落盘/入日志/进 Git** | ❌ **有问题** | **P1-3：`remote_url` 含凭据时明文写入 state.json 并打印到 stdout。** 另：`review-snapshot` 会把所有**未被 gitignore 的** untracked 文件打包进 `untracked.tar`（[:11667](scripts/dev_flow.py:11667)）——若用户有未被忽略的 `.env`，其内容进入 `<PLUGIN_DATA>`。文件权限 0600 且目录 0700，可接受，但应在 README 的 Boundaries 中点明。`--exclude-standard` 已正确排除被忽略的文件。✔ |
| **Hook 执行仓库内不可信代码** | ✔ 无 | hook 只 import `<PLUGIN_ROOT>/scripts/dev_flow.py`，绝不执行仓库内脚本。所有 mutating git 调用都带 `-c core.hooksPath=<devnull>`（[:8415](scripts/dev_flow.py:8415)、[:10544](scripts/dev_flow.py:10544)），禁用仓库 hook。`_run` 对 git 剥离了 `GIT_ASKPASS`/`GIT_SSH_COMMAND`/`GIT_PROXY_COMMAND`/`GIT_CONFIG_*`/`GIT_EXEC_PATH` 等全部可注入执行的变量，并钉死 `--upload-pack=git-upload-pack`、`protocol.ext.allow=never`、`credential.helper=`、`GIT_TERMINAL_PROMPT=0`。这一块做得比大多数生产工具都好。 |
| **归档解压** | ✔ 无问题 | `_validate_untracked_archive` 只用 `extractfile` 做内存哈希，**从不落盘**；`candidate_identity` 明确"never extractall"并逐成员校验路径。无 zip-slip / tar-slip。 |
| **权限** | ✔ 优秀 | POSIX 目录 0700 / 文件 0600；Windows 用 `ctypes` 读真实 owner + inherited DACL（[:1067](scripts/dev_flow.py:1067)），descriptor 为 null / 不可读 / owner 异常 / 广泛可写时**阻断 mutation**，且明确不把 POSIX mode 当作 Windows ACL 证明。 |

---

## 五、兼容性检查

### macOS
* ✔ `resolve_data_dir` 走 `~/Library/Application Support/`。
* ⚠ APFS 默认大小写不敏感但 **Unicode 保留**（不做 NFD 归一化，但比较时归一化）。代码用 `_probe_filesystem_case_sensitive` / `_probe_filesystem_unicode_distinct` 实际探测而非假设，处理正确。
* ⚠ `fcntl.lockf` 在 macOS 上对 NFS/SMB 挂载的行为不同于本地卷；若 `<PLUGIN_DATA>` 落在网络卷上，锁可能静默降级。**需要验证**（README 已说明状态是 host-local，但没说"不得放在网络卷"）。

### Linux
* ✔ `$XDG_STATE_HOME` → `~/.local/state`。CI 覆盖 3.9–3.14 全版本。
* ⚠ `_posix_process_group_alive` 用 `os.killpg(pg, 0)`。在 PID 命名空间（容器）内，PID 回绕后可能误判"进程仍存活" → 误报 quarantine。概率极低。

### Windows / Git Bash / WSL / PowerShell
* ✔ **原生 Windows**：无 POSIX 兼容层依赖；`msvcrt.locking` 字节 0 锁；kill-on-close Job 对象；长路径/UNC 身份处理完备；保留设备名（`con`/`nul`/`com1`…）在 task id 校验中被拒绝（[:156](scripts/dev_flow.py:156)）。
* ❌ **`.cmd` 以 LF 行尾发布**（P2-1，需实机验证）。
* ⚠ **Git Bash**：`os.name` 是 `posix`（MSYS2 Python）还是 `nt`（原生 Python 在 Git Bash 里跑）取决于用哪个解释器。若用 MSYS2 的 Python，`_platform_family()` 返回 `linux`，数据目录会落到 `$XDG_STATE_HOME`，与原生 Windows 运行时**互不可见**——用户会看到"任务消失"。**建议在文档中明确：必须用原生 Windows Python，不得用 MSYS2/Cygwin Python。**
* ⚠ **WSL**：WSL 内的 Linux Python 与 Windows Python 是两套 `<PLUGIN_DATA>`，且 `/mnt/c/...` 上的 `fcntl` 锁在 DrvFs 上不可靠。README 已有"不得跨 OS 迁移状态"的说明，但没有点名 WSL。
* ✔ **PowerShell**：仅作为文档中的调用方式出现，控制器本身不依赖任何 shell。`_powershell_segments` 是 hook 的**只读**分词器（用于识别命令），不执行任何 PowerShell。

### 不同 Shell（Bash / Zsh / Dash）
* ✔ 控制器不依赖 shell。hook 的 `_posix_segments` 用 `shlex(punctuation_chars=...)` 做保守分词，遇到动态展开（`$`、反引号）在严格模式下直接拒绝并给出诊断，**不猜测**。这是正确的失败方式。
* ⚠ `_LEADING_WORDS` / `_WRAPPERS` 是白名单式的启发法。`hooks/dev_flow_hook.py` 顶部的 docstring 与 README「Boundaries」都明确声明这不是安全边界。评价：**设计诚实，实现质量高于其宣称的定位**。

### 路径含空格 / 中文 / 特殊字符
* ✔ 覆盖良好。`tests/support.py` 的 docstring 明确说明"exercises paths containing spaces and non-ASCII characters"；canonical golden vector 本身就用了 `scripts/测试.py`（[scripts/candidate_identity.py:153](scripts/candidate_identity.py:153)）；`path_bytes_hex` 保留原始字节；`os.fsdecode`/`fsencode` + `surrogateescape` 处理非 UTF-8 文件名。
* ⚠ 命令行元字符（`&`、`^`、`(`、`)`）在插件安装路径中的往返，README 明确列为**尚未完成的 Windows 宿主 smoke 验证项**（[README.md:474](README.md:474)）。诚实标注，但意味着这条路径未经证实。

### Git 仓库 / worktree / 非 Git 目录
* ✔ `_canonical_repo` 会拒绝非 Git 目录；`_is_linked_worktree`、`_git_common_dir` 正确区分主检出与 linked worktree；`start` 用 `--git-common-dir` 去重，避免把同一仓库的两个 worktree 当成两个仓库（`DUPLICATE_GIT_REPOSITORY`，[:6276](scripts/dev_flow.py:6276)）。
* ✔ 拒绝 `assume-unchanged`/`skip-worktree`/稀疏检出/脏子模块/LFS 等无法暴露完整字节的情况（[:4807](scripts/dev_flow.py:4807)）。
* ❌ worktree 的**回收**缺失（P1-5）。

### 首次运行 / 重复运行 / 升级 / 卸载
* ✔ **首次**：无 `config.json` 即"处处生效"，行为不变。
* ✔ **重复**：revision 乐观锁 + 内容哈希幂等 + `unchanged: true`。
* ⚠ **升级**：schema v1 保持可读，但 `EVIDENCE_CONTRACT_VERSION` 更严——旧证据对下游 gate 无效、必须重新生成；`branch` 策略的旧任务缺 `branch_binding` 会 fail-closed 且**只能取消重建**。文档已充分说明，但这意味着任何证据格式变更（包括本报告建议的 P1-1/P1-3 修复）都会作废所有在途任务。
* ❌ **卸载**：`<PLUGIN_DATA>` 与用户仓库中的 worktree/分支全部残留，无卸载脚本、无 `release-workspace` 命令（P1-5）。

---

## 六、测试建议

现有覆盖已经相当好（181 个用例，含真实多进程锁竞争、进程死亡、mutation gate 崩溃、原子写中断恢复、Windows launcher 回退、scope 环境覆盖）。以下是**当前无法捕获已确认缺陷**的缺口，按价值排序，全部可自动化。

**T-1（对应 P1-2，最高价值）— matcher 与 handler 工具名集合一致性**
```python
def test_pretooluse_matcher_covers_every_handled_tool_name(self):
    matcher = json.loads(HOOKS_JSON.read_text("utf-8"))["hooks"]["PreToolUse"][0]["matcher"]
    # 直接取 handler 的真实判定集合，而不是复制一份字面量
    for name in ("Bash", "apply_patch", "Edit", "Write", "exec_command", "shell"):
        self.assertIsNotNone(re.match(matcher, name),
                             f"{name} is handled by handle() but never matched")
```
并补一个真正以 `tool_name="shell"` / `"exec_command"` 发起的 deny 用例（现有 `test_unified_exec_cmd_alias_is_guarded` 用的是 `tool_name="Bash"`）。

**T-2（对应 P1-4）— candidate 树不得包含 handoff 产物**
```python
def test_candidate_root_contains_no_handoff_artifacts(self):
    entries = {e.path for e in canonical_entries(PLUGIN_ROOT)}
    self.assertFalse({p for p in entries if p.endswith(".zip")},
                     "handoff archives must live outside the candidate root")
```
再加一条：若 `tests/windows_test/dev-flow-candidate.json` 存在，其 `candidate.sha256` 必须等于当前树的 canonical 摘要（自洽断言）。

**T-3（对应 P1-3）— 凭据脱敏**
```python
def test_remote_url_credentials_never_reach_state_or_stdout(self):
    repo, _ = self.make_repo("credential repo")
    self.git(repo, "remote", "add", "origin",
             "https://x-access-token:ghp_SECRETVALUE@example.invalid/o/r.git")
    out = self.run_controller("preflight", ...)          # preview + confirm
    self.assertNotIn("ghp_SECRETVALUE", out)
    self.assertNotIn("ghp_SECRETVALUE", (state_path).read_text("utf-8"))
```

**T-4（对应 P1-1）— 指纹调用次数与规模上界**
```python
def test_review_snapshot_hashes_each_tracked_file_at_most_twice(self):
    with mock.patch.object(dev_flow, "_sha256_file", wraps=dev_flow._sha256_file) as spy:
        self.run_controller("review-snapshot", ...)
    per_file = collections.Counter(call.args[0] for call in spy.call_args_list)
    self.assertLessEqual(max(per_file.values()), 2)
```
这是唯一能防止性能回归的结构性断言；配一个 500 文件的 fixture 仓库并断言墙钟时间上界。

**T-5 — 真并发（当前只测了 namespace 锁与 revision 竞争）**
* 两个进程同时对**同一任务**执行不同 mutation（`record-artifact` vs `transition`）：断言其中一个拿到 `REVISION_CONFLICT` 或 `LOCK_TIMEOUT`，且 `state.json` 始终是合法 JSON、`events.jsonl` 无交错半行。
* 两个进程同时对**不同任务但同一源仓库**执行 `prepare-workspace --execute`：断言 registry claim 严格互斥，不产生两个指向同一路径的 worktree。

**T-6 — 中断与残留**
* SIGKILL 精确打在 `mkstemp` 之后 / `unlink` 之前，断言 `recover-atomic-write` 能**报告**孤儿临时文件（当前不能，见 P2-10）。
* mutation gate 子进程向 stderr 写一行无害警告，断言操作**不**变成 quarantine（对应 P2-4，当前会失败——这正是它该被写的理由）。

**T-7 — 配置不完整 / 文件缺失**
* `config.json` 存在但 `scope` 缺失 / mode 非法 / include 是字符串而非列表 → `scope --clear` 必须可恢复（已有部分覆盖，补齐三种畸形形态）。
* `state.json` 存在但 `repositories` 缺失、`workspace` 是 null、`approvals` 是列表 → 所有命令必须给出结构化错误而非 `INTERNAL_ERROR`。
* `<PLUGIN_DATA>` 目录被设为只读 → 断言错误码稳定。

**T-8 — 路径含空格与中文（补齐薄弱面）**
参数化 fixture：`plugin root`、`<PLUGIN_DATA>`、repo path、workspace override path 分别取 `"has space"` / `"中文目录"` / `"a&b(c)"`，跑完整 lite 流程。当前对 `<plugin-root>` 含 shell 元字符的覆盖是**缺口**（README 自己承认）。

**T-9 — 双 Hook 注册**
在同一次 handle 调用序列里模拟两份注册，断言两次输出**逐字节相同**（幂等），并断言 `PreToolUse` 的两次 deny 决策一致。这把 P2-7 从"未知"变成"已知且无害"。

**T-10 — Git Worktree 与非 Git 目录**
* 对一个 linked worktree 直接 `start` → 断言与对主检出 `start` 得到相同的 `git_common_dir` 去重行为。
* 对非 Git 目录 `start` → 断言明确错误码。
* 对同一仓库的主检出 + linked worktree 各传一个 `--repo` → 断言 `DUPLICATE_GIT_REPOSITORY`（已有？建议显式补）。

**T-11 — `.cmd` 行尾（需在 Windows job 上跑）**
在 CI 的 Windows 矩阵里，用 LF 版直接执行 shim 并强制走 `run_py_version` 分支（`for` 块内 `goto`），断言 stdout 是合法 JSON、exit code 为 0。

---

## 七、修复顺序

### 第 1 批：必须最先修（阻塞发布，互不冲突，可并行）

| # | 问题 | 理由 |
|---|---|---|
| 1 | **P1-4** 删除 `tests/windows_test/` | 最简单、零风险，且**必须先做**——它决定 canonical 摘要，后面每一次改动都会再次改变摘要，先清干净才有稳定基线 |
| 2 | **P1-2** matcher/handler 一致性 | 单文件 + 校验器改动，无兼容性风险，直接恢复守卫能力 |
| 3 | **P1-3** remote URL 脱敏 | 安全问题，越早越好；**注意**它会改变 `preflight_remote_sha256`，所以要与第 2 批的证据版本 bump 合并 |
| 4 | **P2-5** `finally` 里的 `return` | 一行修复，消除 CI 警告 |

**验证：** `python -m unittest discover -s tests` + `validate_package.py` + `audit_runtime_imports.py`；对干净 `git archive` 导出重算 canonical 摘要并记录为新基线。

### 第 2 批：一起改（都涉及证据格式，必须同批 bump `EVIDENCE_CONTRACT_VERSION` → 2）

| # | 问题 |
|---|---|
| 5 | **P1-1** 指纹改为 `diff-files` 驱动 + 进程内缓存 |
| 6 | **P1-3** 的证据字段变更（与 #3 合并落地） |

**兼容性风险：⚠ 高。** 这一批会使**所有在途任务**的既有证据对下游 gate 失效。必须：
* 在 README「Upgrade existing tasks」中新增 v1→v2 段落，明确"取消并重建"是唯一路径；
* 保证 `_require_current_evidence` 的错误信息指名 v1→v2；
* 在 `start` 之外不提供任何"追认"通道（保持现有的 fail-closed 立场）。

**验证：** T-4（哈希次数上界）+ T-3（脱敏）+ 全量套件 + 在一个 ≥10k 文件的真实仓库上手工跑一次完整 full 流程并记录墙钟时间。

### 第 3 批：生命周期（独立特性，可单独发版）

| # | 问题 |
|---|---|
| 7 | **P1-5** 新增 `release-workspace` 命令 + claim 释放语义 + `cancel` 返回 retained paths |

**兼容性风险：⚠ 中。** `_state_workspace_claims` 的语义变更会影响所有既有 claim 的解释。务必采用"显式 `released_at` 才释放"而非"终态即释放"，否则会让活跃 worktree 被别的任务抢占——那是比现状严重得多的问题。

**验证：** T-5（跨任务 claim 互斥）+ 新增"释放后可复用同路径同分支"用例 + 手工验证 `git worktree list` 在释放后干净。

### 第 4 批：平台与稳健性

| # | 问题 |
|---|---|
| 8 | **P2-1** `.cmd` 行尾（**先验证再改**；若改则 canonical 摘要再变一次，建议与第 3 批同批） |
| 9 | **P2-2** `PLUGIN_ROOT` 回退 |
| 10 | **P2-3** 相对 `--data-dir` |
| 11 | **P2-4** gate stderr 容忍 |
| 12 | **P2-9** PreToolUse 诊断字段 |
| 13 | **P2-8** `check-ref-format -C` |
| 14 | **P2-6** allowlist 排除常见开发目录 |
| 15 | **P2-10** 孤儿临时文件报告 |

**兼容性风险：** #8 改变 canonical 摘要与 Windows 启动路径，需重跑 Windows 原生自测；#11 放宽了一个当前 fail-closed 的条件——必须同时保留 stderr 的 sha256 审计字段，避免降低可审计性。其余为局部修复。

### 第 5 批：可维护性（无功能风险，可持续进行）

P2-7（文档去重指引 + instance_key）、P3-1（拆分 12812 行控制器）、P3-2（版本一致性校验）、P3-3（POSIX shim）、P3-4（上下文瘦身）、P3-5/6/7。

**建议顺序内的最优先项是 P3-2**：把"文档中的 base version 必须等于 manifest version"写进 `validate_package.py`，这样第 1–4 批每次改动都会自动检出文档漂移。

---

### 最终验证清单（每批完成后执行）

```bash
python -m unittest discover -s tests -v
```
```bash
python scripts/audit_runtime_imports.py && python scripts/validate_package.py
```
```bash
git archive HEAD | tar -x -C /tmp/clean && python -c "import sys;sys.path.insert(0,'scripts');from candidate_identity import canonical_entries,canonical_digest;from pathlib import Path;print(canonical_digest(canonical_entries(Path('/tmp/clean'))))"
```
```bash
python scripts/run_bundled_validators.py --require-available
```

外加两项**不可由 CI 替代**的人工验证（README 自己也这么要求）：真实 Windows Codex 宿主上的安装 + hook 拾取 smoke（含含空格/中文/元字符的安装路径），以及在一个 ≥10k 文件的真实仓库上完整跑一遍 full 流程。

---

**测试状态说明：** 报告完成时 `tests/test_dev_flow.py`（84 例）仍在后台运行、尚未输出结果；其余 5 个模块共 97 例已确认全绿（3 skipped）。上述所有缺陷判定均基于代码阅读与已执行的校验器/摘要重算，不依赖该模块的结果。

`tests/test_dev_flow.py` 已跑完：**84 tests, OK, 0 失败**。全套 181 例现已全部确认通过（97 + 84，3 skipped）。报告中的"测试状态说明"一段可更正为：全部测试通过。

一个值得补充进 **P1-1** 的实测佐证：该模块单独耗时 **1441 秒（24 分钟）**，而其余 5 个模块合计仅 72 秒。差距不是用例数量造成的（84 vs 97），而是 `test_dev_flow.py` 是唯一大量走真实 Git 仓库 + `_fingerprint_repo` 全树哈希路径的模块——在**测试用的玩具仓库**（每个只有个位数文件）上就已经是这个量级。这直接印证了 P1-1 的结论：成本来自 `_fingerprint_repo` 的调用次数与进程开销的乘积，在真实规模仓库上会随文件数再乘一个大系数。

这也给 T-4 增加了一个可立即落地的回归护栏：把 `tests/test_dev_flow.py` 的墙钟时间纳入 CI 断言（当前 30 分钟的 `timeout-minutes` 已经接近被这一个模块吃满，Windows runner 上还要更慢——存在 CI 随时超时的风险）。修复 P1-1 后，这个数字应当是验证是否真正生效的首要指标。

其余审核结论不变。