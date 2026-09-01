## Why

同一个酒店可能存在多个飞书群。通过飞书群里申请/配置出来的角色如果只落到 `hotel_memberships`，会让用户在 A 群获得的 owner/operator/frontdesk 权限自动扩散到 B 群。

生产要求是：飞书群配置的角色默认属于当前群；酒店级汇总可以存在，但不能冒充当前群。

## What Changes

- 新增群级角色成员表 `chat_role_memberships`。
- 群聊 ROLE 申请确认后写入当前 `chat_id_hash + hotel_id + principal_id` 的群级角色。
- 群聊鉴权优先使用 `chat_role_memberships`；没有群级角色时再使用私有 `auth_config` bootstrap 的 `hotel_memberships` 基础权限。
- 当前群成员角色查询按当前 `chat_id` 过滤。
- 输出不展示 raw `open_id/user_id/union_id/ou_xxx`。

## Impact

- 影响 SQLite schema、control plane、Feishu auth 和管理读模型。
- 私聊仍使用酒店级 `hotel_memberships`。
- 现有通过 auth_config 明确配置的酒店级权限不变。
