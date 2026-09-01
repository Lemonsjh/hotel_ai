# 身份回复模板

结论：开发环境身份仍以 runtime `auth-check` 为准。
证据：`user_role={{user_role}}`，`auth_status={{auth_status}}`。
建议：调试角色时使用本地 CLI 指定 `--auth-config`，不要依赖会话记忆。
风险：开发环境也不能用用户自称授权。
