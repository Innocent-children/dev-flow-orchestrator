# Dev Flow Orchestrator 架构

[English](ARCHITECTURE.md)

## 产品身份

`0.6.11` 在 MCP 接口旁捆绑名为 `dev-flow` 的正式 Codex Skill，但不改变持久化
模型身份。`MODEL_VERSION`、任务数据命名空间、workflow、policy、binding、record、
finding、snapshot 和 Delivery Dossier 均保持 `0.4.0`。

非持久化传输身份为：`dev-flow-mcp/1.0.0`、`dev-flow-mcp-result/1.0.0`、`dev-flow-mcp-action/1.0.0` 和 `dev-flow-mcp-guidance/1.0.0`。

## 分层

```text
Codex Skill               CLI                 只读 Web UI
     |                      |                         |
     v                      v                         v
MCP adapter ----------- Controller -----------------+
     |                      |
     |                      +--> Engine --> Delivery --> Model
     |                      +--> Store / locks / revision CAS
     |                      +--> GitClient / complete-set capture
     |
     +--> schemas, results, guidance, concurrency, stderr logging
```

Skill 负责激活和路由并调用 MCP，不写入任务状态。Controller 是唯一的状态转换
写入者。MCP 包导入 Controller，但 Controller、Engine、Store、GitClient、workflow、
assurance、delivery、review、snapshot 和 model 模块绝不导入 MCP SDK 或其框架依赖。
核心与 CLI 运行时代码仍只使用标准库；第三方 SDK 由托管 MCP 环境持有。

## Codex Skill

`.codex-plugin/plugin.json` 通过 `skills: "./skills/"` 注册 Skill。规范 Skill
目录树限定为 `skills/dev-flow/` 下的 `SKILL.md`、`agents/openai.yaml` 和
`references/activation-and-routing.md`。

`SKILL.md` 的 description 是 host 的隐式匹配 surface，也声明显式 `$dev-flow`
入口。`agents/openai.yaml` 包含 interface 元数据并启用
`policy.allow_implicit_invocation`。它有意省略 `dependencies`：受支持的 dependency
schema 基于 URL，而本插件的本地 STDIO server 已由
`mcpServers: "./.mcp.json"` 注册，因此不会伪造 URL 或其他 transport。

运行时，Skill 先检查 server 身份，再为每个精确仓库根发现任务，恢复一个明确且兼容
的任务，或启动新任务，然后重复实时 `get_next_action`/执行/apply 循环。任务选择有
歧义时交还用户决定。mutation 状态不确定时，先执行 read-after-write 恢复再考虑重试。

这些内容不是协议权威。包校验会拒绝嵌入 action catalog、payload schema、state
machine、transition table 或带版本 Controller 协议定义的 Skill。当前 MCP 响应仍是
action id、闭合 payload、精确 binding、review/verification obligation、transition
和终止结果的来源。

## MCP 服务器

一个名为 `dev-flow` 的 `MCPServer` 通过 STDIO 运行。初始化只声明 Tools：没有 Resources、Prompts、Tasks、sampling、elicitation、HTTP、SSE、authentication 或监听型 transport。目录恰好包含五个读取工具和六个 mutation 工具。

输入使用闭合 Pydantic/JSON schema，并设字段、枚举、数量和字节限制。领域对象仍经过现有 Controller/model 校验；传输校验不得复制或削弱领域规则。未知工具、未知字段、畸形 JSON 值和协议错误在 Controller dispatch 前被拒绝。

每个工具返回一个简洁文本项和一个结构化 `dev-flow-mcp-result/1.0.0` 信封。领域错误保留其 code，并附有界脱敏 details 和确定性 recovery。适配器意外异常返回 `INTERNAL_ERROR` 与请求 ID；stderr 只记录异常类型和栈帧位置，绝不记录参数、合同、binding、环境值、仓库内容或任务数据根目录。

## 读取模型

复用现有有界 Controller 检查 API：产品身份/健康；分页存储任务清单和隔离诊断；存储任务详情、合同摘要、治理摘要、timeline 页面与终态 Dossier；针对仓库路径的规范活动任务发现；实时权威 next-action 捕获。

MCP current-action 视图是由 `dev-flow-agent/0.4.0` 派生的瞬态紧凑 projection。它保留完整仓库集合、snapshot digest、精确 binding、payload contract、driver、obligation/review 上下文、inputs、governing resources 和来源 projection digest。它不持久化新模型对象，也不暴露 Git 内部 snapshot 路径。如果完整上下文超过上限，适配器返回 `MCP_RESULT_LIMIT`，绝不截断 binding 或必要动作字段。

## Guidance

