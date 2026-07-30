## ADDED Requirements

### Requirement: Current V4 release validates one native macOS host
初始纯净 V4 release SHALL（必须）只支持并验证 native macOS。release evidence
SHALL（必须）记录实际使用的精确 macOS、Python 和 Git version。Windows 和 Linux
job、emulation、handoff 及 support claim SHALL NOT（不得）成为本 change 的 release
gate。在宣传其他 operating-system support 前，需要通过未来的独立 specification
change，并取得该 platform native current-V4 evidence。

#### Scenario: 验证受支持的 V4 宿主
- **WHEN** focused V4 check 在 release host 上运行
- **THEN** evidence 标明 native macOS 以及 exact Python 和 Git version，且不声明更广的 operating-system matrix

#### Scenario: 尝试宣传其他操作系统
- **WHEN** release metadata 或 documentation 声称 current V4 支持 Windows 或 Linux
- **THEN** validation 失败，因为本 release 不包含该 platform 的 native current-V4 evidence

### Requirement: Supported-host failures are diagnosable
每次 required macOS validation failure 都 SHALL（必须）标明 operating-system
version、Python version、invoked focused suite 或 validator，以及相关的 structured
runtime、Hook、Git 或 package diagnostic，且不泄露 secret。
capability handling MUST（必须）保持显式，且 MUST NOT（不得）削弱 approval、
revision、evidence、concurrency 或 mutation-safety gate。

#### Scenario: macOS capability 检查失败
- **WHEN** focused runtime、Hook、Git、validator 或 packaging assertion 失败
- **THEN** recorded result 标明 host、interpreter、check 和 actionable failure reason

#### Scenario: 某项 capability 不可用
- **WHEN** macOS host 无法提供一项 optional filesystem 或 process capability
- **THEN** 只有该 capability-specific assertion 被报告为 unavailable，且任何 deterministic safety gate 都不会被视为通过

## MODIFIED Requirements

### Requirement: Cross-platform tests use portable and isolated fixtures
只要不改变被测 contract，focused current-V4 test SHALL（必须）使用 Python
standard-library helper、`sys.executable`、`tempfile` 和 argument-vector subprocess
call。Git fixture MUST（必须）隔离 host 的 repository、global 和 system
configuration。capability-specific assertion MUST（必须）与 common V4 assertion
分离。这些 portable property 使 test 可复用，但本 release 只要求在
native macOS 上执行，且 MUST NOT（不得）从 portable test construction 推断
Windows 或 Linux support。

#### Scenario: 聚焦 V4 测试在 macOS 上运行
- **WHEN** named V4 suite 在受支持的 native macOS host 上运行
- **THEN** common test 使用 isolated temporary state，且不依赖无关的 host tool 或 configuration

#### Scenario: 宿主 Git 配置具有对抗性
- **WHEN** validation host 的 user-level 或 system-level Git setting 与 repository default 不同
- **THEN** 由于 external configuration 被隔离，ordinary fixture 保持 deterministic，只有 dedicated adversarial test 注入 non-default setting

#### Scenario: 文件系统专属断言不受支持
- **WHEN** validation host 缺少 optional assertion 所使用的 capability
- **THEN** 仅该 assertion 被报告为 unavailable，byte、path、state 及 guardrail assertion 继续运行

### Requirement: Runtime safety contracts have native regression coverage
focused current-V4 suite SHALL（必须）在 native macOS 上覆盖保留的 fail-closed
lock acquisition/release、concurrent-writer exclusion、subprocess quiescence 和
containment、controller-managed private storage、explicit data-directory use、
actor discovery、UTF-8 CLI 与 Hook JSON、subprocess decoding、task identifier、
canonical filesystem identity，以及含 space/Unicode 的 path components。
coverage SHALL（必须）只选择 V4 rewrite 直接影响的 representative path。
Windows DACL、drive、UNC、reserved name、legacy code page 和 Linux-native case
不属于本 release，MUST NOT（不得）要求或据此推断。

