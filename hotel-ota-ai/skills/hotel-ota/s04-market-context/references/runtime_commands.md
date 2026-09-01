# S4 环境行情感知 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py calendar-sync --year 2026`
- `python runtime/hotel_ota_runtime.py calendar-query --date 2026-02-14`
- `python runtime/hotel_ota_runtime.py market-context --hotel-id puyue --date 2026-02-14`
- `python runtime/hotel_ota_runtime.py event-discover --hotel-id puyue --date-range 2026-02-01:2026-02-28`
- `python runtime/hotel_ota_runtime.py demand-index --hotel-id puyue`

## 规则
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须加审批和 dry-run 预览。
- 天气第一版优先 MCP 归一化输入；API 只作为后备。
- 业务日历是 S4 的基础事实，节假日/调休/周末不要由模型临时猜测。
- 只有 `market-context` 明确 `downstream_allowed=true` 时，才可把行情增强信号交给 S5。
