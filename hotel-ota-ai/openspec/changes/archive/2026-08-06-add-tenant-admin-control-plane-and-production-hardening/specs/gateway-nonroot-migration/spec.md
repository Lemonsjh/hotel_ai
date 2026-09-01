## ADDED Requirements

### Requirement: Gateway hardening assets are preflighted before cutover
The repository MUST provide a non-root systemd migration template and a preflight that verifies read/write paths, private file permissions, and absence of required root capabilities without altering server state.

#### Scenario: Missing required private read access
- **WHEN** the configured `openclaw` service account cannot read a required private role-map or market-source file
- **THEN** the preflight MUST fail before any unit replacement or Gateway restart

### Requirement: Gateway has no private configuration write permission
The hardened Gateway unit MUST not receive write access to `/etc/hotel-ota-ai/`; role-map application MUST be documented as a separate narrow privileged helper operation.

#### Scenario: Role-map apply request
- **WHEN** an approved role-map request is queued
- **THEN** the Gateway MUST only record the queue entry and MUST NOT write the private role-map directly
