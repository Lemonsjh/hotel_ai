## ADDED Requirements

### Requirement: Canonical 身份校验
生产飞书鉴权 MUST 使用 canonical `open_id`、`user_id` 或 `union_id`，并拒绝同一逻辑身份映射到多个角色的配置。

#### Scenario: 冲突身份
- **WHEN** role-map 将同一个 canonical identity 配置为多个角色
- **THEN** 鉴权返回配置冲突且不授予业务权限

### Requirement: 群聊与私聊策略
群聊 MUST 校验 `allowed_group_chat_ids`；私聊 MUST 依据已匹配身份和 `direct_message_policy` 判断，不依赖 `user:` 前缀聊天标识。

#### Scenario: 已映射私聊用户
- **WHEN** p2p 消息的身份已在 role-map 匹配且策略允许私聊
- **THEN** 系统授予该角色的业务权限

### Requirement: 审批职责分离
审批和 live handoff MUST 绑定经认证的身份、角色和 hotel scope，且请求人不得审批自己的请求。

#### Scenario: 自审批请求
- **WHEN** 请求人与审批人为同一 canonical identity
- **THEN** 审批操作被拒绝且不会改变审批状态
