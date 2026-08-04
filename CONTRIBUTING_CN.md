# 贡献指南

[English](CONTRIBUTING.md)

贡献保留 0.2.0 产品契约：一个任务跨越精确的、由一到八个用户准备的本地 Git 工作树，一个 Codex 执行器，一个投影操作，以及一个控制器拥有的只追加账本。

## 产品和权限边界

- 从用户旅程和支持的产品矩阵开始。工作流深度、仓库拓扑、工作区策略和执行拓扑是独立维度。
- 将当前策略保持在一个权威来源中，并从中推导目录、验证、测试、技能和文档。
- 将任务状态保留在目标仓库之外。控制器是唯一的状态转换写入者；Hook、CLI、技能和可选驱动程序提交到该边界。
- 将 `TaskState.repositories` 视为不可变的成员关系权威。准入、快照、状态变更、重放、新鲜度、恢复和最终交付必须以原子方式覆盖完整的规范集合；绝不能默认只有一个成员、丢弃不可用成员或重构调用方顺序。
- 保持仓库检查有限且只读。不要添加隐式的 stash、reset、clean、checkout、commit、rebase、merge、push、强制 push 或删除行为。
- 不要将仓库拓扑与工作流深度、管理分支/工作树效果、Git 发布、并行代理或外部 CI/PR/发布效果耦合。当前核心不执行这些操作，也不重用未更改成员的部分保障。
- 在每条状态变更路径上保留动作绑定、契约、输入血缘、资源、源前驱、快照和修订 CAS 检查。
- 将代码库内存视为发现证据。对于每个 `repository_id`，使用不同的基线和当前工作区项目 ID，从不跨成员或代际共享图 ID，按工作流阶段选择，并在命名仓库源中确认材料结论。
- 向 OpenSpec 请求当前 JSON 状态和指令。基于仓库的规划是源生成的并绑定具体的治理/报告资源；运行时代码中不应有固定的阶段顺序。
- 将驱动程序执行保持在引擎之外。可选驱动程序回退记录降级或不可用的保障，并保留相同的终止条件。
- 运行时代码仅使用 Python 标准库。

## 模块所有权

- `product.py`：0.2.0 身份词汇表、官方工作流目录和权威的仓库拓扑能力。
- `model.py`：不可变任务值和规范仓库成员资格、严格 JSON、错误和收据。
- `snapshot.py`：聚合仓库集快照和嵌套成员工作区快照、验证、查找和摘要。
- `workflow.py`：`dev-flow-workflow/0.2.0` 契约、阶段范围取消、图验证和选定定义身份。
- `delivery.py`：契约、决策、密封、绑定、资源、新鲜度、覆盖和档案。
- `engine.py`：重放、突变计划、保障路由、记录、投影和任务视图。
- `store.py`：路径安全、锁、修订 CAS 和原子持久性。
- `git_client.py`：有限内容敏感的只读快照。
- `controller.py`：应用程序协调和所有状态变更。
- `cli.py` 和 `hook.py`：协议接口；两者都不拥有工作流策略。

保持这些依赖显式。避免全局执行顺序、基于字符串的后期绑定、重叠的服务层或纯领域模块中的文件系统/进程访问。

## 当前工作流和身份变更

官方工作流是 `lite`、`feature`、`bugfix`、`investigation`、`refactor` 和 `full`。`dev-flow-workflow/0.2.0` 节点声明类型化工件、工作区角色、输入、有限保障重做、耗尽的档案路径和可选驱动程序降级/不可用元数据。每个工作流声明一个共享取消操作，带有显式的 `cancel.stages`；官方定义涵盖正常多数非终止阶段并排除所有 `delivery.finalize` 节点。

`PRODUCT_IDENTITY` 是当前任务、记录、工件、动作绑定、仓库集快照、嵌套工作区快照、工作流、代理、验证覆盖、交付档案、数据命名空间和一到八个拓扑的权威。选定工作流身份仅绑定选择器、模式和规范文档。对这些当前权威的任何更改都必须更新相应的契约和集中证明。

仓库拓扑独立于官方工作流选择。每个基数使用 `dev-flow-agent/0.2.0`，精确的 `dev-flow-repository-set-snapshot/0.2.0`，必需的 `repository_id` 资源、结构化的 `criteria`/`repositories`/`integration` 验证、聚合新鲜度/审查和交付档案 0.2.0。

## 验证

只运行直接覆盖更改行为的最小测试模块或单个案例。禁止完整 unittest 发现，包括发布或里程碑请求。在该 macOS 主机上，显式未验证原生 Windows 和 Linux 检查。

典型的聚焦命令如下：

```sh
python3 -I -S tests/test_workflow_validation.py -v
python3 -I -S tests/test_yaml_subset.py -v
python3 -I -S tests/test_package.py -v
python3 -I -S tests/test_install_script.py -v
python3 -I -S tests/test_multi_repository_assets.py -v
python3 -I -S tests/test_delivery_runtime.py -v
python3 -I -S tests/test_controller_contracts.py -v
python3 -I -S tests/test_store_integrity.py -v
python3 -I -S tests/test_stale_mutations.py -v
python3 -I -S tests/test_cli.py -v
python3 -I -S tests/test_hook.py -v
python3 -I -S tests/test_git_snapshot.py -v
python3 -I -S tests/test_multi_repository_core.py -v
python3 -I -S tests/test_multi_repository_controller.py -v
python3 -I -S tests/test_multi_repository_delivery.py -v
python3 -I -S tests/test_installed_journeys.py -v
python3 -I -S scripts/validate_package.py
python3 -m json.tool .codex-plugin/plugin.json
```

仅从 0.2.0 聚焦 CI 矩阵中选择适用命令。使用当前 CLI 指令验证活动的 OpenSpec 变更。

编辑后验证每个捆绑技能：

```sh
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/analyze-change-impact
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/follow-dev-flow
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/review-dev-flow-change
python3 /Users/innocent-children/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

捆绑验证器需要带有 PyYAML 的开发解释器；这不是插件运行时依赖。

发布证据区分源检出检查和安装行为。已安装的验收通过识别不可变的安装快照并涵盖六个官方工作流、Hook/技能拾取、结构化/最小启动、绑定所需应用、契约修订恢复、决策和豁免、可选驱动程序可用/降级路径、有限保障成功和耗尽、单成员和更大精确集准入通过同一协议、任何成员 Hook 拾取、成员丢失恢复、结构化成员/集成验证和聚合档案检查。需要真实新 Codex 任务的条件在环境无法观察到时仍标记为手动或未验证。

在移交前：

- 检查完整的跟踪和未跟踪差异；
- 运行更改文件的空白/错误检查；
- 确认英文和中文产品声明具有相同的范围和强度；
- 针对精确当前聚合仓库集快照进行一次独立的只读审查；
- 准确报告每个跳过的或手动检查。
