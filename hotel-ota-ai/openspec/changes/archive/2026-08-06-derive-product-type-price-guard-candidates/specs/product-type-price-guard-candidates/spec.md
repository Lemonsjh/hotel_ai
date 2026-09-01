## ADDED Requirements

### Requirement: OTA 商品映射生成商品级护栏候选
系统 MUST 从 OTA 商品映射输出中生成只读商品级价格护栏候选。

#### Scenario: 美团挂牌全日房
- **WHEN** 美团商品 `is_super_deal=0`
- **AND** 商品名不是钟点房
- **THEN** 候选护栏类型为 `listed_full_day`
- **AND** 上下界为当前价 ±20%
- **AND** 候选必须标记 `activation_required=true`

#### Scenario: 美团超级团购
- **WHEN** 美团商品 `is_super_deal=1`
- **THEN** 候选护栏类型为 `super_deal`
- **AND** 上下界为当前价 ±15%
- **AND** 候选作用域包含 `ota_product_id`

#### Scenario: 钟点房商品
- **WHEN** 商品名包含 `钟点房`、`小时` 或 `hour`
- **THEN** 候选护栏类型为 `hour_room`
- **AND** 不自动纳入普通全日房调价护栏
- **AND** `activation_required=true`
