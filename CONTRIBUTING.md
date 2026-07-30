# Contributing

Preserve the single V4 product boundary:

- task schema is v4;
- catalog entries are exactly `full@4` and `lite@4`;
- activation profiles are exactly the three declared V4 profiles;
- workflow-generation identities use direct V4 modules, handlers and
  registries;
- runtime code uses only the Python standard library;
- workflow state stays outside target repositories;
- Git-changing behavior stays deterministic and explicitly gated.

Use `codebase-memory` first for code discovery, then confirm material
conclusions in source. Query OpenSpec for current JSON status and
instructions; do not hard-code an artifact sequence.

Run only the smallest focused test modules that directly cover a change.
Running the full unittest suite or unittest discovery is prohibited. Validate
only the current macOS host.

Before handoff:

1. run the activation profile's exact focused suites;
2. validate every bundled Skill with `quick_validate.py`;
3. validate the plugin manifest and package;
4. run strict OpenSpec validation;
5. run `git diff --check`;
6. obtain an independent read-only implementation review.

Never reset, stash, clean, stage, commit, push, archive an active OpenSpec
change, or modify a target repository beyond the user's explicit authority.
