## ADDED Requirements

### Requirement: Current V4 profiles are explicitly activated
The package-owned activation data SHALL contain exactly the four profiles from
the authoritative product matrix. New task creation MUST pin task schema v4,
the selected `full@4` or `lite@4` bundle identity and the selected repository
topology only after that exact profile's focused suites pass. No V2/V3,
inactive default, compatibility selector or repository-count fallback SHALL
participate in creation.

#### Scenario: Create each current profile
- **WHEN** each of the four exact V4 profiles is selected after its required suites pass
- **THEN** the first task revision records schema v4, exact bundle identity and selected repository topology

#### Scenario: Reject a partially ready profile
- **WHEN** one exact profile lacks its bundle identity or any required focused suite
- **THEN** only that profile is unavailable and no predecessor or sibling profile is substituted

### Requirement: Bundle activation derives from the product matrix
Bundle graph execution profiles, activation records, runtime selection and
verification suite selection MUST derive from or validate exact equality with
the package-owned product matrix. A bundle-specific implementation MAY add
node capability metadata but MUST NOT redefine the list of product profiles.

#### Scenario: Detect profile drift
- **WHEN** a bundle, activation record or runtime selector omits
  `lite@4`/`multi-repository` or defines a different profile set
- **THEN** package startup or validation fails before task creation

## REMOVED Requirements

### Requirement: Bundle-aware task creation is explicitly activated
**Reason**: 该 requirement 将 V3 task schema、release reservation 和旧的 profile
activation 混在一起，已由 current V4 four-profile activation contract 取代。

**Migration**: 无 historical data；实现只支持新的 schema-v4 product matrix。

### Requirement: Reserved bundle versions are immutable
**Reason**: 当前 product 是没有 predecessor exposure obligation 的 greenfield V4
package，不保留 append-only predecessor ledger 或 supersession proof。

**Migration**: 当前 candidate 使用新的 V4 provenance genesis；不读取或迁移旧
reservation。

### Requirement: Existing reserved V3 tasks fail closed without V4 substitution
**Reason**: 当前 deployment 不存在 V3 task，package 不包含 V3 inspection 或 recovery
path。

**Migration**: 无。
### Requirement: Schema-v1 and schema-v2 tasks use frozen legacy adapters
**Reason**: historical data 不在产品范围内，frozen adapter 会重新引入被明确排除的
compatibility architecture。

**Migration**: 无。
