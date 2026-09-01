## V27 Contract-First Notice

当前以 `contracts/v27/contract.json` 为唯一 machine-readable 工程契约。V26 文件仅作为 legacy migration reference 和历史协作资料；如旧说明与 V27 contract/runtime 冲突，以 V27 为准。

# Phase 7 Skill Algorithm Completion

| Skill | Node | Agent | Algorithm Rules | Behavior Cases | Status |
| --- | --- | --- | --- | --- | --- |
| S1 | N003 | A0 | `runtime/algorithm_rules/auth_policy.yaml` | `skills/hotel-ota/s01-control-config/references/v20_behavior_cases.json` | implemented |
| S2 | N005 | A1 | `runtime/algorithm_rules/operating_snapshot_rules.yaml` | `skills/hotel-ota/s02-operating-snapshot/references/v20_behavior_cases.json` | implemented |
| S3 | N018 | A5 | `runtime/algorithm_rules/message_templates_policy.yaml` | `skills/hotel-ota/s03-message-hub/references/v20_behavior_cases.json` | implemented |
| S4 | N006 | A1 | `runtime/algorithm_rules/demand_rules.yaml` | `skills/hotel-ota/s04-market-context/references/v20_behavior_cases.json` | implemented |
| S5 | N015 | A3 | `runtime/algorithm_rules/revenue_rules.yaml` | `skills/hotel-ota/s05-revenue-decision/references/v20_behavior_cases.json` | implemented |
| S6 | N016 | A4 | `runtime/algorithm_rules/execution_guard.yaml` | `skills/hotel-ota/s06-price-sync-execution/references/v20_behavior_cases.json` | implemented |
| S7 | N007 | A1 | `runtime/algorithm_rules/competition_rules.yaml` | `skills/hotel-ota/s07-competitive-monitoring/references/v20_behavior_cases.json` | implemented |
| S8 | N012 | A3 | `runtime/algorithm_rules/promotion_rules.yaml` | `skills/hotel-ota/s08-promotion-planning/references/v20_behavior_cases.json` | implemented |
| S9 | N020 | A1 | `runtime/algorithm_rules/traffic_rules.yaml` | `skills/hotel-ota/s09-traffic-peak-valley/references/v20_behavior_cases.json` | implemented |
| S10 | N013 | A3 | `runtime/algorithm_rules/roi_rules.yaml` | `skills/hotel-ota/s10-roi-decision/references/v20_behavior_cases.json` | implemented |
| S11 | N021 | A4 | `runtime/algorithm_rules/promotion_execution_rules.yaml` | `skills/hotel-ota/s11-promotion-execution/references/v20_behavior_cases.json` | implemented |
| S12 | N008 | A1 | `runtime/algorithm_rules/reputation_rules.yaml` | `skills/hotel-ota/s12-reputation-management/references/v20_behavior_cases.json` | implemented |
| S13 | N017 | A4 | `runtime/algorithm_rules/review_publish_rules.yaml` | `skills/hotel-ota/s13-review-reply/references/v20_behavior_cases.json` | implemented |
| S14 | N009 | A2 | `runtime/algorithm_rules/operation_diagnosis_rules.yaml` | `skills/hotel-ota/s14-operation-diagnosis/references/v20_behavior_cases.json` | implemented |
| S14-EXT | N022 | A2 | `runtime/algorithm_rules/external_diagnosis_rules.yaml` | `skills/hotel-ota/s14-ext-third-party-diagnosis/references/v20_behavior_cases.json` | implemented |
| S15 | N010 | A2 | `runtime/algorithm_rules/baseline_rules.yaml` | `skills/hotel-ota/s15-sales-baseline/references/v20_behavior_cases.json` | implemented |
| S16 | N011 | A2 | `runtime/algorithm_rules/progress_deviation_rules.yaml` | `skills/hotel-ota/s16-progress-deviation/references/v20_behavior_cases.json` | implemented |
| S17 | N014 | A1 | `runtime/algorithm_rules/customer_rules.yaml` | `skills/hotel-ota/s17-customer-order-analysis/references/v20_behavior_cases.json` | implemented |

Completion definition: every S1-S17 and S14-EXT skill has implemented algorithm rules, DataGate requirements, ordered steps, thresholds, degradation behavior, output contract, forbidden actions, demo fixture, and behavior cases.
