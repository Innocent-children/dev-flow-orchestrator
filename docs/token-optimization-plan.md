# 状态机 Token 优化方案

## 目标与边界

本方案把优化分成两个版本：

- **v1：同样的证据，更少的搬运。** 不改变状态转换、人机确认、审计链和 fail-closed 语义。
- **v2：减少不必要的交互。** 涉及确认策略和流程风险判定，必须单独设计、评审和发布。

v1 必须保持以下约束：

1. evidence contract 继续使用 v2；不要求在飞任务迁移或 `cancel/replace`。
2. `DONE` 仍然需要显式人工确认，且不会被自动推进。
3. 默认 `show` 保持向后兼容；紧凑投影是新增能力。
4. fingerprint 漂移、文件损坏和原子写残留都必须 fail closed。
5. `workflow.remaining` 必须出现在紧凑结果中，避免为展示剩余流程再次查询。

## v1 优化步骤

### 步骤 0：建立基线和保护测试

先记录以下指标，再改数据模型：

- `record-test` 响应字节数；
- `state.json` 字节数；
- 默认 `show` 与紧凑 `show` 字节数；
- fingerprint blob 数量与复用率；
- prompt checkpoint 字节数；
- lite 流程必须读取的技能文档字节数。

同时增加回归测试，锁定 evidence currentness、tamper detection、rollback recovery、默认 `show` 兼容性和 hook fail-open 语义。

### 步骤 1：task-local fingerprint 外置去重

把完整 fingerprint 写入任务目录：

```text
<task>/artifacts/fingerprints/<fingerprint-sha256>.json
```

`state.json`、测试记录和审查快照只保存引用，引用包括：

- storage kind；
- task root 与路径 identity；
- blob 字节哈希和大小；
- fingerprint 语义哈希；
- capability profile 与 tracked-worktree manifest 哈希。

写入顺序为：

1. 原子写 fingerprint blob；
2. 回读并校验 blob；
3. 原子更新 `state.json` 引用。

内容相同的 fingerprint 复用同一 blob。若更新状态失败，最多留下不被引用的安全孤儿 blob；绝不能让状态指向不存在或未校验的 blob。

引用故意不携带 `evidence_contract_version`。这样旧控制器不会把引用误当成完整 v2 evidence，而会按既有规则 fail closed。新控制器加载 blob 后再校验其中的 evidence v2。

### 步骤 2：mutation 返回 compact receipt

以下 mutation 不再把完整 evidence 回传给模型：

- `record-test`：返回测试身份、结果、时间和 `fingerprint_sha256`；
- `review-snapshot`：返回快照身份、仓库数量和定位信息。

完整 evidence 仍保存在状态或 task-local artifact 中，审计能力不变。

### 步骤 3：按需读取状态

提供三种读取方式：

- `show`：完整兼容视图；
- `show --compact`：状态、revision、仓库摘要、workflow、计数和下一动作；
- `show --section <name>`：只读取指定 task section，可重复指定。

成功 mutation 的 receipt 已含足够的 revision、status、workflow 等信息时，调用方直接使用 receipt。只有响应缺字段、出现并发冲突或需要完整证据时才再次 `show`。

### 步骤 4：拆分状态机文档

把原有单文件拆成：

- 公共状态机规则；
- lite 流程；
- full 流程；
- preflight、baseline/impact/route、workspace/plan、verification/review gate。

技能入口只加载公共规则和当前流程需要的文档；原 `state-machine.md` 保留为兼容路由页。

### 步骤 5：压缩 prompt checkpoint

- `SessionStart` 保留完整上下文；
- `UserPromptSubmit` 使用无状态、单行 compact checkpoint；
- 不引入跨会话去重标记，避免并发 session 相互抑制；
- hook 继续 fail open。

### 步骤 6：验证与量化

使用 58 个 tracked files、5 次相同 fingerprint 的 lite 测试夹具，当前结果如下：

| 指标 | 优化前模拟值 | 优化后实测值 | 降幅 |
|---|---:|---:|---:|
| `record-test` 响应 | 20,537 B | 1,629 B | 92.1% |
| `state.json` | 161,707 B | 28,087 B | 82.6% |
| `show --compact` | 106,207 B | 1,187 B | 98.9% |
| fingerprint blob 数量 | 5 份内联副本 | 1 个共享 blob | 80.0% |
| prompt checkpoint | 2,235 B | 1,100 B | 50.8% |
| lite 必需技能文档 | 57,291 B | 22,647 B | 60.5% |

