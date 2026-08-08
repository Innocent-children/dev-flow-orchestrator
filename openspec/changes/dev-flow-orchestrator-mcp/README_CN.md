# Dev Flow Orchestrator MCP 化 OpenSpec 文档包

## 1. 文档定位

这是一套可直接放入仓库 `openspec/changes/dev-flow-orchestrator-mcp/` 的完整
OpenSpec 变更文档，基于仓库 `main` 分支提交：

```text
38685bf09e934ba5c97ea61112110beedb7083ca
```

方案不是简单地把 CLI 命令套一层 MCP Tool，而是把产品调整为：

```text
Codex / 其他本地 MCP Client
              │
              │ MCP STDIO
              ▼
      Dev Flow MCP Adapter
              │
              ▼
          Controller
              │
      ┌───────┼────────┐
      ▼       ▼        ▼
    Engine   Store    GitClient
```

最终推荐形态是：

- **MCP-first**：正常模型交互全部通过类型化 MCP Tools；
- **插件仍保留**：Codex 插件只作为安装、分发和内置 MCP 配置外壳；
- **核心不重写**：Controller、Engine、Store、Git、工作流和持久化模型继续作为唯一权威；
- **CLI 保留**：用于恢复、脚本、人工排障和发布验证，不再要求模型拼接 shell 命令；
- **Web UI 保留**：继续作为本地只读观察面；
- **首版仅 STDIO**：不同时引入 HTTP、OAuth、远程仓库映射或托管服务；
- **移除现行 Skill/Hook 权威**：完成 MCP 等价验证后，不再安装三个长 Skill 和命令 Hook；
- **任务数据不迁移**：目标发布版本为 `0.5.0`，但 `MODEL_VERSION` 仍为 `0.4.0`。

## 2. 为什么不直接删除 Codex 插件

插件和 MCP 不是互斥关系。插件适合承担：

- Marketplace 身份；
- 安装、升级、卸载；
- 内置 `.mcp.json`；
- MCP 启动器与依赖运行环境；
- 文档、版本和候选包验证。

MCP 适合承担：

- 稳定工具发现；
- 类型化输入输出；
- 当前动作投影；
- 精简、按需的操作指导；
- 不依赖 shell 字符串拼接的 Controller 调用。

因此本方案把插件降级为“分发外壳”，而不是把整个项目变成一个必须由用户手工注册的松散脚本。

## 3. 关键兼容性决定

| 项目 | 决定 |
|---|---|
| 目标发布版本 | `0.5.0` |
| 持久化模型版本 | 保持 `0.4.0` |
| MCP 接口版本 | `dev-flow-mcp/1.0.0` |
| 传输 | 仅本地 STDIO |
| Python | 从 3.9–3.14 调整为 3.10–3.14 |
| MCP SDK | 官方 Python MCP SDK v2，锁定上限与精确依赖 |
| 依赖安装 | 安装器管理的隔离运行环境，不写入源码目录或任务数据目录 |
| Controller | 继续作为唯一应用边界和状态写入者 |
| CLI | 保留，但 MCP Server 不调用 CLI |
| Web UI | 保留 |
| 现有任务 | 原地读取和继续，无导出、转换或复制 |
| Skills | MCP 等价验证完成后从当前安装包移除 |
| Hooks | MCP 等价验证完成后从当前安装包移除 |
| PreToolUse 数据目录保护 | 明确取消，不伪装为 MCP 可等价实现的能力 |
| 注册模式 | 默认插件内置；可选独立注册；两者不得同时启用 |

## 4. 稳定 MCP Tool 目录

| Tool | 类型 | Controller 映射 / 作用 |
|---|---|---|
| `dev_flow_server_info` | 只读 | 产品、模型、接口、运行时健康信息 |
| `dev_flow_list_tasks` | 只读 | 有界任务清单，不运行 Git |
| `dev_flow_find_tasks_for_path` | 只读 | 按任一成员仓库路径发现活动任务 |
| `dev_flow_get_task` | 只读 | 有界存储视图、计划、决策和 Dossier |
| `dev_flow_get_next_action` | 只读/实时捕获 | 获取唯一当前动作、精确 binding 与按动作指导 |
| `dev_flow_start_task` | 写入 | `Controller.start` |
| `dev_flow_apply_action` | 写入 | `Controller.apply` |
| `dev_flow_revise_contract` | 治理写入 | `Controller.revise_contract` |
| `dev_flow_record_decision` | 治理写入 | `Controller.decide` |
| `dev_flow_dispose_finding` | 治理写入 | `Controller.dispose_finding` |
| `dev_flow_cancel_task` | 终止写入 | `Controller.cancel` |