#### Scenario: 两个写入方竞争同一 V4 task revision
- **WHEN** 两个 native macOS process 针对同一 schema-v4 task 和 expected revision 尝试 mutation
- **THEN** 只有一个 process 在 exclusive lock 下 commit，另一个收到 deterministic stale-revision 或 lock diagnostic，且不发生 unlocked mutation

#### Scenario: 无法获取原生锁
- **WHEN** macOS locking primitive 报告 unsupported operation 或 unrecoverable acquisition error
- **THEN** mutation fail closed，state 和 event 不变，error 标明 lock path 及 platform cause

#### Scenario: 执行变更的子进程在首次终止请求后仍存活
- **WHEN** 参与 protected V4 mutation 的 native helper subprocess 忽略 first termination request 并尝试 delayed marker write
- **THEN** controller 在 unlock 前 escalate 并 reap 它，或记录 durable containment，阻止后续 mutation，直到 current V4 recovery 证明 quiescence

#### Scenario: controller 管理的权限保持私有
- **WHEN** schema-v4 state directory 和 replacement file 在 macOS validation host 上创建
- **THEN** directory 和 file mode 保持 `0700` 和 `0600`，且 atomic replacement 不扩大 access permission

#### Scenario: Unicode state 穿过受支持接口
- **WHEN** repository path、actor 或 diagnostic 包含 Unicode
- **THEN** V4 CLI 和 Hook boundary 交换 deterministic UTF-8 JSON；如存在 decoding ambiguity，则在任何 commit 前失败

### Requirement: Cross-host validation candidate identity is canonical and layered
candidate identity SHALL（必须）使用 acyclic four-layer contract。计算任何 layer
之前，implementation SHALL（必须）最终确定 existing plugin name、version
`4.0.0+codex.<cachebuster>` 和 cachebuster；cachebuster MUST NOT（不得）由包围它的
candidate digest 派生，或在该 candidate digest 产生后改变。

L0 layer `runtime_inventory_sha256` SHALL（必须）覆盖 explicit installable V4 runtime
allowlist，包括 final manifest 和 cachebuster，同时排除 V4 genesis record 本身、
OpenSpec artifact、test、CI、generated validation/review/handoff evidence 及其他
non-installable file。L0 SHALL（必须）对以下 preimage 计算 SHA-256：
`b"dev-flow-v4-runtime-inventory/v1\x00" || U64BE(entry_count) || entries`。
每个 regular-file entry SHALL（必须）按 exact UTF-8 POSIX-relative path byte 排序，并编码为
`U64BE(path_length) || path_bytes || b"\x46" || U64BE(payload_length) || raw_payload`。
它 SHALL（必须）忽略 directory 和 host metadata，并拒绝 absolute path、drive path、
UNC、backslash、path traversal、duplicate、Unicode-normalization-plus-casefold
colliding entry、symlink、reparse point 和 special entry。two-entry vector
`README.md`=`hello\n` 与 `scripts/测试.py`=`print("ok")\n` SHALL（必须）得到
`4b647f3ea4ae12f214fffb3e87944eb0202dcfe29e812c560342e324d3d0849f`。

L1 layer SHALL（必须）是存放在 candidate 内部的 V4 genesis。它 SHALL（必须）绑定
L0、精确的两个 workflow 和 bundle identity、transitive closure 中的 handler
identity、catalog、activation manifest 及 final plugin manifest identity。它
MUST NOT（不得）包含 L2 candidate digest 或任何 L3 validation、review 或 handoff
digest。

L2 layer SHALL（必须）是 frozen canonical candidate。其 explicit allowlist
SHALL（必须）包含 installable plugin、L1 genesis、current V4 source、focused test、
validator、CI configuration、root documentation、license 和 line-ending policy，
同时排除 OpenSpec 及每个 generated L3 record。L2 SHALL（必须）保留 canonical
contract v1：
`b"dev-flow-canonical-v1\x00" || U64BE(entry_count) || entries`，并使用与 L0
相同的 entry ordering、encoding 和 path/kind rejection rule。其 canonical
two-entry vector `README.md`=`hello\n` 与 `scripts/测试.py`=`print("ok")\n`
SHALL（必须）得到
`a5f265def6c95a23cf668937f83a6d06320d2e784f064627a6847aed11974674`。
L2 内部不得有任何 file 包含 L2 digest。

