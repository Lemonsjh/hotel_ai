## ADDED Requirements

### Requirement: S14 scores controlled Excel and MySQL facts through one canonical contract
S14 MUST normalize both supported source modes before calculating M01-M08. Missing facts MUST be reported and MUST NOT be invented.

#### Scenario: Excel fields are incomplete
- **WHEN** a valid uploaded workbook omits a required scoring field
- **THEN** S14 returns `partial` with missing fields and the resulting caps or confidence constraints

### Requirement: External report artifacts are safe by default
Each generated external report MUST use an unguessable report identifier, contain only aggregated redacted data, and return an HTTPS URL.

#### Scenario: Report artifact creation
- **WHEN** a diagnosis completes with a configured report publisher
- **THEN** the result contains a unique report identifier and an HTTPS report URL without customer identifiers
