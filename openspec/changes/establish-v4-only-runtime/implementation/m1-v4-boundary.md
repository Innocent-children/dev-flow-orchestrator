# M1 — V4 Boundary Freeze

本文件冻结 Atomic V4 Cutover 开始前的 implementation boundary。它记录的是
2026-07-30 当前 source 的语义 reachability，以及每个带 generation/version
编号的 identifier 与 file 的唯一处理分类。后续删除与 rename 必须以此为依据；
不得从字符串中的数字直接推断删除。

## 1. `full@4` / `lite@4` source closure

### 1.1 Bundle roots 与 identity-covered asset

唯一保留的 bundle root：

- `workflows/bundles/full-v4`
- `workflows/bundles/lite-v4`

每个 root 的 identity-covered asset 恰好为：

- `workflow.json`（graph，kind `J`）
- `schemas/contracts.json`（kind `J`）
- `schemas/node-input.json`（kind `J`）
- `schemas/node-result.json`（kind `J`）
- `playbooks/workflow.md`（kind `T`）

两个 graph 分别声明 15/7 个 node、29/2 个 shared action，以及
`single-repository` + `multi-repository` / `single-repository` profile。
它们当前都错误地声明 `task_schema_versions: [3]`，这是 V4 replacement 项，
不是允许保留的 contract。

### 1.2 Reachable runtime registry

两个 bundle 的 union 恰好引用 53 个 runtime contract：

- guard（19）：
  `guard.baseline-current/v1`、`guard.blocked-resume/v1`、
  `guard.index-current/v1`、`guard.lite-approved/v1`、
  `guard.lite-risk-safe/v1`、`guard.manager-registry-action/v1`、
  `guard.multi-repository-barrier-current/v1`、
  `guard.multi-repository-cancellation-quiesced/v1`、
  `guard.multi-repository-integration-current/v1`、
  `guard.multi-repository-review-current/v1`、
  `guard.note-required/v1`、`guard.plan-current/v1`、
  `guard.preflight-current/v1`、`guard.review-approved/v1`、
  `guard.review-current/v1`、`guard.route-approved/v1`、
  `guard.test-current/v1`、`guard.workspace-indexes-current/v1`、
  `guard.workspace-ready/v1`。
- reducer（8）：
  `reducer.action-outcome/v1`、`reducer.block/v1`、
  `reducer.manager-registry-action/v1`、`reducer.resume/v1`，以及必须原位
  replacement 的 `reducer.v3-cancel/v1`、
  `reducer.v3-impact-reassess/v1`、
  `reducer.v3-invalidate-plan/v1`、
  `reducer.v3-invalidate-review/v1`。
- gate（7）：
  `gate.baseline-fetch-outcome/v1`、
  `gate.impact-degraded-outcome/v1`、`gate.lite-outcome/v1`、
  `gate.plan-outcome/v1`、`gate.review-outcome/v1`、
  `gate.route-outcome/v1`、`gate.workspace-outcome/v1`。
- executor（19）：
  `executor.barrier/v1`、`executor.codex-exec/v1`、
  `executor.codex-thread/v1`、`executor.deterministic/v1`、
  `executor.external-tool/v1`、`executor.human-gate/v1`、
  `executor.native-subagents/v1`，以及
  `executor.v4-{abandoned,accepted,archive,compensation,containment,control,dispatch,observation,reattachment,settlement,unblock,unresolved}/v2`。

sealed command registry 的 22 个 `command.*/v1` entry 均属于 current
controller operation protocol；它们不表示 workflow generation，继续保留。

### 1.3 Reachable implementation-file closure

handler manifest 从上述 53 个 contract 解析出的当前 implementation-file
closure 恰好为以下 30 个 file：

- `scripts/dev_flow_parts/action_execution_journal.py`
- `scripts/dev_flow_parts/action_execution_store.py`
- `scripts/dev_flow_parts/baseline.py`
- `scripts/dev_flow_parts/commands.py`
- `scripts/dev_flow_parts/core.py`
- `scripts/dev_flow_parts/git.py`
- `scripts/dev_flow_parts/manager_channel.py`
- `scripts/dev_flow_parts/mutation.py`
- `scripts/dev_flow_parts/orchestration_action_adapters.py`
- `scripts/dev_flow_parts/orchestration_authority.py`
- `scripts/dev_flow_parts/orchestration_results.py`
- `scripts/dev_flow_parts/orchestration_service.py`
- `scripts/dev_flow_parts/process.py`
- `scripts/dev_flow_parts/repository_plan.py`
- `scripts/dev_flow_parts/review.py`
- `scripts/dev_flow_parts/scope.py`
- `scripts/dev_flow_parts/transition_engine.py`
- `scripts/dev_flow_parts/workflow_action_reconciliation.py`
- `scripts/dev_flow_parts/workflow_action_service.py`
- `scripts/dev_flow_parts/workflow_action_transaction.py`
- `scripts/dev_flow_parts/workflow_builtin_handlers.py`
- `scripts/dev_flow_parts/workflow_catalog.py`
- `scripts/dev_flow_parts/workflow_registry.py`
- `scripts/dev_flow_parts/workflow_runtime.py`
- `scripts/dev_flow_parts/workflow_state.py`
- `scripts/dev_flow_parts/workflow_transition_service.py`
- `scripts/dev_flow_parts/workflow_v3_handlers.py`
- `scripts/dev_flow_parts/workflow_v4_handlers.py`
- `scripts/dev_flow_parts/workspace.py`
- `workflows/runtime/executors.json`

