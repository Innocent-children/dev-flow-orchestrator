# 为 Dev Flow Orchestrator 贡献代码

[English](CONTRIBUTING.md)

## 范围与权威

改动应保持为已接受需求所需的最小范围，并可追溯。Controller 是唯一的状态转换写入者。MCP、CLI 和 Web 适配器可以提交命令或检查状态，但不得复制 Engine、Store、仓库、binding、assurance、review 或 delivery 的权威逻辑。

不得增加自动分支/工作树管理、Git 发布、并行执行器、外部 CI/PR/Release 调度、原始状态工具或通用命令面。不得削弱规范路径、仓库身份、精确成员集合、锁、原子写入、修订 CAS、快照稳定性、binding、验收标准或最终 Delivery Dossier 要求。

## 环境

运行时和开发依赖由项目级 `uv` 环境管理，绝不能安装到系统或用户 Python。

```sh
uv sync --locked
uv run python --version
```

支持的运行时元数据为 `>=3.10,<3.15`。托管安装运行时要求 64 位 Python。核心运行时模块必须只使用标准库；只有 `src/dev_flow_orchestrator/mcp/` 可以导入 MCP SDK、Pydantic 或其框架依赖。

## 测试

迭代时运行最小且有用的聚焦测试：

```sh
uv run python tests/test_mcp_runtime.py -v
uv run python tests/test_package.py -v
```

允许完整 unittest discovery。它是规范的完整源码回归命令：

```sh
uv run python -m unittest discover -s tests -p 'test_*.py'
```

仓库原先禁止完整 unittest discovery 的规则已经废止。发布证据不得以手工维护的部分模块列表替代完整 discovery。聚焦测试仍适合快速反馈。
仓库内 CI 矩阵会在 macOS 和原生 Windows 上，对支持的 Python 3.10 至 3.14 每个次版本运行完整 discovery；部分绿色结果不能替代完整发布矩阵。

相关改动还应运行包和 OpenSpec 校验：

```sh
uv run python scripts/validate_package.py
openspec validate dev-flow-orchestrator-mcp --strict
```

同一已安装 STDIO launcher 可与
[官方 MCP Inspector](https://github.com/modelcontextprotocol/inspector) 兼容。
使用 `--`，确保 `--stdio` 传给 Dev Flow，而不是被 Inspector 当作自身选项解析：

```sh
npx @modelcontextprotocol/inspector -- dev-flow-mcp --stdio
npx @modelcontextprotocol/inspector --cli --method tools/list -- dev-flow-mcp --stdio
```

自动化协议门禁仍为 `tests/test_mcp_runtime.py`；它直接使用官方 Python
客户端，不需要 Node.js。

没有实际运行的平台或矩阵不得宣称通过。原生 Windows 证据必须来自原生 Windows x64，而不是 macOS、Wine、WSL 或跳过的测试。必须明确记录跳过项、不可用主机和过期证据。

## MCP 改动

稳定目录恰好包含十一个工具。工具改动必须包含：

- 稳定的 snake-case 名称，以及不超过 512 UTF-8 字节的描述；
- 闭合输入模型，明确必填字段、枚举、数量/字节限制并拒绝未知字段；
- 公共结果信封内的逐工具输出 schema；
- 正确的只读、破坏性、幂等、闭世界和 task-support 注解；
- 直接映射 Controller，不复制领域规则；
- 适用的领域、协议、意外错误、结果边界、并发、取消以及真实官方客户端/STDIO 测试；
- 包校验和已安装旅程覆盖。

服务器导入、启动、运行和关闭路径不得向 stdout 打印任何内容；stdout 仅用于协议。诊断使用有界 stderr 记录和请求 ID，不得包含参数、环境值、合同、binding、仓库内容、秘密或任务数据路径。

保持以下上下文预算：服务器 instructions 4 KiB；首个主流程 512 字节；工具描述 512 字节；工具列表 32 KiB；文本摘要 4 KiB；当前动作 guidance 8 KiB；紧凑当前动作 128 KiB；结构化结果 512 KiB；inventory 或 discovery 页面 256 KiB 且每项 2 KiB；默认 stderr 事件 4 KiB。输入或输出首次超限时应拒绝，不得截断 binding、仓库成员、必需证据或 guidance 权威内容。

## Guidance 改动

每个正式动作节点/处理器必须映射到一个安全目录条目，或闭合的通用 fallback。Guidance 从权威当前 projection 派生，只包含适用的目标、必须读取的字段、允许的影响、必需证据、payload 说明、driver、过期恢复、完成规则和规范 guidance digest。

不得让模型检查包源码、适配器源码、CLI 源码、已移除的 Skills/Hooks、原始 Store 文件或 Controller 数据根目录。影响分析 guidance 必须区分 baseline/current codebase-memory 项目，并对照源码确认图谱结论。治理 OpenSpec guidance 必须携带具体状态、路径/digest、来源阶段和 fallback。Review guidance 必须保留已绑定的 review package 和 guidance digest。

## 安装与平台改动

候选内容校验必须先于候选运行时代码执行。托管运行时必须位于已验证源码和任务数据之外，使用精确 lock，安装 wheel，通过 MCP smoke 检查，并在激活前写入匹配 receipt。构建失败必须保留先前运行时和 launcher。

POSIX 脚本面向 macOS。PowerShell 脚本必须保持 PowerShell 5.1 兼容、literal path 处理、x64 检查、仅 fast-forward 的源码权威、marker 校验删除，并且不依赖 POSIX 工具。跨平台生命周期行为应成对维护，但不得照搬平台专属机制。

已安装旅程必须通过 STDIO 使用真实 PATH launcher 和官方 MCP 客户端；服务器进程不得导入测试辅助代码。覆盖单成员与多成员流程、重启/恢复、0.4.x 数据兼容、治理、review/rework、assurance 耗尽、终态 Dossier、重复注册、构建/激活失败回滚和卸载保留。

## 公共文档

`README.md`、`ROADMAP.md`、`ARCHITECTURE.md`、`CONTRIBUTING.md` 和 `INSTALL.md` 是英文源文档。先更新英文文件，再完整翻译并同步对应 `_CN.md` 文件。产品范围、约束、命令、路径、版本、链接和语言切换必须一致。

不得把 MCP annotations 描述为强制机制，不得把已移除的 Hook 行为描述为仍然存在，不得把未验证的平台描述为已验证，也不得把 OpenSpec/任务勾选当作产品正确性的证据。

## Git 与审查

保留无关的用户改动。除非用户明确授权具体操作，否则不得 stash、reset、clean、switch、rebase、merge、commit、push、publish 或修改外部状态。

对于代码审查请求，必须先完成只读审查并报告全部发现，再进行任何修复。审查后停止，直到用户明确选择并授权修复。
