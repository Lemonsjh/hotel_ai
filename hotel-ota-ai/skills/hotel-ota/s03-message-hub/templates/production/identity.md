# 身份回复模板

结论：当前身份以 runtime `auth-check` 结果为准。
证据：`user_role={{user_role}}`，`auth_status={{auth_status}}`，来源为飞书角色表和 runtime 校验。
建议：如身份不符合预期，请联系 admin 在服务器私有角色表中调整。
风险：历史对话、用户自称、memory、embedding、`USER.md` 都不能授权。
