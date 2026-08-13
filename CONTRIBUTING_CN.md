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

仓库原先禁止完整 unittest discovery 的规则已经废止。发布证据不得以手工维护的部分
模块列表替代完整 discovery。聚焦测试仍适合快速反馈。实现接近结束时运行一次完整
discovery；修复失败后先重跑失败子集，再运行最终完整 discovery。

Release-artifact 证据有意采用分层策略。Shared verifier 与 lifecycle 行为应放在聚焦
unit test 和 deterministic fake-Codex integration test 中。Python 3.10–3.14 矩阵只运行
轻量 wheel-only 依赖安装、import 与 MCP startup smoke check；不要在每个 Python minor
上重复完整 lifecycle matrix。并发只覆盖 upgrade versus upgrade 和 upgrade versus
uninstall。

相关改动还应运行包和 OpenSpec 校验：

```sh
uv run python scripts/validate_package.py
openspec validate install-versioned-release-artifact --strict
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

没有实际运行的平台或矩阵不得宣称通过。原生 Windows 证据必须来自原生 Windows x64，
而不是 macOS、静态 PowerShell、Wine、WSL、deterministic fake 或跳过的测试。
Release-candidate Codex 证据必须使用真实 Codex host，promotion evidence 必须从精确的
官方版本专属地址重新下载最终资产。必须明确记录 skip、不可用 host、权限、retained
path、degradation 与 stale evidence。

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

最终用户安装使用版本专属 GitHub Release 资产，不得要求 Git、`.git`、
`DEV_FLOW_SOURCE_ROOT` 或保留 checkout。Release production 可以检查精确且干净的
`vMAJOR.MINOR.PATCH` tag，但源码 checkout 不得成为 installed、active、repair、
rollback、migration 或 uninstall authority。

维护一个闭合的平台中立 archive contract：完整 sealed plugin tree、恰好一个
pure-Python 项目 wheel、哈希锁定的 `runtime-requirements.txt`、其 `uv.lock`、版本化
lifecycle helper，以及排除自身的内嵌 manifest。`release-index.json` 固定 manifest 的
原始 UTF-8 字节。Artifact member path 使用 portable ASCII grammar；用户安装 root 可
包含空格、撇号和 Unicode。

两个版本匹配 bootstrap 必须内嵌逐字节相同的标准库 Phase A verifier。Phase A 在 parse
前验证固定 index，再验证 archive、全部 header/path、固定 limit、安全 extraction、原始
manifest、完整 inventory 和 topology，之后才能执行任何 artifact code 或产品 mutation。
测试必须明确证明该 gate。SHA-256 证明固定字节一致性；绝不能将其描述为独立签名或
绝对 source authenticity。

Phase B 安装精确、要求 hash 且仅 wheel 的依赖和随附项目 wheel，不执行 sdist backend。
Candidate health 必须先于 host activation。Active record 仍是本地唯一 release selector；
普通 repair、upgrade 或自动 rollback 不替换稳定 `dev-flow`、`dev-flow-mcp` 和
`dev-flow-uninstall` dispatcher。

Fresh install、repair、upgrade、migration、recovery 与 uninstall 共用一把
installation-wide lock、有界 journal、单调 generation 与 generation-plus-digest CAS。
每个 operation 必须终结为 `committed`、`rolled_back` 或 `partial`。不得在 journal
未终结时让命令成功，也不得扩大删除范围以把不确定状态伪装成干净状态。

POSIX bootstrap 测试面向 macOS。PowerShell 保持 PowerShell 5.1 兼容、literal-path
处理、x64 检查、安全的原生 reparse 行为，并且不依赖 POSIX。跨平台生命周期语义应
成对维护，但不得照搬平台专属机制或把静态等价性当成原生证据。

有界 final artifact journey 在原生 macOS 和原生 Windows 上各运行一次，覆盖 fresh
install、healthy/drift repair、upgrade、failed-activation rollback、interrupted
recovery、startup、predecessor migration、uninstall 与 task-data preservation。
Release-candidate evidence 使用真实 Codex host 验证 plugin read-back、bundled Skill
discovery、`dev-flow-mcp --stdio` 与 uninstall。普通开发使用 deterministic fake。

原生 installed journey 通过 STDIO 使用真实 PATH launcher 和官方 MCP 客户端；server
process 不得导入 test helper。

Uninstall 使用精确 compare-and-remove evidence，并必须保留 Controller task data、
changed/unknown content、无关 Codex state、无关 launcher、standalone MCP registration
与每个 legacy checkout。Migration 只支持 frozen 的紧邻 conforming installer，且不得
读取、执行、更新、清理、纳入 ownership 或删除其 checkout。

Signing、Sigstore、transparency log、offline fresh install、mirror、更新 channel、后台
更新、任意历史 rollback、无限 retention、通用 Unicode archive member、更广泛 legacy
migration 与 dispatcher-protocol migration framework 都需要单独的 OpenSpec change。

## 公共文档

`README.md`、`ROADMAP.md`、`ARCHITECTURE.md`、`CONTRIBUTING.md` 和 `INSTALL.md` 是英文源文档。先更新英文文件，再完整翻译并同步对应 `_CN.md` 文件。产品范围、约束、命令、路径、版本、链接和语言切换必须一致。

不得把 MCP annotations 描述为强制机制，不得把已移除的 Hook 行为描述为仍然存在，不得把未验证的平台描述为已验证，也不得把 OpenSpec/任务勾选当作产品正确性的证据。

## Git 与审查

保留无关的用户改动。除非用户明确授权具体操作，否则不得 stash、reset、clean、switch、rebase、merge、commit、push、publish 或修改外部状态。

对于代码审查请求，必须先完成只读审查并报告全部发现，再进行任何修复。审查后停止，直到用户明确选择并授权修复。
