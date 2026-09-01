## ADDED Requirements

### Requirement: 飞书群级角色隔离
系统 MUST 将飞书群内配置或申请产生的角色限定在当前 `chat_id` 范围内。

#### Scenario: 当前群角色查询只返回当前群
- **GIVEN** 同一 `hotel_id` 下存在两个不同 `chat_id`
- **AND** 群 A 配置 owner 张三
- **AND** 群 B 配置 operator 李四
- **WHEN** 在群 A 查询当前群角色
- **THEN** 只能统计群 A 成员角色
- **AND** 不得包含群 B 成员

#### Scenario: 跨群不继承 owner
- **GIVEN** 用户在群 A 是 owner
- **AND** 群 B 绑定同一酒店
- **WHEN** 用户在群 B 发起生产飞书业务请求
- **THEN** 系统不得因为群 A owner 身份在群 B 自动授权 owner

#### Scenario: 酒店级基础权限 fallback
- **GIVEN** 私有 auth_config 明确配置了 `hotel_memberships`
- **AND** 当前群没有群级角色
- **WHEN** 用户在绑定群发起请求
- **THEN** 系统 MAY 使用酒店级基础权限作为 fallback
- **AND** 必须把来源标记为酒店级基础权限 fallback，而不是当前群角色
