# Dev Flow Orchestrator 架构

[English](ARCHITECTURE.md)

## 产品身份

`0.5.0` 引入 MCP 接口，但不改变持久化模型身份。`MODEL_VERSION`、任务数据命名空间、workflow、policy、binding、record、finding、snapshot 和 Delivery Dossier 均保持 `0.4.0`。

非持久化传输身份为：`dev-flow-mcp/1.0.0`、`dev-flow-mcp-result/1.0.0`、`dev-flow-mcp-action/1.0.0` 和 `dev-flow-mcp-guidance/1.0.0`。

## 分层

```text
Codex / MCP client        CLI                 只读 Web UI
        |                  |                         |
        v                  v                         v
   MCP adapter -------- Controller -----------------+
        |                  |
        |                  +--> Engine --> Delivery --> Model
        |                  +--> Store / locks / revision CAS
        |                  +--> GitClient / complete-set capture
        |
        +--> schemas, results, guidance, concurrency, stderr logging
```

Controller 是唯一的状态转换写入者。MCP 包导入 Controller，但 Controller、Engine、Store、GitClient、workflow、assurance、delivery、review、snapshot 和 model 模块绝不导入 MCP SDK 或其框架依赖。核心与 CLI 运行时代码仍只使用标准库；第三方 SDK 由托管 MCP 环境持有。

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

## 运行时与安装

源码 checkout、托管 MCP runtime 和任务数据根目录彼此分离。安装器使用精确 `uv.lock` 构建版本化虚拟环境，安装 wheel，运行启动/目录/读取 smoke check，并写入 `dev-flow-runtime-receipt/1.0.0` receipt。Receipt 绑定 release、source commit、解释器身份与架构、lock digest、launcher 身份和激活时间，且不暴露数据根目录。

插件 manifest 指向根 `.mcp.json`；后者声明一个 `dev-flow` server，调用自有 PATH launcher `dev-flow-mcp --stdio`。Bundled 与 standalone 注册互斥。Runtime 发布和 launcher 替换采用分阶段方式，使构建失败后原运行时仍可用。

## 安全与剩余边界

工具目录没有通用命令、原始状态、分支/工作树、发布、外部 CI/PR/Release 或并行 executor 能力。Tool annotations 是 host 提示，不授予权威。

旧 fail-open Hook、Skills、Hook bootstrap 和 Hook 专用 Windows launcher 不在发布包中，因此不再存在 PreToolUse 数据目录 guard。安全性依赖 Controller 校验、Store 完整性、host 审批、仓库与操作系统权限以及用户复核。这个剩余边界被明确说明，而不是被描述成 MCP 强制机制。

## 兼容性

支持 Python `>=3.10,<3.15`，托管安装要求 64 位。macOS 是主要已安装交付平台。原生 Windows 10 22H2 x64 和 Windows 11 x64 使用 PowerShell 5.1/7 生命周期脚本并要求原生证据；Windows Server 和兼容层不在客户端承诺范围。

由于模型命名空间与字节不变，现有 0.4.x 任务可直接恢复。保留的历史 OpenSpec 材料是证据，不是当前包权威。
