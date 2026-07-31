## ADDED Requirements

### Requirement: Mutation receipts are action-scoped and V4-only
controller SHALL（必须）为 schema-v4 task 提供一种 compact mutation
response profile。其 common envelope SHALL（必须）至多为 1,024 个 UTF-8
byte，外加当前 V4 action contract 所需的 action-specific field。它
SHALL（必须）包含 task ID、
committed revision、current node 或 status、changed section identity、
action result summary 和 next-action locator。CLI 和 MCP SHALL（必须）
使用同一个当前 response model，且不设 legacy response branch。

#### Scenario: 接收紧凑的成功 mutation
- **WHEN** 当前 V4 mutation commit
- **THEN** receipt 包含 committed revision 和足够的 next-action data，且不包含重复的完整 workflow 或无关 index

#### Scenario: 返回 action-specific required field
- **WHEN** V4 mutation contract 要求 preview intent、artifact identity 或 recovery locator
- **THEN** 即使因此会超出 common envelope budget，compact receipt 仍包含该 field

#### Scenario: 丢失 mutation receipt
- **WHEN** caller 无法解析或保留成功的 receipt
- **THEN** 它可使用 committed revision 和 durable state，通过 compact projection 重新加载当前 V4 task

## MODIFIED Requirements

### Requirement: Agent projections expose only the current actionable frontier
controller SHALL（必须）为当前 schema-v4 task 提供版本化的 `agent-v1`
task projection。它 SHALL（必须）包含 task ID、current revision、精确的 V4 workflow
identity、current node 或 ready frontier、legal next action、required state
section、confirmation mode，以及 playbook 或 artifact locator。该 projection
MUST（必须）从 transition validation 所用的同一 V4 workflow catalog 和
live state 派生，并且 MUST NOT（不得）包含无关的 task history 或
repository index data。

#### Scenario: 读取单个 actionable node
- **WHEN** 当前 V4 task 有一个 legal next action
- **THEN** `agent-v1` 返回该 action，且只返回为其 current node 声明的 state section 和 locator

#### Scenario: 读取并行 frontier
- **WHEN** 多个相互独立的 V4 node instance 已 ready
- **THEN** `agent-v1` 返回按确定性顺序排列的 frontier，其中包含稳定的 node-instance 和 repository identity

#### Scenario: 未遇到 legal action
- **WHEN** 当前 V4 task 处于 blocked、terminal 或 waiting for approval 状态
- **THEN** projection 说明该状况并返回准确的 recovery、approval 或 terminal locator，且不虚构 next action

#### Scenario: 检测 catalog 与 state 不一致
- **WHEN** 准确的当前 V4 bundle 无法解释 live node 或 status
- **THEN** controller 返回结构化 workflow-definition blocker，且不返回 action projection

## REMOVED Requirements

### Requirement: Mutation receipts are action-scoped and backward compatible
**Reason**: 单一 V4 response model 取代 schema-v1/schema-v2 response compatibility 和 opt-in compatibility branch。

**Migration**: 无。范围内仅存在新的 schema-v4 task data 和当前 V4 client。
