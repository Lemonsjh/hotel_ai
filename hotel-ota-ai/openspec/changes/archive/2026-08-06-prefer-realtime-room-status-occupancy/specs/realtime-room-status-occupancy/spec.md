## ADDED Requirements

### Requirement: Realtime Room Status Occupancy Basis

经营快照上下文 MUST 在可用时优先使用 `kf11_room_status_snapshot` 实时房态计算房量和满房率。

#### Scenario: Realtime room status is available

- **WHEN** `room_status_result` 包含实时房间状态行
- **AND** 日结 payload 中的 `room_count`、`sold_rooms` 或 `occupancy_rate` 与实时房态不一致
- **THEN** `core_metrics.total_rooms` MUST 使用实时房态房间数
- **AND** `core_metrics.sold_rooms` MUST 使用实时占用态房间数
- **AND** `core_metrics.remaining_rooms` MUST 使用实时可售态房间数
- **AND** `core_metrics.occupancy_rate` MUST 等于实时占用态房间数除以实时房态房间数
- **AND** sources MUST 标记 `kf11_room_status_snapshot`

#### Scenario: Realtime room status is missing

- **WHEN** `room_status_result` 不包含可用房间状态行
- **THEN** runtime MUST 保持原有日结/营收表派生逻辑
