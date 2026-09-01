## ADDED Requirements

### Requirement: Unknown MySQL schemas are inspected without writes
The adapter MUST inspect configured MySQL sources read-only and return table, column, candidate semantic fields, row count and freshness candidates without accepting free SQL.

#### Scenario: Incomplete mapping profile
- **WHEN** a required canonical field is not mapped
- **THEN** the adapter returns `data_gap` and identifies missing canonical fields without fabricating values
