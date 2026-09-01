# Skill To Table Mapping

Source field contract: `数据库数据字段说明_详细版(4).md` from the architecture reference workspace. Current production trial profile is `hotel_puyue`, verified read-only on 2026-06-30 with 27 tables.

## Database Table Roles

| Table | Role | Tenant Scope | Room/Product Scope | Notes |
|---|---|---|---|---|
| `hotel_room_type_mapping` | Canonical mapping fact source | `hotel_id` + `hotel_name` | canonical `room_type_id`, platform room/product ids, mapping status | Primary source for hotel/room/platform product identity. |
| `v_hotel_room_type_mapping_full` | Mapping read model | `hotel_id` + `hotel_name` | same as mapping | Read-only view for diagnostics. |
| `v_hotel_room_type_mapping_result` | Mapping result view | `hotel_id` + `hotel_name` | same as mapping | Read-only view for diagnostics. |
| `hotel_room_type_mapping_sync_queue` | Mapping sync queue | none in table | via `mapping_id` only | Operational queue, not a business fact table. |
| `jy01_hotel_statistics_daily` | Daily operating metrics | `hotel_id` exists but can be empty; fallback to mapped `hotel_name` | no room type id | Legacy historical support for S15/S16 migration; never an S2 source. |
| `jy03_hotel_statistics_month` | Monthly operating metrics | `hotel_id` exists but can be empty; fallback to mapped `hotel_name` | no room type id | Historical S15 baseline support. |
| `jd01_booking_detail` | Reservation/order snapshot | `hotel_id` exists but can be empty; fallback to mapped `hotel_name` | `room_type_name` only | S16/S17 support; normalize room types through mapping. |
| `jd04_inhouse_extension` | In-house/stayover extension | `hotel_id` exists but can be empty; fallback to mapped `hotel_name` | `room_type_name` only | S16/S17 support; guest fields must be redacted. |
| `kf11_room_status_snapshot` | Room status snapshot | `hotel_id` exists but can be empty; fallback to mapped `hotel_name` | `room_type_name` only | Legacy physical-state diagnostic only; not an S2 source or fallback. |
| `rs01_room_revenue_daily` | Room revenue daily | `hotel_id` + `hotel_name` | `room_type_name` only | S5/S10/S15/S16 support; normalize room types through mapping. |
| `ctrip_ota_goods_price_mapping` | Ctrip OTA product price snapshot | exact `hotel_id` | OTA product name, current price, canonical `room_type_id`, `product_cipher` | S5/S6 source; read-only product list displays OTA name/price even when guard is absent; S6 requires confirmed active mapping and cipher. |
| `meituan_ota_goods_price_mapping` | Meituan OTA product price snapshot | exact `hotel_id` | OTA product name, current price, canonical `room_type_id` | S5/S6 source; read-only product list displays OTA name/price even when guard is absent; S6 requires confirmed active mapping. |
| `ctrip_price_task` | Ctrip price task outbox | `hotel_id` + `hotel_name` | canonical and OTA product fields | Write target only after confirmed mapping and approval gates. |
| `meituan_price_task` | Meituan price task outbox | `hotel_id` + `hotel_name` | canonical and OTA product fields | Write target only after confirmed mapping and approval gates. |
| `ctrip_ota_business_metrics` | Ctrip traffic/conversion metrics | `hotel_id` + `hotel_name` | none | S4/S7/S9/S5 context. S14 consumes the upstream capability result, not this table. |
| `meituan_ota_business_metrics` | Meituan traffic/conversion metrics | `hotel_id` + `hotel_name` | none | S4/S7/S9/S5 context. S14 consumes the upstream capability result, not this table. |
| `meituan_ota_order_loss_monthly` | Meituan monthly order-loss competition background | exact `hotel_id` | competitor POI/circle, aggregated loss facts | S7 groups by `competitor_circle_name`; it uses `competitor_loss_order_count` and `competitor_loss_amount`, never sums repeated `total_loss_*` fields. It is not real-time product pricing or a causal attribution. |
| `ctrip_ota_promotion_activity` | Ctrip promotion summary | `hotel_id` | activity summary only | Legacy promotion activity context; S8 does not read this table. |
| `meituan_ota_promotion_activity` | Meituan promotion summary | `hotel_id` | activity summary only | Legacy promotion activity context; S8 does not read this table. |
| `ctrip_ota_activity_product_detail` | Ctrip activity product detail | `hotel_id` | `ota_room_type_id` + `room_type_name` | Legacy activity product detail; S8 does not read this table. |
| `meituan_ota_activity_product_detail` | Meituan activity product detail | `hotel_id` | `ota_room_type_id` + `room_type_name` | Legacy activity product detail; S8 does not read this table. |
| `meituan_ota_promotion_performance_30d` | Meituan Promotion display/performance snapshot | exact `hotel_id` | `plan_id` + `launch_id` | S8 sole direct business-data source; S8 reads the latest `snapshot_time` only when triggered and remains display-only. S10 may independently consume this table for its own ROI observation path. |
| `meituan_ota_nearby_event` | Nearby activity/event context | `hotel_id` + `hotel_name` | none | S4/S9 event enhancement; never directly triggers price actions. |
| `ctrip_ota_review_detail` | Ctrip review detail | `hotel_id` + `hotel_name` | `room_type_name` only | S12/S13 source; S14 consumes the S12 result. |
| `meituan_ota_review_detail` | Meituan review detail | `hotel_id` + `hotel_name` | `room_type_name` only | S12/S13 source; S14 consumes the S12 result. |
| `ctrip_ota_review_overview` | Ctrip review overview | `hotel_id` | none | S12 source; S14 consumes the S12 result. |
| `meituan_ota_review_overview` | Meituan review overview | `hotel_id` | none | S12 source; S14 consumes the S12 result. |
| `ctrip_ota_review_ranking` | Ctrip review/ranking list | `hotel_id` | none | S7/S12 source; S14 consumes the upstream result. |
| `meituan_ota_review_ranking` | Meituan review/ranking list | `hotel_id` | none | S7/S12 source; S14 consumes the upstream result. |

