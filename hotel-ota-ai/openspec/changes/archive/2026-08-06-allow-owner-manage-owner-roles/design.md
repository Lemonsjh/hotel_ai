## Design

### Chat ROLE request

`create_chat_role_change_request()` 继续要求：

- `requested_role` 属于 `owner/operator/frontdesk`
- `operation` 属于 `grant/revoke`
- requester 是当前酒店 scope 内的 `admin` 或 `owner`
- `chat_id` 绑定到同一 `hotel_id`
- target principal 存在

移除 `requested_role=owner` 只能由全局 admin 发起的限制。

### Target protection

目标保护改为：

- requester 是 owner 且 target 是自己：阻断 `owner_cannot_modify_self_membership`
- target 当前是 admin：阻断 `owner_cannot_modify_admin_membership`
- target 当前是 owner：
  - `operation=revoke` 且 requester 不是自己：允许进入确认流程
  - `operation=grant` 且 target 已经是 owner：阻断，避免无意义重复申请
  - grant owner 给非 owner target：允许进入确认流程

### Confirmation

`confirm_chat_role_change_request()` 继续要求当前 `chat_id` hash 匹配、请求未过期、actor 有酒店 scope，且 actor 是 owner 或 global admin。

移除 `requested_role=owner` 必须 global admin 确认的限制。确认时仍禁止 target 自己确认自己的角色申请。

### Role-map configuration request

`_owner_membership_change_allowed()` 和 `create_role_membership_request_from_role_map()` 同步允许 owner 申请 `owner/operator/frontdesk`，并保留不能改自己、必须是当前酒店 owner 的校验。
