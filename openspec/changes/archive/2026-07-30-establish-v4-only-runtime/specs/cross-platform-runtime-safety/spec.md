## MODIFIED Requirements

### Requirement: Portable task identifiers
V4 controller SHALL（必须）只接受满足以下条件的新 task identifier：长度为 1–64 个 ASCII 字节、
匹配 `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`、不包含 separator 或 path traversal form，
并且在当前 macOS data root 中映射到唯一且无歧义的 directory。controller
MUST（必须）拒绝 control character，以及 filesystem identity 与其他 task 冲突的
identifier。这是 native V4 identifier contract，不包含任何 historical task-name
admission behavior。

#### Scenario: 创建 V4 task
- **WHEN** caller 提供 valid identifier，且不存在 filesystem-equivalent task identity
- **THEN** controller 只创建一个 schema-v4 task directory，并原样持久化该 identifier

#### Scenario: 强制 task identifier 边界
- **WHEN** caller 分别提供 64-byte valid ASCII identifier、65-byte identifier 或含 non-ASCII code point 的 identifier
- **THEN** controller 只接受 64-byte valid form，并在创建 task path 前对其余 form 返回 structured `INVALID_TASK_ID` error

#### Scenario: 拒绝文件系统等价的 task identifier
- **WHEN** 新 identifier 按实际 macOS filesystem-identity rule 与现有 task 互为 alias
- **THEN** controller 串行化 task-namespace check，并在创建 directory 或 commit state 前拒绝该 identifier

#### Scenario: 加载当前 V4 task
- **WHEN** schema-v4 task 使用符合本契约的标识符
- **THEN** controller 解析其 task directory 并保持 identifier 不变

### Requirement: Filesystem-aware path identity
source repository、analysis tree、managed worktree、task data 和 protected path
SHALL（必须）按受支持 macOS filesystem 上的 canonical identity 进行比较。
identity algorithm MUST（必须）考虑 resolved symlink、Unicode normalization 及实际
case sensitivity。protected identity 含糊、缺失或重叠时，mutation
MUST（必须）被阻止。

#### Scenario: 识别等价的 macOS 路径拼写
- **WHEN** 两种 path spelling 经大小写、Unicode normalization 或 symlink alias 解析到同一 filesystem object
- **THEN** ownership 和 protection check 将它们视为同一 identity

#### Scenario: 在大小写敏感文件系统上保留不同路径
- **WHEN** host 证明两个大小写不同的 path 是不同 filesystem object
- **THEN** canonical identity 保持二者不同，同时继续进行 non-overlap check

#### Scenario: 拒绝含糊的受保护路径
- **WHEN** canonical resolution 无法证明 requested path 是否与 protected data 或其他 workspace 重叠
- **THEN** controller 在 filesystem 或 Git mutation 前阻止该 operation

### Requirement: Platform-native state directory and actor defaults
只有在未提供显式 `--data-dir` 时，独立 V4 命令 MAY（可以）使用文档规定的 macOS
native state directory。空 environment value SHALL（必须）视为未提供。bundled Hook
和 MCP launcher MUST（必须）使用 injected `PLUGIN_DATA`；actor discovery
SHALL（必须）使用当前 macOS account，而不是虚构 predecessor data root。

#### Scenario: 忽略空的 state 目录变量
- **WHEN** optional state-directory environment variable 为空
- **THEN** standalone command resolution 将其视为未提供，而不是 current directory

#### Scenario: 使用 macOS 原生默认目录
- **WHEN** standalone V4 command 既没有 explicit data directory，也没有 injected plugin data directory
- **THEN** 它选择 documented macOS per-user state directory

#### Scenario: 使用注入的插件数据目录
- **WHEN** bundled Hook 或 MCP command 带着 `PLUGIN_DATA` 启动
- **THEN** 每个 V4 operation 都使用该 exact directory，且不静默替换为 default directory

### Requirement: Locale-independent UTF-8 protocols
schema-v4 CLI、MCP 和 Hook boundary SHALL（必须）读写 deterministic UTF-8 JSON，
且不受 user locale 影响。persisted controller text SHALL（必须）使用 canonical
UTF-8，且不重写 repository bytes。无法按照 command explicit
contract 解码的 subprocess output，MUST（必须）在 commit 任何依赖它的 mutation
之前产生 structured error。

#### Scenario: 输出 Unicode protocol data
- **WHEN** V4 path、actor name 或 diagnostic 包含 Unicode
- **THEN** CLI、MCP 和 Hook output 保持为 valid deterministic UTF-8 JSON

#### Scenario: 接受 CRLF Hook 输入
- **WHEN** supported Hook event 使用 CRLF line ending 到达
- **THEN** parser 接受该 JSON frame，且不改变 persisted byte 或 repository byte

#### Scenario: 报告无法解码的子进程输出
- **WHEN** required subprocess output 无法按照其 explicit contract 解码
- **THEN** controller 在 commit 任何依赖该 output 的 result 前返回 bounded decoding diagnostic

### Requirement: Atomic portable state writes
在受支持的 macOS filesystem 上，每次 schema-v4 state mutation 都 SHALL（必须）
在 destination directory 中写入并 flush 一个 private temporary file、atomically
replace destination，并在报告 success 前 sync required file 和 directory metadata。
replacement failure 时 MUST（必须）保留 old complete revision 或 new complete
revision，且 MUST（必须）绝不暴露 partially written state file。

