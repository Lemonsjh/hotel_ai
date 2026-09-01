## ADDED Requirements

### Requirement: Runtime authorizes daily Feishu requests from SQLite active auth
For a configured hotel account, the plugin MUST claim inbound traffic and the runtime MUST use SQLite principals, memberships and group bindings before JSON bootstrap data.

#### Scenario: SQLite active membership
- **WHEN** a group binding and matching member exist in SQLite
- **THEN** runtime authorizes the member for the bound hotel without reading a JSON business role

#### Scenario: SQLite unavailable
- **WHEN** SQLite authorization cannot be read
- **THEN** non-admin business access is denied and only a JSON bootstrap global administrator may receive an emergency read-only result

### Requirement: Chat configuration requests require a second confirmation
Configuration text MUST create a sealed pending request. It MUST NOT modify policy or membership until an eligible identity confirms the request before expiry.

#### Scenario: Operator price request
- **WHEN** an operator requests a price guard change
- **THEN** the request is `pending_owner_approval` and only an in-scope owner or global admin can confirm it

#### Scenario: Owner confirmation
- **WHEN** an owner confirms their own valid in-scope request
- **THEN** the request becomes confirmed, the transaction applies the change, and an audit event is appended
