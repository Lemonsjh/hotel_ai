# 设计

## 方案

在 `runtime/derived_contexts.py` 中增强实时房态派生：

1. 读取 `room_status_result.payload.rooms/rows/items`。
2. 统计 `room_status` 分布，并识别占用态和可售态：
   - 占用态：`occupied`、`inhouse`、`checked_in`、`stayover`、`已住`、`入住`。
   - 可售态：`vacant`、`available`、`clean`、`空房`、`可售`。
   - 维修/停用/脏房保留在分布内，但不算可售剩余。
3. 若实时房态有房间行：
   - `total_rooms = 实时房态去重房间数/行数`
   - `sold_rooms = 占用态数量`
   - `remaining_rooms = 可售态数量`
   - `occupancy_rate = sold_rooms / total_rooms`
4. 若实时房态没有可用行，保持原日结表逻辑。

## 风险

- 不同 PMS 房态枚举可能不完全一致；本次先覆盖现有常见中文/英文别名，未知状态不参与已售/可售，但保留在分布中。
- 真实 `kf11` 字段需要隧道恢复后只读核实；当前实现用现有 mapping contract 和 mock 回归保护。

## 验证

- `openspec validate prefer-realtime-room-status-occupancy --strict`
- `python -m unittest tests.test_derived_contexts`
- `python -m unittest discover -s tests/runtime`
