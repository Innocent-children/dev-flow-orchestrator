# Promotion Kit

This file prepares repository and launch copy. Applying GitHub settings,
publishing a Release, and posting to external communities remain operator-owned
actions.

## GitHub About

**Description**

```text
A local-first workflow controller that keeps Codex development tasks resumable, verifiable, and aligned across 1–8 Git repositories.
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
ai-coding-agent
developer-workflow
agentic-coding
software-delivery
workflow-engine
multi-repository
git
python
```

## v0.2.0 Release draft

**Title:** Dev Flow Orchestrator v0.2.0 — resumable multi-repository delivery for Codex

**Summary**

Dev Flow Orchestrator 0.2.0 keeps long-running Codex development tied to one
explicit delivery contract across one to eight local Git worktrees. A task can
survive Codex session changes, reject stale work, require structured
verification and review evidence, and finish with a Delivery Dossier that makes
gaps visible instead of hiding them in a final chat summary.

**Highlights**

- Resume the same task by ID from any member repository.
- Coordinate an immutable set of 1–8 user-prepared Git worktrees.
- Choose from six workflows: `lite`, `feature`, `bugfix`, `investigation`,
  `refactor`, and `full`.
- Bind acceptance criteria to per-repository and integration verification.
- Route failed verification or review through bounded rework.
- Preserve local state and produce a final `DONE` or `INCOMPLETE` Delivery
  Dossier.

**Try it**

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

Current platform support is macOS with Python 3.9–3.14, Git, and Codex
plugin/Hook support. The installer selects authoritative `main` explicitly and
only fast-forwards an existing clean `main` checkout from the expected origin.
It refuses an ignored local path that the incoming commit would overwrite and
preserves unrelated ignored content; other unsafe checkout states require
manual intervention. Review the installed Hook in `/hooks` before trusting it.

## Show and tell draft

**Title:** I built a local state machine so Codex tasks can survive sessions and span repositories

Codex rarely struggles with writing the next function. The harder problem in
my older projects was delivery state: after a session change, which acceptance
criteria were still open, which repository had been verified, and whether the
final answer reflected current code.

I built Dev Flow Orchestrator to put that state outside the conversation. It
binds one requirement to an exact repository set, exposes one authoritative
next action, rejects stale evidence, and generates a Delivery Dossier at the
end. The controller stays local; Codex still performs the implementation.

The 0.2.0 release supports six workflow depths and one to eight prepared Git
worktrees on macOS. I would especially value feedback on the first-install
experience and whether the cross-session demo makes the distinction from
prompts, `AGENTS.md`, and specification tools clear.

Repository: https://github.com/Innocent-children/dev-flow-orchestrator

## 中文发布草稿

**标题：** 我给 Codex 加了一个本地状态机，让跨会话、跨仓库开发不再丢交付状态

Codex 通常不缺写下一段代码的能力。真正困扰我的，是历史项目里的交付状态：切换会话
以后还有哪些验收标准没完成、哪个仓库尚未验证、最终总结是否对应当前代码。

因此我做了 Dev Flow Orchestrator。它把一项需求绑定到精确的仓库集合，每次只给出一个
权威下一动作，拒绝过期证据，并在结束时生成 Delivery Dossier。状态保存在本地，实际
实现仍由 Codex 完成。

0.2.0 版本在 macOS 上支持六种工作流深度和 1–8 个预备 Git 工作树。我尤其希望获得
关于首次安装体验，以及“跨会话恢复”演示是否清晰的反馈。

仓库：https://github.com/Innocent-children/dev-flow-orchestrator

## Launch checklist

1. Merge the promotion branch and verify that the raw `main` installer URL is
   available.
2. Set the About description and topics above.
3. Publish the v0.2.0 Release with the prepared notes.
4. Submit the repository to an appropriate Codex plugin directory.
5. Post the problem-led launch story and demo to the Codex community.
6. Ask 5–10 Codex users to install without guidance; record where they stop.
7. After each channel, compare GitHub Traffic visitors, clones, referrers, and
   popular content over the same 14-day window.