L3 layer SHALL（必须）包含位于 candidate root 外的 focused validation、
independent review 和 handoff record。每条 L3 record SHALL（必须）绑定 exact
frozen L2 digest，且 MUST NOT（不得）改变 L0、L1 或 L2。单独的、mode-sensitive
host-local review digest MAY（可以）覆盖 OpenSpec 和 POSIX mode drift，但
MUST NOT（不得）与 L0 或 L2 比较或用作 package cachebuster。L0、L1 或 L2
的任何 byte change 都会使所有 existing L3 evidence 失效。

#### Scenario: 构建底层 runtime inventory
- **WHEN** final manifest、cachebuster 和 installable V4 byte 已经稳定
- **THEN** L0 在不包含 genesis 或 external evidence 的情况下计算，其 digest 可以且只能一次嵌入 L1

#### Scenario: 无递归地冻结 candidate
- **WHEN** L1 genesis 已写入
- **THEN** L2 包含其 exact byte，同时 genesis 和其他任何 candidate file 都不包含 L2 或 L3 digest

#### Scenario: 绑定外部 evidence
- **WHEN** focused validation、independent review 或 handoff 完成
- **THEN** L3 record 写在 candidate 之外，并绑定已经 frozen 的 L2 digest，且不改变 candidate byte

#### Scenario: evidence 产生后某个已纳入输入发生变化
- **WHEN** L3 evidence 存在后，manifest、cachebuster、runtime、genesis、focused test、validator、CI、documentation、license 或 line-ending policy 发生变化
- **THEN** L2 随之变化，所有 affected validation、review 和 handoff record 都会重新生成

#### Scenario: 计算规范向量
- **WHEN** identity implementation 计算任一 canonical two-entry vector
- **THEN** 它先产生规定的 layer digest，之后才标识 release candidate

### Requirement: Bundled hook behavior is tested through real launch commands
focused validation SHALL（必须）执行 packaged `hooks/hooks.json` 中真实的 macOS
`command` entry，而不能只直接调用 handler function。它 SHALL（必须）通过包含
space 和 Unicode 的 path，提供 representative current-V4 Codex JSON event 以及
`PLUGIN_ROOT`、`PLUGIN_DATA` value。parser coverage SHALL（必须）包括 current
macOS contract 所需的 direct `git` 和 supported POSIX shell wrapper。Windows
launcher 和 shell 不属于本 release。

#### Scenario: 打包的 macOS Hook 命令往返 JSON
- **WHEN** supported host 使用每个 handler 的 packaged `command` 启动它
- **THEN** handler 读取 representative V4 event、使用 injected plugin directory、输出 supported event-specific wire shape，并按 Hook contract exit

#### Scenario: Compact recovery 使用当前生命周期边界
- **WHEN** focused validation 启动 `PreCompact`、`PostCompact` 以及紧随其后的 compact-source `SessionStart`
- **THEN** lifecycle 恢复 current schema-v4 controller、task、revision、node 和 next-action locator，且不经过 historical projection branch

#### Scenario: 参数化受保护的 Git 命令
- **WHEN** parser table 直接或通过 supported POSIX wrapper 提供等价的 protected Git mutation
- **THEN** 每种 recognized form 都返回相同 denial category，任何 ambiguous wrapper payload 都 fail safely

#### Scenario: 良性命令仍被允许
- **WHEN** 同一个 macOS command table 承载不会改变 protected Git state 的 command
- **THEN** Hook 保持原有 allow behavior，且不产生 false denial

### Requirement: Git evidence and worktree flows are capability-aware and byte-accurate
focused native macOS validation SHALL（必须）在 V4 rewrite 改变相关 path 时，使用
real Git 覆盖 current V4 preflight、baseline、analysis、managed-worktree
materialization、fingerprinting、test evidence 和 review evidence path。
capability-aware normalization MUST（必须）保留 explicit byte-accurate
tracked-content manifest 和 deterministic dirty-state detection。Windows 和
Linux native worktree behavior 不是 release claim 或 validation obligation。

