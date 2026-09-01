## Context

`deviation.py` 在数据库启用时读取 `operating_snapshot`、`operation_diagnosis`、`order_snapshot`、`daily_metrics` 和 `monthly_metrics`。实时模板 `reservation_snapshot`、`stayover_snapshot` 已存在于数据库适配器，但未接入 S16 当日累计已售逻辑。

## Goals / Non-Goals

**Goals:** 当日实际进度优先使用实时预订/在住数据；输出分量和来源；日结表为空时不把实际进度当作 0。

**Non-Goals:** 不调整 S5/S17；不新增数据库表；不把当前 `operating_snapshot.occupied_rooms` 当成今日销售代理。

## Decisions

- `reservation_snapshot.new_arrival_rooms` 作为今日已预订/今日到店预订分量。
- `stayover_snapshot.stayover_rooms` 作为今日已入住/在住分量。
- 两个分量至少有一个可信时，`actual_room_nights = checked_in + reserved_arrival`，并标记 `actual_source=realtime_reservation_stayover_snapshot`。
- 可信条件沿用当前 S16 口径：`freshness_status=fresh` 且 `data_business_date` 等于目标日期。
- 如果实时分量不可用，保留现有 `order_snapshot` 与 `operating_snapshot` fallback。

## Risks / Trade-offs

- `stayover_snapshot` 表名和业务含义可能覆盖续住/在住，不等价于完整订单结构；本 change 只把它作为 S16 进度分量，并明确输出来源。
- 真实数据库字段状态枚举依赖适配器现有 alias；状态 alias 不匹配时会返回 data_gap 风险，而不是输出 0 作为事实。
