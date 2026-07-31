# Contributing

Keep the architecture easy to trace:

- `product.py` owns the four-profile matrix;
- `workflow.py` owns full, lite, and shared repository node contracts;
- `engine.py` owns pure transition planning;
- `controller.py` is the only task-state writer;
- adapters parse and serialize only;
- runtime code uses only the Python standard library;
- task state stays outside target repositories;
- Git-changing effects remain deterministic, explicit, journaled, and gated.

Do not add dynamic source loading, a service locator, duplicate workflow
assets, or abstractions without a current second use.

Use `codebase-memory` for discovery and confirm material conclusions in source.
Ask OpenSpec for current JSON status and instructions instead of hard-coding a
phase sequence.

Run only the smallest focused test modules that cover the changed behavior.
Full unittest discovery is prohibited. Validate only the current macOS host;
do not infer Windows or Linux support.

Before handoff:

1. run the affected focused greenfield test modules;
2. validate every bundled Skill;
3. validate architecture, plugin manifest, package, and candidate inventory;
4. run strict OpenSpec validation;
5. run `git diff --check`;
6. obtain an independent read-only implementation review.

Never reset, stash, clean, stage, commit, push, or archive an active OpenSpec
change without explicit authority.