#### Scenario: 为 macOS 检出计算指纹
- **WHEN** current V4 worktree 在 supported host 上验证
- **THEN** evidence 记录 relevant file-mode、symlink、case 和 line-ending capability，同时将 unchanged checkout 判定为 clean

#### Scenario: 跟踪字节发生变化
- **WHEN** tracked-file bytes 在 observed macOS capability set 下发生变化
- **THEN** manifest 和 workflow evidence 检测该 change，deterministic gate 阻止 stale 或 mismatched evidence

#### Scenario: worktree 路径包含空格或 Unicode
- **WHEN** managed worktree plan 位于包含 space 或 Unicode 的 supported macOS path 下
- **THEN** argument-vector Git operation 访问 intended path，ownership claim 阻止 equivalent path 被重复分配

### Requirement: Every release validates skills, manifest, and package inventory
required automation SHALL（必须）运行三个 activation profile 要求的 exact named
current-V4 suite；它使用 static closure 加每个 retained contract class
的一个 behavioral representative，而不是为每个 action placement 分别测试。
它还 SHALL（必须）运行 automated runtime import/dependency audit、对每个 shipped
Skill 执行 bundled Skill validator、plugin manifest validator、package
inventory/reference 和 default-Hook-discovery validator、V4 genesis 与 candidate
layer validation，以及 change artifact 的 strict OpenSpec validation。
full unit-test discovery 或 broad unrelated aggregation SHALL NOT（不得）执行。
这些 check MUST（必须）作用于 exact frozen L2 source snapshot。

runtime audit MUST（必须）解析每个 shipped controller 和 Hook Python import，
验证其属于 standard library 或 package-internal module，然后在没有 third-party
package 的 isolated environment 中启动 runtime。manifest 和 inventory check
SHALL（必须）确认 Hook configuration、runtime script、Skill reference、V4 workflow
asset、template 及中英文 documentation 均存在，并使用 valid macOS path spelling。

#### Scenario: 内置 Skill 变为无效
- **WHEN** 任一 shipped Skill 违反 Skill schema 或包含 broken required reference
- **THEN** validator 标明该 Skill、以 non-zero exit status 退出并阻止 packaging

#### Scenario: manifest 或 V4 包内容漂移
- **WHEN** manifest invalid、referenced V4 file 缺失，或 validation snapshot 与 frozen L2 不同
- **THEN** release validation 标明 offending path 或 digest，并在 publication 前失败

#### Scenario: 引入第三方 runtime 导入
- **WHEN** shipped controller 或 Hook runtime file 导入 Python standard library 及 package-internal module 之外的 top-level module
- **THEN** dependency audit 标明 file 和 import、以 non-zero exit status 退出并阻止 candidate

#### Scenario: 运行聚焦 V4 验证
- **WHEN** exact profile suite 和所有 required package validator 在 frozen L2 上成功
- **THEN** L3 result 记录每项 selected check 和 source identity，且不声称运行了 full suite 或 non-macOS native matrix

## REMOVED Requirements

### Requirement: Native operating-system and supported-Python CI matrix
**Reason**: 初始纯净 V4 product 只支持 macOS，且 user 已明确排除 broad 或 unrelated release test。

**Migration**: 无。未来的 platform-support change 必须先定义并产生自身 native current-V4 evidence，才能声明 support。

### Requirement: Project-local Windows native validation is safe and evidence-producing
**Reason**: Windows runner、handoff launcher、UNC fixture 和 evidence schema 会保留 unsupported platform surface，并在纯净 V4 scope 外制造 release work。

**Migration**: 无。Windows 不受本 release 支持。

### Requirement: Windows support includes a real Codex-host pickup smoke
**Reason**: current V4 release 不声明 Windows support。

**Migration**: 无。未来 Windows-support change 必须定义新的 native-host acceptance contract。

### Requirement: Platform parity and failures are diagnosable
**Reason**: Windows/macOS/Linux parity 不是 initial V4-only release contract；supported-host diagnostic 已单独规定。

**Migration**: 无。不保留 cross-platform parity claim。
