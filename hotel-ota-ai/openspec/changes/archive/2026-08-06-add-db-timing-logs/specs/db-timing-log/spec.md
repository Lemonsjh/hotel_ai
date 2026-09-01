# db-timing-log Specification

## ADDED Requirements

### Requirement: Database template timing log is opt-in

The system SHALL write database template timing logs only when `HOTEL_OTA_DB_TIMING_LOG=1`.

#### Scenario: Timing log disabled by default

- **GIVEN** `HOTEL_OTA_DB_TIMING_LOG` is not set
- **WHEN** `database_template_result()` runs
- **THEN** no `database-template-timing.jsonl` file SHALL be created by this feature

#### Scenario: Timing log enabled writes safe summary

- **GIVEN** `HOTEL_OTA_DB_TIMING_LOG=1`
- **WHEN** `database_template_result()` runs
- **THEN** a JSONL record SHALL be written
- **AND** the record SHALL include `template`, `hotel_id`, `status`, `duration_ms`, `source_status`, `row_count`, and `risk_flags`
- **AND** the record SHALL NOT include DSN values, SQL text, credentials, or raw identity IDs
