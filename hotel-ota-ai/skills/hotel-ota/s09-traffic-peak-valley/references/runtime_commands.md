# S9 流量峰谷分析 runtime 命令

OpenClaw 调用时继续使用兼容入口 `python runtime/hotel_ota_runtime.py ...`。

## 可用命令
- `python runtime/hotel_ota_runtime.py demand-index --hotel-id puyue`
- `python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id puyue`

## 规则
- 不直接调用 runtime 内部模块路径。
- 真实写动作必须加审批和 dry-run 预览。
- API 未确认时优先使用 `normalize-sample`、manual upload 或 RPA 输入。
