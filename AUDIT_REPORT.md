# Dev Flow Orchestrator 当前 HEAD 综合对抗性审计报告

生成时间：`2026-08-09T12:06:00+08:00`  
审计对象：`e8ca09bebfadb1a90eb84767b0c5303163da4179`（`main`）  
审计方式：只读静态调用链审计、完整测试基线、临时 Git/运行时/伪 Codex 故障注入、真实本地 MCP STDIO 协议探测  
审计结论：发现 24 项独立问题；`CRITICAL 2 / HIGH 11 / MEDIUM 10 / LOW 1`。当前 HEAD 不满足“证据与当前仓库一致才可 `DONE`”以及“卸载只删除已验证安装器所有物”两条最高优先级不变量。

| ID | 严重程度 | 类型 | 标题 | 是否复现 | 主要影响 |
| -- | ---- | -- | -- | ---- | ---- |
| DFO-AUDIT-001 | CRITICAL | CONFIRMED_DEFECT | 最终 snapshot 与 Store 提交间竞态可固化错误 `DONE` | 是 | 终态 Dossier 立即过期，用户被误告知交付正确 |
| DFO-AUDIT-002 | CRITICAL | CONFIRMED_DEFECT | 卸载 source 的预检—递归删除竞态可删除新产生的用户代码 | 是 | 无外部备份时不可恢复的数据损坏 |
| DFO-AUDIT-003 | HIGH | CONFIRMED_DEFECT | 两次 clean capture 之间的 commit 不进入 task-change manifest | 是 | 已提交任务改动从 ownership、assurance、Dossier 消失 |
| DFO-AUDIT-004 | HIGH | CONFIRMED_DEFECT | symbol-only impact closure 被退化为 repository/path | 是 | 越界 finding 绕过 planning re-entry |
| DFO-AUDIT-005 | HIGH | CONFIRMED_DEFECT | 活跃仓库 lease 只在 admission 校验，后续动作仍可推进冲突任务 | 是 | 两个任务可继续占用同一 worktree |
| DFO-AUDIT-006 | HIGH | CONFIRMED_DEFECT | 安装器验证后继续从可写 candidate 读取并激活 | 是 | dirty/broken candidate 被成功激活且 receipt 仍声称原 commit |
| DFO-AUDIT-007 | HIGH | CONFIRMED_DEFECT | upgrade/repair rollback 非事务且可“恢复”错误版本 | 是 | 失败后留下 candidate active、旧资产缺失的混合态 |
| DFO-AUDIT-008 | HIGH | CONFIRMED_DEFECT | runtime receipt 不参与启动 attestation，篡改 runtime 被 repair 复用 | 是 | 已安装代码被改后继续执行且 repair 不修复 |
| DFO-AUDIT-009 | HIGH | CONFIRMED_DEFECT | fresh install 自产 `__pycache__` 并阻断默认卸载 | 是 | 正常生命周期在首次安装后即不可闭合 |
| DFO-AUDIT-010 | HIGH | CONFIRMED_DEFECT | runtime ownership 仅浅验 receipt 却递归删除整个 root | 是 | 未知/用户文件随 runtime 不可恢复删除 |
| DFO-AUDIT-011 | HIGH | HIGH_RISK_DEFECT | native Windows lifecycle fixture 未隔离真实 runtime root | 否（无 Windows） | CI/开发机上的真实 managed runtime 可能被创建、替换或删除 |
| DFO-AUDIT-012 | HIGH | CONFIRMED_DEFECT | 深层但未超字节上限的 JSON 可终止整个 MCP STDIO 进程 | 是 | 单个畸形请求造成进程级拒绝服务并丢弃后续有效请求 |
| DFO-AUDIT-013 | HIGH | CONFIRMED_DEFECT | MCP current-action output schema 不约束嵌套 authority | 是 | 空 task/action、缺 binding 的结果仍通过 schema gate |
| DFO-AUDIT-014 | MEDIUM | CONFIRMED_DEFECT | MCP 取消/断开未桥接到 Git 子进程 | 是 | 取消后 worker/slot 仍占用至 Git 超时；MCP/Web 语义分叉 |
| DFO-AUDIT-015 | MEDIUM | CONFIRMED_DEFECT | POSIX 文档化 `DEV_FLOW_PYTHON` override 实际被忽略 | 是 | 合法 Python 无法按 troubleshooting 恢复安装/卸载 |
| DFO-AUDIT-016 | MEDIUM | CONFIRMED_DEFECT | Windows 安装不提供已宣称的 `dev-flow` CLI/Web launcher | 静态穷尽确认 | Windows 用户无法使用公开文档中的 CLI/Web 产品面 |
| DFO-AUDIT-017 | MEDIUM | CONFIRMED_DEFECT | 基线测试继承真实 `DEV_FLOW_DATA_DIR`，逃出临时 `CODEX_HOME` | 是 | canonical suite 非 hermetic，并读取环境中既有 Web 状态 |
| DFO-AUDIT-018 | MEDIUM | CONFIRMED_DEFECT | public-doc validator 提前 `return`，语义校验全部不可达 | 是 | 错误文档/平台能力仍获得 package PASS |
| DFO-AUDIT-019 | MEDIUM | TEST_GAP | Windows lifecycle 仍断言已删除的 Hook 文案 | 未在 Windows 执行 | native suite 预期必红，不能充当 release evidence |
| DFO-AUDIT-020 | MEDIUM | DOC_MISMATCH | current base OpenSpec 仍要求已删除 Hook/Skills | 静态确认 | 当前产品真相与有效验收基线相反 |
| DFO-AUDIT-021 | MEDIUM | DOC_MISMATCH | INSTALL/active spec 宣称的 standalone provision 路径不可执行 | 静态确认 | 操作者无法按文档建立受支持 standalone 模式 |
| DFO-AUDIT-022 | MEDIUM | DOC_MISMATCH | `VALIDATION_REPORT.md` 把陈旧、非默认卸载证据标为 current | 动态基线反证 | 审计/发布者会误判当前 HEAD 与默认卸载能力 |
| DFO-AUDIT-023 | MEDIUM | HIGH_RISK_DEFECT | 外层 MCP output guard 可能丢失已提交 mutation 的 uncertain 语义 | 否（普通路径有内层保护） | SDK 后处理/旁路回归时返回错误的 `INTERNAL_ERROR` |
| DFO-AUDIT-024 | LOW | MAINTAINABILITY_RISK | MCP tool catalog digest 未覆盖 input schema、描述和 annotations | 静态确认 | 破坏性接口漂移可保持同一 catalog identity |

## 1. 审计摘要

本次没有把 README、OpenSpec、测试名或既有 Validation Report 当作产品事实。审计先从产品声明提取不变量，再沿 Controller → Engine → Store → GitClient、MCP SDK → application → Controller、以及 installer → runtime → Codex activation → uninstaller 的真实调用链交叉验证。动态实验全部使用 `uv`、`TemporaryDirectory`、临时 Git bare remote、临时 HOME/CODEX_HOME/marketplace/runtime/PATH 与伪 Codex；没有运行真实用户环境的安装、卸载、迁移、push、PR 或远程写操作。

最高风险由两条可重复证据构成：

1. `Controller.apply()` 在完成双 capture 后、进入 Store 锁并落盘前仍有未受保护的仓库变化窗口。最终动作可把旧 snapshot 写入 Dossier 并返回 `dossier.current=true`，而紧接着重新 capture 已得到 `workspace_changed`；状态却已经是 `DONE`。
2. uninstaller 在 source 所有权预检后先调用外部 Codex、删除 launcher/runtime/marketplace，最后不复验地 `rm -rf` source。伪 Codex 在 `plugin remove` 期间创建的新用户文件被无提示删除。

安装链的风险不是单个边缘点：candidate source 无 seal、rollback 不保存旧 artifact、runtime receipt 不度量安装内容、安装过程自产 ignored cache、卸载对 source/runtime 都执行“先验证、后整树删”。这些根因共同说明当前生命周期不是以不可变 artifact 和精确 ownership manifest 为核心的事务。

完整测试没有通过：两次独立 discovery 均为 415 tests、2 failures、22 skips。两个失败均来自测试继承了高优先级 `DEV_FLOW_DATA_DIR`，观察到环境中的既有 Web 进程，而非临时 `CODEX_HOME`。这既不能被忽略为噪声，也不能外推为产品 Web 缺陷；它是一个已确认的测试隔离缺陷。

## 2. HEAD、工作区与环境

| 项 | 结果 |
| -- | -- |
| commit | `e8ca09bebfadb1a90eb84767b0c5303163da4179` |
| branch | `main` |
| 初始 `git status --short` | rc=0，空 |
| 报告写入前 `git status --short` | rc=0，空 |
| 主机 | macOS 27.0, Darwin 27.0.0, arm64 |
| 项目 Python | CPython 3.14.4, 64-bit |
| uv | 0.11.29 |
| OpenSpec CLI | 1.6.0 |
| 网络/远程写 | 未执行 |
| 真实 Codex profile/marketplace/task data | 未读取或修改；测试仅使用临时替身 |

## 3. 执行命令与结果

