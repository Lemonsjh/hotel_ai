## ADDED Requirements

### Requirement: Canonical inbound events are claimed before an Agent turn
The plugin MUST use OpenClaw canonical inbound fields when they are present and MUST claim every message for a configured hotel account, including rejected and failed messages.

#### Scenario: Canonical group event
- **WHEN** a configured Feishu account emits an event with `conversationId`, `senderId`, and `isGroup=true`
- **THEN** authorization receives those values as chat, sender and group context and the handler returns `handled=true`

### Requirement: V3 preview reports tenant membership statistics
The role-map preview MUST calculate V3 counts from global administrators, hotel memberships and group bindings rather than legacy user role fields.

#### Scenario: V3 role-map preview
- **WHEN** a valid V3 role map contains one global administrator and two hotel memberships
- **THEN** the preview reports nonzero administrator, membership, hotel and group-binding counts
