# S5 智能收益决策 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py revenue-decision --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py expected-occupancy --hotel-id puyue --date 2026-06-08`
- `python runtime/hotel_ota_runtime.py baseline-price --hotel-id puyue --date 2026-06-08`
- `python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-price`
- `python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-price`
- `python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template operating_snapshot --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template price_snapshot --hotel-id puyue`

## 规则
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须加审批和 dry-run 预览。
- API 未确认时优先使用 `normalize-sample`、manual upload 或 RPA 输入。
- MySQL 房态和房费日报只能作为收益建议证据；真实调价仍必须走 S6 dry-run 和 admin/owner 审批。
- S5 正式调价建议必须同时有今晚预期出租率和房型基准价；实时在住率、昨日出租率或 sample 数据不得作为调价依据。
