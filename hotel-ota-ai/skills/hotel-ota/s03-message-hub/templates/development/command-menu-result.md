结论：command-menu-reply 已执行白名单命令。
数据：检查 `selected_command`、`execution_status`、`result_summary`。
证据：`final_reply` 是飞书可展示摘要，不是完整 runtime JSON。
风险：不得把完整 `result_summary` 扩展为原始数据外发。
建议：继续覆盖权限、过期、参数缺失和他人接管场景。
审批：写动作仍按原审批链路。