Rows without an explicit platform are normalized as `walkin` / direct guest data. This is a source classification, not a permission shortcut.

## Skill Mapping

| Skill | Tables / Direct Inputs |
|---|---|
| S1 | SQLite auth/config tables; private JSON bootstrap fallback only |
| S2 | Required core: fixed `pms_room_type_forecast_v1`. Optional parallel read-only views: OTA business metrics, price mappings, Ctrip competition 30d, Ctrip/Meituan order-loss monthly, promotion activity and activity-product detail. Each optional view preserves its own window/freshness and degrades independently. `pms_room_type_hourly_status` is S15 pace; `kf11_room_status_snapshot` is not an S2 fallback. |
| S3 | SQLite command/session tables, Feishu runtime route |
| S4 | `jy01_hotel_statistics_daily`, calendar seed, weather provider, `meituan_ota_nearby_event` |
| S5 | Required: `pms_room_type_forecast`, `ctrip_ota_goods_price_mapping`, `meituan_ota_goods_price_mapping`, control-plane price guard. Enhancement: S15 baseline, OTA business metrics, Ctrip competition 30d and Ctrip/Meituan `order_loss_monthly`. Every candidate binds exact `hotel_id+channel+ota_product_id+stay_date`; S7 aggregate/loss evidence is never an exact product comparison. |
| S6 | `hotel_room_type_mapping`, `ctrip_ota_goods_price_mapping`, `meituan_ota_goods_price_mapping`, `ctrip_price_task`, `meituan_price_task` |
| S7 | `ctrip_ota_goods_price_mapping`, `meituan_ota_goods_price_mapping`, `ctrip_ota_business_metrics`, `meituan_ota_business_metrics`, `ctrip_ota_competition_metrics_30d`, Ctrip/Meituan `order_loss_monthly`, activity/right/ranking. Competition-circle aggregation is Meituan-only (`meituan_ota_order_loss_monthly`); Ctrip monthly loss, when mapped, remains `loss_context` only. S7 does not read or display Meituan scan-order observations or Ctrip order dynamics. `peer_aggregate` requires own and peer values from the same metric, unit, business date/window and snapshot; current-day partial values never borrow yesterday's peer value/rank. Output must label `exact_product` / `peer_aggregate` / `loss_context` / `own_only`, and no exact competitor product collection means no room-type price gap. |
| S8 | Only `meituan_ota_promotion_performance_30d`. On trigger, read the exact hotel's latest `snapshot_time` and display only promotion data plus deterministic display metrics; no status inference, recommendation, planning, approval, task, execution, or other Skill dependency. |
| S9 | `ctrip_ota_flow_conversion_30d`, `meituan_ota_flow_conversion_30d`, `meituan_ota_exposure_source_daily`; S15 reference only when materialized |
| S10 | `ctrip_ota_promotion_performance_30d`, `meituan_ota_promotion_performance_30d`; exact-hotel, platform-separated observation. 美团先按 `plan_id+launch_id+window`，再在相同窗口加权组合；携程仅酒店渠道窗口。输出 CTR/CPC/CPA/间夜成本/观测 ROAS，区分 source gap、延迟、真实零投放和来源冲突。平台归因收入不构成增量或净利润证明。 |
| S11 | No direct business-table or action-table access. Deterministic derived inputs are aligned S8/S9/S10/S16 results plus the user's current suggestion intent. Output is `PromotionPlan` only; no AI, no approval/task/dispatch/write, no OTA/control-plane state mutation, and no execution/readback mode. |
| S12 | Review overview/detail/ranking |
| S13 | `meituan_ota_review_detail`, overview/ranking, `ota_review_reply_task` only after confirmation and exact pending readback |
| S14 | **No direct business-table or Excel source.** Direct inputs are versioned deterministic results from S2/S4/S7/S8/S9/S10/S12/S15/S16/S17. Existing S5/S6/S8/S13 results may appear only as validated handoff refs. Missing inputs degrade only affected modules. |
| S15 | `pms_room_type_hourly_status` plus historical daily facts; requires versioned materialization |
| S16 | S2 `pms_room_type_forecast` committed sales plus a fixed S15 materialization |
| S17 | Core: `jd01_booking_detail`, `rs01_room_revenue_daily`, `kf11_room_status_snapshot`, `jd04_inhouse_extension`; independent provider background: `meituan_ota_scan_order_detail`, `meituan_ota_user_source_monthly`, `ctrip_ota_order_detail`, `ctrip_ota_userprofile_distribution`, Meituan/Ctrip order-loss monthly, `jl11_room_type_classification`. Missing optional mappings remain population-level `data_gap`; populations are never added into a total customer count. |

