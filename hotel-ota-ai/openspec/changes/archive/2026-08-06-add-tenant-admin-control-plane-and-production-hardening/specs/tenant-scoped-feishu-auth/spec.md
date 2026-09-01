## ADDED Requirements

### Requirement: V3 role-map tenant scope
The runtime MUST support a V3 private role-map with globally unique canonical identities, global admins, hotel memberships, group chat bindings, and a direct-message policy. V2 role-map input MUST remain read-compatible.

#### Scenario: Cross-tenant request
- **WHEN** an authenticated owner sends a request for a hotel outside that user's membership
- **THEN** the runtime MUST reject the request before a business result is built

#### Scenario: Direct message without selected hotel
- **WHEN** a V3 direct-message user has more than one hotel membership and no explicit server-side selection exists
- **THEN** the runtime MUST return a tenant-selection response and MUST NOT choose a hotel implicitly

### Requirement: Group binding is authoritative
A V3 group chat binding MUST resolve exactly one hotel id and a caller-provided hotel id MUST NOT override it.

#### Scenario: Forged hotel id
- **WHEN** a group-bound request supplies a different hotel id
- **THEN** the runtime MUST reject it as a tenant scope mismatch
