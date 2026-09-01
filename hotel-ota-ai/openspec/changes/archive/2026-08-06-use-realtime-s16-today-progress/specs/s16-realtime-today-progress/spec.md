## ADDED Requirements

### Requirement: S16 当日进度优先使用实时分量
S16 当日实际进度 MUST 优先使用实时 PMS 预订和在住数据，而不是 T+1 日结表。

#### Scenario: 日结表滞后但实时表有数据
- **WHEN** `daily_metrics` 当天实际售出为空或为 0
- **AND** `reservation_snapshot` 或 `stayover_snapshot` 对目标日期返回 fresh 数据
- **THEN** S16 使用实时分量计算 `actual_room_nights`
- **AND** 输出 `today_checked_in_rooms`、`today_reserved_arrival_rooms` 和 `actual_source`

#### Scenario: 实时分量不可用
- **WHEN** `reservation_snapshot` 和 `stayover_snapshot` 都不可用或不是目标日期 fresh 数据
- **THEN** S16 保留现有 `order_snapshot` / `operating_snapshot` fallback
- **AND** 不得把 `operating_snapshot.occupied_rooms` 当作今日已售

#### Scenario: 节点偏差和全日缺口同时可见
- **WHEN** S16 有实际进度和日目标
- **THEN** 输出节点目标、节点缺口、全日目标和全日剩余缺口