| 命令 | 执行 | rc | 关键结果与限制 |
| -- | -- | -- | -- |
| `git status --short` | 是 | 0 | 初始为空 |
| `git rev-parse HEAD` | 是 | 0 | `e8ca09bebfadb1a90eb84767b0c5303163da4179` |
| `git branch --show-current` | 是 | 0 | `main` |
| `uv sync --locked` | 是 | 0 | `Resolved 34 packages`；`Checked 30 packages` |
| `uv run python -m unittest discover -s tests -p 'test_*.py'` | 是 | 1 | `Ran 415 tests in 1004.023s`; 391 passed, 2 failed, 22 skipped |
| `uv run python -m unittest discover -s tests -v` | 独立复跑 | 1 | `Ran 415 tests in 906.258s`; 同样 2 failures / 22 skips |
| `uv run python -m unittest tests.test_mcp_runtime` | 是 | 0 | `Ran 31 tests in 16.896s`, `OK`；随后对 deep JSON/cancellation/schema 另做对抗实验 |
| `uv run python scripts/validate_package.py` | 是 | 0 | 输出 `ok=true`, `errors=[]`, 六个 workflow；DFO-AUDIT-018 证明此 PASS 为不充分证据 |
| `uv run python -B -I -S scripts/validate_package.py` | 是 | 0 | 同样 PASS；用于 validator false-positive 复核 |
| `openspec validate dev-flow-orchestrator-mcp --strict` | 是 | 0 | change 结构有效；不证明实现正确或 base spec 已同步 |
| `openspec validate fix-source-action-payload-recovery --strict` | 是 | 0 | change 结构有效 |
| `openspec validate make-mcp-action-contract-self-contained --strict` | 补充执行 | 1 | 工作区存在非 HEAD、无文件的空目录，OpenSpec 将其识别为无 delta change；该目录不属于审计 commit，未列为 HEAD 缺陷，也未删除 |
| skip 清单静态枚举（`uv run python` 加载 suite，不运行用例） | 是 | 0 | 精确得到 22 个 skip 及原因，见 §8 |

两个完整测试失败：

- `test_cli.CliTests.test_data_directory_defaults_to_codex_plugin_namespace`
- `test_install_script.InstallerBehaviorTests.test_launcher_uses_automatic_codex_data_directory`

两者预期 `web status == stopped`，实际均为 `running`。未输出环境变量值或用户路径；只确认调用进程中存在 `DEV_FLOW_DATA_DIR`，而测试没有移除它。

## 4. 产品声明—实现—证据映射

| 声明/不变量 | 声明位置 | 主要实现位置 | 直接证据 | 结论 |
| -- | -- | -- | -- | -- |
| Controller 是唯一状态转换写入者 | `README.md:10-11`, `ARCHITECTURE.md:33-34` | `controller.py`, `store.py:387-414` | 调用图与 adapter parity tests | `CONFIRMED_OK`（仅写入权威）；提交前仓库隔离另有 DFO-AUDIT-001 |
| 任务绑定精确、不可变的 1–8 仓库集合 | `ARCHITECTURE.md:94-98` | `controller.py:508-547`, `snapshot.py` | multi-repository tests、临时 linked worktree/lease 实验 | `CONFIRMED_DEFECT`：后续 lease 不复验（005） |
| mutation 使用 exact action/binding/snapshot/revision | `README.md:49-50`, base delivery spec `158-197` | `engine.py:1190+`, `store.py:387-414` | stale mutation/CAS tests | binding/revision `CONFIRMED_OK`；capture→commit 为 `CONFIRMED_DEFECT`（001） |
| mutation 非幂等，丢响应后不得盲重放 | `README.md:106-108`, `ARCHITECTURE.md:114+` | `mcp/application.py:146-300`, `mcp/results.py:72-108` | cancellation/uncertain tests | ordinary application path `CONFIRMED_OK`；外层 guard 为 `HIGH_RISK`（023） |
| 可跨进程/重启恢复 | README/ROADMAP、delivery specs | Store 持久化、installed journeys | 完整 suite 与 installed harness | POSIX narrow path `CONFIRMED_OK`；真实进程 kill/Windows `NOT_TESTED` |
| snapshot 覆盖完整成员且不截断 | `ARCHITECTURE.md:71-76`, base delivery spec `114+` | `controller.py:449-495`, `git_client.py` | snapshot/multi-repo tests | capture 内稳定性 `CONFIRMED_OK`；clean commit manifest 与 post-capture drift 缺陷见 001/003 |
| stale evidence/ambient drift 失败关闭 | `ARCHITECTURE.md:98`, base delivery spec | `engine.py:2880-2940`, `delivery.py` | targeted finalization checks | finalize 前 ambient drift gate 存在；commit 窗口仍失效（001） |
| assurance/review/rework 有界 | ROADMAP、review specs | `assurance.py`, `review.py`, `engine.py` | adaptive assurance tests | budgets `CONFIRMED_OK`；symbol closure 为 `CONFIRMED_DEFECT`（004） |
| DONE/Dossier 对应当前权威状态 | README、base delivery spec `311-336` | `engine.py`, `delivery.py`, `controller.py` | 最终 fault injection | `CONFIRMED_DEFECT`（001、003） |
| MCP 恰好 11 个工具，无 shell/任意状态写 | `ROADMAP.md:28`, manifest | `mcp/tools.py`, `mcp/server.py` | official client STDIO + catalog inspection | 工具集合 `CONFIRMED_OK`；schema identity 不完整（013、024） |
| stdout 仅协议，stderr 有界且不泄密 | `ROADMAP.md:35`, `ARCHITECTURE.md:55-57` | `mcp/server.py`, `mcp/logging.py` | raw UTF-8/duplicate tests、异常日志审计 | 日志/redaction `CONFIRMED_OK`；deep JSON 会杀进程（012） |
| 安装/升级/回滚/卸载不破坏用户数据 | README/INSTALL、packaging specs | `scripts/install*`, `uninstall*`, `manage_runtime.py` | 临时完整 lifecycle fault injection | 多项 `CONFIRMED_DEFECT`（002、006–010） |
| 旧任务不静默迁移 | ARCHITECTURE/ROADMAP | Store model/version validators | store integrity/legacy resume tests | 受测 POSIX fixture `CONFIRMED_OK`；native Windows未验证 |
| CLI、MCP、Web 共享一套权威 | `README.md:10-11` | adapters → `Controller` | parity tests | 状态映射 `CONFIRMED_OK`；MCP/Web cancellation parity 缺陷（014） |

## 5. 审计覆盖矩阵

| 区域 | 状态 | 证据 | 限制 |
| -- | -- | -- | -- |
| A1 tracked/untracked/rename/mode/symlink、旧 action/binding/revision、重复提交 | CONFIRMED_OK | `test_git_snapshot`, `test_stale_mutations`, `test_controller_contracts` 在完整 suite 通过 | 只代表当前 macOS 文件系统 |
| A2 capture 内双遍稳定性 | CONFIRMED_OK | `controller.py:476-495`; snapshot fault tests | 不覆盖第二遍完成后到 Store commit |
| A3 capture→commit 与终态 freshness | CONFIRMED_DEFECT | EXP-01，DFO-AUDIT-001 | 所有依赖仓库 capture 的 mutation 共享结构风险 |
| A4 clean commit 的 path provenance | CONFIRMED_DEFECT | EXP-04，DFO-AUDIT-003 | commit 中多路径/多仓库需回归扩展 |
| B1 application 内丢响应/commit 后取消 | CONFIRMED_OK | `test_cancellation_before_entry_and_after_commit_are_distinct` | 非真实慢持久化/进程 kill |
| B2 OS 进程在写前/写后强制终止与只靠磁盘恢复 | TEST_GAP | installed uncertain-disconnect harness | 未对任意写入指令点做真实 SIGKILL/power-loss |
| B3 外层 MCP 输出后处理 | HIGH_RISK | DFO-AUDIT-023 | 正常 `_call_result` 内层 gate 当前可保护 |
| C1 同任务并发、revision CAS、原子写、锁释放 | CONFIRMED_OK | concurrency/store tests；POSIX `flock`, fsync+replace | Windows lock/pipe/taskkill 未运行 |
| C2 持续 membership lease | CONFIRMED_DEFECT | EXP-05，DFO-AUDIT-005 | 人工/旧版本形成的合法冲突 inventory 即可触发 |
| C3 native Windows locks/process cleanup | NOT_TESTED | 6 个 Windows runtime tests 被 skip | 无 Windows 10/11 x64 host |
| D1 多仓库缺失/顺序/别名/重叠/common-dir/第二成员发现 | CONFIRMED_OK | multi-repository core/controller/delivery tests | Windows 大小写/reparse 未验证 |
| D2 capture 后成员变化 | CONFIRMED_DEFECT | EXP-01 的同根窗口 | 删除整个成员目录的专门复现未单独执行 |
| E1 Store symlink、坏 JSON、身份错配、旧 namespace | CONFIRMED_OK | `test_store_integrity`, read-only inspection tests | 非法 UTF-8/磁盘满/断电矩阵未全做 |
| E2 磁盘写失败、只读目录、临时文件残留、数据 root Unicode/超长 | TEST_GAP | atomic-write 静态审计 | 未执行磁盘满、权限翻转或崩溃恢复 |
| F1 六个 official workflows 的 schema/可达/有界预算 | CONFIRMED_OK | 六个 YAML 均由 workflow/package/delivery tests 加载 | 不表示所有语义组合正确 |
| F2 review finding impact closure | CONFIRMED_DEFECT | EXP-06，DFO-AUDIT-004 | resource/integration-only locator 也需新增测试 |
| F3 manifest、freshness 与 Dossier | CONFIRMED_DEFECT | EXP-01/04，DFO-AUDIT-001/003 | 既有 happy paths 不能抵消缺陷 |
| G1 exact tools、unknown/extra/type/nonfinite/size/result envelope/request ID | CONFIRMED_OK | 31 个 MCP tests、official local SDK | nested authority schema 除外 |
| G2 raw STDIO framing、非法 UTF-8/duplicate/nonfinite/deep nesting | CONFIRMED_DEFECT | EXP-07，DFO-AUDIT-012 | Windows pipe semantics未验证 |
| G3 current-action output schema | CONFIRMED_DEFECT | EXP-09，DFO-AUDIT-013 | 当前正常 producer 恰好输出完整对象 |
| G4 cancellation/disconnect | CONFIRMED_DEFECT | EXP-08，DFO-AUDIT-014 | 真实客户端 in-flight EOF 仍未跑 |
| G5 stdout/stderr/redaction | CONFIRMED_OK | logging static audit、raw protocol tests | 真实 Codex host 如何展示 stderr 未验证 |
| H1 macOS fresh/repair/upgrade/rollback/default uninstall | CONFIRMED_DEFECT | EXP-02/03 | 伪 Codex，不外推真实 Codex 内部状态 |
| H2 native Windows lifecycle | NOT_TESTED | 16 个 PowerShell tests 被 skip | fixture 本身有 DFO-AUDIT-011/019 |
| H3 standalone lifecycle | DOC_MISMATCH | DFO-AUDIT-021 | 产品无可调用 provision path，无法动态执行 |
| H4 real Codex activation/return-format drift | NOT_TESTED | 本次安全边界禁止触碰真实 profile | 使用伪 Codex 验证脚本可观察事务 |
| 文档/有效规格/package semantic gate | CONFIRMED_DEFECT | DFO-AUDIT-018/020-022 | 中英文标题/主要命令窄范围一致 |
| Web/CLI 测试隔离 | CONFIRMED_DEFECT | 两个 canonical failures，DFO-AUDIT-017 | 未读取实际数据 root 值 |

