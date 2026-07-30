## MODIFIED Requirements

### Requirement: Platform-specific bundled hook launch
初始 V4-only plugin SHALL（必须）为每个 bundled Codex Hook handler 注册供受支持
macOS host 使用的 portable `command` entry。每条 command MUST（必须）通过受支持的
interpreter 和对 plugin root 安全的 shell quoting 调用预期的 bundled handler。
本 release 不要求 Windows-specific `commandWindows` entry，也不要求 Linux
support claim。

#### Scenario: macOS Hook 从非简单插件路径启动
- **WHEN** Codex 在 macOS 上调用 bundled Hook，且 `PLUGIN_ROOT` 包含空格和 Unicode 字符
- **THEN** bundled `command` 启动预期的 Python handler，从 standard input 读取 JSON event，并输出有效的 Hook response

#### Scenario: Hook 注册指向唯一 V4 实现
- **WHEN** 检查 packaged Hook configuration
- **THEN** 每个 registered handler 都指向当前 V4 implementation，且不引用任何 predecessor workflow wrapper

### Requirement: Platform-specific MCP profiles use their native packaged launch commands
初始 V4-only package SHALL（必须）为受支持的 macOS host 提供一个默认禁用的 POSIX
MCP profile。focused validation MUST（必须）选择这一精确的 packaged profile，
并通过其 configured command 完成 MCP initialization 和 bounded tool discovery。
直接调用 underlying server MUST NOT（不得）替代 launcher proof。本 release 的
package SHALL（必须）不要求也不宣传 Windows 或 Linux MCP profile。

#### Scenario: 验证 macOS MCP 配置
- **WHEN** focused validation 在 native macOS 上选择 packaged POSIX profile
- **THEN** 其 configured command 从 plugin root 启动，并返回有效的 initialize response 和 bounded V4 tool list

#### Scenario: 拒绝多个已启用的 MCP 配置
- **WHEN** package validation 发现启用了多个 MCP profile
- **THEN** 在 plugin handoff 前拒绝这一 ambiguous configuration

### Requirement: Canonical Codex command matcher is preserved
Hook configuration SHALL（必须）在受支持的 macOS host 上，为 command-tool event
保留 canonical Codex `Bash` matcher。V4 cleanup MUST（必须）通过当前 launch
command 和 command-payload recognition 实现，而不是发明 undocumented tool alias。

#### Scenario: 验证打包后的匹配器
- **WHEN** 在 macOS 上检查 packaged Hook configuration
- **THEN** command-related handler 仍注册在 canonical `Bash` matcher 下，并指向当前 V4 code

### Requirement: Wrapped Git commands receive equivalent guardrails
command guard SHALL（必须）通过 executable basename 识别 `git`。它 SHALL（必须）
检查直接启动或通过 supported POSIX shell 启动的 current supported invocation，
包括 chained command 和 supported quoting form。等价的 protected Git mutation MUST（必须）得到相同
guardrail decision。已识别但无法安全解析的 wrapper payload MUST（必须）被阻止
并返回 diagnostic。Windows drive、UNC、`git.exe`、Command Prompt 和 PowerShell
parsing 不属于当前 macOS contract。

#### Scenario: 防护直接 Git 变更
- **WHEN** command 直接调用 protected Git mutation
- **THEN** Hook 识别该 invocation 并返回已记录的 denial result

#### Scenario: 防护 POSIX wrapper behavior
- **WHEN** supported POSIX shell 承载等价的 protected Git mutation
- **THEN** Hook 以相同 reason 识别并拒绝该 mutation

#### Scenario: 含糊的包装载荷安全失败
- **WHEN** 已识别 supported shell wrapper，但无法无歧义地拆解其 payload
- **THEN** Hook 使用 actionable parse diagnostic 阻止该 payload，而不是把它当作 non-Git command 放行

### Requirement: Skill commands preserve the injected executable prefix
所有 bundled workflow Skill SHALL（必须）复用 Hook 注入或 controller inspection
返回的 controller prefix。Skill MUST NOT（不得）用 hard-coded interpreter 重建该
prefix、遗漏显式 data directory，也不得生成 predecessor workflow command 或 field。
example SHALL（必须）使用有效的 macOS shell syntax 和当前 V4 controller operation。

#### Scenario: Skill 在 macOS 上继续执行
- **WHEN** agent 在 supported host 上遵循 bundled Skill
- **THEN** 每个 controller operation 都保留 injected interpreter 和 data-directory argument，并使用当前 V4 command model

#### Scenario: 审计生成的命令指引
- **WHEN** 扫描 packaged Skill Markdown 和 reference
- **THEN** 不存在重建 controller prefix 或引用 V2/V3 workflow selection、state 或 recovery 的 example

### Requirement: Installable package and manifest are internally complete
plugin manifest 和 package layout SHALL（必须）通过受支持 Codex plugin schema 的
validation，并 SHALL（必须）通过 official default discovery convention 暴露
`hooks/hooks.json`。package inventory MUST（必须）包含 manifest 或 published
documentation 所引用的所有当前 V4 runtime script、Hook、Skill asset、template 和
project-guidance file。引用的 local file 缺失、在受支持 filesystem 上存在 ambiguous
case spelling，或仅属于 predecessor workflow 时，release MUST（必须）失败。

#### Scenario: 插件清单通过验证
- **WHEN** plugin manifest validator 处理 release candidate
- **THEN** manifest 有效、不包含 unsupported Hook field，且每个 declared path 都解析到 package 内

#### Scenario: 默认 Hook 发现检查通过
- **WHEN** package/default-discovery validator 检查 frozen candidate
- **THEN** `hooks/hooks.json` 存在于 official location、是有效 Hook JSON，且每条 macOS command 都指向 packaged current V4 handler

#### Scenario: 包引用在受支持文件系统上可解析
- **WHEN** inventory validation 解析所有 manifest、Skill、template 和 documentation reference
- **THEN** 每个 reference 都精确指向一个 packaged file，stale 或 predecessor-only reference 会使 release 失败

### Requirement: English and Chinese documentation describe one platform contract
`README.md`、`README.zh-CN.md` 和 `INSTALL.md` SHALL（必须）一致描述一个仅支持
macOS 的 V4-only plugin、Python 和 Git prerequisite、installation/replacement
command、Hook 和 MCP launch behavior、focused validation，以及由 user 执行的三项
real-host acceptance。它们 SHALL（必须）不声明 Windows/Linux support，也不描述
V2/V3 selection、migration、inspection、recovery 或 fallback。

#### Scenario: 双语 V4 声明一致
- **WHEN** review 英文和中文 documentation set
- **THEN** 二者描述相同的 single plugin identity、V4-only workflow、supported macOS host、prerequisite、limitation 和 acceptance boundary

#### Scenario: 文档命令符合 macOS
- **WHEN** user 遵循已记录的 installation、replacement、validation 或 acceptance flow
- **THEN** 每个 example 都使用有效的 macOS shell syntax，并操作 packaged current V4 file 和 operation

#### Scenario: 文档不宣传缺失资产
- **WHEN** 对照 package inventory 检查 documentation link 和 local-path reference
- **THEN** 每个 referenced file 均已 packaged 且可读，否则 pre-release validation 失败
