## 1. Skill Package

- [x] 1.1 Initialize `skills/dev-flow/` with the built-in Skill Creator and replace the scaffold with final `SKILL.md`, `agents/openai.yaml`, and `references/activation-and-routing.md` content.
- [x] 1.2 Register `./skills/` in `.codex-plugin/plugin.json` while preserving the existing `.mcp.json` bundled STDIO registration.
- [x] 1.3 Validate explicit `$dev-flow` metadata, enabled implicit invocation, and the absence of unsupported local-STDIO dependency metadata.

## 2. Package and Installed Validation

- [x] 2.1 Extend `scripts/validate_package.py` to require the exact Skill tree and validate frontmatter, Codex metadata, authority boundaries, manifest linkage, and package topology.
- [x] 2.2 Extend installed-stage validation to inspect the sealed installed Skill and report bounded Skill discovery evidence alongside the live MCP handshake and catalog.
- [x] 2.3 Preserve Skill files in managed-runtime integrity, ownership, repair, rollback, and isolated installation paths.

## 3. Regression Coverage

- [x] 3.1 Update package-validation tests for valid and malformed Skill manifests, frontmatter, interface/policy metadata, routing guidance, and unsupported dependency declarations.
- [x] 3.2 Update installer, managed-runtime, installed-journey, MCP-runtime, and topology tests to prove one installed copy exposes both the Skill and MCP without changing the tool catalog.
- [x] 3.3 Forward-test the Skill with representative explicit, implicit, ambiguous-discovery, and uncertain-mutation prompts without modifying production systems.

## 4. Documentation

- [x] 4.1 Update `README.md`, `INSTALL.md`, and `ARCHITECTURE.md` with the installed Skill experience, invocation routes, authority boundary, and validation evidence.
- [x] 4.2 Translate and synchronize the same product claims and constraints in `README_CN.md`, `INSTALL_CN.md`, and `ARCHITECTURE_CN.md`.

## 5. Verification

- [ ] 5.1 Run Skill Creator validation and the repository package validator.
- [ ] 5.2 Build and install the candidate into an isolated destination, then verify installed Skill discovery and MCP initialization/catalog availability.
- [ ] 5.3 Run focused tests, complete unittest discovery, strict OpenSpec validation, and all repository-defined release checks; record platform-specific limitations truthfully.
