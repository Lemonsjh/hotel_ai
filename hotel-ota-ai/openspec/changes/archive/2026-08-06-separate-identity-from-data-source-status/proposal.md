## Why

用户问“我是谁 / 查身份 / 鉴权状态”时，只想确认身份、角色和当前群绑定。把 demo/live/MySQL 数据源状态混入身份话术，会误导用户以为群绑定或数据库有问题。

## What Changes

- 生产飞书 identity 输出只展示鉴权状态、当前角色、当前群绑定酒店和鉴权来源。
- 明确说明本指令只检查身份和群绑定，不读取 PMS/MySQL 经营数据。
- 移除 identity 输出中的 demo/live/formal approval 环境判断。

## Impact

- 影响飞书 identity 路由结果摘要和 renderer 文案。
- 不改变实际权限判断和 permission gate。
