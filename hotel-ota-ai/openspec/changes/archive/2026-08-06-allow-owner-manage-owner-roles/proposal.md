## Why

酒店 owner 是生产飞书端的主要运营管理员。全局 admin 不可能一直在线，因此 owner 必须能在当前绑定酒店和当前群范围内发起 owner/operator/frontdesk 的授予和撤销。

当前控制面仍限制 owner 只能管理 operator/frontdesk，并且 owner 角色申请只能由全局 admin 创建和确认，导致业务上无法由 owner 扩充 owner。

## What Changes

- owner 可以在自己有酒店 scope 的当前绑定群内发起 owner/operator/frontdesk 授权或撤销。
- owner 不能修改自己。
- owner 不能修改 admin。
- 角色变更仍然走申请、确认和审计日志，不直接无审计写入。
- 跨酒店、跨群绑定不放行。

## Impact

- 影响 `runtime/control_plane.py` 的 ROLE 申请和确认逻辑。
- 影响飞书角色配置相关测试。
- 不改变 global admin 全局权限。
