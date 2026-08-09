## ADDED Requirements

### Requirement: Package validation checks current public semantics

The package validator SHALL execute structured checks that public commands have packaged
launchers, bundled-only behavior matches lifecycle parameters, English/Chinese support
claims agree, source retention and exact runtime ownership match implementation, and
current existing specifications match packaged assets.

#### Scenario: Tokens remain but product semantics drift

- **WHEN** a launcher or parameter is removed, language support modes diverge, standalone
  or Hook claims reappear, or retention claims oppose implementation while tokens remain
- **THEN** package validation SHALL fail

#### Scenario: Historical governance files are absent

- **WHEN** intentionally deleted OpenSpec or validation-report files are absent
- **THEN** validation SHALL evaluate current tracked authority without requiring restore

### Requirement: Current repository truth supersedes obsolete audit references

Only currently tracked specifications and evidence links SHALL be authoritative. Deleted
obsolete Hook/Skills specifications and stale validation reports SHALL NOT be restored or
represented as current evidence.

#### Scenario: No equivalent current conflict exists

- **WHEN** current tracked files contain neither the obsolete requirement nor a reference
  to the deleted report
- **THEN** the audit finding SHALL be recorded as not reproducible on the current HEAD

#### Scenario: A current conflict remains

- **WHEN** a currently tracked document or specification contains an equivalent conflict
- **THEN** only that current file SHALL be corrected and validated