完整 controller/adapters closure 还包含下列加载、projection、protocol、CLI、
Hook、MCP 与 package-owned support file；它们是两个 bundle 的共享
controller infrastructure：

- `scripts/dev_flow.py`
- `scripts/dev_flow_mcp.py`
- `scripts/dev_flow_parts/agent_protocol.py`
- `scripts/dev_flow_parts/cli.py`
- `scripts/dev_flow_parts/external_tools.py`
- `scripts/dev_flow_parts/external_write_bridge.py`
- `scripts/dev_flow_parts/mcp_controller_service.py`
- `scripts/dev_flow_parts/node_telemetry.py`
- `scripts/dev_flow_parts/runtime_adapters.py`
- `scripts/dev_flow_parts/workflow_action_recovery_cli.py`
- `scripts/dev_flow_parts/workflow_action_recovery_commands.py`
- `scripts/dev_flow_parts/workflow_handlers.py`
- `scripts/dev_flow_parts/workflow_projection.py`
- `scripts/workflow_bundle_identity.py`
- `hooks/dev_flow_hook.py`

五个 registry manifest
`workflows/runtime/{commands,guards,reducers,gates,executors}.json`、catalog、
activation、plugin manifest、Hook configuration、MCP configuration 与 shipped
Skill 是 startup/package closure 的其余 declarative root。

## 2. Numbered identifier 与 file classification

每个 current numbered identifier/file 必须唯一落入以下一类。

### 2.1 V4 replacement（generation-bound）

以下全部原位替换为 V4 identity：

- task `schema_version: 3`、`V3_TASK_SCHEMA_VERSION`、
  `validate_v3_task_state*`、`build_v3_task_creation_fields`；
- `workflow_v3_handlers.py` 与 `_workflow_v3_*` symbol；
- `execute_v3_*`、`recover_v3_*`、`reconcile_v3_*`、
  `bind_v3_*`、`claim_ready_v3_*`、`verify_active_v3_*`；
- `V3_*` / `_v3_*` action、transition、manager、workspace、baseline、
  review、journal、receipt、proof、containment、quarantine 与 recovery
  constant/function/class；
- `dev-flow-v3-*` digest/schema/domain string；
- `reducer.v3-*`、`v3-transition-reducers-v1`、
  `v3-gate-outcome-v1`；
- V4 graph 中的 `task_schema_versions: [3]`；
- `workflow_v4_handlers.py` 中 `_dev_flow_v4_wrapper`、对 V3 function 的
  conditional dispatch 和 monkeypatch facade。

replacement 后使用 V4 module、function、class、domain、schema 和 registry
entry，不保留 alias。

### 2.2 独立版本化的通用 protocol（保留）

下列编号不表示 workflow generation，保持其当前 protocol version：

- workflow、catalog、activation、handler-registration、bundle identity、
  handler implementation identity、canonical JSON、candidate canonicalization、
  Hook、MCP、agent projection、manager capability、repository plan、evidence、
  receipt、runtime handle、worker result 等 `*/v1` contract；
- V4 handler request/result 的 `/v1`；
- `executor.v4-*/v2` 及其 `v4-runtime-v2` implementation-file set；这里
  `/v2` 是 V4 handler contract 自身的第二版；
- `agent-v1` projection；
- `tests/fixtures/repository_plan/valid_v1.json`（若作为 focused current-V4
  fixture 保留）。

### 2.3 删除项（predecessor/unsupported content）

以下不进入 V4 candidate：

- `workflows/bundles/{full,lite}-legacy-v2`
- `workflows/bundles/{full,lite}-v3`
- `scripts/legacy_base_oracle.py`
- legacy adapter、frozen state table、reserved-V3 loader/policy/activation、
  compatibility response/grammar、schema selector 与 predecessor fallback；