## 6. 隔离实验登记

所有 heredoc 均从仓库根执行，Python 均为 `uv run python`；代码只创建 `TemporaryDirectory` 中的 repo/data/runtime/launcher/marketplace。报告保留程序逻辑和原始输出，不把一次性脚本写入测试目录。

### EXP-01：snapshot→Store commit 与最终 `DONE` 竞态

命令形态：

```sh
uv run python - <<'PY'
# 创建临时 Git repo 和 lite task；推进至 finalize。
# wraps controller.store.update：在 Controller 完成 _snapshot 后、原 update 前修改 tracked 文件。
# 比较 receipt projection snapshot 与立即重新 capture 的 snapshot/dossier freshness。
PY
```

普通 transition 原始结果：`injected_after_capture=true`、提交 revision=1；receipt snapshot `23014...`，重新 capture `cd160...`，`receipt_matches_refreshed=false`。最终 transition 原始结果：

```text
injected_after_final_capture=true
receipt_status=DONE, receipt_node=done, receipt_dossier_current=true
receipt_snapshot=845690..., refreshed_snapshot=673f12...
refreshed_dossier_current=false
refreshed_stale_reasons=[workspace_changed, workspace_changed:work-33f3085803a3]
stored_status=DONE, stored_revision=5
```

### EXP-02：macOS 安装/回滚/卸载统一 fault harness

命令形态：`uv run python -B - <<'PY'`，通过 `importlib` 复用 installer/uninstaller fixture 的临时 remote 与伪 Codex，再调用生产 `scripts/install.sh` / `scripts/uninstall.sh`。关键输出：

```text
SOURCE_TOCTOU: installer_rc=0, source_status="M scripts/dev_flow.py", cli_rc=1,
  plugin_active=true, receipt_source_commit=<unchanged verified HEAD>
LATE_FAILURE: installer_rc=1, activation_calls=[plugin add ...], plugin_active=true,
  cli_launcher_exists=false, marketplace_exists=false, mcp_launcher_exists=false
ROLLBACK_WRONG_SOURCE: installer_rc=1, claimed_restored=true,
  source_head_after=<candidate B>, old_head=<A>, calls=[remove, add(fail), add(restore)]
FRESH_DEFAULT_UNINSTALL: install_rc=0, uninstall_rc=1,
  ignored=[three dev_flow_orchestrator __pycache__ directories], source_exists=true
RUNTIME_EXTRA_DELETE: uninstall_rc=0, runtime_exists=false, sentinel_exists=false
SOURCE_DELETE_RACE: uninstall_rc=0, source_exists=false, raced_file_exists=false
PYTHON_OVERRIDE: installer_rc=1, source_exists=false,
  stderr="64-bit Python 3.10-3.14 is required"
```

### EXP-03：runtime receipt/内容 attestation

真实临时 managed runtime 生成后删除 receipt，再用生产 launcher 模板运行 installed stage-1 smoke：rc=0、`ok=true`、11 tools、read/mutation smoke=true、terminal=`CANCELLED`、`receipt_exists=false`。另一轮向临时 site-packages `delivery.py` 追加 marker 后同 commit/lock repair：`repair_reported_reused=true`、`tamper_survived_repair=true`、`receipt_equal=true`。

### EXP-04：clean commit 的 manifest 丢失

命令形态：`uv run python - <<'PY'`；临时 repo 对 `a.txt` 做 initial commit → capture → 修改并 commit → capture，然后调用 `derive_path_changes` 与 `derive_manifest`。原始输出：

```text
before_head=b58e..., after_head=9743...
before_entries=[], after_entries=[]
derived_change_count=0, manifest_entry_count=0
```

### EXP-05：持续 lease 完整性

命令形态：`uv run python - <<'PY'`；正常 start `task-one`，再直接用公开 Store fixture API 写入另一个结构有效、revision 0、同 repository 的 `task-two`。原始输出：`projection_returned=true`，但 `tasks_for_path(repo)` 为 `LEASE_INTEGRITY_CONFLICT`。

### EXP-06：symbol-only finding scope

命令形态：`uv run python - <<'PY'`；impact closure 为 `(repo=app,path=null,symbol=allowed_symbol)`，affected finding 为同 repo/path、`symbol=different_symbol`。原始输出：`impact_gap=false`, `derived_outcome=changes-requested`, `rework_count=1`, `gap_count=0`。

### EXP-07：deep JSON STDIO

命令形态：`uv run python - <<'PY'`；向临时 data-dir 的 `python -m dev_flow_orchestrator.mcp --stdio` 写入低于 2 MiB 的 100,000 层 JSON array，随后写合法 initialize。原始结果：rc=2、stdout 0 行、stderr 为单条 `INTERNAL_ERROR/startup_failed`；decoder probe 在 100,000/500,000 层抛 `RecursionError: Stack overflow`。

### EXP-08：MCP cancellation → Git bridge

命令形态：`uv run python - <<'PY'`；临时 repo 上 start/next，wrap Git runner 记录 `_GIT_CANCEL_EVENT`。原始输出：`start_ok=true`, `next_ok=true`, `git_calls=126`, `cancel_event_values=[None]`。

### EXP-09：嵌套 output schema

命令形态：`uv run python - <<'PY'`；构造具备正确 top-level schema/digest、但 `task/contract/repository_set/guidance/action={}` 且无 binding 的 current action，调用 `validate_current_action`。原始输出：`validated=true`, `action_keys=[]`, `task_keys=[]`, `has_binding=false`。

### 失败但未隐瞒的实验

- EXP-01 首次脚本使用了错误 projection key，`KeyError`、rc=1，尚未触发注入；纠正为 `repository_set.digest` 后得到上述复现。
- EXP-03 首次把仓库 `.venv` 当 production managed runtime；`-I` 下因 wheel 未安装而 `ModuleNotFoundError`。随后用 `manage_runtime.build()` 建立真实临时 managed runtime 并成功复现。两次失败尝试均未写仓库或用户环境。

## 7. 完整发现与修复建议

### DFO-AUDIT-001 — 最终 snapshot 与 Store 提交间竞态可固化错误 `DONE`

- **分类**：`CONFIRMED_DEFECT / CRITICAL / confidence HIGH`；模块：Controller、Store、Delivery。
- **位置**：`src/dev_flow_orchestrator/controller.py:449-495,665-718,720-878`；`src/dev_flow_orchestrator/store.py:387-414`。
- **不变量**：mutation 必须绑定 apply/commit 时的完整 repository-set snapshot；`DONE` Dossier 必须对当前 workspace 为 current。
- **前置条件**：任一仓库在第二次完整 capture 结束后、`Store.update()` 获得 task lock 并写入前改变；finalize 时影响最严重。
- **最小复现/命令**：EXP-01。用临时 repo 推进 lite 到 finalize，wrap `store.update` 并在调用原实现前修改 tracked 文件。
- **预期/实际**：预期 mutation 在变化后失败且 revision 不变；实际旧 snapshot 被写入，receipt 与持久化状态均为 `DONE`、`dossier.current=true`，立即重捕获却为 stale。
- **原始证据**：stored revision=5/status=`DONE`；receipt/refreshed digest 不同；stale reasons 包含 `workspace_changed`。
- **根因**：双 capture 只证明 capture 内部稳定；仓库没有被锁，Store task lock/CAS 只保护 state revision，不重新验证 repository identity。snapshot 被闭包捕获后直接用于 durable transition。
- **用户影响/数据**：明确错误终态和静默交付错误；任务数据内部自洽但事实错误。用户可能基于错误 Dossier 交付代码。
- **可恢复性**：当前任务已终态，产品没有安全重开/撤销 `DONE` 路径；需人工核查并建立新任务，历史错误终态仍保留。
- **现有测试漏因**：只在两次 capture 之间制造 drift，或在 apply 前制造 drift；没有 deterministic hook 覆盖第二遍 capture 返回到 durable write 的窗口。
- **最小修复**：把 repository validation 与状态提交组成可验证 commit protocol。最小方案是在 Store mutation 临界点前重新 capture/比较，并在落盘后以相同 authority 做最终验证；更强方案为对 snapshot inputs 建立 OS/Git 可验证 lease。不能仅增加第三次无锁 capture。
- **回归测试**：对 apply/revise/decision/disposition/cancel 逐个注入 capture-return→write drift；finalize 必须断言没有 `DONE`/revision change；覆盖一个成员和 8 个成员中任一变化。
- **兼容性**：不必改变 model schema，但会改变竞态下的错误码/重试流程；若增加 commit token，则需版本化 binding/持久化协议。

