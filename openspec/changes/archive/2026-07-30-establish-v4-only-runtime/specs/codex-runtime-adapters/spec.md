## ADDED Requirements

### Requirement: The JSON CLI is the complete V4 operation and recovery surface
JSON CLI SHALL 在不使用 MCP、Codex SDK、Agents SDK、Node.js 或第三方
Python package 的情况下操作 current schema-v4 runtime。其 command
definition SHALL 来自 sealed V4 command registry，其 stdout protocol 和
stable current error code SHALL 由 CLI-backed adapter 共享。任何 legacy
command grammar、schema selector、response branch 或 workflow fallback
均 SHALL 不予注册。

对于 V4 agent-plane mutation，CLI SHALL 仅通过其 local secret channel
接受 manager proof，并 SHALL 提供显式的 operator authorization 和
revocation command；它 MUST NOT 将该 proof 放入 argv、JSON output、log、
Hook、worker assignment 或 task state。isolated CLI MUST NOT 从 caller
JSON、environment value、inherited descriptor、manager approval、user
statement 或 model output 中推导 trusted-host fact。当没有 trusted host
能够证明 `ABANDONED` 或提供 one-shot `COMPENSATED` approval 时，CLI SHALL
返回带有 `dev-flow-v4-operator-intervention/v1` 的 scope-blocking
`UNRESOLVED`，要求用户 inspect 或 operate，然后退出，且不自动 redispatch、
compensation、archive 或 unblock。

#### Scenario: 在没有 Codex integration 时运行 V4
- **WHEN** plugin 的 MCP server 和 lifecycle Hook 已禁用
- **THEN** authorized operator 可以通过 JSON CLI 创建 current V4 task，并对其执行 inspect、preview、apply 和 recovery

#### Scenario: 通过 CLI 对 V4 task 执行 recovery
- **WHEN** authorized local operator 在没有 MCP 或 SDK 的情况下显式打开 scoped schema-v4 manager session
- **THEN** CLI 执行 authenticated evidence 支持的每个 recovery step，使 manager proof 不进入 argv 和 model-visible output，并在 trusted host authority 不可用时返回带有 V4 intervention packet 的 `UNRESOLVED`

#### Scenario: 在 hostless recovery 后自动继续
- **WHEN** CLI 针对 claimed 或 quarantined effect 返回 V4 operator-intervention packet
- **THEN** CLI 要求用户 inspect 或 operate 并停止，且不调用其他 dispatcher、executor、compensation provider、replacement lease、archive 或 unblock operation

#### Scenario: 生成 parser entry
- **WHEN** 已 review 的 V4 command 在 registry sealing 前注册
- **THEN** CLI 使用已注册的 action identity 恰好公开一次其 parser 和 handler

#### Scenario: 尝试在 startup 后注册
- **WHEN** code 尝试在 registry sealing 后添加或替换 command
- **THEN** startup 或 registration 在 task mutation 前 fail closed

## MODIFIED Requirements

### Requirement: The plugin provides a thin typed MCP facade with accurate policies
plugin SHALL 捆绑一个 standard-library stdio MCP server，该 server 仅公开
current V4 task projection、node description、evidence projection、action
preview、action apply 和 worker-result submission tool。每个 tool SHALL
具有 strict input schema、bounded structured output 以及准确的 read-only、
destructive 和 write annotation。用户 MUST 能够在不编辑 controller code
的情况下禁用 server，或限制 tool 和 approval mode。

initial V4 package SHALL 包含一个用于 native macOS 且默认禁用的 POSIX MCP
profile。该 profile MUST 启动准确的 packaged server，并且不要求也不宣传
Windows 或 Linux companion profile。

#### Scenario: 发现 V4 MCP tool
- **WHEN** compatible client 初始化 bundled server
- **THEN** client 仅收到 bounded current-V4 workflow tool 及其 independently versioned protocol schema

#### Scenario: 启动 packaged macOS MCP profile
- **WHEN** validation 在 native macOS 上从 packaged `.mcp.json` 中选择 POSIX profile
- **THEN** 它从 plugin root 启动该准确的 configured command，并完成 initialization 和 tool discovery

#### Scenario: 调用 read-only projection tool
- **WHEN** Codex 使用 authorized schema-v4 task identity 调用 `task-next`
- **THEN** server 返回 controller 的 bounded current projection，且不改变 state

#### Scenario: 调用 write-capable tool
- **WHEN** Codex 调用 apply 或 result-submission tool
- **THEN** 该 tool 被标记为 write-capable，并委托给 V4 revision、intent、evidence 和 approval check

#### Scenario: 限制 MCP tool set
- **WHEN** plugin-scoped configuration 禁用 mutation tool
- **THEN** Codex 可以使用 permitted read tool，但无法发现或调用 disabled tool

### Requirement: The public Skill is a current-node dispatcher
`follow-dev-flow` Skill SHALL 继续作为 public orchestration entry point，
并 SHALL 仅包含 current V4 invariant、typed adapter selection、current
recovery rule 和 current-node dispatch。它 MUST 仅加载 current controller
projection 引用的 playbook 和 state section，并且 MUST NOT 包含 generation
selector、predecessor command、migration 或 historical recovery guidance。

Skill MAY 将单个 packaged macOS MCP profile 声明为 optional dependency。
当 MCP 已禁用或不可用时，它 MUST 仍可通过准确的 injected CLI locator
使用，并且 MUST NOT reconstruct interpreter 或 data directory。

