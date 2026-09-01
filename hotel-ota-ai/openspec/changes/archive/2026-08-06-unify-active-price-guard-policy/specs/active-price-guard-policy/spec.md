## ADDED Requirements

### Requirement: Production price guard values come from one resolved policy
S5, S6 and Feishu policy status MUST use the same active SQLite policy for a hotel and room type. When no policy exists, the result MUST identify a controlled default policy.

#### Scenario: Active policy is present
- **WHEN** an active directional policy exists for a hotel room type
- **THEN** S5, S6 and the status query expose its version and directional thresholds

#### Scenario: Active policy is absent
- **WHEN** no active policy exists
- **THEN** the result uses a controlled default and identifies `source=default_policy`
