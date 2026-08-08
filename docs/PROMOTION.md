# Promotion Kit

This file prepares repository and launch copy. Applying GitHub settings,
publishing a Release, enabling a plugin in a host, and posting to external
communities remain operator-owned actions.

## GitHub About

**Description**

```text
A local-first workflow controller that keeps Codex development tasks resumable, verifiable, and aligned across 1–8 prepared Git worktrees.
```

**Website**

```text
https://github.com/Innocent-children/dev-flow-orchestrator#readme
```

**Topics**

```text
codex
openai-codex
codex-plugin
mcp
model-context-protocol
ai-coding-agent
developer-workflow
software-delivery
workflow-engine
multi-repository
git
python
```

## v0.5.0 Release draft

**Title:** Dev Flow Orchestrator v0.5.0 — MCP-first, resumable delivery for Codex

**Summary**

Dev Flow Orchestrator 0.5.0 replaces its installed Skill-and-Hook interaction
path with one local STDIO MCP server. Five read tools and six mutation tools
connect Codex to the same Controller authority used by the CLI and read-only Web
UI. The persisted model remains `0.4.0`, so existing 0.4.x tasks resume without
state or byte migration.

**Highlights**

- Discover, inspect, start, resume, govern, and cancel a task through exactly
  eleven typed `dev_flow_*` tools.
- Keep one requirement bound to an immutable set of 1–8 user-prepared Git
  worktrees, with one current action and exact mutation binding at a time.
- Use bounded, action-specific guidance for all six workflows: `lite`,
  `feature`, `bugfix`, `investigation`, `refactor`, and `full`.
- Preserve structured contracts, causal review, finite assurance and rework,
  current evidence, and terminal `DONE` or `INCOMPLETE` Delivery Dossiers.
- Install an exact-lock managed MCP runtime outside source and task data, with
  an identity-bound receipt, staged activation, rollback, and marker-scoped
  uninstall.
- Keep the Controller as the only transition writer. MCP does not add generic
  shell, branch/worktree management, Git publication, external CI/PR/release
  dispatch, or parallel-agent execution.

**Current evidence and platform boundary**

The current local macOS evidence exercises the official MCP client over real
STDIO through both the source launcher and the activated managed PATH launcher.
It covers the exact catalog and tool mappings, closed protocol bounds, action
guidance, cancellation and disconnect recovery, six-workflow focused and
closed-trigger routes, multi-member restart/resume, a task created by the 0.4.2
CLI, governing-resource and causal-review paths, contract revision,
corrupt-inventory admission failure, linked-worktree concurrency, and terminal
Dossiers. A fully isolated Codex 0.146.0 profile enabled the bundled plugin,
reported exactly one enabled `dev-flow` STDIO registration, completed an
idempotent repair, discovered an existing `0.4.0` task through the default
installed data path, and completed the full workflow journey. Marker-scoped
uninstall then removed the plugin, registration, launchers, and managed runtime
while preserving the source and byte-identical current and retained
prior-version task namespaces.

The PowerShell installation and lifecycle paths for Windows 10 22H2 x64 and
Windows 11 x64 remain preview paths until the native client matrix is actually
run and recorded. Windows Server automation, static checks, WSL/Wine, macOS
results, and skipped tests are not native Windows client evidence. Repository
tests and the isolated local-host evidence do not establish that a
different external Codex installation has enabled or discovered the server;
verify each target installation directly before publishing a host-specific
claim.

**Try it on macOS**

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

The installer selects authoritative `main`, validates the candidate, builds
the locked managed runtime, installs the `dev-flow-mcp` PATH launcher, and
activates bundled plugin registration. It refuses unsafe checkout states and
duplicate enabled standalone registration. Review every mutation approval and
never blindly replay a mutation after cancellation or a lost response.

## Show and tell draft

**Title:** I moved my local Codex delivery state machine to an eleven-tool MCP interface

Codex rarely struggles with writing the next function. The harder problem in
my older projects was delivery state: after a session change, which acceptance
criteria were still open, which repository had current evidence, and whether
the final answer reflected the current code.

I built Dev Flow Orchestrator to put that state outside the conversation. It
binds one requirement to an exact set of prepared worktrees, exposes one
authoritative next action, rejects stale evidence, routes verification and
review through finite assurance, and generates a Delivery Dossier at the end.
The Controller stays local; Codex still performs the implementation.

Release 0.5.0 makes a single local STDIO MCP server the primary Codex interface.
Its eleven closed tools and bounded current-action guidance replace the former
installed Skills and fail-open Hook while keeping existing 0.4.x task data
compatible. Current local delivery evidence is from macOS; the native
Windows client gate remains open and the PowerShell path is still preview.

I would especially value feedback on first install, cross-session resume, and
whether the distinction from prompts, `AGENTS.md`, and specification tools is
clear.

Repository: https://github.com/Innocent-children/dev-flow-orchestrator

## 中文发布草稿

**标题：** 我把 Codex 本地交付状态机迁移到了一个包含十一个工具的 MCP 接口

Codex 通常不缺写下一段代码的能力。真正困扰我的，是历史项目里的交付状态：切换会话
以后还有哪些验收标准没完成、哪个仓库拥有当前证据、最终总结是否对应当前代码。

因此我做了 Dev Flow Orchestrator。它把一项需求绑定到一组精确的预备工作树，每次只
暴露一个权威下一动作，拒绝过期证据，让验证与审查遵循有限保障，并在结束时生成
Delivery Dossier。Controller 保持本地运行，实际实现仍由 Codex 完成。

0.5.0 使用一个本地 STDIO MCP 服务器作为主要 Codex 接口。十一个闭合工具和有界的
当前动作 guidance 取代此前已安装的 Skills 与 fail-open Hook，同时保持现有 0.4.x
任务数据兼容。当前本地交付证据来自 macOS；原生 Windows 客户端门禁尚未完成，
PowerShell 路径仍为预览。

我尤其希望获得关于首次安装、跨会话恢复，以及它与 prompts、`AGENTS.md` 和规格工具
之间区别是否清晰的反馈。

仓库：https://github.com/Innocent-children/dev-flow-orchestrator

## Launch checklist

1. Merge the promotion branch and verify that the raw `main` installer URL is
   available.
2. Rerun strict OpenSpec validation, package validation, full unittest
   discovery, the full MCP journey through the activated PATH launcher, and
   lifecycle checks against the exact tracked release candidate; record every
   skip or unavailable environment.
3. Run and record the native Windows 10 22H2 x64 and Windows 11 x64 client
   matrix before changing the preview wording or making a Windows support
   claim.
4. On each target Codex installation, confirm directly that exactly one
   `dev-flow` registration is enabled and that its tool catalog matches the
   candidate.
5. Set the About description and topics above.
6. Publish the v0.5.0 Release with the prepared notes and the recorded platform
   limitations.
7. Submit the repository to an appropriate Codex plugin directory and post the
   problem-led launch story and demo to the Codex community.
8. Ask 5–10 Codex users to install without guidance; record where they stop.
9. After each channel, compare GitHub Traffic visitors, clones, referrers, and
   popular content over the same 14-day window.