初始化 instructions 只包含发现、显式选择、get-next、执行与 apply 循环，上限 4 KiB。版本化目录按当前 node/handler 为 preflight、impact、planning、implementation、investigation、documentation、rework、assurance/review、finalization、cancellation 及闭合通用 fallback 选择 guidance。

影响分析 guidance 区分 current/baseline codebase-memory 项目并要求源码确认。Planning guidance 携带治理 OpenSpec 的 status、path/digest、source stage 和 fallback。Review guidance 使用已绑定 review package 并保留 snapshot/digest 权威。最终 guidance 上限 8 KiB。

## 仓库与状态权威

一个任务拥有用户预先准备的一至八个 Git 工作树根目录的不可变规范集合。Controller 不创建、切换、修复或删除 Git 工作树或分支。snapshot 协议要求时，完整实时捕获会覆盖所有成员两次。成员缺失、重叠、别名、共享 Git 管理目录、过期 binding、不稳定 snapshot 或 revision 冲突都在状态转换前原子失败。

存储清单检查不执行实时 Git capture，并隔离损坏项。路径发现排除终态任务，对重叠活动 claim 返回明确 ambiguity。任务存储继续位于所有仓库之外的模型 `0.4.0` 命名空间。

## 并发与不确定完成

MCP 适配器增加有界进程内协调器：同任务 mutation 串行化，最多四个实时 capture 或 mutation 调用可立即进入且不排队，超额调用立即失败。这只是 admission 优化；跨进程权威仍由 Store locks、仓库成员、精确 binding 和 revision CAS 提供。

Mutation 非幂等。commit 后断连或取消可能使完成状态不确定，客户端必须读取存储任务和当前动作，再判断是否需要另一次 mutation。适配器不得通过 retry loop 自动重放 mutation。

## Release 获取与执行前边界

最终用户生命周期操作获取版本寻址的 GitHub Release 资产，而不是源码 checkout。每个
版本发布一个闭合的平台中立 archive、一个闭合 `release-index.json`、版本无关的
`install.sh`/`install.ps1` 首次安装入口，以及版本匹配的
`install-<version>.sh`/`install-<version>.ps1` bootstrap。Archive 包含完整 sealed
plugin tree、一个 pure-Python 项目 wheel、哈希锁定的 `runtime-requirements.txt`、
其 `uv.lock`、版本化 lifecycle helper 和内嵌的闭合 manifest。Manifest inventory
覆盖除自身以外的所有后代；外部 index 对 manifest 的原始 UTF-8 字节求 hash。

两个版本匹配 bootstrap 内嵌相同的标准库 Phase A verifier。它在 parse 前检查 bootstrap
固定的 index digest，随后检查闭合 index、archive size 与 digest、每个 tar header 和
portable ASCII member path、固定资源上限、安全的 exclusive extraction、原始 manifest
digest、完整 inventory 及静态 package topology。Link、reparse ancestor、special 或
sparse member、不支持的 tar extension、traversal、path collision 以及缺失或未声明的
member 都会失败，且 extraction 不能成为权威。

首次安装入口与已安装的 `update`/`reinstall` 命令共享同一个标准库 release resolver：
严格的 `MAJOR.MINOR.PATCH` 或 `latest` 语法、仅规范仓库的 HTTPS 主机、拒绝 draft 与
prerelease 的正式 Release 过滤器，并且只在规范的 `releases/download/v<version>/` 地址
下载。`latest` 通过规范仓库的官方 release listing 解析，随后所选 Release 的版本匹配
bootstrap 执行与精确版本完全相同的固定 Phase A、Phase B 校验。无效版本、Release 不
存在或下载失败都会在任何产品状态变化前以非零状态退出。

Phase A 完成前，不得执行 artifact helper、artifact import 或 artifact subprocess，
也不得创建或修改 runtime authority、lifecycle state、dispatcher、marketplace、plugin、
MCP、Codex state、active record 或 transaction authority。Acquisition staging 是
installer-owned temporary state，绝不是已安装或 rollback selector。

Bootstrap 是首个版本专属 trust input，它固定规范 repository、version、asset 和 index
digest。动态 `latest` 路径依赖规范仓库的 release listing，该 listing 被限制为携带
两个版本化 bootstrap 资产的正式、非 draft、非 prerelease Release。SHA-256 证明
bootstrap、index、archive 与 manifest 之间的字节一致性；它不是独立签名或发布真实性
的绝对证明。Source commit 与 tree 是 release-builder publication assertion。设计不
声称抵御所有同用户 trust input 被一致替换，也不增加签名、Sigstore、transparency
log、mirror 或 offline fresh install。

