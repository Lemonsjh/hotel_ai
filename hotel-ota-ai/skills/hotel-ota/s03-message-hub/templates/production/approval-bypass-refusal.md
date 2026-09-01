# 审批绕过拒绝模板

结论：不能绕过数据新鲜度、审批记录或 live 开关。
证据：当前请求命中 `{{blocked_reason}}`。
建议：人工补数必须走受控 `manual_upload` 或 `manual_entry`，带录入人、录入时间、来源和审计摘要。
风险：聊天里手动提供的数据不能创建正式审批，stale/demo/sample/manual_chat 不得 live 执行。
