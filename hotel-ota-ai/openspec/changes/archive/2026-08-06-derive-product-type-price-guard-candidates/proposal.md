## Why

同一房型下可能同时存在挂牌全日房、超级团购和钟点房商品，价格跨度很大。单一房型级 `[floor_price, ceiling_price]` 无法同时约束全日房和团购商品，容易让调价建议使用错误护栏。

## What Changes

- 从 `ota_price_mapping` 读取结果中识别商品类型。
- 为美团挂牌全日房和超级团购生成只读商品级护栏候选。
- 钟点房商品标记为不适合普通全日房调价护栏。
- 不自动写入或激活 `price_guard_policies`；正式生效仍需 CFG/审批或受控配置写入。

## Capabilities

### New Capabilities
- `product-type-price-guard-candidates`: 从 OTA 商品映射生成商品类型级价格护栏候选。

### Modified Capabilities
- None.

## Impact

影响 `runtime/adapters/database.py` 的 `ota_price_mapping` 输出和相关测试；不改变 live 调价审批和 price task 写入。
