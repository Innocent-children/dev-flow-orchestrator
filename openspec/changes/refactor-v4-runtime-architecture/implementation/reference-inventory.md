# Greenfield Reference Inventory

本 inventory 只回答“真实 product 需要什么”和“哪些安全 invariant 必须保留”。它不把
当前 function、class、module、call graph、registry 或 response shape 当作新实现
contract。

## User journeys

1. 用户配置 plugin scope，选择在哪些 directory 启用。
2. 用户显式选择 `full@4` 或 `lite@4`、workspace strategy，并提供一个或多个
   repository。
3. controller 在 repository 外创建 schema-v4 task state。
4. 用户或 Codex 查询当前 node、允许 action 和所需 evidence。
5. controller 执行 preflight；full workflow 再执行 baseline、impact、route、
   workspace 和 planning，lite workflow 直接进入 implementation。
6. 一个或多个 repository worker 在明确 authority 和 path scope 内工作。
7. controller 接收 artifact、test、review、repository result 和 external-tool
   evidence。
8. controller 对 effect interruption 进行 inspect、settle、reattach、abandon、
   compensate 或 operator intervention，不猜测完成。
9. controller 在验证和 review 后 finalization；Git-changing action 始终显式授权。

## Public capability disposition

| Current command/capability | Decision | Greenfield capability |
|---|---|---|
| `start` | rebuild | 显式 workflow、topology、workspace 和 repository set；四 profile |
| `show` / `agent-v1` | rebuild | bounded current-node projection |
| `preflight` | rebuild | current macOS Git read evidence |
| `list` | rebuild later | data-dir task summaries，不读取 repository |
| `scope` | rebuild later | `allowlist`/`all` 和 include/exclude directory |
| gated action confirmation | rebuild | first exact apply creates a durable request; later exact `UserPromptSubmit` records a decision; a fresh projection permits only an exact retry |
| `baseline` | rebuild for full | baseline evidence node |
| `record-index` | simplify | generic bounded evidence record node |
| `set-route` | rebuild for full | impact-bound route node |
| `prepare-workspace` | rebuild | explicit workspace strategy 与 gated Git effect |
| `record-artifact` | simplify | one artifact reference contract |
| `record-test` | rebuild | current-revision test evidence |
| `review-snapshot` | rebuild for full | immutable review snapshot |
| `transition` | drop as generic escape hatch | public action resolves exact node action |
| `cancel` | rebuild | current scope cancellation node |
| `manager-authorize` / `manager-revoke` | simplify later | repository manager authority node |
| `action-recovery-inspect` | rebuild | read-only current effect projection |
| `action-recovery-preview` / `apply` | rebuild | explicit recovery node action |
| `recover-atomic-write` | simplify into store invariant | public command only if a real greenfield failure requires operator choice |
| `recover-quarantine` | replace | current effect quarantine/recovery node |
| MCP tools | rebuild | thin projection/apply adapter |
| Hooks | rebuild | scope-aware advisory guardrail |
| Skill | rebuild | current-node dispatcher |

## Workflow capability disposition

### Shared by `full@4` and `lite@4`

- intake and explicit product selection;
- preflight;
- implementation;
- test evidence;
- task completion;
- block, cancel and current effect recovery;
- single- and multi-repository topology;
- repository ownership, result and barrier kernel;
- state revision, lock, atomic replace and receipt;
- scope-aware Hook, CLI and optional MCP access.

### Full-only workflow depth

- baseline capture;
- codebase-memory baseline/current phase separation;
- impact analysis;
- route approval;
- managed worktree planning;
- explicit plan approval;
- independent review;
- finalization gate.

### Lite workflow depth

- bounded target-path declaration;
- no workflow-entry approval; single-repository Lite enters implementation and
  multi-repository Lite enters the shared repository-plan node after preflight;
- current test evidence;
- no implicit baseline/impact/route/plan/review node.

Multi-repository is not full-only. Lite multi-repository uses the same shared
repository nodes and their own declared authority contracts without a Lite
entry gate.

## Safety invariants to rebuild

| Boundary | Required invariant |
|---|---|
| task state | schema v4 only; state outside repository; private directory/file |
| mutation | one controller writer; expected revision; task lock; atomic replace |
| workflow | exact current bundle/profile; deterministic node placement; bounded write set |
| Git | argument-vector subprocess; read/write separation; mutation only after explicit authority |
| repository | canonical identity; exclusive writable ownership; deterministic ordering |
| effect | durable claim before dispatch; single dispatcher; idempotency binding |
| receipt | target/action/attempt/profile/revision binding; replay-safe |
| recovery | no caller assertion as proof; scope blocking; target-bound observation |
| compensation | diagnose unavailable host capability before confirmation; conversation agreement is not effect or compensation proof |
| Hook | advisory and fail open on internal errors; only `UserPromptSubmit` may forward bounded decision evidence and it cannot apply a transition |
| MCP/CLI/Skill | wire adapter only; cannot write state or implement workflow policy |
| evidence | bounded structured record; digest and current-revision binding |
| privacy | secret, token, credential and raw unbounded output never enter model-visible receipt |

Conversation confirmation records the local execution account, session, turn,
prompt digest and actor role separately. These fields are correlation and audit
evidence, not macOS or authenticated-human identity and never fabricate a
second person. Full review evidence remains an independently produced
read-only review fingerprint explicitly confirmed through the same exact
conversation lifecycle, not a role-qualified actor string.

## Failure modes to design explicitly

- invalid or duplicate repository;
- repository ownership conflict;
- stale revision or lost mutation receipt;
- Git executable/output unavailable;
- task lock or atomic replace failure;
- product/profile asset drift;
- action requested outside its node;
- undeclared state write or effect;
- process interruption before claim, after claim or after external completion;
- duplicate dispatch, receipt replay or conflicting replay;
- repository drift before result acceptance;
- partial multi-repository completion;
- barrier member invalidation;
- cancellation while effect is live;
- no trusted host recovery authority;
- Hook or MCP unavailable;
- oversized or malformed evidence.

## Explicitly dropped obligations

- task schema v1/v2/v3 inspection, validation, rejection, migration or recovery;
- V2/V3 bundle, handler, oracle, ledger, fallback or predecessor provenance;
- shared-global facade identity and monkeypatch compatibility;
- old internal Python symbol and response compatibility;
- Windows/Linux launcher, lock, path, Git or CI parity;
- dynamic handler/plugin registration;
- target-repository executable workflow override;
- automatic stash, reset, clean, commit, push, force-push, rebase or merge.
