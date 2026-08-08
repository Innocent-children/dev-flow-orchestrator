# Dev Flow Orchestrator

[English](README.md)

Dev Flow Orchestrator 让跨一个至八个用户预先准备的 Git 工作树的长期 Codex
开发任务保持可恢复、上下文有界且可验证。`0.5.0` 版本把主要 Codex 接口改为
本地 MCP 服务器，同时保留持久化 `0.4.0` 模型和任务数据命名空间。

Controller 仍是唯一的状态转换权威。MCP、CLI 和只读 Web UI 都是同一 Controller
之上的适配器；它们不会创建或切换分支/工作树、发布 Git 改动、运行并行执行器，
也不会调度外部 CI、Pull Request 或 Release。

## 快速开始

要求：

- macOS、Git、`uv`、支持插件的 Codex，以及 64 位 CPython 3.10–3.14；
- Windows 10 22H2 x64 或 Windows 11 x64 使用 PowerShell 预览路径，发布证据仍需
  原生 Windows 验证；
- 一个至八个现有且由用户预先准备的 Git 工作树根目录。

在 macOS 上安装捆绑模式：

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

或克隆权威分支后运行安装器：

```sh
git clone --branch main --single-branch \
  https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
sh "$HOME/plugins/dev-flow-orchestrator/scripts/install.sh"
```

安装器会验证候选包，在源码和任务数据之外构建精确锁定的 MCP 运行时，将
`dev-flow-mcp` 安装到 `PATH`，然后激活插件。Windows、独立注册、修复、回滚和
卸载参见 [INSTALL_CN.md](INSTALL_CN.md)。

在 Codex 中要求发现或启动 Dev Flow 任务。正常顺序是：

1. 使用 `dev_flow_find_tasks_for_path` 或 `dev_flow_list_tasks` 发现任务；
2. 显式选择或启动一个任务；
3. 调用 `dev_flow_get_next_action`；
4. 只在精确仓库集合上执行投影的当前动作；
5. 提交精确动作 ID、封闭 payload 和未经修改的 binding；
6. 重复执行，直到任务生成终止 Delivery Dossier。

## MCP 接口

捆绑的 `.mcp.json` 只暴露一个名为 `dev-flow` 的本地 STDIO 服务器，调用
`dev-flow-mcp --stdio`。HTTP、SSE、监听套接字、token 和 OAuth 传输会被拒绝。

只读工具：

- `dev_flow_server_info`
- `dev_flow_list_tasks`
- `dev_flow_find_tasks_for_path`
- `dev_flow_get_task`
- `dev_flow_get_next_action`

变更工具：

- `dev_flow_start_task`
- `dev_flow_apply_action`
- `dev_flow_revise_contract`
- `dev_flow_record_decision`
- `dev_flow_dispose_finding`
- `dev_flow_cancel_task`

每个工具都具有封闭输入 schema、结构化成功/错误 envelope、一个简短文本摘要、
有界结果、请求 ID、封闭世界注解，并禁用 MCP task augmentation。注解只描述意图，
不是授权或操作系统强制边界。

## 工作流与状态

正式工作流目录为 `lite`、`feature`、`bugfix`、`investigation`、`refactor` 和
`full`。它们继续使用未改变的 `dev-flow-workflow/0.4.0`、
`dev-flow-agent/0.4.0`、action binding、record、assurance、review 和 Delivery
Dossier 标识。

任务成员是不可变的规范仓库数组。实时下一动作捕获覆盖完整集合，并返回下一次变更
所需的精确 binding。从第二成员仓库发现任务会返回同一任务；多个活动声明造成的歧义
会失败关闭。

任务数据位于每个目标仓库之外的模型 `0.4.0` 命名空间。MCP 适配器不会在正常结果
或安装收据中暴露 Controller 数据根路径。现有 0.4.x 任务无需状态迁移即可恢复。

## 引导与恢复

服务器初始化文本只包含发现、获取下一动作、执行和应用循环。当前动作引导从版本化、
有界的目录中选择，只包含适用的目标、必须读取的字段、允许的影响、必需证据、payload
说明、driver 规则、过期恢复、完成规则和规范 guidance digest。

在取消或响应丢失后，绝不能盲目重试变更。先读取存储任务和当前动作，比较已提交修订
与 binding，再判断是否需要新的变更。

## CLI 与只读 Web UI

现有 CLI 和本地 Web UI 继续作为同一 Controller 的受支持视图：

```sh
dev-flow --help
dev-flow web start
```

Web UI 绑定 `127.0.0.1`，默认读取存储任务视图，并且没有变更权威。MCP 是主要的
Codex 执行接口。

## 安全边界

- Controller、Store 锁、仓库成员、snapshot、binding 和修订 CAS 保持权威。
- MCP 不提供通用 shell、原始状态、分支/工作树、发布、CI、PR、Release 或并行 Agent
  工具。
- 移除旧的失败开放 Hook 后，不再存在 pre-tool 写入 guard。仍需宿主审批、仓库权限和
  用户审查。
- 插件不会授予宽泛的变更审批。宿主支持时，应把审批限定到 `dev-flow` 服务器和精确工具。

## 开发

使用项目环境和包校验：

```sh
uv sync --locked
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python scripts/validate_package.py
openspec validate dev-flow-orchestrator-mcp --strict
```

开发过程中可以使用聚焦测试；仓库允许完整 unittest discovery，它是完整回归的标准命令。
参见 [CONTRIBUTING_CN.md](CONTRIBUTING_CN.md)、
[ARCHITECTURE_CN.md](ARCHITECTURE_CN.md) 和 [ROADMAP_CN.md](ROADMAP_CN.md)。

## 许可证

Apache-2.0。参见 [LICENSE](LICENSE)。
