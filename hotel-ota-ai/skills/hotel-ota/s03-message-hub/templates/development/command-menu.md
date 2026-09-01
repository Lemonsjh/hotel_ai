结论：command-menu-start 已生成菜单。
数据：检查 `menu_id`、`expires_at`、`starter_role`、`available_commands`。
证据：菜单项来自权限过滤后的 runtime 白名单。
风险：开发调试也不得扩展为自由命令执行。
建议：用 command-menu-reply 复测编号和参数。
审批：写动作仍按原审批链路。
