## Why

S16 当前实际进度优先从 `order_snapshot` 或经营快照/日结指标推导。当日 `jy01_hotel_statistics_daily` 等 T+1 日结表为空或滞后时，系统会把当天进度误判为 0 或 data_gap，影响节点偏差和后续 S5/S14 路由。

## What Changes

- S16 当日实际进度优先读取 `reservation_snapshot` 与 `stayover_snapshot`。
- 输出保留两个分量：`today_checked_in_rooms` 与 `today_reserved_arrival_rooms`。
- `actual_room_nights` 可用于节点进度计算，但必须暴露来源和分量，避免把实时分量伪装成日结总售出。
- T+1 日结指标继续可作为目标/历史基准，不再作为当天实际进度的首选事实源。

## Capabilities

### New Capabilities
- `s16-realtime-today-progress`: S16 当天进度使用实时 PMS 预订/在住房态证据。

### Modified Capabilities
- None.

## Impact

影响 `runtime/decisions/deviation.py` 与 S16 回归测试。暂不改 S5 收益决策、S17 订单结构或房型级满房率。
