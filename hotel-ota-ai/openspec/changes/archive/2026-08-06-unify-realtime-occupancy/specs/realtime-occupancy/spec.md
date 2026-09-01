# realtime-occupancy Specification

## ADDED Requirements

### Requirement: Unified realtime occupancy formula

The system SHALL provide a single realtime occupancy calculation for production decision paths.

#### Scenario: Computes realtime numerator and denominator

- **GIVEN** jd01 contains checked-in rows whose `departure_time` is after `as_of_time`
- **AND** jd01 contains reserved rows whose `arrival_time` date equals the business date
- **AND** jd04 contains in-house rows whose `checkout_time` is after `as_of_time`
- **AND** kf11 contains total room status rows including maintenance and dirty rooms
- **WHEN** realtime occupancy is calculated
- **THEN** the numerator SHALL include the three required components
- **AND** duplicate rooms SHALL be deduplicated by `room_no`, falling back to `order_id`
- **AND** the denominator SHALL equal total rooms minus maintenance rooms
- **AND** dirty rooms SHALL NOT be deducted from the denominator
- **AND** the result SHALL include `formula_version=jd01_jd04_kf11_realtime_occupancy_v1`

### Requirement: S5 uses unified realtime occupancy

S5 expected occupancy SHALL use the unified realtime occupancy result instead of a local `stayover_rooms + new_arrival_rooms` formula.

#### Scenario: Dirty rooms do not reduce sellable denominator

- **GIVEN** realtime occupancy has total rooms 31, maintenance rooms 1, dirty rooms 3, and numerator 20
- **WHEN** S5 expected occupancy is generated
- **THEN** `denominator_rooms` SHALL be 30
- **AND** dirty rooms SHALL be present only as an operational risk field
- **AND** the output SHALL include the unified formula version

### Requirement: S2 and S14 expose unified realtime occupancy evidence

Production S2 snapshot and S14 OTA health outputs SHALL expose the same realtime occupancy evidence when jd01, jd04, and kf11-derived inputs are available.

#### Scenario: Snapshot and OTA health include unified occupancy evidence

- **GIVEN** production database evidence includes operating, reservation, and stayover snapshots
- **WHEN** S2 snapshot or S14 OTA health output is generated
- **THEN** the output evidence SHALL include `formula_version=jd01_jd04_kf11_realtime_occupancy_v1`
- **AND** the output evidence SHALL include `actual_numerator_rooms`, `denominator_rooms`, `actual_occupancy_rate`, and `duplicate_risk`

### Requirement: S16 judges progress by occupancy rate

S16 progress deviation SHALL primarily compare checkpoint actual occupancy rate to checkpoint target occupancy rate.

#### Scenario: Occupancy gap is the primary progress metric

- **GIVEN** a realtime occupancy result with `actual_occupancy_rate`
- **AND** a baseline with `checkpoint_target_occupancy_rate`
- **WHEN** S16 deviation is generated
- **THEN** `actual_occupancy_rate` SHALL be present
- **AND** `target_occupancy_rate` SHALL be present
- **AND** `occupancy_gap` SHALL be present
- **AND** `actual_room_nights` SHALL be auxiliary evidence only

### Requirement: Baseline distinguishes real curves from fallback curves

Sales baseline SHALL expose source and confidence for daily targets and checkpoint curves.

#### Scenario: Default anchor curve is low confidence

- **GIVEN** no explicit baseline and no reliable historical booking curve
- **WHEN** baseline is generated from default anchors
- **THEN** `hourly_curve_source` SHALL be `fallback_ratio_curve`
- **AND** `source_confidence` SHALL be `low`
- **AND** fallback curve SHALL NOT allow automatic pricing decisions

### Requirement: Daily jy01 and rs01 alignment can be verified

The system SHALL provide a read-only developer verification command for comparing daily `jy01_hotel_statistics_daily` room nights with `rs01_room_revenue_daily` room nights filtered to `charge_subject='房费'`.

#### Scenario: rs01 room-fee-only room nights align with jy01

- **GIVEN** `jy01_hotel_statistics_daily` has daily `room_count` and `room_nights`
- **AND** `rs01_room_revenue_daily` has rows for the same `business_date`
- **WHEN** the alignment command runs
- **THEN** output SHALL include `business_date`, `jy01_room_count`, `jy01_room_nights`, `rs01_room_nights_room_fee_only`, `difference`, and `match_status`
- **AND** rows whose `charge_subject` is not `房费` SHALL be excluded from `rs01_room_nights_room_fee_only`
- **AND** the output SHALL include an unfiltered rs01 total as diagnostic evidence when it differs
