## Why

当前 role-map 未校验身份别名冲突，群聊和私聊 allowlist 语义不一致，owner/admin 权限边界也与运行规则冲突。这会导致静默错误授权、合法用户误拒绝或跨范围操作。

## What Changes

- 定义 V2 role-map 的 canonical identity、群聊和私聊语义，并保留 V1 只读兼容与迁移预览。
- 对冲突身份、未知 chat type 和不完整生产身份 fail-closed。
- 收敛 owner/admin/审批人权限与酒店绑定，禁止自审批自执行。

## Capabilities

### New Capabilities
- `feishu-role-authentication`: 角色配置验证、身份匹配、聊天范围和审批身份边界。

### Modified Capabilities
- None.

## Impact

影响 `runtime/safety/auth.py`、飞书路由、role-map example、审批校验、测试和部署说明；不自动写私有角色表。