#### Scenario: 在 macOS 上替换 schema-v4 state
- **WHEN** V4 revision 成功 commit
- **THEN** reader 只会观察到一个 complete canonical state file，不会看到 partially written revision

#### Scenario: 原子替换失败
- **WHEN** flush、replacement 或 required sync 失败
- **THEN** mutation 返回 structured storage blocker，且不报告 revision 已 commit

#### Scenario: 中断后清理临时文件
- **WHEN** interrupted write 留下 controller-owned temporary file
- **THEN** 当前 V4 recovery 只能删除已证明属于该 write 的 temporary file，且不解释 predecessor state format

### Requirement: Controller-managed storage remains private
controller 在 macOS 上创建的 schema-v4 directory 和 file SHALL（必须）使用 private
POSIX permission：directory 为 `0700`，regular state file 为 `0600`。creation、
temporary write 和 atomic replacement MUST NOT（不得）扩大这些 permission。

#### Scenario: 创建并替换私有 state
- **WHEN** controller 在 macOS 上创建或替换 V4 state
- **THEN** directory 保持 `0700`、file 保持 `0600`，且任何 intermediate replacement 都不会暴露 broader permission

#### Scenario: 检测不安全的 V4 存储
- **WHEN** 无法按 supported permission model 证明 controller-owned V4 path 为 private
- **THEN** affected mutation 使用 structured storage diagnostic fail closed

### Requirement: Portable subprocess and interruption handling
V4 controller 和 Hook runtime SHALL（必须）在 macOS 上使用 argument vector 和
`shell=False` 启动 executable，使用 standard-library null-device 和
temporary-directory API，并区分 spawn failure 与 non-zero subprocess exit。包含
空格、Unicode 或 shell metacharacter 的 path MUST（必须）保持为 single argument。
对于参与 protected mutation 的 subprocess，interruption handling MUST（必须）请求
termination、在需要时 escalate，并在释放 mutation lock 前 wait 或 reap owned
subprocess 或 process group。如果无法证明 quiescence，controller MUST（必须）在
持锁时原子持久化当前 V4 containment blocker，并持续阻止后续 mutation，
直到 recovery 证明 process quiescence 并验证 partial postconditions。

#### Scenario: 执行包含 shell 元字符的参数
- **WHEN** repository path 或 data-directory path 包含空格、Unicode、`&` 或括号
- **THEN** subprocess 在 macOS 上将完整 path 作为一个 argument 接收，且不经 shell interpretation

#### Scenario: 报告缺失的可执行文件
- **WHEN** executable 无法在 host 上 spawn
- **THEN** controller 返回 structured `COMMAND_FAILED` output，并区分 spawn error 与 subprocess exit code

#### Scenario: 中断受管操作
- **WHEN** subprocess-backed operation 尚未完成时，controller 收到 interactive interruption
- **THEN** controller 在释放 lock 前 terminate 并 reap owned subprocess，不把任何 incomplete result 标为 ready，并从 last committed V4 revision 开始 recovery

#### Scenario: 子进程无法证明静止
- **WHEN** mutating subprocess 忽略 first termination request，或 escalation 后仍无法证明其已 exit
- **THEN** controller 在 unlock 前记录 durable current-V4 containment，后续 mutation 保持 blocked，直到 recovery 证明 subprocess 已消失并验证每个 partial postcondition

### Requirement: Fail-closed cross-platform locking
task state、workspace registry 和 configuration mutation SHALL（必须）只能在
stable non-empty range 上成功获取受支持的 macOS exclusive operating-system
lock 后进入 critical section。缺少 lock support、initialization failure、timeout、
acquisition failure 或 unlock uncertainty，都 MUST（必须）产生 structured blocker，
且 MUST（必须）绝不能 fallback 到 unlocked mutation。

#### Scenario: 串行化同一 revision 上的两个写入方
- **WHEN** 两个 native macOS process 尝试从同一 expected revision 对同一 V4 task 执行 mutation
- **THEN** 只有一个 process commit，另一个随后返回 stale-revision error，且不重复执行 mutation

#### Scenario: 拒绝不受支持的锁后端
- **WHEN** state filesystem 没有 verified macOS locking backend
- **THEN** task、workspace-registry 和 configuration mutation 继续保持 blocked

#### Scenario: process death 后重新获取 lock
- **WHEN** process 在持有 operating-system lock 时终止
- **THEN** 后续 process 可以获取 kernel 已释放的 lock，并在 mutation 前验证 persisted V4 revision

### Requirement: Standard-library-only runtime parity
shipped V4 controller、Hook 和 MCP server SHALL（必须）在 supported macOS 上仅使用
Python standard library 和 package-internal module 运行，且 startup
SHALL（必须）不依赖 optional SDK 或 external planning/discovery integration。
本 release 不声明 Windows/Linux runtime parity。

#### Scenario: 在隔离 Python 环境中启动
- **WHEN** plugin 在 supported macOS 上具有 Python 和 Git、但没有 third-party Python package
- **THEN** controller、Hook 和 MCP server 成功 import、处理各自 protocol 并强制 native runtime guard