### DFO-AUDIT-002 — source 预检与递归删除之间可不可恢复地删除用户代码

- **分类**：`CONFIRMED_DEFECT / CRITICAL / confidence HIGH`；模块：POSIX/Windows uninstaller。
- **位置**：`scripts/uninstall.sh:416-489,491-560`；`scripts/uninstall.ps1:230-280`。
- **不变量**：卸载只删除在删除时仍能证明属于安装器的精确资产，且必须保留预检后出现的用户成果。
- **前置条件**：source 通过 clean/ignored/local-history 检查；随后外部命令或并发进程在最终递归删除前创建文件。
- **最小复现/命令**：EXP-02 `SOURCE_DELETE_RACE`；伪 Codex 在生产 uninstaller 的 `plugin remove` 中写入 `raced-user-work.txt`。
- **预期/实际**：预期最后一刻复验失败并保留新文件；实际 rc=0，source 与新文件均被 `rm -rf` 删除。
- **原始证据**：`activation_calls=[plugin remove ...]`, `source_exists=false`, `raced_file_exists=false`。
- **根因**：所有权验证与 destructive operation 相隔多个外部副作用；最终删除以路径字符串重新解析，无 tree identity/manifest/handle 锚定和复验。
- **用户影响/数据**：校验后创建的源文件、未提交工作甚至 local commit 可被不可恢复删除；符合 CRITICAL 的用户代码损坏标准。
- **可恢复性**：没有外部备份或文件系统快照时不可恢复。
- **现有测试漏因**：只覆盖 uninstaller 启动时已经 dirty/ignored/local-ahead 的拒绝；合成 clean checkout；未覆盖 preflight→delete race。
- **最小修复**：安装时记录逐项 ownership manifest；删除前原子隔离同文件系统目录并复验 exact tree identity，发现未知条目立即恢复；只逐项删除 known-owned 内容，不对容器 `rm -rf`。
- **回归测试**：在 plugin remove、launcher 删除、runtime 删除、marketplace write 各注入 tracked/untracked/ignored/local commit/symlink；断言新成果仍存在且卸载非零。
- **兼容性**：改变卸载 receipt/失败行为，不涉及 task model；旧安装没有 manifest 时需保守 fail-closed 或一次显式 adoption。

### DFO-AUDIT-003 — clean commit 的改动不进入 task-change manifest

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：Git snapshot、Capsule、Engine。
- **位置**：`src/dev_flow_orchestrator/git_client.py:259-269,1368-1422`；`capsule.py:133-187`；`engine.py:1106-1124,1243-1253`。
- **不变量**：source-producing action 的 manifest 必须精确包含其完整变更，或在 HEAD/branch 越过 source interval 时失败关闭。
- **前置条件**：action 起点与终点均为 clean worktree，但期间把变更 commit 到新 HEAD。
- **最小复现/命令**：EXP-04。
- **预期/实际**：预期拒绝 HEAD transition 或记录 `a.txt`；实际 HEAD 不同，两个 snapshot entries 都为空，derive/manifest 均 0 条。
- **原始证据**：`before_head != after_head`, `derived_change_count=0`, `manifest_entry_count=0`。
- **根因**：路径枚举只取相对当前 HEAD 的 `diff-index` 与 untracked；两个 clean HEAD 都没有候选路径。`derive_path_changes` 只比较已枚举 entries，Engine 对 produces-source 不拒绝 HEAD/branch movement。
- **用户影响/数据**：已提交任务代码从 ownership/provenance、assurance slice、review 和 Dossier 中消失；后续可基于空 manifest 错误完成。
- **可恢复性**：Git commit 仍在仓库，可人工恢复证据；已写任务历史不会自动补齐。
- **现有测试漏因**：测试覆盖 staged/unstaged/untracked，不覆盖 clean-before/clean-after commit。
- **最小修复**：最小直接方案为 source interval 禁止 HEAD/branch 改变；若产品要允许 agent commit，则必须枚举 old tree→new tree delta 并合并 index/worktree delta。
- **回归测试**：单/多仓库 commit、rename/delete/mode/symlink、merge commit、commit 后再 dirty；断言 exact manifest 或原子拒绝。
- **兼容性**：禁止 commit 只改变行为；支持 commit delta 会扩展 manifest 生成语义，现有 schema 可容纳路径条目。

### DFO-AUDIT-004 — symbol-only impact closure 被错误视为同一 scope

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：Review/Assurance。
- **位置**：`src/dev_flow_orchestrator/review.py:95-107,240-264`；`openspec/specs/review-finding-governance/spec.md:60-77`。
- **不变量**：`affected` finding 只有在完整 typed locator 属于 impact closure 时才能直接进入 source rework；越界影响必须 `impact_gap` 并回到 planning。
- **前置条件**：impact 与 finding 都是同 repository、`path=null`，但 symbol 不同。
- **最小复现/命令**：EXP-06。
- **预期/实际**：预期 `impact_gap=true`, `triage-required`；实际 `impact_gap=false`, `changes-requested`, rework=1。
- **原始证据**：`allowed_symbol` 对 `different_symbol` 仍被当作 closure member。
- **根因**：`_closure_keys()` 与最终比较都只保留 `(repository_id,path)`，丢弃 symbol/location_label/resource/integration 身份。
- **用户影响/数据**：未规划范围被直接当作已知实现问题处理，绕过影响分析与合同修订；Dossier 的 finding lineage 错误。
- **可恢复性**：未终态时可人工 revise contract；终态历史需要新任务纠正。
- **现有测试漏因**：只用不同文件路径证明 gap，没有 pathless symbol/label cases。
- **最小修复**：统一 canonical typed locator；无法精确匹配的 affected finding 保守标记 gap。
- **回归测试**：symbol-only、location-label-only、resource、integration、相同 symbol 不同 repo、ambiguous null locator。
- **兼容性**：会改变 finding routing/Dossier 内容；无需持久化迁移，但 replay 旧记录时必须保留原规则或显式版本化。

### DFO-AUDIT-005 — 活跃 membership lease 未在后续操作复验

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：Store/Controller/Multi-repository。
- **位置**：`src/dev_flow_orchestrator/store.py:184-208`；`controller.py:449-495,654-878,880-900`。
- **不变量**：任何 repository-dependent projection/mutation 都必须证明每个成员仍由唯一 active task 租用。
- **前置条件**：旧 bug、恢复操作、复制 state 或并发异常形成两个结构有效的 active states，二者声明同 worktree。
- **最小复现/命令**：EXP-05。
- **预期/实际**：预期 `next()` fail closed；实际返回可执行 projection，只有 discovery 报 `LEASE_INTEGRITY_CONFLICT`。
- **原始证据**：projection 含 action/contract/repository_set/binding；同一 inventory 的 `tasks_for_path` 明确冲突。
- **根因**：`create_admitted()` 是唯一全 inventory lease scan；后续 capture/mutation 只加载当前 task members。
- **用户影响/数据**：两个 active task 可对同一 worktree 产生彼此不一致的证据、manifest、review 与最终结果。
- **可恢复性**：需人工识别并取消/隔离一个任务；如果都已推进，历史无法自动归并。
- **现有测试漏因**：覆盖并发 admission 与 discovery ambiguity，未覆盖预存合法冲突后的 next/apply/revise/cancel。
- **最小修复**：建立统一 active-membership assertion，在 membership lock 下包围所有 repository-dependent capture/commit，并规定与 task lock 的一致顺序。
- **回归测试**：对 next/apply/revise/decision/disposition/cancel 注入冲突；断言无 revision change、无死锁；覆盖 linked worktree/common dir。
- **兼容性**：旧冲突数据将变成 fail-closed，需要诊断/人工恢复命令；不应静默迁移。

### DFO-AUDIT-006 — candidate source 验证与实际激活之间存在 TOCTOU

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：installer/source authority。
- **位置**：`scripts/install.sh:132-141,177-191,402-409,614-685`；`scripts/install.ps1:214-250,289-400`。
- **不变量**：成功激活的 artifact 必须与已验证 clean authoritative commit 完全相同。
- **前置条件**：验证完成后，外部程序修改可写 checkout；实际注入点为 plugin add 后。
- **最小复现/命令**：EXP-02 `SOURCE_TOCTOU`。
- **预期/实际**：预期最终 identity recheck + rollback；实际 installer rc=0、plugin active，source dirty，CLI SyntaxError，receipt 仍记录原 HEAD。
- **原始证据**：`source_status=M scripts/dev_flow.py`, `cli_rc=1`, `plugin_active=true`, receipt commit 未变。
- **根因**：验证的是路径，不是不可变 wheel/snapshot；runtime build、health、最终 launcher 多次重新读取 checkout，结束前不复验 HEAD/status/digest。
- **用户影响/数据**：可激活损坏或被替换代码，source receipt 失真；升级信任边界失效。
- **可恢复性**：人工还原权威 checkout并重装；当前 installer 不能证明修复后的 authority。
- **现有测试漏因**：只破坏已生成 launcher，不在 build/plugin/health/final-launcher 边界改变 source。
- **最小修复**：从 verified commit 生成 immutable artifact 并全链路引用；最少也要在每个信任边界和成功前复验 exact tree/key file digests，失败统一 rollback。
- **回归测试**：在 runtime build、marketplace write、plugin add、health、CLI launcher 各点注入 drift。
- **兼容性**：安装 artifact/receipt 需增强；不改变 task model。