明确不提供：

- 通用 CLI 透传 Tool；
- 任意 shell 或 Python 方法调用 Tool；
- 原始状态文件读写 Tool；
- 分支、工作树、提交或推送 Tool；
- CI、PR、发布 Tool；
- Web UI 启停 Tool；
- 远程 HTTP MCP 服务。

## 5. 文档结构

```text
openspec/changes/dev-flow-orchestrator-mcp/
├── proposal.md
├── design.md
├── tasks.md
└── specs/
    ├── mcp-server-runtime/spec.md
    ├── mcp-controller-tools/spec.md
    ├── mcp-guidance-and-context/spec.md
    ├── mcp-plugin-packaging/spec.md
    ├── personal-delivery-workflows/spec.md
    ├── task-discovery-boundaries/spec.md
    ├── package-delivery-validation/spec.md
    ├── authoritative-plugin-installation/spec.md
    ├── native-windows-product-support/spec.md
    └── native-windows-runtime/spec.md
```

### `proposal.md`

说明为什么迁移、用户价值、变化与不变化的边界、兼容策略、影响范围、迁移步骤和完成定义。

### `design.md`

包含 20 个架构决定，重点包括：

- MCP-first 而不是直接移除插件；
- 仅 STDIO；
- 官方 SDK 与 Python 版本；
- MCP Adapter 分层；
- 11 个稳定 Tool；
- 严格输入和结构化输出；
- 当前动作精简投影；
- 按动作指导替代长 Skill；
- 显式发现替代 Hook 注入；
- 并发、取消和不确定提交恢复；
- Tool annotations 与审批；
- Hook Guard 取消后的残余风险；
- 隔离依赖运行环境；
- 插件内置与独立注册冲突；
- STDOUT 纯协议；
- 上下文预算；
- 发布、灰度和回滚。

### `tasks.md`

按依赖顺序列出 17 个实施阶段和可勾选任务，覆盖核心重构、MCP 协议、工具、指导、安装器、Windows、测试、文档、迁移和发布证据。

### `specs/`

包含 4 个新增能力和 6 个现有能力增量：

- 新增：MCP Runtime、Controller Tools、Guidance、Plugin Packaging；
- 修改：工作流执行、任务发现、包验证、权威安装、Windows 产品、Windows Runtime。

## 6. 迁移阶段

### 阶段 A：开发隐藏入口

- 新增 MCP Adapter、Tool、协议测试和 CLI/MCP 等价测试；
- 保持现行安装入口，MCP 仅用于开发验证；
- 不改变模型版本和任务数据。

### 阶段 B：MCP 成为默认入口

- 插件内置 MCP Server；
- 安装器创建隔离运行环境；
- 正常任务全部通过 MCP；
- 旧 Skill/Hook 仅作为受控回滚路径，不再作为正常验收路径。

### 阶段 C：移除当前 Skill/Hook

只有在六类工作流的真实安装旅程、Windows/macOS 生命周期、上下文预算和“不读取插件源码”证据全部通过后，才从当前包中移除 Skill/Hook。

## 7. 需要特别关注的风险

### 7.1 Hook 自动注入消失

MCP 不会在 SessionStart 自动把任务投影塞进上下文。替代方式是：

1. `dev_flow_find_tasks_for_path`；
2. 明确选择任务；
3. `dev_flow_get_next_action`。

这是一项交互变化，但能消除大量每轮重复上下文。

### 7.2 PreToolUse Guard 无法等价迁移

MCP Server 看不到 Codex 的所有 shell、编辑和 patch 操作，不能声称继续拦截对数据目录的直接访问。

补偿措施包括：

- 数据目录与仓库严格分离；
- Tool 和正常日志不返回数据路径；
- 所有模型侧状态写入均走封闭 Tool；
- 安装器只操作经过验证的自有资产；
- 文档明确 unrestricted local shell 不在 MCP 安全边界内。

### 7.3 MCP 依赖破坏原来的“零运行时依赖”

方案通过两层隔离控制：

