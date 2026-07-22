# OpenSpec route

## Discover the installed workflow

Treat the target project's generated OpenSpec skills and CLI JSON as authoritative. Do not embed a proposal/design/spec/tasks phase sequence; schemas and available actions may differ.

1. Resolve the OpenSpec planning root from the controller-recorded implementation worktree, never from the source or detached analysis worktree. If the user names a registered store, discover and retain its store ID and pass it to supported commands.
2. Confirm `openspec` is available.
3. Enumerate `.codex/skills/openspec-*/SKILL.md` under the resolved project root. Read each candidate's frontmatter description and read the full body of the skill relevant to the next requested action.
4. If OpenSpec or the generated skills are absent, stop at the planning gate. Offer initialization or update as an explicit repository-changing action. Run `openspec init <implementation-worktree> --tools codex` or `openspec update <implementation-worktree>` only after approval, then rediscover the generated skills.
5. Never substitute bundled memories of an older OpenSpec workflow for missing current guidance.

## Start a new OpenSpec change

Use the generated skill whose description covers proposing or creating a change. Let that skill and current CLI choose identifiers, artifacts, and ordering. Preserve the resulting change name and planning root in workflow evidence.

After every OpenSpec action, run:

```text
openspec status --change "<change>" --json [store arguments]
```

Parse `schemaName`, planning/change roots, action context, artifact identifiers, concrete paths, dependencies, statuses, and completion. Never infer these from conventional filenames.

For each ready artifact or action, request current instructions:

```text
openspec instructions <artifact-or-action> --change "<change>" --json [store arguments]
```

Follow the returned `instruction`, `context`, `rules`, `template`, dependencies, output path, and concrete context files. Treat context/rules as authoring constraints, not content to paste into artifacts. Re-run status after writing and confirm expected outputs exist.

## Resume an OpenSpec change

Use the change identity stored in workflow state. Query `status --json` before reading or changing artifacts, even if the conversation remembers the previous step. Rediscover generated skills after an OpenSpec update.

If state and CLI disagree:

- adopt existing artifacts only after checking their concrete paths and content against the recorded task;
- record new hashes rather than recreating equivalent artifacts;
- pause on a different change root, schema, or intent;
- never create a second change merely to escape ambiguous resume state.

Use the current generated update/continue/apply skill that matches the needed action. If status reports blocked artifacts, obtain the indicated dependency instructions instead of forcing a later step.

## Reach the planning gate

Use status and the current action instructions to determine when implementation is ready. Read every concrete planning file returned for the apply action, across all participating repositories or stores. Present to the user:

- change ID, schema, planning root, and affected repositories;
- requirement and scenario coverage;
- design and compatibility decisions;
- task order, tests, migrations, rollout, rollback, and unresolved questions;
- status-reported missing or blocked artifacts.

Record the apply-ready change directory reported as `changeRoot` (normally `openspec/changes/<change-id>`) with `record-artifact --kind openspec-plan`; let the controller recursively hash its complete contents. Bind plan approval to that returned hash. Obtain explicit approval before invoking implementation guidance or editing application code.

## Implement and verify

After approval, use the current generated apply skill and re-query `openspec status --json` plus `openspec instructions apply --json` on every resume. Read all `contextFiles` returned by the CLI. Work only in the workflow's recorded isolated worktrees.

When implementation invalidates an artifact, stop and use the current generated update guidance. Re-present material scope or contract changes for approval before continuing.

If implementation changes anything under the recorded OpenSpec change directory, including task-progress checkboxes, return to `PLANNING` with a reason before verification. Query current status/instructions, record the current `changeRoot` again as `openspec-plan`, and obtain a new plan approval. Then return through `IMPLEMENTING` and `VERIFYING`, recording a new passing result for every configured repository after that approval. Do not record an `openspec-plan` while in an implementation, verification, review, or finalization state.

Use the current generated verification skill, if present, as supplementary evidence. Independently review the complete Git snapshot with `$review-dev-flow-change`; OpenSpec verification never constitutes the workflow's final gate by itself.

Do not archive, sync, or otherwise finalize the OpenSpec change automatically. Present those actions separately after review and execute them only with explicit user authorization and current generated guidance.
