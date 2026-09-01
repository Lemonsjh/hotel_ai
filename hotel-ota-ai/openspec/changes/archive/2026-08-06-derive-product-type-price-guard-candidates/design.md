## Context

`price_guard_policies` 已支持 `channel_source` 和 `ota_product_id`，resolver 已按商品、渠道、房型优先级读取 active policy。但当前从 OTA 商品表读取价格时，没有把商品类型转成可审查的候选护栏。

## Goals / Non-Goals

**Goals:** 在只读价格映射输出中为每个商品给出候选护栏；明确商品类型；让运营/CFG 可以基于候选创建正式 active policy。

**Non-Goals:** 不自动写数据库；不绕过审批；不把候选护栏当作 live 可执行 active policy。

## Decisions

- `is_super_deal=1` 识别为 `super_deal`，候选上下界为当前价 ±15%。
- 商品名包含 `钟点房`、`小时`、`hour` 时识别为 `hour_room`，普通全日房调价护栏不自动覆盖。
- 其他美团可编辑商品识别为 `listed_full_day`，候选上下界为当前价 ±20%。
- 候选结构包含 `policy_scope=product`、`channel_source`、`ota_product_id`、`room_type_id`、`floor_price`、`ceiling_price`、`max_increase_pct`、`max_decrease_pct`、`activation_required=true`。

## Risks / Trade-offs

- 候选价格依赖当前采集价格；如果价格本身异常，候选也会异常，因此只能作为待审批建议。
- 钟点房识别基于名称和字段信号，保守标记为不自动纳入全日房护栏。
