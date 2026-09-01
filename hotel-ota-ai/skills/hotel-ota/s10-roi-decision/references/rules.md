# S10 ROI 决策 规则

## 核心输入字段
- `promotion_cost`
- `promotion_revenue`
- `room_nights`
- `adr`
- `revpar`
- `commission`
- `refund_amount`

## 当前真实来源口径

- 主源为 `meituan_ota_promotion_performance_30d` 与 `ctrip_ota_promotion_performance_30d`，必须按 exact `hotel_id`、平台、30 日窗口和 `snapshot_time` 独立读取；不得借用同库其他酒店。
- `booking_order_amount / spend_amount` 仅称为“来源归因 ROAS”。`booking_order_amount - spend_amount` 仅是未观测成本前差额，不是净利润。
- `cash_spend_amount` 与 `spend_amount` 并列展示，不能混为一个成本口径。缺佣金、退款、固定/变动成本或增量归因时，只能 `observe_only`，不得输出继续、加投或暂停的正式投放结论。
- 美团必须先按 `plan_id+launch_id+period_start_date+period_end_date+snapshot_time` 输出，再在同渠道、同窗口按总量计算组合指标；携程无计划 ID 时仅输出酒店渠道窗口。不得平均各计划 ROAS/CPC/CPA，也不得跨平台或跨窗口合并。
- 零分母必须输出 `not_computable`，不能以 0 代替。`data_delayed=1` 为 `source_delayed`；存在且所有投放值为 0 为 `observed_zero_delivery`；来源原生指标和派生指标冲突时标记 `source_derived_conflict`。贡献估算和增量 ROI 缺批准成本政策或对照时均为 unavailable。

## 判断逻辑
1. 满房派、RevPAR派、利润派分开看
2. 无固定成本时只输出准利润
3. 低转化时不先加预算

## 可配置参数
- 蓝图中未最终确认的阈值标记为 `configurable`。
- 多源资料冲突时输出 `needs_business_confirm`，并采用更保守建议。
- API 未确认时字段质量为 `manual_required` 或 `inferred`。

## 异常处理
- 缺关键字段时先追问或降级为 sample/manual/RPA，不让 skill 失败退出。
- 低质量字段只能用于诊断、提示和 dry-run，不得用于真实执行。
- 原始 API 状态码必须先由 runtime 转成统一枚举后再解释。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- 必须记录请求摘要、响应码、失败原因和人工处理建议。


## V27 可施工算法规格

字段与 IO 以 `contracts/v27/` 为准；demo_data 仅可 preview/dry-run，不能正式审批或 live。
