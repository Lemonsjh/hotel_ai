# S17 客户订单分析 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py customer-analysis --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-order`
- `python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template order_snapshot --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py database-inspect --db-kind mysql --mode sample --table fact_room_fee_daily --limit 5`

## 规则
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须加审批和 dry-run 预览。
- API 未确认时优先使用 `normalize-sample`、manual upload 或 RPA 输入。
- MySQL `order_snapshot` 默认脱敏 `guest_name`、`room_no`、`order_no`、`operator_name`，飞书回复不得展示完整敏感字段。
- 生产飞书优先调用 `customer-analysis`，只展示聚合摘要；不得贴出 `order_snapshot.orders` 行级列表。
