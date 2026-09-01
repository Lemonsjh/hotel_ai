# S16 进度偏差诊断 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py deviation --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template daily_metrics --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py database-query --db-kind mysql --template monthly_metrics --hotel-id puyue`

## 规则
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须加审批和 dry-run 预览。
- API 未确认时优先使用 `normalize-sample`、manual upload 或 RPA 输入。
- MySQL 指标只作为偏差证据来源；指标别名变化时改 `database-source.json`。
