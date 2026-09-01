## Why

当前 live price guard 在缺少 `old_price` 时跳过涨跌幅校验，payload hash 未绑定 `hotel_id`，审批操作也未完整绑定认证身份。虽然 live 默认关闭，这些缺口必须在任何启用前 fail-closed。

## What Changes

- 对 live handoff 强制可信 old price、hotel binding 和权威 room-type guard config。
- 将 hotel、认证请求人/审批人和 price guard version 纳入审批与 payload 校验。
- 拒绝自审批和旧 payload hash；保持 demo/dry-run 只能预览。

## Capabilities

### New Capabilities
- `live-price-handoff-guard`: 价格执行 handoff、审批身份和 hotel 绑定安全约束。

### Modified Capabilities
- None.

## Impact

影响 S5/S6 payload hash、price guard、approval storage/CLI 和回归测试；不启用任何 live 渠道，也不新增飞书配置写入。
