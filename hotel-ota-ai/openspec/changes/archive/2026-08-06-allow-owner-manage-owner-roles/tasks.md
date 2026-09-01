## 1. Red tests

- [x] 1.1 owner 在当前群可发起 owner 授权申请。
- [x] 1.2 owner 不能修改自己。
- [x] 1.3 owner 不能修改 admin。
- [x] 1.4 owner 可撤销当前群/酒店内其他 owner。

## 2. Implementation

- [x] 2.1 放开 owner 发起 owner 授权。
- [x] 2.2 放开 owner 确认 owner 授权。
- [x] 2.3 调整目标保护逻辑，只阻断 self/admin 和无意义重复 owner grant。
- [x] 2.4 同步 role-map 配置申请 helper。
- [x] 2.5 飞书角色命令解析支持 `owner`、`业主`、`老板`。

## 3. Verification

- [x] 3.1 `openspec validate allow-owner-manage-owner-roles --strict` 通过。
- [x] 3.2 角色申请/确认相关测试通过。
