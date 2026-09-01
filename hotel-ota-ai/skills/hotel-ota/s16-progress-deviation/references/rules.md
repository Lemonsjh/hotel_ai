# S16 进度偏差诊断规则

## 核心输入字段
- `orders_today`
- `actual_orders`
- `target_orders`
- `progress_checkpoint`
- `checkpoint_target_orders`
- `completion_rate`
- `daily_completion_rate`
- `traffic_problem`
- `conversion_problem`
- `field_freshness`

## 判断逻辑
1. 按 12 点、16 点、20 点节点目标判断当前进度，不能只看全天目标。
2. `actual_orders` 优先使用 `order_snapshot.business_date` 或 `order_snapshot.checkin_time` 的日期部分统计今日唯一订单数。
3. `actual_orders` 不得取 `daily_metrics.room_nights`；缺失今日实时订单/今日已售字段时只能输出 `data_gap`。
4. `target_orders` 来自 S15 基准线或明确日目标；必须输出 `actual_source`、`target_source`、`actual_basis_date`、`target_basis_date` 和 `field_freshness`。
5. 节点进度落后时先区分流量不足和转化不足。
6. 只有流量不足时，优先建议推广、曝光入口、活动资源和内容优化，不直接降价。
7. 只有转化不足时，才允许进入 S5 调价或活动调整候选。
8. 任一核心字段不是可信今日口径时，不得触发 S5，只能转 S14 或提示数据缺口。

## 房态和销量口径
- 入住销量按入住当夜统计。
- 次日下午 14:00 前退房且未续住的房间，按当日可售房处理。
- 数据上传时间不能替代业务时间；必须区分 `data_snapshot_time` 和订单/入住业务日期。

## 数据库来源
- 可读取 `database-query --template operating_snapshot`、`daily_metrics`、`monthly_metrics` 和 `order_snapshot`。
- 预订明细应先归一化为 `order_snapshot` 或 `reservation_snapshot`；不要在 skill 里写死 JD01/JD04/RS01 表名。
- MySQL 报表库只作为偏差诊断证据来源，目标口径不一致时输出 `needs_business_confirm`。
- 月/年累计只能作为对比证据，不能作为今日节点目标。
- 旧数据只能输出历史/演示偏差，不得触发 S5 正式调价审批。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- S16 不直接执行写动作，只能给 S14/S9/S5 提供诊断信号。
- 输出必须带 `data_business_date`、`data_snapshot_time`、`freshness_status`。

## V27 可施工算法规格

# 算法来源

- 对应节点：N011 / S16 进度偏差诊断
- 对应 Agent：A2
- 对应 BP：P0
- 对应源文件：`references/source/source_manifest.yaml`
- 对应字段契约：`contracts/node_io_contract.yaml`
- 对应 runtime algorithm_rules：`runtime/algorithm_rules/progress_deviation_rules.yaml`

# 输入字段

## hard_required
缺失则阻断：hotel_id, data_business_date, daily_target, actual_progress

## soft_required
缺失可继续但必须输出 data_gap：hourly_curve, demand_index, traffic_bottleneck

## optional
增强判断，不阻断主链路：none

## candidate
候选字段，不稳定，不用于 live：none

## blocked_for_live
可用于诊断或 dry-run，不得用于正式执行：demo_data, sample_data, stale, missing_date

# 算法步骤

1. Calculate progress_gap=actual_progress-baseline_progress and completion_rate.
2. Attribute gap to traffic, conversion, price, inventory, reputation, or baseline quality.
3. Classify ahead/normal/behind/critical.
4. Route traffic gap to S9/S8, price gap to S5, and summary to S3/A6 candidate learning.

# 判断规则

阈值与分级来自 `runtime/algorithm_rules/progress_deviation_rules.yaml`：`{"behind_gap_pct": -0.1, "critical_gap_pct": -0.2, "ahead_gap_pct": 0.1}`。
冲突处理顺序：DataGate > freshness > approval/live guard > price/budget guard > skill-specific threshold。

# 降级规则

- When hard-required fields are missing, return missing_fields and confidence=low.
- When input is demo/sample/stale, return preview_only or dry_run and block formal approval/live.
- When source capability is read-only/manual, produce recommendation or task only.

# 输出结构

- confirmed outputs：progress_status, room_night_gap, deviation_reasons
- candidate outputs：urgency_level, downstream_suggestion

# forbidden_actions / 禁止事项

- treat_demo_data_as_real_today_data
- create_formal_approval_from_demo_or_stale_data
- bypass_data_gate_or_approval_guard

# 测试样例

- 正常样例：见 `references/v20_behavior_cases.json` 的 normal/preview case。
- 缺字段样例：见 `references/v20_behavior_cases.json` 的 missing_hard_required case。
- demo/sample/stale 阻断样例：见 `references/v20_behavior_cases.json` 的 demo_preview case。
