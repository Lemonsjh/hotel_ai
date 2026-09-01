## MODIFIED Requirements

### Requirement: Owner 管理当前群角色
系统 MUST 允许 owner 在当前绑定酒店和当前群范围内发起 owner/operator/frontdesk 的授予或撤销，并保持申请、确认和审计流程。

#### Scenario: owner 授予 owner
- **GIVEN** requester 是当前酒店 owner
- **AND** 当前 `chat_id` 已绑定该酒店
- **AND** target principal 存在且不是 requester
- **WHEN** requester 发起授予 `owner`
- **THEN** 系统 MUST 创建待确认 ROLE 请求

#### Scenario: owner 不能修改自己
- **GIVEN** requester 是当前酒店 owner
- **WHEN** requester 尝试修改自己的角色
- **THEN** 系统 MUST 阻断
- **AND** 原因为 `owner_cannot_modify_self_membership`

#### Scenario: owner 不能修改 admin
- **GIVEN** target 当前是 active admin
- **WHEN** owner 尝试授予或撤销该 target 的角色
- **THEN** 系统 MUST 阻断
- **AND** 原因为 `owner_cannot_modify_admin_membership`

#### Scenario: owner 撤销其他 owner
- **GIVEN** requester 和 target 都是当前酒店 active owner
- **AND** requester 与 target 不是同一 principal
- **WHEN** requester 发起撤销 target 的 owner 角色
- **THEN** 系统 MUST 创建待确认 ROLE 请求
