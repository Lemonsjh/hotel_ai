# S8 推广通数据展示规则

## 唯一数据源

S8 只允许读取：

`meituan_ota_promotion_performance_30d`

不得读取携程推广表、活动表、价格表、经营指标表、推广状态表或其他 Skill 的结果作为 S8 业务输入。

## 触发与快照规则

1. 只有 S8 被触发时才读取数据库。
2. 必须使用可信 `hotel_id` 精确过滤，不得跨酒店读取。
3. 默认读取该酒店 `MAX(snapshot_time)` 对应的完整快照。
4. 如运行上下文提供 `as_of_time`，读取 `snapshot_time <= as_of_time` 范围内的最大快照。
5. 不使用上次运行缓存、demo、sample、synthetic 或其他平台数据回填。
6. 最新快照无记录时返回 `source_status=no_rows`，不得推断为“未开通”“已暂停”或“效果为 0”。

## 原始展示字段

名称：

- `plan_name`
- `launch_name`
- `promotion_name`

推广花费与效果：

- `spend_amount`
- `cash_spend_amount`
- `exposure_count`
- `click_count`
- `booking_order_count`
- `room_night_count`
- `booking_order_amount`
- `click_rate_pct`
- `cost_per_click`

时间范围：

- `period_start_date`
- `period_end_date`
- `snapshot_time`

内部定位字段：

- `plan_id`
- `launch_id`

内部定位字段允许保留在结构化证据中，但不作为默认中文展示重点。

## 禁止展示和推断

不得读取、展示或推断：

- `promotion_status`
- `promotion_open_status`
- OPEN / CLOSED / PENDING
- RUNNING / PAUSED
- 预算建议、出价建议、扩量建议
- enable / resume / maintain / observe / pause / close
- 活动冲突、价格风险、经营诊断或其他推广规划结论

## 确定性展示计算

同一条推广通记录可计算：

- `cost_per_booking = spend_amount / booking_order_count`
- `cost_per_room_night = spend_amount / room_night_count`
- `average_booking_order_amount = booking_order_amount / booking_order_count`
- `promotion_adr = booking_order_amount / room_night_count`
- `roas = booking_order_amount / spend_amount`
- `promotion_amount_after_spend = booking_order_amount - spend_amount`
- `cash_roas = booking_order_amount / cash_spend_amount`
- `booking_conversion_rate_pct = booking_order_count / click_count * 100`

这些指标仅用于展示，不转换为推荐、评分、动作或经营结论。

## 不可计算规则

任何除法遇到以下情况返回 `not_computable`：

- 分母为空；
- 分母不可解析为数字；
- 分母为 0；
- 分子为空或不可解析为数字。

不得返回无穷大，不得把不可计算值替换为 0，不得借用其他计划或其他酒店数据。

`promotion_amount_after_spend` 只有在 `booking_order_amount` 和 `spend_amount` 均可解析时计算；该值只表示“推广归因订单金额减推广花费”，不得描述为利润、净利润或增量收益。

## 输出边界

S8 必须保持：

- `recommendations=[]`
- `actions=[]`
- `approval_required=false`
- `write_performed=false`
- `live_allowed=false`
- `execution_supported=false`
- `task_creation_supported=false`
- `ota_write_attempted=false`

不得创建审批、任务、确认命令，不得向 OTA、插件、第三方服务或内部写入端发送请求。

## Skill 隔离

- S8 不调用任何其他 Skill。
- S8 不依赖任何其他 Skill 的输入或输出。
- S8 不作为推广建议、规划、审批、任务或执行能力的兼容入口。
- 其他 Skill 的推广相关命令不得重定向到 S8 展示链路。

## 异常处理

- 数据源未配置、表不可用、查询失败：`status=data_gap`。
- 必需结构字段缺失：`status=data_gap`，并标记 schema drift。
- 最新快照无记录：`status=ok`、`source_status=no_rows`。
- 任何异常都不得回退到其他表或其他 Skill。

## 命令语义

`promotion-plan` 仅保留历史命令名，当前业务语义只有“读取并展示推广通数据”。

该命令不得产生任何推广计划、推荐或执行语义。
