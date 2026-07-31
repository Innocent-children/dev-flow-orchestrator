## ADDED Requirements

### Requirement: Package nodes are direct V4 modules
Every current workflow node, guard, reducer and effect executor SHALL resolve
to a direct importable V4 function in the greenfield package. A package-owned
static catalog SHALL bind stable IDs to callable objects through normal Python
imports. Runtime registration, global symbol lookup, predecessor wrapper and
target-repository executable extension are forbidden.

#### Scenario: Resolve a current node
- **WHEN** the controller loads a node referenced by `full@4` or `lite@4`
- **THEN** the static catalog returns one direct greenfield callable with its explicit node contract

#### Scenario: Attempt runtime registration
- **WHEN** code attempts to add or replace a node after package import
- **THEN** the product catalog remains unchanged and validation rejects the mutation path

### Requirement: Node execution returns plans instead of mutating
Guard and node evaluation SHALL be pure over an immutable projection. Reducer
behavior SHALL return a bounded mutation plan whose JSON-pointer write set is
declared by the node contract. Only the controller mutation boundary may apply
that plan.

#### Scenario: Evaluate an eligible action
- **WHEN** a current projection satisfies one node's guards
- **THEN** evaluation returns a deterministic plan and performs no state or external write

#### Scenario: Return an undeclared write
- **WHEN** a node plan includes a JSON pointer outside its contract
- **THEN** the controller rejects the plan before state commit or effect dispatch

#### Scenario: Submit an invalid effect payload
- **WHEN** an effectful action omits a required field or includes an undeclared or invalid field
- **THEN** pure payload validation rejects it before authority confirmation, journal claim or effect dispatch

### Requirement: Action placement is V4-only and node-exact
Every public V4 action SHALL appear at exactly one declared node placement or
one explicitly shared placement family. The placement MUST bind its guard,
mutation plan, effect port, receipt and recovery node without consulting a
schema selector or compatibility branch.

#### Scenario: Invoke an action at its node
- **WHEN** a caller requests an action at its declared current node
- **THEN** the engine evaluates that exact placement and its direct V4 contract

#### Scenario: Invoke an action elsewhere
- **WHEN** a caller requests the same action outside every declared placement
- **THEN** the engine returns a stable placement error without mutation or effect

## REMOVED Requirements

### Requirement: Runtime registries are unique and sealed
**Reason**: dynamic registry construction and sealing are replaced by a simple
static product catalog of directly imported callables.

**Migration**: Reimplement each required current node in the static greenfield
catalog; no runtime registration API remains.

### Requirement: Schema-v3 public actions are catalog-exhaustive and node-exact
**Reason**: task schema v3 and generation-bound action placement are not part of
the greenfield V4 product.

**Migration**: Current actions use the new V4-only node-exact requirement.