## 2026-08 Algorithm Compatibility Boundary

This table is a legacy V27 adapter inventory, not the V3 authority. For the repaired compatibility path, the following rules are mandatory and take precedence over the older table notes above:

| Scope | Data use | Output / guardrail |
|---|---|---|
| S2 operating snapshot | `total_rooms` and `available_rooms` are inventory facts; `base_committed_sold=max(total_rooms-available_rooms,0)` and `committed_sold=base_committed_sold+overbooking_rooms`. `occupied_rooms` and `kf11_room_status_snapshot` are physical-state facts only. | Emit both committed and physical metrics. `sold_rooms` / `occupancy_rate` remain compatibility aliases for committed values; never infer committed sales from physical occupancy or room nights. |
| S8 promotion display | Only `meituan_ota_promotion_performance_30d`, exact `hotel_id`, latest `snapshot_time` at trigger time; `as_of_time` may constrain the latest eligible snapshot. | Display source fields and deterministic ratios only. Never read activity/price/business-metric/status/Ctrip sources for S8, never infer promotion status, and never generate recommendations, actions, approvals, tasks, or writes. |
| S11 promotion suggestion | Consume aligned deterministic S8 promotion-display facts, S9 traffic/conversion facts, S10 promotion-effect observations and S16 sales-progress facts for the same hotel/channel/time scope. | Emit `PromotionPlan` only. User words such as open/pause/close/change budget/change bid remain suggestion intent. Ambiguous plan identity returns `clarification_required`. No AI, request, confirmation command, approval, task, dispatch, execution, OTA/control-plane write, state mutation or readback is permitted under any role or approval condition. |
| S14 operation diagnosis | Consume aligned versioned results only. Excel/MySQL `operation_diagnosis`, sample/manual/RPA and direct database-query paths are retired. | Emit deterministic eight-module items, coverage, health state, root-cause clusters, seven axes, room/product projections and existing handoffs. Never recompute upstream facts or create tasks. |
| S15 hourly curve | A V3 materialized baseline must be versioned and persisted. The present V27 sales/history curves are legacy-derived inputs; default, synthetic, and fallback-ratio curves are advisory scaffolding. | Emit `baseline_status`, `materialized_baseline_available`, `s16_deviation_allowed`, and explicit forbidden conclusions. Until V3 materialization exists, every legacy curve is blocked from S16 timeline/deviation, price candidates/tasks, or baseline activation. |
| S16 progress | Use the S2 committed-sales metric as the operational progress fact; physical occupancy is contextual only. | The current V27 decision implementation remains a migration candidate. It must consume a materialized S15 baseline before it can be represented as a V3 S16 timeline/deviation result. |
| OTA priceable product list | Reads each channel's exact-hotel OTA product snapshot. PMS room type is only an internal guard-match key. | Display OTA channel, OTA product name and current price. A missing/invalid product guard changes the row to view-only; it does not hide it or create a price request. |

## Execution Boundaries

- S11 is never an execution surface. Approval, confirmation, operator role, admin/owner role, or live switch cannot enable S11 writes; `promotion-execute` is a historical compatibility command name with read-only suggestion semantics only.
- S14 never binds directly to a business table. Physical tables remain owned by their source capabilities.
- The repaired PMS S2/S15/S16 path binds exact `hotel_id`; database names and display names must never select a hotel. Legacy V27 name fallback remains migration debt and is not an approved source for these skills.
- `hotel_room_type_mapping` resolves canonical room/product identity only after the exact hotel scope is established.
- S6 / price task creation requires confirmed active mapping, canonical `room_type_id`, `source_product_id`, editable product, non-hour-room product, an active exact price guard, and an explicit single stay date or date range; Ctrip also requires `product_cipher`.
- The default guard layer remains available for dry-run preview, percentage-risk disclosure, and missing-guard diagnosis. It has no task-write authority and cannot be promoted to an active guard by confirmation.
- Missing or candidate mapping returns `mapping_pending` / `disabled_until_data_ready` and must not create approval, price task, plugin call, or live execution.