- Core 继续只用标准库；
- MCP SDK 仅允许出现在 `src/dev_flow_orchestrator/mcp/` 和受管运行环境。

### 7.4 非幂等 Tool 的网络/进程不确定性

`start`、`apply`、合同修订、决策、处置和取消都不是可盲重试操作。响应丢失后必须先读任务或当前动作，不能直接重放。

### 7.5 Tool 元数据本身也可能膨胀上下文

方案把以下内容设为发布门槛：

- Server instructions ≤ 4 KiB，前 512 字节必须自包含；
- 每个 Tool 描述 ≤ 512 字节；
- 完整 `tools/list` ≤ 32 KiB；
- 当前动作指导 ≤ 8 KiB；
- 结构化结果不在文本内容中重复一遍。

## 8. 放入仓库的方法

将本包中的目录复制到仓库根目录：

```bash
cp -R openspec/changes/dev-flow-orchestrator-mcp \
  <repo>/openspec/changes/
```

然后在项目环境中执行：

```bash
openspec validate dev-flow-orchestrator-mcp --strict
```

开始开发前，建议再执行：

```bash
openspec status --change dev-flow-orchestrator-mcp --json
openspec instructions proposal --change dev-flow-orchestrator-mcp --json
```

实际命令中的 artifact 名称应以当前 OpenSpec 返回的状态和 instructions 为准。

## 9. 当前校验状态

已执行本地结构校验：

- 10 个 capability delta 文件全部存在；
- 54 条 Requirement；
- 169 个 Scenario；
- 每个 ADDED/MODIFIED Requirement 都包含 `SHALL`/`MUST`；
- 每个 ADDED/MODIFIED Requirement 至少一个 `WHEN`/`THEN` Scenario；
- REMOVED Requirement 均包含 Reason 与 Migration；
- proposal 中声明的 capability 与实际目录一致；
- 11 个稳定 Tool 在 proposal、design 和 tool spec 中一致；
- `0.5.0` 发布版本与 `0.4.0` 模型保持策略在核心文档中一致。

当前仓库已经执行并通过：

```bash
openspec validate dev-flow-orchestrator-mcp --strict
uv run python scripts/validate_package.py
uv run python -m unittest discover -s tests -p 'test_*.py'
```

最终冻结工作树在本机可用的三个受支持解释器上完成了完整 discovery：Python 3.12 与
3.13 各运行 413 项测试、跳过 22 项，Python 3.14 同样运行 413 项、跳过 22 项，三者
均返回 `OK`。22 项 skip 是平台门禁，不计为原生 Windows 证据。macOS installer
34/34、uninstaller 21/21 通过；Windows product/lifecycle 集合在 macOS 上有 11 项
host-neutral 测试通过、16 项原生 Windows 测试按设计跳过。

完全隔离的真实 Codex 0.146.0 profile 已完成激活、幂等 repair、恰好一个 bundled MCP
注册、默认路径发现既有 `0.4.0` 任务、经受管 PATH launcher 的 12 条 workflow 路线和
marker-scoped 卸载。卸载后插件、注册、launcher 与 runtime 均移除，源码以及 current/
prior-version 任务命名空间字节保持不变；用户正常 Codex profile 未被读取或修改。

追踪清单覆盖 54 条 Requirement 与 169 个 Scenario，共 223 项，canonical SHA-256 为
`adccec38fe75728342d79551b4c85e28d54451e5a8bfccb024980e156c6c3948`。137 个任务项中
133 项已完成。仍未勾选的四项是：原生 Windows pre-change baseline、完整 Python/host
矩阵、原生 Windows x64 生命周期，以及必须等待这些平台门禁后才能发布的 Delivery
Dossier。不得用静态 PowerShell 检查、macOS 结果、skip、WSL/Wine 或 Windows Server
自动化替代这些外部证据。

## 10. 参考来源

- 仓库：`https://github.com/Innocent-children/dev-flow-orchestrator`
- OpenAI Codex MCP 文档：`https://developers.openai.com/codex/mcp/`
- OpenAI 插件文档：`https://developers.openai.com/codex/plugins/`
- MCP Python SDK：`https://github.com/modelcontextprotocol/python-sdk`
- MCP Tool 规范：`https://modelcontextprotocol.io/specification/`
- OpenSpec：`https://github.com/Fission-AI/OpenSpec`