### DFO-AUDIT-007 — rollback 不是完整安装事务

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：install/upgrade/repair。
- **位置**：`scripts/install.sh:120-129,425-445,575-603,614-712`；`scripts/install.ps1:295-373`。
- **不变量**：任何 late failure 后，旧版本仍必须是完整、可验证的 active 安装；不能只恢复部分文件或重装 candidate。
- **前置条件**：已装 A，fast-forward source 到 B；candidate add 或最终 CLI launcher 阶段失败。
- **最小复现/命令**：EXP-02 `ROLLBACK_WRONG_SOURCE` 与 `LATE_FAILURE`。
- **预期/实际**：预期恢复 A；实际 re-add 当前 B 并声称 previous restored。另一故障在 health 后使 candidate plugin active，但 EXIT trap 删除 marketplace/launchers，无 plugin remove。
- **原始证据**：source HEAD after=B；calls `remove, add(fail), add(restore)`；late failure 只有 `plugin add`，plugin_active=true，三个安装资产不存在。
- **根因**：source 先 fast-forward且旧 artifact 未保存；rollback 仅保存 marketplace/MCP launcher；final CLI failure 走 `fail` 而非 activation rollback。Windows 更早修改资产再定义 rollback。
- **用户影响/数据**：混合版本、错误 runtime/launcher/plugin 组合，installer receipt 文案误导恢复决策。
- **可恢复性**：通常可人工移除混合态并安装已知 artifact；installer 自身不可靠。
- **现有测试漏因**：只比较 marker/marketplace/version stub，不断言 old source HEAD/真实 artifact，也无 final CLI failure。
- **最小修复**：保存 immutable previous release + activation identity；source update、runtime、两 launcher、marketplace、plugin activation 纳入一个 transaction；恢复后重新 health，只有通过才声称 restored。
- **回归测试**：每个 mutation 点 fail injection；A→B 后验证运行的确是 A；rollback 自身失败必须明确 partial state。
- **兼容性**：receipt/installer state格式可能扩展；task data不需迁移。

### DFO-AUDIT-008 — runtime receipt 不是运行时内容 attestation

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：managed runtime/MCP startup/repair。
- **位置**：`scripts/dev_flow_mcp_launcher:1-5`, `.cmd:1-4`；`src/dev_flow_orchestrator/mcp/runtime.py:63-119`；`scripts/manage_runtime.py:147-207,256-265`。
- **不变量**：launcher/startup/repair 必须证明执行的 wheel、metadata 与 exact locked dependencies 对应 receipt。
- **前置条件**：删除 receipt 后直接启动已建 runtime，或修改 site-packages 后执行同 commit/lock repair。
- **最小复现/命令**：EXP-03。
- **预期/实际**：预期启动失败、repair rebuild；实际无 receipt 完成完整 smoke，篡改文件被 `reused=true`。
- **原始证据**：11 tools/read/mutation/CANCELLED 全通过且 receipt absent；tamper marker surviving repair。
- **根因**：launcher 不读 receipt；startup 只验版本/常量/digest；reuse 只验 receipt 字段、Python executable hash和行为 smoke，不验 wheel RECORD/site-packages/dependency inventory。
- **用户影响/数据**：篡改、残缺或意外依赖漂移可继续执行；repair 给出虚假安全感。
- **可恢复性**：人工删除 owned runtime 后重建；现有 repair 不会察觉。
- **现有测试漏因**：identity drift 只 mock 常量/version；runtime tests 只 clean create/reuse。
- **最小修复**：receipt 绑定 wheel RECORD、distribution metadata、exact lock inventory；launcher 启动前验证 active receipt→runtime；repair mismatch staging rebuild。
- **回归测试**：missing/corrupt receipt、package byte/metadata、extra/missing dependency、wrong release symlink、tampered launcher。
- **兼容性**：runtime receipt schema需升级并为旧 receipt fail-closed/rebuild；不改 task model。

### DFO-AUDIT-009 — 安装自产 bytecode cache 使默认卸载失败

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：installer/manage_runtime/uninstaller。
- **位置**：`scripts/manage_runtime.py:19-27`；`scripts/install.sh:177-191,402-409`；`scripts/uninstall.sh:474-482`；`scripts/install.ps1:217-245,289`；`scripts/uninstall.ps1:243-245`。
- **不变量**：安装不得污染 verified source，fresh install→repair→default uninstall 必须闭合。
- **前置条件**：fresh mac install；source imports 未禁 bytecode。
- **最小复现/命令**：EXP-02 `FRESH_DEFAULT_UNINSTALL`。
- **预期/实际**：预期 source clean且默认卸载成功；实际生成三个 ignored `__pycache__`，uninstall rc=1，source/plugin 留存。
- **原始证据**：ignored paths 位于 package、`_platform`、`mcp`；tracked status仍空。
- **根因**：candidate/source Python invocation 未统一 `-B`/scoped `PYTHONDONTWRITEBYTECODE`；成功检查只看普通 porcelain。Windows只临时保护 package validator，随后 manage_runtime 仍可污染。
- **用户影响/数据**：最普通生命周期失败；Windows repair 也可能在下一次启动前拒绝 ignored source。
- **可恢复性**：用户逐项核验并删除 cache，或 keep-source；无任务数据损坏。
- **现有测试漏因**：只断言 `status --porcelain`，uninstaller fixture为合成 clean checkout，没有真实 install→default uninstall。
- **最小修复**：所有 source Python 调用统一 `-B`和 scoped env；build/activation后复查 tracked/untracked/ignored。
- **回归测试**：两平台 fresh install→repair→default uninstall，断言 `git status --ignored --porcelain` 为空。
- **兼容性**：无 schema 影响。

### DFO-AUDIT-010 — runtime root 浅验后整树删除未知文件

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：uninstaller runtime ownership。
- **位置**：`scripts/uninstall.sh:102-175,517-523`；`scripts/uninstall.ps1:134-174,260-263`。
- **不变量**：unknown/unattested entry 必须 fail closed，不得因根 marker/浅 receipt 合法而删除。
- **前置条件**：结构合法 managed runtime root 中存在 receipt 不涵盖的额外文件/目录。
- **最小复现/命令**：EXP-02 `RUNTIME_EXTRA_DELETE`；加入 `user-important-unvalidated.txt` 后 `--keep-source`。
- **预期/实际**：预期未知 entry 阻止删除；实际 rc=0，runtime root与 sentinel 都消失。
- **原始证据**：`runtime_exists=false`, `sentinel_exists=false`。
- **根因**：preflight只枚举 release dirs并浅验每个 receipt/Python；不枚举 root 额外条目或 release contents，最终 recursive delete root。
- **用户影响/数据**：误放或第三方创建的文件不可恢复；虽位于 managed root，仍不能视作安装器所有物。
- **可恢复性**：无备份不可恢复；runtime 本身可重建。
- **现有测试漏因**：只覆盖 marker/receipt mismatch，不覆盖 manifest外文件。
- **最小修复**：精确安装 manifest、逐项删除 known-owned 文件；任何额外 entry 都保留并报告。
- **回归测试**：root/release/venv 各层 extra file/dir/symlink/reparse；并发创建。
- **兼容性**：旧 runtime 需 conservative adoption或人工清理；无 task schema 影响。

### DFO-AUDIT-011 — Windows lifecycle tests 可能操作真实 managed runtime

- **分类**：`HIGH_RISK_DEFECT / HIGH / confidence HIGH`；模块：test harness/Windows lifecycle。
- **位置**：`tests/test_windows_lifecycle.py:88,124-173,186-245`；`scripts/install.ps1:12`；`scripts/uninstall.ps1:21`；`.github/workflows/focused.yml:42-43`。
- **不变量**：测试所有生产写路径必须位于可证明的 temp root。
- **前置条件**：native Windows 执行 suite，未预设 `DEV_FLOW_RUNTIME_HOME`；开发机已有或可创建默认 LocalAppData runtime。
- **最小复现/命令**：未执行，因为没有 Windows host且不能冒险。静态追踪显示 fixture 设置 source/marketplace/CODEX_HOME/PATH，却未设置 runtime/LOCALAPPDATA；生产脚本默认真实 `%LOCALAPPDATA%`。
- **预期/实际**：预期 runtime temp 隔离；实际路径解析将落到真实用户 runtime。
- **原始证据**：suite 会执行 fresh install、repair、default uninstall；后者递归删除 `$RuntimeRoot`。
- **根因**：fixture 隔离清单漏掉新的 managed runtime authority；macOS 上整个 class skip，风险不可见。
- **用户影响/数据**：Windows CI runner或开发机现有 runtime 可能被替换/删除；属于高风险而非 confirmed，因为未在 native host 动态验证。
- **可恢复性**：runtime通常可重装；在 DFO-AUDIT-010 下混入的未知文件可能不可恢复。
- **现有测试漏因**：风险就在被 skip 的测试 fixture；host-neutral static tests 不解析实际默认路径。
- **最小修复**：fixture强制 temp `DEV_FLOW_RUNTIME_HOME`, `LOCALAPPDATA`, `USERPROFILE`，并断言每个 mutation target 在 temp 下；加外部 sentinel。
- **回归测试**：Windows suite 前后验证真实默认 runtime sentinel byte-identical。
- **兼容性**：仅测试设施。

