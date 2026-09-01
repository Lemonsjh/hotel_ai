# S2 PMS Contract Migration

S2 now reads the fixed `pms_room_type_forecast_v1` contract. The connection profile still selects an approved read-only database target, but it no longer decides S2 table names, fields, status aliases, or fallback algorithms.

The query binds the exact `hotel_id`, target `stay_date`, and, when supplied, the `as_of_datetime` cutoff. It selects the latest eligible PMS snapshot and separates committed sales from physical occupancy.

`kf11_room_status_snapshot`, reservation snapshots, stayover snapshots, and daily settlement metrics may remain available to other legacy capabilities. They must not overwrite, recalculate, or block a successful S2 PMS snapshot.

## Six-view product composition

S2 is an operating runtime snapshot, not an inventory-only response. The fixed PMS contract remains its required core for the operating overview and room-type status. When that core succeeds, S2 concurrently reads independent, read-only optional views for flow conversion, market competition, own OTA price/lead-price observation, and promotion activity state. It does not invoke S5, S6, S8, or S13.

Every optional view keeps its own business date/window, snapshot time, unit, comparison level, and explicit query state: `no_records` means a successful query returned zero rows, while `data_gap` identifies a missing source, schema/query failure, or unavailable result. Optional snapshots also honor an explicit request cutoff, so a later OTA extract is never presented as visible at an earlier request time. Flow conversion deliberately reads the preceding complete business date and only renders the canonical Meituan `FLOW_*` funnel codes; legacy aliases remain source facts but are not duplicated in the card. The PMS core remains on the requested stay date. Market and lead-price metrics use a separate query on the PMS target business date; in Meituan, `DAY_ROOM_LOWEST_PRICE_AVG` is the hotel-level lead-price metric. This Meituan table has no platform column, so its configured table identity supplies the channel. Activity product counts are only exact when retrieval is complete; a capped retrieval is displayed as a lower bound. A missing or stale platform view never changes the PMS core into a failure and cannot be replaced by another hotel's data. Market output remains `peer_aggregate` or `loss_context`; exact room-type competitor price gaps require a real exact-product collection.

Deployment validation is read-only: confirm the fixed table and required columns, query a target date, verify the returned `s2_contract` is `pms_room_type_forecast_v1`, and verify that Feishu reports committed sales and physical occupancy separately. Do not deploy, alter database grants, or change secrets as part of this repository change.
