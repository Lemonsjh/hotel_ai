## ADDED Requirements

### Requirement: Live handoff 必填证据
任何 live 调价 handoff MUST 包含可信 `old_price`、`hotel_id`、权威房型 guard config 和当前版本 payload hash。

#### Scenario: 缺当前价格
- **WHEN** live handoff 缺少 `old_price`
- **THEN** 系统拒绝 handoff 且不调用渠道 adapter

### Requirement: Hotel-bound payload
S5/S6 价格 payload hash MUST 包含 `hotel_id` 和 price guard version，旧 hash MUST NOT 用于 live。

#### Scenario: 跨酒店 payload
- **WHEN** payload 的 hotel 与审批或执行 hotel 不一致
- **THEN** 系统拒绝执行并保留审计原因

### Requirement: 认证审批人
审批状态变更 MUST 使用经认证身份和角色，并拒绝请求人审批自己的请求。

#### Scenario: 未认证审批
- **WHEN** approval mark 未提供已验证审批身份
- **THEN** 系统不改变 approval 状态