### DFO-AUDIT-012 — deeply nested JSON 终止 MCP STDIO server

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：MCP framing/runtime。
- **位置**：`src/dev_flow_orchestrator/mcp/server.py:25-75`；`mcp/runtime.py:122-152`。
- **不变量**：每个非法消息应被隔离为 protocol error；一个低于 2 MiB 的请求不得终止 server 或丢弃随后请求。
- **前置条件**：发送约 100,000 层 JSON array，再发送合法 initialize。
- **最小复现/命令**：EXP-07。
- **预期/实际**：预期 `_INVALID_JSON_LINE` 交给 SDK处理并继续；实际 `RecursionError` 穿透 async iterator，outer runtime rc=2、无响应。
- **原始证据**：stdout_lines=0；stderr只有 `INTERNAL_ERROR/startup_failed`；100k层 decoder stack overflow。
- **根因**：`_checked()`只捕获 `UnicodeError, ValueError`，没有捕获 JSON decoder 的 `RecursionError`。
- **用户影响/数据**：本地 MCP peer 可稳定使进程退出、丢弃有效请求；未观察 task state corruption。
- **可恢复性**：host 重启 MCP；在途响应丢失时 mutation completion需重新读取 authority。
- **现有测试漏因**：raw tests只覆盖 duplicate keys/invalid UTF-8，二者都落入已捕获异常。
- **最小修复**：明确捕获 `RecursionError`及限定 decoder failures，转为 invalid sentinel；避免吞掉真正系统异常。
- **回归测试**：deep line + valid initialize，断言进程存活并响应第二条；边界在 2 MiB 上下。
- **兼容性**：仅错误处理语义。

### DFO-AUDIT-013 — current-action schema 接受无 authority 的嵌套对象

- **分类**：`CONFIRMED_DEFECT / HIGH / confidence HIGH`；模块：MCP output schema。
- **位置**：`src/dev_flow_orchestrator/mcp/schemas.py:128-176,353-373`；`mcp/server.py:78-102`。
- **不变量**：对外 schema gate 必须要求 task identity、repository set、action ID/payload contract/exact binding 或明确 terminal alternative。
- **前置条件**：producer回归输出正确 top-level keys/digest，但嵌套对象为空。
- **最小复现/命令**：EXP-09。
- **预期/实际**：预期 schema violation；实际 validator通过，无 binding。
- **原始证据**：`validated=true`, empty task/action, `has_binding=false`。
- **根因**：`OBJECT={type:object}` 被用于所有 authoritative nested fields；mutation `current` 同样不受约束。
- **用户影响/数据**：未来 adapter回归可把不可执行/错误 authority 标为成功，客户端无法安全提交 exact mutation；这是关键验证绕过。
- **可恢复性**：客户端只能重新读取；若据此自行构造 mutation会被 Controller拒绝，但工作流会卡住/误导。
- **现有测试漏因**：只删除 top-level server-info fields；happy output断言实现生成内容，不对 schema做 nested mutation testing。
- **最小修复**：定义 closed nested task/repository/action/guidance schemas与 active/terminal exclusivity；只对真正 domain-owned payload保留必要 openness。
- **回归测试**：missing binding/task ID/action ID、empty object、active+terminal并存、unknown nested keys、mutation `current`。
- **兼容性**：收紧 MCP output schema与catalog digest；需要 interface/version策略评估。

### DFO-AUDIT-014 — MCP cancellation 未传给 GitClient

- **分类**：`CONFIRMED_DEFECT / MEDIUM / confidence HIGH`；模块：MCP cancellation/Git subprocess。
- **位置**：`src/dev_flow_orchestrator/mcp/application.py:153-225,466-469`；`controller.py:449-495,610-624,654-656`；`git_client.py:42-49,69-98`；`web.py:403-415`。
- **不变量**：request取消或断开应及时终止实时 Git capture，释放 coordinator slot；MCP/Web 对同一 Controller应有一致取消边界。
- **前置条件**：MCP tool 正在长 Git capture 时 peer取消/EOF。
- **最小复现/命令**：EXP-08；wrap Git calls记录 context cancel event。
- **预期/实际**：预期非空 event并在 subprocess poll中观察；实际126次调用均为 `None`。MCP仅dispatch前后检查；Web显式使用 `GitClient.cancellation(cancel_event)`。
- **原始证据**：`cancel_event_values=[None]`。
- **根因**：AnyIO cancellation check 是函数，不是 `threading.Event`；MCP未建立到现有 contextvar cancellation bridge。
- **用户影响/数据**：断开后工作线程和最多4个slot可占用至30秒命令/完整capture结束；mutation会在capture后检查而通常不提交，但响应及时性与资源边界失真。
- **可恢复性**：等待timeout或重启进程。
- **现有测试漏因**：mock在dispatch前取消或 `_snapshot()` 完成后翻转；没有真正阻塞Git/in-flight EOF。
- **最小修复**：把 AnyIO取消转换成 event-like signal，所有 MCP live/mutation scopes进入 `GitClient.cancellation`；保持commit前checkpoint。
- **回归测试**：阻塞 Git + protocol cancellation和stdin close；断言prompt kill、revision unchanged、slot释放、restart成功。
- **兼容性**：改变取消时序/错误码，不改持久化模型。

### DFO-AUDIT-015 — POSIX `DEV_FLOW_PYTHON` troubleshooting 契约无效

- **分类**：`CONFIRMED_DEFECT / MEDIUM / confidence HIGH`；模块：POSIX install/uninstall/docs。
- **位置**：`INSTALL.md:207-212`；`scripts/install.sh:148-157`；`scripts/uninstall.sh:77-83`；对照 `scripts/install.ps1:37-52`。
- **不变量**：公开恢复命令必须被实现；显式 interpreter override 应优先于 PATH 候选。
- **前置条件**：PATH 首个 `python3` 不受支持/失败，`DEV_FLOW_PYTHON` 指向合法 CPython。
- **最小复现/命令**：EXP-02 `PYTHON_OVERRIDE`；临时 PATH 中 `python3` exit39，override 指向项目 Python。
- **预期/实际**：预期使用 override；实际 installer rc=1，source 未创建。
- **原始证据**：stderr `64-bit Python 3.10-3.14 is required`。
- **根因**：shell scripts从不读取该变量，只选第一个可发现命令；选中后失败也不继续 fallback。
- **用户影响/数据**：合法用户无法按文档自助恢复；卸载也可能被坏 python3 阻断。
- **可恢复性**：临时改 PATH/重命名命令可绕过；无数据损坏。
- **现有测试漏因**：已有用例把坏 python3 预期固化为失败，没有 override优先/fallback case。
- **最小修复**：显式 override优先，校验 regular executable；否则逐候选验证而非只选名字；install/uninstall共享逻辑。
- **回归测试**：合法/坏 override、python3坏但python好、路径含空格/Unicode/单引号。
- **兼容性**：只改善 documented environment behavior。

### DFO-AUDIT-016 — Windows 安装缺失 `dev-flow` CLI/Web launcher

- **分类**：`CONFIRMED_DEFECT / MEDIUM / confidence HIGH`；模块：Windows product/install。
- **位置**：`pyproject.toml:9-10`；`scripts/install.ps1:165-170,295-314,402-412`；`README.md:110-121`；active Windows spec `:126-132`；`tests/test_windows_product_support.py:52-71`。
- **不变量**：支持的 Windows preview 应提供与公开文档一致的 CLI与read-only Web入口。
- **前置条件**：fresh Windows install。
- **最小复现/命令**：静态穷尽 `install.ps1` 与 project entry points：只生成 `dev-flow-mcp.cmd`，没有 `dev-flow.cmd` 或 CLI console entry；因无 Windows host未执行命令。
- **预期/实际**：预期 `dev-flow --help` / `dev-flow web start`；实际 installer receipt只报告 MCP command。
- **原始证据**：PowerShell全文件无 `dev-flow.cmd`；host-neutral test还明确断言旧 Python CLI launcher不在 installer。
- **根因**：MCP runtime迁移只为 Windows实现 MCP launcher，公共 CLI/Web 声明未同步或漏实现。
- **用户影响/数据**：Windows用户无法按 README 运行同产品面；不损坏数据。
- **可恢复性**：手工从 source调用可临时绕过，但不属于受支持安装。
- **现有测试漏因**：只静态检查 MCP launcher；native lifecycle不调用CLI/Web且在macOS skip。
- **最小修复**：在managed runtime提供真正 CLI entry point/owned `dev-flow.cmd`，纳入install/rollback/uninstall；或收窄公开Windows能力并同步中英文/spec。
- **回归测试**：native PATH执行 help、web bind/start/status/stop，验证data root与卸载ownership。
- **兼容性**：新增Windows executable surface；无模型迁移。

### DFO-AUDIT-017 — canonical tests 继承真实数据 root override

- **分类**：`CONFIRMED_DEFECT / MEDIUM / confidence HIGH`；模块：CLI/installer test isolation。
- **位置**：`tests/test_cli.py:62-85`；`tests/test_install_script.py:189-235,418-440`；`src/dev_flow_orchestrator/runtime_paths.py:19-46`。
- **不变量**：临时 `CODEX_HOME` 测试不能被 inherited higher-priority data env 覆盖，更不能观察用户状态。
- **前置条件**：运行测试的 shell 已设置 `DEV_FLOW_DATA_DIR`（或 `PLUGIN_DATA`）并指向有 running Web state 的目录。
- **最小复现/命令**：完整 discovery；也可在完全临时 data root 启动测试 Web后设置 `DEV_FLOW_DATA_DIR`再运行上述两个用例。
- **预期/实际**：预期解析 temp CODEX_HOME且 status stopped；实际优先使用 inherited override并返回 running。
- **原始证据**：两次415-test discovery都在同两用例失败；解析优先级明确为 explicit→data override→plugin→Codex home。
- **根因**：fixtures从 `os.environ` 全量复制，只移除少数Git/color变量，没有移除 `DEV_FLOW_DATA_DIR`/`PLUGIN_DATA`。
- **用户影响/数据**：suite非hermetic，可读取环境中现有pid/status，并产生误报；本次失败调用为read-only，未修改用户task data。
- **可恢复性**：清理测试env后可运行；不应把清环境当成产品修复。
- **现有测试漏因**：它就是基线测试缺陷；CI通常未设置该变量而形成假阳性。
- **最小修复**：fixture从最小 allowlist构造环境，显式删除所有Dev Flow data authorities，并断言解析目标在temp下。
- **回归测试**：父进程注入每个优先级变量和sentinel，验证子进程绝不越界。
- **兼容性**：仅测试设施。