- `workflows/release-ledger.json`、
  `workflows/release-provenance/first-introduction.json`、
  `workflows/release-provenance/reserved-v3-activation.json`、
  `workflows/release-provenance/introduction-epochs/`
  及 `scripts/release_ledger.py`；
- predecessor-only fixture、oracle、test 与 historical documentation；
- `scripts/windows_native_validation.py`、
  `scripts/windows_native_validation.cmd`、
  `scripts/dev_flow_mcp_launcher.cmd`、`hooks/dev_flow_hook.cmd`、
  Windows-only branch/fixture/CI input，以及 Linux/Windows support claim。

## 3. Frozen target contract

### 3.1 Task schema v4

唯一 persisted schema constant 为 `V4_TASK_SCHEMA_VERSION = 4`，唯一 supported
schema set 为 `{4}`。首个 revision 必须包含：

- `schema_version: 4`
- valid `task_id`
- `revision: 0`
- `flow: "full" | "lite"`
- exact `execution_profile`
- current `status`
- exact `workflow_ref`：`id`、`version: 4`、`schema`、
  `graph_sha256`、`bundle_sha256`
- deterministic `node_instances`

task validation、bundle validation、creation、loading、projection、recovery
和 orchestration 仅调用 V4 validator。不存在 schema selector、inspection
branch 或 historical-data error path。

### 3.2 Generation-bound naming map

| Current | Frozen V4 target |
|---|---|
| `V3_TASK_SCHEMA_VERSION` | `V4_TASK_SCHEMA_VERSION` |
| `validate_v3_task_state*` | `validate_v4_task_state*` |
| `build_v3_task_creation_fields` | `build_v4_task_creation_fields` |
| `workflow_v3_handlers.py` | direct implementation in `workflow_v4_handlers.py` |
| `_workflow_v3_*` | `_workflow_v4_*` |
| `execute_v3_*` | `execute_v4_*` |
| `recover_v3_*` | `recover_v4_*` |
| `reconcile_v3_*` | `reconcile_v4_*` |
| `V3_*` / `_v3_*` | `V4_*` / `_v4_*` |
| `dev-flow-v3-*` | `dev-flow-v4-*` |
| `reducer.v3-*` | `reducer.v4-*` |
| `v3-transition-reducers-v1` | `v4-transition-reducers-v1` |
| `v3-gate-outcome-v1` | `v4-gate-outcome-v1` |

### 3.3 Catalog、activation 与 focused suites

最终 catalog 恰好包含 `full@4` 和 `lite@4`。最终 activation 恰好包含：

| Profile | Required suites |
|---|---|
| `full@4` / `single-repository` | `v4-static-closure`, `v4-core-runtime`, `v4-effect-recovery`, `v4-external-tools` |
| `full@4` / `multi-repository` | 上述四项加 `v4-multi-repository` |
| `lite@4` / `single-repository` | `v4-static-closure`, `v4-core-runtime`, `v4-effect-recovery` |

五个 suite 的 frozen contract：

- `v4-static-closure`：枚举每个 reachable action placement，证明 unique、
  complete、direct V4 contract closure 及恰好两个 bundle。
- `v4-core-runtime`：full/lite 各一次 schema-v4 creation 与 common
  engine/guard/reducer/revision/projection path。
- `v4-effect-recovery`：每个 retained settlement/recovery class 一个代表，
  包含适用的 bounded hostless `UNRESOLVED` stop。
- `v4-external-tools`：full least-capability evidence 与 serialized
  host/workflow write boundary。
- `v4-multi-repository`：full plan、lease、result、barrier、integration 与
  serialized-CAS invariant。

### 3.4 Provenance layers

- L0 schema：`dev-flow-v4-runtime-inventory/v1`；explicit installable
  allowlist，domain `b"dev-flow-v4-runtime-inventory/v1\x00"`，排除 genesis、
  OpenSpec、test/CI、L3 与 non-installable file。
- L1 schema：`dev-flow-v4-genesis/v1`；位于 candidate 内，只绑定 L0、两个
  bundle 及 transitive handler identity、catalog、activation 和 final plugin
  manifest；不含 L2/L3 digest。
- L2 contract：`dev-flow-canonical-v1`；explicit candidate allowlist，
  包含 exact L1 byte，排除 OpenSpec/L3；任何 candidate file 不得包含 L2
  digest。
- L3 schema：`dev-flow-v4-release-evidence/v1`；只位于 candidate root 外，
  绑定 frozen L2，记录 focused validation、独立 review 与 handoff。

layer order 固定为 manifest/cachebuster → L0 → L1 → L2 → L3。
