## 1. Guard 与 payload

- [x] 1.1 为缺 old price、hotel binding、guard source 和旧 hash 编写失败测试。
- [x] 1.2 实现 live handoff fail-closed 与 hotel-bound payload hash。

## 2. 审批身份

- [x] 2.1 为认证请求人、审批人角色和 self-approval 拒绝编写测试。
- [x] 2.2 将身份和 hotel scope 写入并校验 approval handoff。

## 3. 验收

- [x] 3.1 运行 S5/S6、approval、freshness 与 demo safety 回归。
- [x] 3.2 确认 demo/sample/stale 仍不能创建正式审批或 live。