这些数字用于比较同一夹具的序列化开销，不代表模型 tokenizer 的精确 token 数；token 降幅应以实际调用遥测复核。

## v1 发布验收

- [x] legacy inline evidence 仍能读取；
- [x] 新写入状态只保存 task-local fingerprint reference；
- [x] 重复 fingerprint 复用同一 blob；
- [x] blob 被篡改、缺失或带原子写残留时 fail closed；
- [x] `record-test` 与 `review-snapshot` 返回 compact receipt；
- [x] 默认 `show` 保持兼容，compact/section 投影可用；
- [x] `workflow.remaining` 保留；
- [x] mutation 成功后不再无条件重复 `show`；
- [x] 状态机文档按流程和 gate 拆分；
- [x] `UserPromptSubmit` 为无状态单行 checkpoint；
- [x] 目标测试、package validation、runtime import audit 通过；
- [x] 完整测试套件通过（由本地完整运行确认）。

## v2 设计清单

v2 不与 v1 性能改造混合发布。

### 1. Risk-gated confirmation 与 intent 泛化

设计判据采用“是否不可逆，或是否产生仓库外可见后果”，而不是笼统的“是否内部操作”。

- `DONE` 始终显式确认；
- 可逆且无外部后果的边才允许自动推进；
- approval 与 transition 即使在一次交互内完成，也必须写成两条独立审计事实；
- 两条事实通过稳定 `intent_id` 关联；
- intent 至少覆盖 task、revision、evidence、side effects 和 target state；
- intent 任一输入变化后，旧批准立即失效。

### 2. lite/full 机器化风险判定

配置中的 protected path glob 只作为硬信号之一，还需要结合变更类别：

- public API、schema、鉴权、迁移、基础设施、跨仓库变更强制 full；
- 多仓库任务强制 full；
- 在进入验证和完成前，根据实际 diff 再执行一次风险检查；
- 无法确定分类时 fail closed 到 full；
- 记录“为何升级为 full”的机器可读原因。

### 3. 漏斗式影响分析

按成本从低到高检索：

1. 当前任务与目标文件；
2. 索引摘要和架构元数据；
3. 符号引用、路由和依赖图；
4. 必要时扩大到全文或跨仓库检索。

每层需要定义停止条件、完整性要求和查询预算。若低成本层不能证明影响面完整，则自动进入下一层，不能为了省 token 提前停止。

### 4. 可选的 session-scoped checkpoint 去重

只有宿主提供稳定 session id 且遥测证明单行 checkpoint 仍是主要成本时才实现：

- 去重 key 必须包含 session id 和 revision；
- 标记写入尽力而为，失败不能阻塞 prompt；
- 并发 session 不能相互压制；
- 没有可靠 session id 时继续使用 v1 的无状态单行方案。

## v2 开工门槛

在实现前完成独立设计评审，并至少准备以下测试：

- 不可逆边和外部副作用边不能静默自动推进；
- `DONE` 无论配置如何都要求显式确认；
- approval/transition 审计事实可分别查询并通过 intent 关联；
- intent 输入变化使批准失效；
- protected path、变更类别和实际 diff 均能触发 lite → full；
- 影响分析预算耗尽时 fail closed，而不是返回不完整结论；
- 两个并发 session 的 checkpoint 状态互不影响。

## v2 实施状态

- [x] task schema v2 与 config schema v2 分离，schema-v1 任务保持兼容；
- [x] 默认显式确认、精确自动白名单及 transition/cancel intent；
- [x] approval/transition 双事实 durable event batch；
- [x] 变更类别、protected glob、目标路径和实时 diff 风险判定；
- [x] lite 风险命中后阻塞且只能 cancel/replace full；
- [x] 漏斗式影响分析、查询预算和完整性元数据校验；
- [x] `UserPromptSubmit` 按可靠 session id 去重并保持 fail-open；
- [x] v2 定向契约、Hook、配置、打包和关键兼容测试通过；
- [ ] 合入前由维护者运行完整回归套件。
