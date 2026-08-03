# Contributor guidance

This directory is the source of the `dev-flow-orchestrator` Codex plugin.

- Keep workflow state outside target repositories. Runtime state belongs in the plugin data directory or the explicit `--data-dir` used by tests.
- Keep Git-changing operations deterministic and gated. Never add automatic stash, reset, clean, force-push, or implicit commit behavior.
- Treat `codebase-memory` as discovery evidence, not as proof of complete coverage. Keep baseline and current-generation workspace project IDs separate, require explicit phase-based selection, and confirm material conclusions in source.
- Ask OpenSpec for current JSON status and instructions. Do not copy a fixed OpenSpec phase sequence into Python.
- Keep hooks small and fail open on internal errors. Hooks are guardrails; the state-machine CLI owns transitions.
- Use only the Python standard library in runtime code.

## Python tooling environment

- For development, test, and validation commands that need third-party Python
  packages, prefer the project `uv` environment (`uv run ...`) over the system
  Python interpreter.
- Required development or validation packages may be installed with `uv` (for
  example, `uv add --dev <package>`). Keep them out of runtime dependencies so
  shipped runtime code continues to use only the Python standard library.
- When a validator fails because a Python package is missing, install the
  package in the project `uv` environment and rerun the validator. Report an
  environment blocker only if the `uv` installation or rerun actually fails.
- The root `pyproject.toml`, `uv.lock`, and project `.venv` are host-local
  tooling inputs and must not be included in the shipped plugin candidate.

- On this macOS host, skip all native Windows and Linux cross-platform
  validation and never extrapolate macOS results to those platforms.
- Validate every skill with the bundled `skill-creator` validator and validate the plugin manifest before handoff.

## Product-minded implementation

在真正开发前，先把自己当作需要长期安装、使用、排错和维护本项目的开发者。不要把完成
OpenSpec、task checkbox、test 或 validation 当作产品正确性的替代品；它们只能证明
已经声明的设计被一致实现，不能证明设计本身符合真实用户目标。

- 先明确用户最终要完成的工作、实际操作路径和产品边界，再编写或执行 planning
  artifact。OpenSpec 必须表达产品意图，而不能反过来代替产品思考。
- 在设计前拆分彼此独立的产品维度，并检查完整组合矩阵。尤其不要把 `full`/`lite`
  workflow 深度、single/multi-repository 拓扑和 `in-place`/`branch`/`worktree`
  workspace strategy 错误绑定；任何有意限制都必须来自明确的产品规则。
- 实施前预演正常路径、边界输入、并发、权限冲突、中断、部分 effect、重试、恢复和
  operator intervention。只覆盖真实可能发生且属于当前产品范围的情况。
- 同时检查安装、启用范围、升级、启动、观测、诊断、恢复、卸载和 documentation，
  使用户从安装到完成真实 workflow 形成闭环。
- 持续检查职责、authority、lock boundary、state mutation、effect lifecycle 和
  dependency direction 是否清楚。拆成多个文件不等于形成了清晰 module；避免依赖
  ordered global execution、隐式 namespace、字符串式 late binding、巨型 function
  或职责重叠的 service/handler/adapter layer。
- 把可变的产品矩阵和 policy 收敛到一个权威 source of truth，再由 runtime、
  registry、activation、test 和 documentation 派生或验证，避免多个彼此复制的
  hard-coded definition 共同验证一个错误假设。
- Validation 必须回答“正确的产品设计是否被正确实现”，不仅是“当前 artifact 是否
  相互一致”。当现实用户场景与冻结 artifact 冲突时，先查明并修正规范，不要为了
  保持 digest 或 milestone 状态而实现错误模型。
- 预料各种情况不等于为不存在的问题增加复杂度。当前产品明确没有 historical
  data 时，不得凭空增加 detection、migration、legacy recovery、fallback 或
  compatibility layer；主动覆盖真实风险，也主动排除无价值复杂性。
