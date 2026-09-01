## ADDED Requirements

### Requirement: Production Feishu must not emit sample snapshot business values

When handling production Feishu business requests, the runtime MUST NOT use demo/sample snapshot values as business evidence.

#### Scenario: Production Feishu lacks real demand context

- **WHEN** `production_feishu=True`
- **AND** the requested business decision lacks real `demand_context` / OTA health evidence
- **THEN** the result is `data_gap` or has equivalent missing-data semantics
- **AND** business numeric fields derived from sample snapshot are `null` / absent
- **AND** output does not contain `170`, `107`, `5.74`, `58`, `sample_data`, or `demo_data` as production evidence

### Requirement: Demo sample snapshot is explicit local/demo-only fixture

The sample snapshot helper MUST be named or guarded so callers cannot treat it as production data accidentally.

#### Scenario: Local demo path asks for sample fixture

- **WHEN** a local demo/test path explicitly requests the demo sample fixture
- **THEN** the runtime MAY return stable sample values
- **AND** the result MUST be marked as demo/sample only
- **AND** this behavior MUST NOT be used when `production_feishu=True`
