## ADDED Requirements

### Requirement: Feishu configuration mutations require a two-person card workflow
The runtime MUST create opaque, expiring configuration requests and require a distinct authorized approver before role-map or price-guard state can change.

#### Scenario: Self approval
- **WHEN** the requester attempts to approve their own configuration request
- **THEN** the request MUST remain pending and an audit event MUST record the rejection

#### Scenario: Replayed card callback
- **WHEN** an already consumed, expired, or mismatched nonce is submitted
- **THEN** the runtime MUST reject it and MUST NOT change configuration state

### Requirement: Audit events are tenant scoped and chained
Every configuration request transition MUST create an insert-only audit event containing the tenant scope, actor role, action, payload hash, previous hash, and event hash.

#### Scenario: Audit query outside membership
- **WHEN** a non-admin user requests audit entries for another hotel
- **THEN** the runtime MUST reject the query without returning event details
