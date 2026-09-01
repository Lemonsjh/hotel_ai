# 审批绕过拒绝模板

结论：不能绕过数据新鲜度、审批记录或 live 开关。
证据：当前请求命中 `{{blocked_reason}}`。
建议：开发调试可构造 dry-run 或测试审批，但不得把 stale/demo/sample/manual_chat 当正式审批数据。
风险：绕过式审批会污染生产审计链路。
