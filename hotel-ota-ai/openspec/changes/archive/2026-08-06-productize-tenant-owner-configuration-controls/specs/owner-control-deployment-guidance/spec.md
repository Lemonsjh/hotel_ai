## ADDED Requirements

### Requirement: Migration and operational guidance preserves private boundaries
Deployment guidance MUST explain V3 role-map migration, legacy price policy read compatibility, plugin registry inspect/remove/reinstall workflow, and non-root preflight. It MUST state that repository deployment does not overwrite `/etc`, delete OpenClaw registry JSON manually, restart Gateway, or enable live execution.

#### Scenario: Plugin registry diagnostic
- **WHEN** a server has stale plugin installation diagnostics
- **THEN** the guidance MUST instruct an operator to inspect, remove, and reinstall through OpenClaw commands rather than manually deleting registry JSON
