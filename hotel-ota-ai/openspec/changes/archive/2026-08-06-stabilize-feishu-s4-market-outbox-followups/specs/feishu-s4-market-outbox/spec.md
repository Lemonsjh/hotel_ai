## ADDED Requirements

### Requirement: Controlled Feishu status outputs are not blocked as config export
Runtime MUST allow controlled business status templates such as `chat_binding_status`, `identity`, `auth_path_explanation`, `member_role_status`, `market_context_demo`, and `price_task_outbox_write` through the Feishu output gate when they contain only sanitized operational summaries.

#### Scenario: Bound chat status is rendered
- **WHEN** a production Feishu user asks to view the current chat binding and the chat is bound to `puyue`
- **THEN** the response has `send_allowed=true`
- **AND** the response does not include full raw `open_id`, `chat_id`, `user_id`, or `union_id`
- **AND** the response does not contain `config_or_secret_export_not_allowed`

### Requirement: S4 production Feishu routes use authenticated hotel scope
Protected Feishu business intents MUST use the authenticated `resolved_hotel_id` as the runtime `hotel_id` and MUST NOT silently fall back to `puyue-demo`.

#### Scenario: Bound group asks S4
- **WHEN** a bound Feishu group mapped to `puyue` sends `s4`
- **THEN** the result has `intent=market_context_demo`
- **AND** `hotel_id=puyue`
- **AND** `resolved_hotel_id=puyue`
- **AND** `rendered.template=market_context_demo`

### Requirement: Open-Meteo weather provider is supported
Weather configuration MUST support `open_meteo` per hotel with configurable latitude, longitude, timezone, display location, timeout, cache TTL, optional API key, fallback providers, and cross-check providers.

#### Scenario: Open-Meteo current weather is parsed
- **WHEN** Open-Meteo returns WMO code `3` with no precipitation
- **THEN** normalized weather reports `weather_text` as overcast/cloudy class
- **AND** `weather_signal=neutral`
- **AND** it does not report rain.

#### Scenario: Missing hotel coordinates
- **WHEN** `open_meteo` is enabled without latitude or longitude
- **THEN** weather returns `data_gap`
- **AND** it does not use a hard-coded default city.

### Requirement: Holiday remote providers are cached and quality-tagged
Holiday data MUST support configured remote providers `apisbo_holidays_year` and `jiejiariapi_holidays_year`, cache results in SQLite, expose commercial-use status, and fallback to builtin seed with `partial` quality on remote failure.

#### Scenario: APIsBO maps adjusted workday
- **WHEN** APIsBO returns `type=workday`
- **THEN** runtime stores and reports `day_type=adjusted_workday`.

#### Scenario: Remote failure falls back
- **WHEN** a configured holiday API fails
- **THEN** S4 may use builtin seed fallback
- **AND** exposes `holiday_source=fallback_builtin_seed`
- **AND** exposes `source_quality=partial`.

### Requirement: OpenClaw bridge event search is authenticated and quality-gated
`openclaw_bridge_http_search` MUST NOT trust localhost results unless the bridge token is configured, the service id matches, and the response source type is verified.

#### Scenario: Bridge returns placeholder without handshake
- **WHEN** a bridge response lacks `service_id` or `source_type`, or contains demo/placeholder/example results
- **THEN** event discovery returns `data_gap`
- **AND** `source_quality=demo_or_untrusted`
- **AND** the event is not used in regional heat or price decisions.

### Requirement: Zhiting outbox migration and mapping queries are additive and schema tolerant
Outbox deployment MUST provide additive MySQL migration and runtime queries MUST avoid referencing missing mapping columns.

#### Scenario: Mapping table has hotel_id but no hotel_name
- **WHEN** product mapping contains `hotel_id` but not `hotel_name`
- **THEN** runtime filters by `hotel_id`
- **AND** does not generate SQL referencing `hotel_name`.

#### Scenario: Mapping table has no hotel scope column
- **WHEN** product mapping lacks both `hotel_id` and `hotel_name`
- **THEN** runtime may query by room/date only
- **AND** returns warning `hotel_scope_filter_missing`.

### Requirement: Ctrip editable flag accepts numeric truthy values
Ctrip product expansion MUST treat numeric and string variants such as `1`, `1.0`, `1.0000`, `Decimal("1.0000")`, `true`, `Y`, and `yes` as editable, and false-like variants as not editable.

#### Scenario: Decimal-like editable flag
- **WHEN** Ctrip mapping has `price_editable_flag="1.0000"`
- **THEN** S6 writes a `PENDING` task for that product.

### Requirement: Price guards support platform and product scoped priority
Price guard resolution MUST prefer platform product guard over platform room type guard over hotel room type guard over default policy.

#### Scenario: Product-level guard exists
- **WHEN** a Meituan product-level guard and a hotel room-type guard both exist
- **THEN** S5/S6 use the product-level guard
- **AND** expose `guard_scope=platform_product`.

### Requirement: Feishu outbox replies use a dedicated task template
Feishu output for outbox task creation MUST use `price_task_outbox_write` and MUST state that tasks are waiting for plugin processing, not that OTA prices have changed.

#### Scenario: Pending tasks written
- **WHEN** S6 writes `PENDING` outbox rows
- **THEN** Feishu output shows platform, sale date, room type, expanded product count, inserted count, skipped count, `PENDING`, source decision id, and `live_api_called=false`
- **AND** it does not say the OTA price change succeeded.
