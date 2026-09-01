## 1. Role-map 验证

- [x] 1.1 为 V2 schema、别名冲突、重复身份和非法角色编写失败测试。
- [x] 1.2 实现 canonical identity、V1 只读兼容和不暴露身份值的迁移预览。

## 2. 聊天与权限边界

- [x] 2.1 为 group/p2p、self-claim 和 chat type 传递补充回归测试。
- [x] 2.2 在 auth context、CLI、command menu 和插件 route 中透传 chat type 并 fail-closed。
- [x] 2.3 收敛 owner/admin、审批人、hotel binding 与 self-approval 限制。

## 3. 文档与验收

- [x] 3.1 更新 V2 role-map 示例和私有配置边界。
- [x] 3.2 运行鉴权、审批和飞书回归测试。
