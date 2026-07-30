## MODIFIED Requirements

### Requirement: Capability-aware Git evidence profile
在检查 Git `status`、diff、tracked file 或 worktree 之前，V4 controller
SHALL（必须）确定并记录会影响 `core.fileMode`、`core.symlinks` 和
`core.ignoreCase` 的有效 macOS filesystem capability 与 Git capability。
evidence command MUST（必须）遵守已验证的 host capability。生成的 evidence
或 fingerprint MUST（必须）绑定该 capability profile；capability result
不可用或相互矛盾时，MUST（必须）阻止 complete-evidence claim。

#### Scenario: 检查受支持的 macOS 检出
- **WHEN** Git 和 filesystem 报告其有效的 mode、symlink 及 case capability
- **THEN** unchanged checkout 保持 clean，且 evidence 精确记录实际观察到的 semantic

#### Scenario: 遇到相互矛盾的 capability evidence
- **WHEN** Git configuration 声称具备某项 capability，但 deterministic filesystem probe 否定了该声明
- **THEN** controller 返回结构化 capability blocker，且不认证该 repository snapshot

### Requirement: Evidence contracts are versioned and downgrade-safe
每个 capability-aware fingerprint、baseline、workspace proof、test record 和
review snapshot 都 SHALL（必须）绑定显式的当前 evidence contract version 及
capability-profile digest。V4 runtime SHALL（必须）只使用其精确当前 workflow
bundle 声明的 evidence contract。当 controller 遇到当前 package 声明、但自身尚未
实现的更新 evidence contract 时，MUST（必须）返回结构化 blocker，且不执行任何
state 或 Git mutation。implementation SHALL（必须）不包含 schema-v1 evidence
regeneration 或 rollback behavior。

#### Scenario: 接受当前 V4 evidence
- **WHEN** schema-v4 task 提交使用其精确 workflow bundle 所声明 contract 及 capability-profile digest 的 evidence
- **THEN** controller 通过当前 V4 gate 评估该 evidence

#### Scenario: 拒绝不受支持的当前契约
- **WHEN** 精确当前 package 声明了运行中 controller 无法提供的 evidence contract
- **THEN** 启动或受影响的 V4 操作在任何变更前返回 `EVIDENCE_CONTRACT_UNSUPPORTED`

### Requirement: Line-ending settings remain evidenced, not normalized
Git `status` 和 cleanliness check SHALL（必须）使用 repository 在 macOS 上经验证的
有效 line-ending behavior。tracked worktree manifest MUST（必须）哈希磁盘上的精确
byte，同时由 tree 和 index object ID 绑定 repository content。evidence comparison
MUST NOT（不得）重写文件或隐藏 byte change，以制造合成的 platform-neutral result。

#### Scenario: 检查干净的检出
- **WHEN** Git 在其 effective line-ending setting 下报告 checkout clean
- **THEN** controller 记录 clean `status`、哈希 worktree 的精确 byte，并绑定相关 Git object 和 capability profile

#### Scenario: 仅行尾字节发生变化
- **WHEN** worktree byte 相对先前 evidence 中的 line ending 发生变化
- **THEN** 即使面向文本的 diff 会规范化 content，tracked manifest 仍发生变化

### Requirement: Canonical worktree ownership identity
workspace plan、durable claim、materialization check 和后续 integrity check
SHALL（必须）使用 canonical macOS filesystem identity 比较 repository 与 worktree。
当 filesystem 证明大小写、Unicode normalization form 或 symlink spelling
互为 alias 时，它们 MUST（必须）映射到同一 claim。workspace MUST（必须）
独立于所有 source tree 和 analysis tree；在执行 `git worktree add` 前，
含糊或重叠的 identity MUST（必须）被拒绝。

#### Scenario: 拒绝别名目标位置
- **WHEN** proposed destination 通过不同大小写、Unicode normalization form 或 symlink spelling 到达 source worktree 或 analysis worktree
- **THEN** workspace preparation 在任何 Git mutation 前拒绝该 plan

#### Scenario: 拒绝重复的持久声明
- **WHEN** 两个 task 提出的 path 解析到同一 filesystem identity
- **THEN** workspace registry 最多允许一个 live claim，失败方收到结构化 ownership conflict

#### Scenario: 保留大小写敏感文件系统上的不同目标
- **WHEN** 两个 path 仅大小写不同，且 host 证明它们是不同 object
- **THEN** identity check 保持二者不同，同时继续强制 source tree、analysis tree 和 workspace 互不重叠

### Requirement: Portable repository path selectors
每个语法上类似路径的 selector 都 SHALL（必须）按 macOS/POSIX path 规范化，并同时
与记录的 source identity 和 canonical repository identity 比较。匹配零个或多个
repository 的 selector MUST（必须）确定性失败，且 MUST NOT（不得）fallback
到按 basename 猜测。

#### Scenario: 通过等价路径选择仓库
- **WHEN** caller 为一个已配置 repository 提供相对、绝对、大小写等价、Unicode 等价或 symlink 等价的 spelling
- **THEN** selector 通过 canonical filesystem identity 将其精确解析一次

#### Scenario: 拒绝含糊的 basename
- **WHEN** 非路径 selector 匹配到多个已配置 repository 的 basename
- **THEN** controller 返回 `AMBIGUOUS_REPOSITORY`，且不执行 repository operation
