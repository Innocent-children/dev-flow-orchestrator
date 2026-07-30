# Codex 新会话恢复 Prompt

复制以下内容到新的 Codex 会话：

```text
继续执行 dev-flow-orchestrator 的 OpenSpec 重构。

项目路径：
/Users/innocent-children/PycharmProjects/dev-flow-orchestrator

OpenSpec change：
introduce-versioned-workflow-kernel

开始前必须完整阅读：

1. /Users/innocent-children/PycharmProjects/dev-flow-orchestrator/AGENTS.md
2. /Users/innocent-children/PycharmProjects/dev-flow-orchestrator/openspec/changes/introduce-versioned-workflow-kernel/RESUME.md
3. OpenSpec 当前 change 的 proposal、design、specs 和 tasks

然后重新执行并以实时 JSON 为准：

openspec status --change introduce-versioned-workflow-kernel --json
openspec instructions apply --change introduce-versioned-workflow-kernel --json
git status --short

这是一个包含大量未提交、未跟踪文件的脏工作区。所有现有修改都必须保留，不得 reset、clean、checkout、stash 或覆盖，也不要删除忽略的 pyproject.toml、uv.lock。

请从 RESUME.md 记录的精确停止位置继续，不要从头重做。首先检查被中断的并行改动是否语法完整、契约一致，然后优先解决：

1. schema-v3 generic transaction 的短锁边界；
2. preflight、record-test、review-snapshot 不能在 task/workspace registry 锁内启动事务；
3. 补齐这三个命令的事务、丢失响应、重启恢复和零重复 dispatch 测试；
4. 完成 reconciliation/compensation 的 live evaluator、独立 journal、终态提交与零重复 dispatch；
5. 完成 29 个 orchestration operation 通过 catalog-sealed ActionOutcome generic transaction 的路由与并发测试；
6. 完成 CLI-only claimed/quarantined recovery E2E。

可以使用 Codex 子代理并行开发，但必须明确划分文件所有权；子代理不得互相覆盖修改。主代理负责集成、独立验证和 OpenSpec 任务状态，不得仅根据子代理自报结果勾选任务。

必须遵守：

- runtime 仅使用 Python 标准库；
- 状态存放在插件数据目录，不进入目标仓库；
- Git 变更必须确定、显式、受控；
- 不弱化锁顺序、CAS、proof、quarantine 或 zero-redispatch 断言来通过测试；
- codebase-memory 只能作为发现证据，结论必须回到源码确认；
- OpenSpec 阶段顺序必须读取实时 JSON，不能硬编码；
- hooks 保持轻量并 fail-open，状态迁移由 controller 负责；
- full/lite v3 activation 保持关闭，直到闭包和验证全部完成。

不要提前 canonical reseal。只有所有 identity-covered 输入完全冻结后，才进行一次统一 identity/provenance/release-ledger 流程。不得安装、发布、外部 handoff 或激活。

Windows 实机证据、发布/CI、Windows 安装仍是外部授权项，必须保持未完成，除非我另行明确授权并提供所需环境。

开发过程中持续汇报：

- 当前 OpenSpec 进度；
- 正在处理的任务；
- 子代理分工；
- 实际测试结果和阻塞；
- 哪些结论仍未独立验证。

最终必须在同一个冻结候选上运行：

python3 -m unittest discover -s tests -v

并完成 AGENTS.md 与 OpenSpec 12.x 要求的全部校验、Skill validator、插件/MCP/Hook/package 校验、严格 OpenSpec 校验、git diff --check 和独立只读代码/规范审查。

现在先读取恢复记录和实时状态，核对工作区，然后从记录的锁边界问题继续实施。
```
