# prefer-realtime-room-status-occupancy

## 背景

房型/酒店满房率当前可能继续使用 T+1 日结表的 `room_count`、`sold_rooms` 或 `occupancy_rate`。实测反馈指出当天满房率应以 `kf11_room_status_snapshot` 实时房态为准，避免日结 `room_count` 与实时房态不一致时误判。

## 目标

- 当 `room_status_snapshot` 有实时房态数据时，经营快照上下文优先用实时房态计算 `total_rooms`、`sold_rooms`、`remaining_rooms`、`occupancy_rate`。
- 仅在实时房态缺失时沿用日结/营收表推导。
- 输出标记 `kf11_room_status_snapshot` 为使用来源，方便审计口径。

## 非目标

- 不改数据库表结构或 mapping profile。
- 不新增写库、修复真实数据或迁移数据。
- 不改变 S14/S16/S5 以外未接入 `build_operating_snapshot_context()` 的独立算法。
