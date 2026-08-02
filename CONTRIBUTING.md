# Contributing

Keep the architecture easy to trace:

- `product.py` owns the schema/workflow version constants and the built-in
  workflow registry;
- `workflow.py` owns YAML document validation, node contracts, graph checks
  and the agent projection;
- `workflows.py` owns built-in file resolution and custom-path loading;
- `yaml_subset.py` owns strict YAML-subset parsing;
- `engine.py` owns pure transition planning and node handlers;
- terminal-node membership is the sole completion authority; never infer
  activity from a status label;
- persisted states must remain deterministically replayable and evidence is
  append-only;
- `controller.py` is the only task-state writer;
- adapters parse and serialize only;
- runtime code uses only the Python standard library;
- task state stays outside target repositories;
- Git access stays lock-free, bounded and read-only; never add automatic stash, reset, clean,
  force-push, or implicit commit behavior.

Workflow changes are YAML changes, not code changes — except when a node uses
a handler the runtime does not ship. Adding a handler is a vertical slice:
catalog entry, validation rule, and a focused test in one change.

Do not add dynamic source loading, a service locator, duplicate workflow
assets, or abstractions without a current second use. Keep the complexity
budget: the core should stay small enough that one person can hold it.

Use `codebase-memory` for discovery and confirm material conclusions in
source. Ask OpenSpec for current JSON status and instructions instead of
hard-coding a phase sequence.

Run only the smallest focused test modules that cover the changed behavior.
Full unittest discovery is prohibited. Validate only the current macOS host;
do not infer Windows or Linux support.

Before handoff:

1. run the affected focused `tests.test_v5_*` modules;
2. run `python3 -I -S scripts/validate_package.py`;
3. validate every bundled Skill;
4. run `git diff --check`;
5. obtain an independent read-only implementation review.

Never reset, stash, clean, stage, commit, push, or archive an active OpenSpec
change without explicit authority.
