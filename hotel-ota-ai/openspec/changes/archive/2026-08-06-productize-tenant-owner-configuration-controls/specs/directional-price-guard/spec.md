## ADDED Requirements

### Requirement: New price guard policies use directional thresholds
Every new price guard policy MUST include `max_increase_pct`, `max_decrease_pct`, `min_increase_pct`, and `min_decrease_pct`. Each minimum MUST be less than or equal to its matching maximum.

#### Scenario: Incomplete new policy
- **WHEN** a caller creates a new policy without one directional threshold
- **THEN** the runtime MUST reject the request

### Requirement: Legacy policy remains readable
An existing policy that has only `max_single_change_pct` MUST resolve as both maximum thresholds with zero minimum thresholds.

#### Scenario: Read legacy single-cap policy
- **WHEN** the active stored policy has `max_single_change_pct=0.12` and no directional columns
- **THEN** the resolved policy MUST expose both maximum thresholds as `0.12` and both minimum thresholds as `0`

### Requirement: Directional checks are bound to approval
The price guard MUST validate increase and decrease ranges separately. A no-change request MUST return `no_effective_change` and MUST NOT create a formal approval. Hashes for formal approval and execution handoff MUST include all directional thresholds and policy identity.

#### Scenario: Decrease below effective minimum
- **WHEN** the trusted old price is 100 and a policy has `min_decrease_pct=0.05`
- **THEN** a new price of 98 MUST be rejected as below the effective decrease threshold
