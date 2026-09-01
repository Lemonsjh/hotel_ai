## ADDED Requirements

### Requirement: Management status is read-only and tenant-scoped
The runtime MUST offer protected read-only management intents for member-role status, room price guard status, pending configuration requests, and audit summary. They MUST resolve hotel scope from trusted V3 authorization and MUST NOT mutate configuration.

#### Scenario: Operator requests management status
- **WHEN** an operator requests a protected management status
- **THEN** the runtime MUST block the request without returning role-map or policy details

### Requirement: Management output is redacted
Normal Feishu management output MUST NOT include principal identifiers, raw role-map contents, private paths, raw JSON, or callback payloads.

#### Scenario: Owner views a guard summary
- **WHEN** an authorized Owner requests a price guard status
- **THEN** the response MUST contain only the approved summary fields and MUST omit all internal identifiers and private paths

### Requirement: Card backend remains transport-neutral
Card previews and callbacks MUST use sealed request id, nonce, expiry, and payload hash checks. The runtime MUST NOT assume a native Feishu callback event shape until a verified redacted event sample is available.

#### Scenario: Unverified callback transport
- **WHEN** no verified native Feishu callback event schema has been configured
- **THEN** the runtime MUST expose only the platform-neutral sealed card contract and MUST NOT register a production callback handler
