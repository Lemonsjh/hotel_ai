## ADDED Requirements

### Requirement: Owner may manage ordinary members in scope
An Owner MUST be allowed to create and confirm a grant or revoke request for another existing V3 principal's `operator` or `frontdesk` membership in the Owner's own hotel. The approved request MUST enter the apply queue and MUST NOT write a private role-map directly.

#### Scenario: Owner grants an operator role
- **WHEN** an Owner requests and confirms an `operator` grant for another existing principal in the Owner's bound hotel
- **THEN** the request MUST become approved and queue exactly one pending apply record

### Requirement: Owner scope is fail-closed
An Owner MUST NOT change self membership, a role of `owner` or `admin`, a principal missing from the V3 role-map, or a membership in another hotel.

#### Scenario: Cross-hotel grant
- **WHEN** an Owner requests an `operator` grant for a different hotel
- **THEN** the runtime MUST block the request before it is persisted

### Requirement: Sensitive changes retain distinct approval
Owner membership and global administrative changes MUST continue to require two distinct global administrators.

#### Scenario: Global admin changes an Owner membership
- **WHEN** a global admin requests an Owner membership change
- **THEN** the same global admin MUST NOT approve it and a different global admin MUST be required
