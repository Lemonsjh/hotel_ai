# Algorithm Coverage Matrix

Current machine-readable contract: `contracts/v27/contract.json`. V26 and earlier files are legacy migration references only.

This matrix records where each V27 algorithm blueprint is carried in runtime code, contract fields, degradation policy, and tests. A row is not considered complete unless it has both executable runtime logic and a regression test.

| Skill | Blueprint reference | Runtime carrier | Contract carrier | Runtime outputs / limits | Tests |
| --- | --- | --- | --- | --- | --- |
| S4 demand and market context | `docs/architecture_reference/v27/01-需求指数与流量峰谷算法.md` | `runtime/algorithms/demand_index.py`, `runtime/decisions/demand.py`, `runtime/decisions/calendar.py` | `contracts/v27/skill_io_contract.yaml#S4`, `contracts/v27/node_io_contract.yaml#N006`, `runtime/algorithm_rules/demand_rules.yaml` | `formula_version=revised_first_formula_v27`; active weights: `date_environment=0.20`, `regional_heat=0.15`, `historical_same_period=0.15`, `booking_progress=0.20`, `current_traffic=0.10`, `current_conversion=0.10`, `room_type_inventory_pressure=0.10`; peak/valley calibration rules; `degradation_policy=calendar_only_when_external_sources_missing` | `tests/runtime/test_v27_algorithm_deepening.py`, `tests/contracts/test_v27_demand_formula_alignment.py`, `tests/test_security_and_freshness.py` |
| S5 revenue decision | `docs/architecture_reference/v27/02-调价建议算法.md` | `runtime/algorithms/s5_decision_context.py`, `runtime/algorithms/revenue_decision_engine.py`, `runtime/decisions/pricing.py` | `contracts/v27/skill_io_contract.yaml#S5`, `contracts/v27/node_io_contract.yaml#N015`, `runtime/algorithm_rules/revenue_rules.yaml` | `contract_input_coverage`, `runtime_feed_coverage`, `algorithm_usage_coverage`, `decision_strength`, `not_allowed_conclusions`; demo/synthetic remains preview only | `tests/runtime/test_s5_decision_context_coverage.py`, `tests/runtime/test_demo_revenue_decision_coverage.py`, `tests/runtime/test_s5_s6_handoff_contract.py` |
| S7 competitor alert | `docs/architecture_reference/v27/06-竞对预警算法.md` | `runtime/algorithms/s7_competition_context.py`, `runtime/decisions/competition.py` | `contracts/v27/skill_io_contract.yaml#S7`, `contracts/v27/node_io_contract.yaml#N007`, `runtime/algorithm_rules/competition_rules.yaml` | four-level comparison contract; exact competitor products absent => no room-type gap; `direct_price_trigger_allowed=false` | `tests/test_s7_competition_context.py`, `tests/test_skill_transform_maximize.py` |
| S9 traffic peak-valley | `docs/architecture_reference/v27/01-需求指数与流量峰谷算法.md` | `runtime/algorithms/time_aware_progress.py`, `runtime/decisions/progress_diagnosis.py`, `runtime/algorithms/demand_index.py`, `runtime/decisions/baseline.py` | `contracts/v27/skill_io_contract.yaml#S9`, `contracts/v27/node_io_contract.yaml#N020`, `runtime/algorithm_rules/traffic_rules.yaml` | shares S4 `formula_version=revised_first_formula_v27`; `traffic_state=valley` caps demand index unless booking progress is materially above history; `traffic_state=peak` floors demand index unless booking/conversion are materially weak; no future data backfill | `tests/runtime/test_time_aware_progress.py`, `tests/runtime/test_s16_hourly_trend.py`, `tests/runtime/test_v27_algorithm_deepening.py` |
| S14 OTA health and conversion diagnosis | `docs/architecture_reference/v27/03-OTA健康诊断算法.md`, `docs/architecture_reference/v27/04-流量转化诊断算法.md` | `runtime/algorithms/ota_health_score.py`, `runtime/algorithms/conversion_funnel.py`, `runtime/decisions/ota_health.py` | `contracts/v27/skill_io_contract.yaml#S14`, `contracts/v27/node_io_contract.yaml#N009`, `runtime/algorithm_rules/operation_diagnosis_rules.yaml` | `diagnosis_status`, `field_coverage_rate`, `missing_fields`, `not_allowed_conclusions`; partial diagnosis constrains S5 strength | `tests/reports/test_field_coverage.py`, `tests/runtime/test_v27_algorithm_deepening.py` |
| S16 progress deviation | `docs/architecture_reference/v27/01-需求指数与流量峰谷算法.md` | `runtime/algorithms/time_aware_progress.py`, `runtime/algorithms/progress_trend.py`, `runtime/decisions/progress_diagnosis.py`, `runtime/decisions/deviation.py` | `contracts/v27/skill_io_contract.yaml#S16`, `contracts/v27/node_io_contract.yaml#N011`, `runtime/algorithm_rules/progress_deviation_rules.yaml` | `actual_hourly_sales`, `target_hourly_curve`, `as_of_checkpoint_gap`, `daily_remaining_gap`, `pickup_speed`, no future data leakage | `tests/runtime/test_progress_diagnosis_synthetic_context.py`, `tests/runtime/test_room_night_progress_contract.py`, `tests/feishu/test_feishu_progress_natural_language.py` |

## Shared Coverage Semantics

- `available_fields`: fields present in the active context.
- `used_by_algorithm`: fields actually consumed by executable runtime logic.
- `display_only`: fields shown to Feishu or reports but not used for calculation.
- `missing`: fields required by active scenario edges and unavailable in the active context.
- `disabled_by_time_context`: future or stale values intentionally excluded by time-aware logic.
- `degradation_policy`: the explicit rule used when an upstream source is partial or missing.
- `not_allowed_conclusions`: conclusions the runtime must not claim under partial/demo/stale context.

## Refactor Targets

Large modules should be split only after the tests above stay green. Priority order: extract database source/query helpers from `runtime/adapters/database.py`, move Feishu intent lexicons out of `runtime/feishu_command_router.py`, and split demo node/chain builders from `runtime/demo_mode.py`.