### DFO-AUDIT-018 — public-doc semantic validator 是 dead code

- **分类**：`CONFIRMED_DEFECT / MEDIUM / confidence HIGH`；模块：package validation/docs gate。
- **位置**：`scripts/validate_package.py:2110-2194,2196+`, `2616-2666`；`tests/test_package.py:149-197`。
- **不变量**：release validator 必须验证产品声明与能力/模型/workflow/中英文语义一致，而非只搜 token。
- **前置条件**：文档仍保留要求 token，但改变其语义或遗漏真实可执行能力。
- **最小复现/命令**：`uv run python -B -I -S scripts/validate_package.py`。
- **预期/实际**：预期 Windows CLI gap、effective spec矛盾/standalone不可执行至少一项使gate失败；实际 `ok=true, errors=[]`。
- **原始证据**：`_validate_public_docs`在token循环后无条件return；其后数百行语义检查不可达。Windows validator同样只做token presence。
- **根因**：迁移时遗留提前返回，测试只 mutation return之前的tokens。
- **用户影响/数据**：错误package/docs可获得release PASS，Validation Report可信度下降；无直接数据损坏。
- **可恢复性**：修复validator后重新生成证据。
- **现有测试漏因**：只删除/替换token，不保留token而改变语义。
- **最小修复**：移除return并修正后续逻辑；对command inventory、effective spec和EN/CN关键声明做结构化比较。
- **回归测试**：语义mutation tests：保留所有token但删launcher、反转Hook声明、提供不存在命令、EN/CN版本分叉。
- **兼容性**：release gate会更严格；无runtime/model影响。

### DFO-AUDIT-019 — Windows lifecycle 断言已删除 Hook 文案

- **分类**：`TEST_GAP / MEDIUM / confidence HIGH`；模块：native Windows evidence。
- **位置**：`tests/test_windows_lifecycle.py:186-195`；`scripts/install.ps1:402-412`；`openspec/changes/dev-flow-orchestrator-mcp/tasks.md:255-258`。
- **不变量**：native lifecycle suite 必须断言当前 MCP-first产品边界并可在支持host通过。
- **前置条件**：在 native Windows 运行 `test_fresh_install_and_repair...`。
- **最小复现/命令**：未执行；静态比较测试要求 `HOOK REVIEW`/`does not establish Hook trust`，当前receipt不输出这些字符串，active tasks明确要求移除。
- **预期/实际**：预期断言 MCP health/approval residual risk；实际断言陈旧产品。
- **原始证据**：macOS上class整体skip；focused workflow会在Windows执行它。
- **根因**：product migration更新脚本但未同步native test expectation。
- **用户影响/数据**：Windows release evidence会红或促使错误恢复Hook文案；本项本身不证明product runtime bug。
- **可恢复性**：更新测试后重跑native matrix。
- **现有测试漏因**：目标平台被skip，host-neutral tests不执行receipt assertions。
- **最小修复**：改为当前 MCP catalog/health/command/approval boundary断言。
- **回归测试**：package gate交叉检查测试token与active/current spec。
- **兼容性**：仅测试/证据。

### DFO-AUDIT-020 — base OpenSpec 与当前 Hook/Skills 边界相反

- **分类**：`DOC_MISMATCH / MEDIUM / confidence HIGH`；模块：OpenSpec governance。
- **位置**：`openspec/specs/native-windows-product-support/spec.md:6-10,27-31,48-52,69-73,85-89`；`openspec/specs/package-delivery-validation/spec.md:332-380`；`ARCHITECTURE.md:140-145`；active delta `native-windows-product-support/spec.md:7-45`；tasks `:355-356`。
- **不变量**：current base specs 应代表当前产品真相；active delta未归档时必须明确effective view。
- **前置条件**：审计/agent/package tool只读取base current specs。
- **最小复现/命令**：静态对照；`openspec validate dev-flow-orchestrator-mcp --strict`仅证明delta结构，不能修正base语义。
- **预期/实际**：预期base与0.5实现一致；实际base仍要求 command Hook、PreToolUse guard、Hook trust、Skills，而code/public docs明确不存在。
- **原始证据**：active change 133/137 tasks，16.10未完成，尚未archive。
- **根因**：大型change已改产品实现/文档，但base更新被延迟到未完成archive gate。
- **用户影响/数据**：后续agent、review和回归标准会得出相反安全结论；无数据损坏。
- **可恢复性**：发布/归档时原子更新base；此前提供明确effective-spec索引。
- **现有测试漏因**：strict validate不比较base与active delta/public package。
- **最小修复**：完成外部gates后archive并更新base；短期标注 superseded boundaries，validator计算effective spec。
- **回归测试**：base+active delta→effective truth，与manifest/docs/runtime asset inventory比对。
- **兼容性**：规格治理，无persisted model变化。

### DFO-AUDIT-021 — standalone provision 流程在产品中不存在

- **分类**：`DOC_MISMATCH / MEDIUM / confidence HIGH`；模块：INSTALL/packaging/registration。
- **位置**：`INSTALL.md:116-130`；`scripts/install.sh:397-400,614-618`；`scripts/install.ps1:269-286,365-373`；active `mcp-plugin-packaging/spec.md:102-114`。
- **不变量**：文档化支持模式必须有完整 create/health/upgrade/uninstall path。
- **前置条件**：操作者选择 standalone，要求先安装runtime/launcher但不启用bundled plugin。
- **最小复现/命令**：静态穷尽脚本参数与分支；两installer都无 `--standalone`/no-activate，且总是 plugin add；已有standalone反而在build前被拒绝。
- **预期/实际**：预期先provision owned launcher再 `codex mcp add`；实际没有支持命令可完成第一步。
- **原始证据**：uninstaller又拒绝指向owned launcher的standalone并准备删除同launcher/runtime。
- **根因**：spec/docs定义了模式，但lifecycle实现只含bundled路径。
- **用户影响/数据**：用户无法按文档建立或安全维护standalone；可能手工拼接出无法升级/卸载状态。
- **可恢复性**：手工清理；没有产品级transaction。
- **现有测试漏因**：只测试冲突检测，没有 provision→register→validate→upgrade→uninstall journey。
- **最小修复**：增加显式standalone mode，复用同runtime/launcher而不改marketplace/plugin；模式切换transactional。若不实现则删除支持声明。
- **回归测试**：完整standalone生命周期及 bundled↔standalone冲突/切换。
- **兼容性**：registration/installer interface改变；无task schema影响。

### DFO-AUDIT-022 — Validation Report 的“current”证据已陈旧

- **分类**：`DOC_MISMATCH / MEDIUM / confidence HIGH`；模块：release evidence。
- **位置**：`openspec/changes/dev-flow-orchestrator-mcp/VALIDATION_REPORT.md:37-67,69-96,118-133`。
- **不变量**：current evidence 必须绑定 exact HEAD/tree/environment，并区分 keep-source 与默认 source-removal。
- **前置条件**：审计者按报告判断当前 HEAD。
- **最小复现/命令**：当前完整 discovery 得 415 tests、2 failures；报告固定为413 OK。EXP-02 fresh default uninstall失败，而报告real lifecycle只执行 `--keep-source`。
- **预期/实际**：预期报告明确stale/适用范围；实际把旧计数与局部lifecycle标为current。
- **原始证据**：报告自身仍承认22 platform skips和4个外部gates未完成。
- **根因**：证据没有不可变 commit/tree绑定，后续HEAD变化和新缺陷没有superseding标记。
- **用户影响/数据**：release决策误判；无直接数据损坏。
- **可恢复性**：保留历史报告但新增绑定当前HEAD的superseding报告，作废受影响claims。
- **现有测试漏因**：package validator只找报告token/count，不重新执行或比对HEAD/能力矩阵。
- **最小修复**：每次报告记录commit/tree、命令、env boundary、platform、keep/default mode和known defects。
- **回归测试**：validator拒绝报告HEAD/count与当前run manifest不一致。
- **兼容性**：证据格式/流程，无runtime影响。

### DFO-AUDIT-023 — 外层 MCP schema guard 丢失 completion-uncertain 语义

- **分类**：`HIGH_RISK_DEFECT / MEDIUM / confidence MEDIUM`；模块：MCP server/result recovery。
- **位置**：`src/dev_flow_orchestrator/mcp/server.py:86-102`；`mcp/results.py:205-234,263-272`；`mcp/application.py:293-339`。
- **不变量**：任何可能发生在 mutation commit 后的响应构造失败都必须返回 `MCP_COMPLETION_UNCERTAIN`、原request关联和read-after-write recovery。
- **前置条件**：SDK post-processing、result mutation或未来handler旁路使 application已提交后，outer `validate_structured_result` 才失败。
- **最小复现/命令**：可mock `super().call_tool()` 返回“已发生模拟commit”的invalid `CallToolResult`，调用 `DevFlowMCPServer.call_tool`；当前outer分支确定返回新request ID的 `INTERNAL_ERROR`。未证明ordinary producer自然可达，因为内层 `_call_result()`当前先验证并正确映射uncertain。
- **预期/实际**：预期 conservative uncertain；实际 `inspect-diagnostics` recovery，无task/read tool，且换request ID。
- **原始证据**：代码分支不检查tool是否mutation，也拿不到application原request ID。
- **根因**：最终guard位于丢失commit context的adapter层。
- **用户影响/数据**：未来SDK/adapter回归下客户端无法区分未提交和已提交；可能错误恢复。当前普通路径受内层guard保护，故不标confirmed。
- **可恢复性**：用户若主动读task可恢复判断；返回值没有指导这一点。
- **现有测试漏因**：只测试application内层output violation，不模拟outer post-processing。
- **最小修复**：最终验证留在持有 `entered_mutation/task_id/request_id` 的层；或outer对mutation tool一律conservative uncertain并保留关联。
- **回归测试**：mock outer invalid result after simulated commit，断言read-after-write、exact tool/task、blind_retry=false。
- **兼容性**：只改变罕见错误envelope。

