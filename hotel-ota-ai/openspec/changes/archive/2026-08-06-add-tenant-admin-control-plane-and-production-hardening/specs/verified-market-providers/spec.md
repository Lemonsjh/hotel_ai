## ADDED Requirements

### Requirement: Market configuration is tenant scoped and private
The runtime MUST resolve QWeather and activity provider settings by hotel id from private configuration and MUST NOT expose endpoints or credentials in Feishu output.

#### Scenario: Missing market provider
- **WHEN** a provider is not configured for the hotel
- **THEN** market context MUST return partial or data_gap and MUST NOT claim fresh external data

### Requirement: Verified activity provider validates transport and schema
The activity provider MUST require HTTPS, bearer credentials from an environment variable, and valid source metadata before events become confirmed context.

#### Scenario: Invalid event response
- **WHEN** the HTTP response omits source id, fetched timestamp, event id, event date, confidence, or source URL
- **THEN** the runtime MUST return partial or data_gap and MUST NOT cache it as confirmed
