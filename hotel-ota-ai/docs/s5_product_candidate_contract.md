# S5 Product Candidate Contract

S5 is a real-data, read-only product candidate capability. It does not invoke S2/S7 through Feishu text, create approvals, write an outbox row, or execute a channel action.

Each candidate binds the exact `hotel_id`, OTA `channel`, `ota_product_id`, and requested `target_stay_date`. The price observation retains its own `business_date` and `snapshot_time`; it is not asserted to be a future stay-date price.

The required source set is PMS room-type forecast, OTA price mapping, and the price-guard resolver. S15 baseline, S16-equivalent checkpoint evidence, same-date vertical traffic metrics, and S7 peer/loss evidence independently improve confidence. Missing evidence returns `partial` and a quality flag instead of a fabricated zero.

`active_price_guard_policy` with configured floor and ceiling is the only guard state eligible for `S6` dry-run. `default_policy` creates a visibly labeled ± configured-change preview band and remains `preview_only_default_guard`. A peer aggregate or loss context may be shown as background but never becomes an exact competitor product price or a follow-price instruction.