### DFO-AUDIT-024 — tool catalog digest 未封装完整接口身份

- **分类**：`MAINTAINABILITY_RISK / LOW / confidence HIGH`；模块：MCP identity。
- **位置**：`src/dev_flow_orchestrator/mcp/catalog.py:11-27`；`mcp/runtime.py:100-119`；`mcp/tools.py:27-125`。
- **不变量**：catalog identity 应随客户端可观察input schema、描述、annotations与output schema的兼容性变化而改变。
- **前置条件**：更改参数约束、工具描述或side-effect annotations但保持名称/output schema。
- **最小复现/命令**：静态公式 `digest({names, output_schemas})`；上述输入不参与hash，因此变化后digest必然相同。
- **预期/实际**：预期接口漂移改变 identity；实际保持不变。
- **原始证据**：runtime self-check重算同一不完整公式，因此无法发现这种漂移。
- **根因**：catalog digest建立时只纳入工具名与outputs。
- **用户影响/数据**：缓存/审计/host可能把破坏性input或annotation变化误认为同一接口；当前未见已发生的不兼容漂移。
- **可恢复性**：更新digest/重新发现catalog。
- **现有测试漏因**：package tests锁定现有digest公式而非完整observable catalog。
- **最小修复**：对规范化 tools/list projection（inputSchema、outputSchema、description、annotations、execution/meta）整体hash。
- **回归测试**：逐一改变每个observable字段，digest必须改变；顺序变化不应改变。
- **兼容性**：catalog digest会变化；可能需要interface version说明。

## 8. 测试体系的假阳性、盲区与 skip 清单

### 8.1 精确 skip 统计

完整 discovery 的 22 skips 全部来自 Windows 条件：6个native runtime/snapshot，16个native PowerShell lifecycle。

| Test | 原因 | 未验证的声明 |
| -- | -- | -- |
| `test_canonical_repository_root_preserves_host_spelling` | requires native Windows paths | drive/case/path spelling |
| `test_windows_runner_closes_pipes_after_timeout` | requires Windows pipe handles | timeout pipe cleanup |
| `test_windows_runner_timeout_terminates_live_parent_and_descendant` | requires Windows taskkill | descendant termination |
| `test_windows_snapshot_covers_common_worktree_states` | native Windows snapshot coverage | Windows snapshot states |
| `test_windows_snapshot_ignores_only_text_eol_conversion` | native Windows EOL coverage | CRLF/EOL normalization |
| `test_windows_two_repository_order_and_admission_atomicity` | native Windows repository-set coverage | multi-repo Windows atomicity |
| `test_activation_failure_is_nonzero_with_recovery_command` | native Windows PowerShell | activation rollback |
| `test_detached_source_is_rejected` | native Windows PowerShell | detached refusal |
| `test_dirty_source_is_rejected_without_activation` | native Windows PowerShell | dirty refusal |
| `test_fast_forward_install_and_default_uninstall_preserve_task_data` | native Windows PowerShell | FF + default uninstall |
| `test_fresh_install_and_repair_preserve_one_marketplace_entry` | native Windows PowerShell | fresh/repair; currently stale assertion |
| `test_ignored_predecessor_cache_failure_has_recovery_commands` | native Windows PowerShell | ignored cache recovery |
| `test_incoming_main_does_not_overwrite_ignored_path` | native Windows PowerShell | ignored collision |
| `test_keep_source_uninstall_preserves_checkout_and_task_data` | native Windows PowerShell | keep-source |
| `test_local_ahead_and_diverged_histories_are_rejected` | native Windows PowerShell | history refusal |
| `test_malformed_marketplace_preserves_original_bytes` | native Windows PowerShell | marketplace corruption |
| `test_non_main_source_is_rejected` | native Windows PowerShell | branch authority |
| `test_older_version_is_upgraded` | native Windows PowerShell | upgrade |
| `test_unexpected_origin_is_rejected` | native Windows PowerShell | origin authority |
| `test_uninstaller_refuses_ignored_source` | native Windows PowerShell | source preservation |
| `test_uninstaller_refuses_local_only_commit` | native Windows PowerShell | local commit preservation |
| `test_unrelated_marketplace_entries_are_preserved` | native Windows PowerShell | unrelated entries |

### 8.2 假阳性模式

- Installer tests只看普通 `git status --porcelain`，未看ignored；安装自产cache因此躲过成功断言。
- rollback test只看marker/marketplace/version stub，不验证旧source HEAD和真正执行artifact。
- runtime reuse只比较receipt字段、Python executable与smoke，producer与test共享同一浅identity模型。
- current-action schema tests验证正常producer对象和top-level字段，没有用独立negative model验证exact binding。
- MCP cancellation tests在dispatch前或snapshot返回后翻转boolean，没有真正取消活跃Git子进程。
- raw STDIO tests覆盖decoder已捕获的异常，没有resource/nesting输入。
- package docs tests只mutation必需token，且语义逻辑位于不可达return后。
- platform static asset tests只证明字符串存在，不能证明PowerShell、reparse、cmd quoting或真实PATH行为。
- installed real launcher journey在macOS有覆盖，但默认uninstall证据只用 `--keep-source`，不能外推source-removal。

## 9. 文档与实现不一致

主要不一致已经分别记录为 DFO-AUDIT-015、016、020、021、022：POSIX Python override、Windows CLI/Web、base Hook/Skills、standalone lifecycle、Validation Report。中英文公共文档的标题、版本号、主要命令与语言切换链接在本次静态对照中未发现另一个可独立行动的分叉；但 DFO-AUDIT-018 意味着自动validator不能为此提供语义保证。

## 10. 尚未验证的高风险区域

- native Windows 10 22H2 x64 / Windows 11 x64：PowerShell 5.1/7、cmd quoting、reparse points、case/drive alias、pipe/taskkill、real PATH collision。
- 真实 Codex plugin/marketplace activation与CLI JSON格式漂移；本次严格使用伪Codex，避免触碰真实profile。
- 权限翻转、磁盘满、fsync/rename失败、进程在任意写指令处SIGKILL/power-loss、lock文件ACL异常。
- 真实客户端在活跃Git capture期间发送MCP cancellation或关闭stdin，以及高并发wire-level stress。
- Unicode、单引号、超长路径、多同名PATH launcher的完整lifecycle组合；空格路径已在临时fixture验证。
- Store非法UTF-8、partial inventory与坏task隔离虽有部分测试，但没有完整corruption×list/find/get×restart矩阵。
- 8-member repository set在capture后单成员被删除的专门race；DFO-AUDIT-001已证明同类无锁窗口。
- Python 3.10/3.11与非当前3.14解释器矩阵；既有Validation Report的旧结果未作为当前证据复用。

## 11. 修复优先顺序

| 顺序 | Findings | 理由 |
| -- | -- | -- |
| 0 | 001, 002 | 错误 `DONE` 与不可恢复用户代码删除；在继续发布/默认卸载前必须封堵 |
| 1 | 006, 007, 008, 009, 010 | 安装authority、transaction、runtime attestation和精确ownership必须作为一套修复，避免局部补丁继续混合态 |
| 2 | 003, 004, 005 | 修正manifest、review scope与持续lease，恢复状态机证据完整性 |
| 3 | 012, 013, 014, 023 | 收紧MCP进程、schema、取消和completion语义 |
| 4 | 011, 016, 019 | 先修安全fixture，再在native Windows完成真实能力证据；不能在当前fixture上直接跑破坏性suite |
| 5 | 015, 017, 018, 020, 021, 022, 024 | 恢复troubleshooting、测试hermeticity、effective specs和release evidence的可信度 |

## 12. 推荐分阶段修复计划

1. **立即安全门禁**：默认卸载临时改为`--keep-source`等价的fail-safe；finalize在commit边界重新证明snapshot；暂停把旧Validation Report当current release evidence。
2. **状态与证据闭合**：设计可验证capture→commit protocol；clean HEAD transition明确禁止或纳入tree delta；持续lease检查；typed impact locator。
3. **artifact事务化**：immutable candidate/previous release、content-attested receipt、统一rollback、exact ownership manifest、所有source Python禁bytecode。
4. **MCP hardening**：deep JSON隔离、closed nested schemas、Git cancellation bridge、outer uncertain guard、完整catalog digest。
5. **测试可信度**：最小环境allowlist；安全隔离Windows runtime；增加每个failure injection与restart/assert-final-state；修正Hook stale test。
6. **平台与文档收口**：在安全fixture上运行native Windows client matrix；实现或撤回Windows CLI/Web与standalone声明；归档active delta并同步base/EN/CN；生成绑定exact HEAD的superseding Validation Report。

## 13. 审计限制与不确定性

- 本报告针对指定HEAD；工作区额外存在一个非HEAD、无文件的空OpenSpec目录，未计入commit缺陷，也未删除。
- 本次不接触真实Codex profile、marketplace、task data或生产服务，因此不能声称真实Codex内部activation行为已验证。
- macOS fault harness使用伪Codex，但发现均依赖生产脚本可观察的调用顺序、文件状态和退出码，不依赖伪造Codex内部语义。
- CRITICAL/HIGH confirmed finding均有动态复现或穷尽代码路径；Windows-only项因平台限制明确标为HIGH_RISK/NOT_TESTED。
- 完整suite失败被原样保留，没有清理环境、放宽断言或修改测试来制造PASS。
- 审计没有修改产品源码、测试、workflow、installer、spec或remote；只生成用户授权的本报告与机器可读findings。

