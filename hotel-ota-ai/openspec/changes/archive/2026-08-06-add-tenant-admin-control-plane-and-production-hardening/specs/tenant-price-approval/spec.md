## ADDED Requirements

### Requirement: Price guards are versioned by hotel and room type
The runtime MUST resolve price guard policy by hotel id, room type id, effective interval, and policy version.

#### Scenario: Inactive policy
- **WHEN** no active policy exists for the requested hotel, room type, and business time
- **THEN** formal approval and execution handoff MUST be blocked

### Requirement: Formal approval does not execute a channel write
Formal price approval MUST bind hotel id, room type, old price, policy version, fresh/current data, requester, approver, and payload hash, but MUST NOT call an OTA or PMS adapter.

#### Scenario: Approved price request
- **WHEN** a valid distinct approver approves a fresh price request
- **THEN** the request status MAY become approved and live execution count MUST remain zero