## Managed release 与启动权威

只有 Phase B 才能执行 semantic wheel validation、要求哈希且仅 wheel 的依赖安装、
项目 wheel 安装、candidate 构建，以及 staged Skill/MCP health。它绝不在用户机器上
执行 sdist build backend。Candidate-specific health 不读取公共 active record。

```text
version-matched bootstrap
          |
          v
Phase A verified extraction（临时，绝不是权威）
          |
          v
Phase B candidate + staged health
          |
          v
provisional marketplace/plugin read-back
          |
          v
active.json generation CAS
          |
          v
public dev-flow and dev-flow-mcp --stdio proof
```

Managed release 包含隔离 environment、sealed plugin、runtime receipt、installed-
content verifier 与版本化 lifecycle entry point。Receipt 绑定完整 artifact 与 installed
identity：index、archive、manifest、source assertion、wheel、requirements、lock、
distribution、Python、plugin、verifier、helper、owned inventory、release path 与
transaction。

闭合 `active.json` record 是本地 active-release 的唯一 selector。它只包含单调递增
generation、release ID、contained 的绝对 managed-release path、receipt digest、
stable-dispatcher protocol 与提交它的 transaction ID。Receipt、marketplace、plugin
state、launcher 和 helper file 可以佐证 active record，但绝不选择一个竞争 release。

三个产品自有的小型 dispatcher `dev-flow`、`dev-flow-mcp` 和
`dev-flow-uninstall` 是稳定安装基础设施。普通 repair、upgrade 与自动 rollback 不会
替换它们。CLI 与 MCP dispatcher 在调用该 verifier 前检查 active schema、contained
path、receipt digest、protocol、managed Python 与 versioned verifier。Verifier 在项目
import 或 MCP initialization 前证明完整 installed content。`dev-flow update` 与
`dev-flow reinstall` 由同一稳定 dispatcher 在解析 active release 之前识别；它校验并
复制 digest 固定的命令驱动，在 managed runtime 之外运行，因此 active release 无法
启动时这两个命令仍然可以执行。

插件 manifest 指向根 `.mcp.json`；后者声明一个调用 `dev-flow-mcp --stdio` 的
`dev-flow` server。Personal marketplace 只指向 active managed release 内的精确
plugin root，绝不指向 download、extraction、checkout、candidate staging 或可变的共享
plugin tree。

`lifecycle/installation.json` 中的闭合安装记录是每个生命周期命令运行前都要验证的
digest 固定证据。它记录实际使用的 runtime root、dispatcher 目录、Codex home、
personal marketplace 文件、Controller 任务数据根目录、该根目录下的 Dev Flow 自有
数据条目名称，以及全部稳定支持文件的 digest。升级、卸载与重装都从该证据推导精确
路径，因此安装时选择的自定义 data root 会被之后的每个生命周期命令遵守。小型
data-root ownership marker 证明所记录的根目录及其自有名称；重装在修改任何数据之前
会验证该 marker（或闭合的自有名称布局）。只有记录、稳定支持文件和 dispatcher
均与冻结身份精确一致的紧邻前代安装，才允许一次性迁移到扩展后的安装证据 schema；
支持字节发生变化或属于其他历史布局时会保留原状，而不会覆盖。

## Lifecycle 状态机

Fresh install、repair、upgrade、reinstall、predecessor migration、recovery 与 uninstall
在每次 authority 读取和修改时共用一把 installation-wide lifecycle lock。Reinstall
调用的子 bootstrap 也必须获取该锁，因此父命令在调用期间释放它；持久的 pending
journal 会阻止无关操作，独立 operation guard 会阻止并发的第二个 reinstall driver，
而且只有携带精确匹配 reinstall transaction 授权的子进程才能越过该 journal。Active
创建、替换、恢复与删除使用 expected generation
加 active-record-digest CAS。单调 generation 防止 stale writer 与
`A -> B -> A` identity confusion。

每个 operation 创建或恢复一个有界 transaction journal，其中包含 operation 与
transaction ID、expected active state、target/previous authority、external observation、
provisional effect、transaction-owned/retained path、phase 和 outcome。新操作先恢复或
分类已有 non-terminal journal。

Activation 按 candidate staged health、provisional marketplace/plugin effect、host
read-back、active CAS 与真实 public CLI/MCP startup proof 的顺序执行。Active commit 前
失败会恢复 previous external state；commit 后失败会用 CAS 恢复 immediate previous
generation，并重新验证其 public startup。终态仅有 `committed`、`rolled_back` 与
`partial`；`partial` 保留不确定性并停止 identity-specific mutation。Rollback 只在该
activation transaction 尚未终结时自动恢复 immediate previous authority。

