# Dev Flow Orchestrator

Dev Flow Orchestrator 是一个面向 macOS 的 Codex plugin，用于执行受控、可恢复
的开发工作。产品只有 V4 runtime：每个新 task 都使用 task schema v4，并直接
解析到恰好一个已安装 workflow bundle：

- `lite@4`：受限的单 repository 工作；
- `full@4`：完整的单 repository 或多 repository 工作。

Prerequisite 为 macOS、Git 与 Python 3.9 或更高版本。

catalog 只包含这两个 bundle。activation matrix 只包含 lite 单 repository、
full 单 repository 和 full 多 repository 三个 profile。每个 task 都固定其
graph 与 bundle 的 SHA-256 identity。

## Architecture

`scripts/dev_flow.py` controller 加载 `scripts/dev_flow_parts/` 中仅依赖 Python
标准库的 module。直接 V4 registry 绑定 command、guard、reducer、gate、
executor、action transaction、journal、receipt、reconciliation、workspace
effect、review effect、external tool 和多 repository orchestration。

workflow state 存放在目标 repository 之外，并使用 Codex 传入的明确
`--data-dir`。所有会修改 Git 的 action 都是确定性的，并由 controller gate；
任何 action 都不会隐式授权 stash、reset、clean、commit、push 或 force-push。

`codebase-memory` 只提供 discovery evidence。baseline project ID 与当前
workspace project ID 必须分离，按 phase 明确选择，并回到 source 确认重要结论。

## Entry point

- `scripts/dev_flow.py`：CLI controller。
- `scripts/dev_flow_mcp.py`：类型化 MCP surface。
- `hooks/dev_flow_hook.py`：fail-open context 与 command guardrail Hook。
- `skills/follow-dev-flow`：公开 workflow Skill。
- `skills/analyze-change-impact`：只读 impact Skill。
- `skills/review-dev-flow-change`：独立只读 review Skill。

MCP 配置默认 disabled，并只指向随 package 提供的 macOS launcher。Hook
配置使用同一个 Python launcher。

## 本地检查

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py --help
./scripts/dev_flow_python_launcher ./scripts/dev_flow_mcp.py
```

只运行当前 activation profile 指定的 focused tests。本 repository 禁止运行
unittest discovery。

安装方式见 [INSTALL.md](INSTALL.md)，验证规则见
[CONTRIBUTING.md](CONTRIBUTING.md)。
