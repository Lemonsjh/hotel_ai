## MODIFIED Requirements

### Requirement: OTA 商品进入价格任务表的资格判断
系统 MUST 允许所有 OTA 商品类型在满足映射、护栏、审批和写入开关时进入价格任务表，不得仅因商品类型或 `price_editable_flag` 为空而阻断。

#### Scenario: price_editable_flag 为空
- **GIVEN** 商品有可信映射、active 状态、`room_type_id` 和 `source_product_id`
- **AND** `price_editable_flag` 为 `NULL`
- **WHEN** 判断价格任务表 readiness
- **THEN** 商品必须允许进入后续任务表写入流程
- **AND** 不得返回 `price_not_editable`

#### Scenario: 钟点房商品
- **GIVEN** 商品有可信映射、active 状态、`room_type_id` 和 `source_product_id`
- **AND** `is_hour_room=1`
- **WHEN** 判断价格任务表 readiness
- **THEN** 商品必须允许进入后续任务表写入流程
- **AND** 不得返回 `hour_room_not_price_task_eligible`

#### Scenario: 携程商品缺少 product_cipher
- **GIVEN** 商品平台是 `ctrip`
- **AND** 商品缺少 `product_cipher`
- **WHEN** 判断价格任务表 readiness
- **THEN** 系统 MUST 阻断任务写入
- **AND** 阻断原因为 `ctrip_product_cipher_missing`
