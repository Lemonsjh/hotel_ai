# production-feishu-regressions Specification

## ADDED Requirements

### Requirement: Production realtime occupancy must not use stale daily metrics

`经营快照` MUST NOT present `jy01` stale daily occupancy as today's realtime occupancy.

#### Scenario: kf11 occupied count differs from formula numerator

- **GIVEN** `kf11` shows 24 occupied rooms out of 31
- **AND** `jd01/jd04` formula evidence only explains a small subset
- **WHEN** production runtime computes realtime occupancy
- **THEN** it emits the realtime occupancy rate from `jd01/jd04` numerator divided by `kf11` total rooms minus maintenance rooms
- **AND** `jd01` checked-in and reserved components are deduplicated by `order_id` / `order_no` / `reservation_no` before summing room counts
- **AND** `jd01` same-day cancelled reservations are reported as a reservation adjustment and deducted from the reserved-arrival component used by the numerator
- **AND** `target_business_date` is runtime request context, not a required `jd01.business_date` column
- **AND** same-day reservation and cancellation matching uses `DATE(arrival_time)=target_business_date`
- **AND** `kf11` occupied count is emitted only as auxiliary room-status evidence
- **AND** the renderer must not display the `kf11` occupied ratio as realtime occupancy.

#### Scenario: skill guidance routes realtime occupancy to the unified formula

- **GIVEN** an agent reads S2 skill documentation for "实时出租率"
- **WHEN** it selects a runtime command
- **THEN** production Feishu uses `feishu-route --production-feishu`
- **AND** local diagnosis uses `expected-occupancy`
- **AND** `snapshot` / `jy01_hotel_statistics_daily.occupancy_rate` are documented as historical or compatibility evidence, not current realtime occupancy.

### Requirement: Source room_type_id must be preserved

Runtime normalization MUST preserve source table `room_type_id` when present.

#### Scenario: source row has room_type_id but no mapping row

- **GIVEN** a source table row has `room_type_id`
- **AND** no mapping table entry matches the row
- **WHEN** runtime normalizes the row
- **THEN** `room_type_id` remains present
- **AND** mapping risk is reported without overwriting the source identity.

### Requirement: Price candidates are dynamic from mapping and OTA product tables

Adjustable products MUST be derived from mapping data and OTA product rows, not hard-coded room type counts.

#### Scenario: mapped products are eligible candidates

- **GIVEN** OTA products exist in `meituan_ota_goods_price_mapping`
- **AND** matching mapping rows or source `room_type_id` provide a trusted unified room identity
- **WHEN** runtime lists price candidates
- **THEN** all mapped products are eligible candidates
- **AND** unmapped products remain `mapping_pending`.

### Requirement: Production data gaps must not carry demo evidence

Production `data_gap` responses MUST NOT include demo/sample evidence.

#### Scenario: database is enabled but actual data is missing

- **GIVEN** database mode is enabled
- **AND** a template returns `data_gap`
- **WHEN** production diagnosis emits a result
- **THEN** it does not include demo numbers such as `170`, `107`, `5.74`, or `58`
- **AND** it does not identify the evidence as `sample_data`.

### Requirement: Feishu identity and role management stay scoped

Feishu role output MUST remain scoped to the current chat and hide raw platform IDs.

#### Scenario: owner grants owner in current chat

- **GIVEN** requester is an owner of the hotel
- **WHEN** they grant owner role to another member in the same chat
- **THEN** the request is allowed
- **AND** raw `open_id` values are not displayed.

#### Scenario: missing trusted Feishu context is not reported as unbound chat

- **GIVEN** a business request lacks trusted `chat_id` or sender identity
- **WHEN** runtime blocks the request with `missing_required_feishu_auth_context` or `missing_trusted_business_chat_id`
- **THEN** the safe message says trusted Feishu context is missing
- **AND** it does not say the current group is unbound unless runtime actually checked the real chat id and returned `chat_not_bound_to_hotel`.

### Requirement: S14 and market metrics use real sources when present

S14 and market diagnosis MUST use real database metrics when present.

#### Scenario: real HOS or market fields exist

- **GIVEN** real business metric rows contain HOS, OTA health, or market comparison values
- **WHEN** S14 or market diagnosis runs
- **THEN** the values are used with source evidence
- **AND** missing same-period data returns `data_gap` instead of substituting yesterday.