#### Scenario: 进入已知 V4 node
- **WHEN** `task-next` 识别出一个当前 playbook
- **THEN** Skill 加载该 playbook，且不加载任何不相关的 flow 或 gate playbook

#### Scenario: 使用 current CLI path
- **WHEN** MCP 已禁用或不可用
- **THEN** Skill 调用 injected schema-v4 CLI argument，而不推断 controller 或 data-directory path

#### Scenario: 打包 macOS MCP command
- **WHEN** package validation 检查 Skill 和 `.mcp.json`
- **THEN** 这一个 optional profile 解析到准确的 shipped command，并且 Skill 在其被禁用时仍然 valid

#### Scenario: 遇到 unsupported current action contract
- **WHEN** controller 与 Skill 不共享 current action 或 projection contract
- **THEN** Skill 在 mutation 前停止，并报告 current-package blocker

#### Scenario: 在 receipt 后继续
- **WHEN** successful compact mutation receipt 包含所有 next-action field
- **THEN** Skill 使用该 receipt，而不会立即发出 duplicate task query

#### Scenario: 收到 hostless operator-intervention packet
- **WHEN** V4 recovery 返回带有 `dev-flow-v4-operator-intervention/v1` 的 scope-blocking `UNRESOLVED`
- **THEN** Skill 显示 bounded action-required packet、要求用户 inspect 或 operate，然后停止，且不会将该 packet 或任何 reply 转换为 evidence、redispatch、compensation、replacement、archive 或 unblock authority

### Requirement: Plugin packaging declares runtime adapters without adding hidden dependencies
single plugin manifest 和 package inventory SHALL 使用 portable
package-relative path 声明 bundled Skill、lifecycle Hook 和 MCP
configuration。plugin version SHALL 使用 major version `4`，并且 package
MUST NOT 创建第二个 installable legacy 或 V4-suffixed plugin identity。
runtime import validation SHALL 证明 controller、Hook 和 bundled MCP Python
file 仅使用 standard library 或 package-internal module。安装或启用 plugin
MUST NOT 静默安装 custom agent、optional SDK 或 external credential。

在计算 L0 inventory 前，final manifest version/cachebuster SHALL 固定。
L2 canonical package candidate SHALL 准确包含 installable plugin 内的 V4
workflow、schema、playbook、runtime module、adapter、manifest、Skill 和
L1 genesis，外加 current-V4 source、focused test、validator、CI
configuration、root documentation、license 和 line-ending policy。它 SHALL
排除 OpenSpec 以及生成的 L3 validation、review 和 handoff record，且其中
任何 file 均不得包含自身的 L2 digest。automated verification SHALL 限于
已命名的 current-V4 suite，加上 runtime、Skill、manifest、package、MCP
launch、identity-layer 和 OpenSpec validator。禁止运行 full test suite 和
unrelated aggregation。independent read-only review SHALL 是绑定到未更改
L2 candidate 的 external L3 record。此 change 生成的 native evidence 仅
适用于 macOS，并不表示任何 Windows 或 Linux result。

real-host acceptance SHALL 是 reviewed candidate 准备就绪后由用户负责的
short checklist：替换 existing plugin installation、确认仅启用了一个
plugin instance、确认 Codex 已发现 Hook 和 MCP，并完成一次 current V4
real-project smoke。这些 host check MUST NOT 与大型 local compatibility
matrix 重复。

#### Scenario: 验证 packaged V4 adapter
- **WHEN** release candidate 接受 validation
- **THEN** single major-V4 manifest、V4-only catalog 和 genesis、Hook discovery、MCP configuration、被引用的 playbook、schema 和 runtime file 均已存在且 portable

#### Scenario: 保持 controller facade isolation
- **WHEN** controller 直接在 `-I -S` 下启动，或通过 `spec_from_file_location` 加载两个 independent facade module
- **THEN** 每个 facade 初始化完整且 sealed V4 registry、catalog 和 `RuntimeServices`，同时其 monkeypatch-visible operation、filesystem cache 和 `ContextVar` value 保留已记录的 facade-local identity

#### Scenario: 验证 native MCP launch command
- **WHEN** candidate 在 native macOS 上接受 validation
- **THEN** validation 选择其 packaged POSIX profile，并通过准确的 configured command 证明 initialize 和 tool-list，而不是直接调用 Python server

#### Scenario: 引入 third-party runtime import
- **WHEN** shipped controller、Hook 或 MCP runtime file 导入未声明的 third-party module
- **THEN** isolated runtime audit 指出该 import 并阻止 packaging

#### Scenario: 禁用捆绑的 MCP
- **WHEN** 用户禁用 plugin-scoped MCP server
- **THEN** package validation 以及 current V4 CLI、Hook 和 Skill fallback 仍然 valid

#### Scenario: 执行 real-host acceptance
- **WHEN** reviewed V4 candidate 交给用户进行 Codex-host testing
- **THEN** 用户替换 prior installation、验证一个 enabled plugin 以及 Hook 和 MCP 均被发现，并运行一次 real-project V4 smoke，且不执行 legacy-data test

## REMOVED Requirements

### Requirement: The JSON CLI remains a complete compatibility and recovery surface
**Reason**: compatibility grammar、schema-v1/schema-v2 semantics 和 legacy response branch 已移除；CLI 现在直接表示唯一的 V4 runtime。

**Migration**: 无。deployment 中不包含 historical runtime data 或 legacy client。
