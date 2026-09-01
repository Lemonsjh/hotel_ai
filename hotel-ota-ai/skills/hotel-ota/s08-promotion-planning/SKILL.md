---
name: s08-promotion-planning
description: "S8 推广通数据展示：触发时只读取美团推广通近30天最新快照，展示原始字段与确定性派生指标，不生成规划、建议、审批或执行动作。"
---

# S8 推广通数据展示

## Reference 导航

执行本 skill 前读取本目录 `references/`：

- `references/input_schema.json`
- `references/output_schema.json`
- `references/rules.md`
- `references/examples.md`
- `references/runtime_commands.md`

## 适用场景

用户要求查看 S8、推广通、推广投放近30天表现或当前最新推广通快照时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`
- `{baseDir}/../_shared/operating-policy.md`

共享规范仅用于租户隔离、安全和通用交付约束，不得把其他 Skill 的经营判断、推广规划或执行逻辑引入 S8。

## 唯一职责

S8 仅做推广通数据展示：

1. 在 S8 被触发时读取数据库。
2. 唯一业务数据表为 `meituan_ota_promotion_performance_30d`。
3. 按可信 `hotel_id` 隔离，并读取该酒店最新 `snapshot_time`；如运行上下文提供 `as_of_time`，读取不晚于该时间的最新快照。
4. 展示推广通原始字段及由同一行数据确定性计算的展示指标。
5. 返回后结束，不做诊断、规划、推荐、审批、任务或执行。

## 允许展示的数据

名称字段：

- `plan_name`
- `launch_name`
- `promotion_name`

推广花费与效果字段：

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

`plan_id`、`launch_id` 只用于内部定位和去重，可保留在结构化证据中，不作为默认中文展示重点。

## 确定性展示指标

仅允许基于同一推广通记录计算：

- 单次获客成本 = `spend_amount / booking_order_count`
- 每间夜成本 = `spend_amount / room_night_count`
- 推广预订单均价 = `booking_order_amount / booking_order_count`
- 推广间夜均价 ADR = `booking_order_amount / room_night_count`
- ROAS = `booking_order_amount / spend_amount`
- 推广花费后金额 = `booking_order_amount - spend_amount`
- 现金 ROAS = `booking_order_amount / cash_spend_amount`
- 推广预订转化率 = `booking_order_count / click_count * 100%`

任何分母为 0、空值或不可解析时返回 `not_computable`，不得用 0、无穷大或其他计划数据替代。

`click_rate_pct` 直接展示数据库来源值，不由 S8 推断推广状态或业务结论。

## 明确禁止

S8 不得：

- 读取 `ctrip_ota_promotion_performance_30d` 或任何其他业务表；
- 读取活动、价格、经营指标、推广开通状态表；
- 调用 S2、S4、S7、S9、S10、S16 或其他 Skill 生成 S8 结果；
- 展示或推断 `promotion_status`、`promotion_open_status`、OPEN/CLOSED/PENDING、RUNNING/PAUSED；
- 输出 enable/resume/maintain/observe/pause/close 等推广动作；
- 给出预算、出价、扩量、暂停、关闭或活动优化建议；
- 创建审批、任务、确认命令或任何写请求；
- 用 demo、sample、synthetic、缓存旧结果或其他平台数据补齐真实数据缺口。

## 输出要求

S8 使用通用 runtime envelope，并保持：

- `recommendations=[]`
- `actions=[]`
- `approval_required=false`
- `write_performed=false`
- `live_allowed=false`
- `execution_supported=false`
- `task_creation_supported=false`

业务数据放在 `evidence.promotion_display` 中。

## 数据缺口

- 数据源、表结构或查询失败：返回 `data_gap`，不回退其他来源。
- 最新快照没有记录：返回 `status=ok`、`source_status=no_rows`，明确当前无可展示数据。
- 不得把无记录解释为推广未开通、已暂停或效果为 0。

## V27 兼容说明

目录和 wrapper 继续保留 V27 兼容元数据，但本分支 S8 的运行时业务范围已收窄为“推广通只读展示”。旧的活动计划、推广计划、预算、动作、时间窗和上游 Skill 输入只作为已退役兼容语义记录，不再参与 S8 运行。

## 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py promotion-plan --hotel-id <hotel_id>
```

`promotion-plan` 为历史兼容命令名，当前语义仅为“读取并展示 S8 推广通数据”。

## 飞书输出规则

- 生产飞书输出继续遵守 feishu-output-gate 语义。
- 不得输出 DSN、token、服务器私有路径、原始 SQL 或内部 request payload。
- 中文回复只陈述本次读取到的推广通数据及可计算展示指标，不追加经营建议。
