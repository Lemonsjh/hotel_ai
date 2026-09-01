## Context

现有 V1 角色表允许 `open_id` 与 `feishu_open_id` 等别名并存，匹配按数组顺序返回。`allowed_chat_ids` 同时承载群聊和私聊语义，无法表达明确的聊天类型策略。

## Goals / Non-Goals

**Goals:** 以 canonical identity 校验冲突；用 `chat_type` 区分 group 与 p2p；定义受控 owner/admin 权限；使现有 V1 配置在迁移期可读。

**Non-Goals:** 不提供飞书写入角色表、不自动迁移 `/etc`、不实现多酒店团队管理 UI。

## Decisions

- V2 使用 `allowed_group_chat_ids` 和 `direct_message_policy=role_mapped_users_only`；业务配置不再出现 `user:ou_*`。
- V1 继续读取，但别名冲突、重复逻辑身份或无效角色必须拒绝相关认证并在预检中明确报错。
- owner 仅拥有业务审批和未来业务配置预览范围；系统安全配置与直接 live 执行仅属于 admin/受控服务路径。
- 生产 route 必须带 `chat_type`、身份和 auth config；缺失即 `invalid_context`。

## Risks / Trade-offs

- 严格校验会暴露现有私有配置问题 → 先提供只读 preflight 和 V1 兼容，再人工迁移。
- 收紧 owner 权限会改变旧调用结果 → 用回归测试和明确拒绝原因保障可解释性。