只有 complete startup、receipt、ownership 与 installed-content attestation 均通过时，
健康的 exact-version repair 才能复用 active release。Drift 会构建新的已验证同版本
candidate。相同版本的 index、archive 或 manifest digest 发生变化时会拒绝采用。
Upgrade 始终运行目标版本的 bootstrap。

`dev-flow update` 用共享 resolver 解析最新正式 Release，并以记录路径运行其版本化
bootstrap。即使 active release 已经是最新版本，Phase B 仍会完成 runtime、installed-
content、public startup 与 stable infrastructure 的完整证明。健康 release 会被复用，
不会重建或替换；receipt 身份尚存的损坏 release 会被修复重建；无法证明的状态被报告
为 `partial`，绝不会是成功。`dev-flow reinstall` 运行一个持久的 `reinstall`
事务：它证明数据根目录只包含 Dev Flow 自有条目（Controller `0.4.0` 命名空间、
`web-runtime` 与 ownership marker），把它们移动到带 digest inventory 的事务备份，
通过版本化 bootstrap 安装最新 Release，并且只有在安装 committed 之后才删除备份。
失败或中断时，只要仍能证明精确回滚，就会恢复之前的数据字节；否则保留两侧 authority
并把事务分类为 `partial`。数据移动之前遗留的 activation journal 会先被恢复。安装
期间只有 transaction 匹配的子进程可以越过该 reinstall journal；任何无关 activation
都会被拒绝。

## Migration 与卸载边界

Migration 只接受 frozen fixture 所表达的紧邻 conforming checkout installer 的 installed
observation。Classification 使用 plugin、marketplace、launcher marker、receipt、
ownership 与 transaction evidence；它绝不读取、导入、执行、更新、清理、纳入
ownership、删除 checkout，也不把 checkout 用于 rollback。更旧、未来、畸形或歧义
observation 会在 identity-specific mutation 前停止。

`dev-flow-uninstall` 验证稳定基础设施和复制出的最小标准库 removal driver，然后在同一
lifecycle lock 下创建或恢复 uninstall journal。它按依赖顺序 compare-and-remove 精确
plugin/marketplace state、managed release、active record、CLI/MCP dispatcher 与 lifecycle
support。Changed、unknown、concurrent、linked、reparse、special 或无法证明的内容会被
保留并报告。Lifecycle support 与 uninstall dispatcher 最后移除；释放锁后不再发生
产品修改。

Controller task data、model namespace、无关 marketplace/plugin state、无关 launcher、
standalone MCP registration 与每个 legacy checkout 都在安装 ownership 和 uninstall
removal 之外。卸载还完整保留所有 Dev Flow 用户数据，包括任务、历史、证据、锁、
Web UI runtime 状态与日志，以及 data-root ownership marker。只有
`dev-flow reinstall` 会清空 Dev Flow 自有任务数据，而且只在记录的 data root 内、
所有权可证明、精确回滚且无法证明的内容被分类为 `partial` 时进行。用户仓库、工作
树、Git 数据、checkout 与无关插件数据永远不在重装删除范围内。

## 安全与剩余边界

工具目录没有通用命令、原始状态、分支/工作树、发布、外部 CI/PR/Release 或并行 executor 能力。Tool annotations 是 host 提示，不授予权威。

旧 fail-open Hook、前代 Skills、Hook bootstrap 和 Hook 专用 Windows launcher 不在
发布包中。正式 `dev-flow` Skill 存在，但只负责激活和路由。因此不再存在 PreToolUse
数据目录 guard。安全性依赖 Controller 校验、Store 完整性、host 审批、仓库与操作
系统权限以及用户复核。这个剩余边界被明确说明，而不是被描述成 Skill 或 MCP 强制机制。

## 兼容性

支持 Python `>=3.10,<3.15`，托管安装要求 64 位。macOS 使用 POSIX bootstrap。
原生 Windows 10 22H2 x64 和 Windows 11 x64 使用不依赖 POSIX 的 PowerShell 5.1/7
bootstrap；Windows Server 和 compatibility layer 不在客户端声明范围。用户选择的
root 可以包含空格、撇号和 Unicode，而 archive 内部名称使用闭合 portable ASCII
grammar。

由于模型命名空间与字节不变，现有 0.4.x 任务可直接恢复。保留的历史 OpenSpec 材料是
证据，不是当前包权威。静态 PowerShell 检查与 macOS 执行不是原生 Windows 证据。
真实 Codex release-candidate 与最终 promotion/re-download gate 同样必须在各自所需环境
真实运行后才算已验证。
