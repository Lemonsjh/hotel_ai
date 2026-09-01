# S15 销售基准线规则

## 核心输入字段
- `business_date`
- `historical_same_weekday`
- `historical_same_date_type`
- `holiday_history`
- `calendar_context`
- `target_orders`
- `hourly_curve`
- `progress_checkpoints`

## 判断逻辑
1. 保留近 7/14/30 天、同星期、同日期属性、节假日和业务日历口径。
2. 输出全天目标 `target_orders`，同时输出 12 点、16 点、20 点节点目标。
3. 节假日、调休上班、节前节后、寒暑假和本地事件只影响基准线修正，不直接触发调价。
4. 调休上班日不能按普通周末高需求处理。
5. 缺历史数据时输出中低置信度基准线，不包装成正式高置信结论。

## 数据库来源
- 可读取 `database-query --template daily_metrics`、`monthly_metrics` 或 `order_snapshot` 作为基准线输入。
- MySQL `fact_daily_metrics` 日目标只采纳 `period_type=本日/今日/当天/当日` 等日口径。
- `fact_monthly_metrics` 和本月/本年累计只作对比证据，不得覆盖当天目标。
- 数据库来源必须只读，不允许写回外部业务库。

## 输出要求
- 必须输出 `target_basis_date`、`target_basis_type`、`source_confidence`、`decision_confidence`。
- 必须输出 `progress_checkpoints`，至少包含 12、16、20 三个节点。
- 输出要说明是否可作为 S16 今日进度判断依据。

## 安全规则
- S15 不执行任何写动作。
- 低质量字段只能用于诊断、提示或 dry-run，不得用于真实执行。
- 输出必须带 `data_business_date`、`data_snapshot_time`、`freshness_status`。

## V27 可施工算法规格

# 算法来源

- 对应节点：N010 / S15 销售基准线
- 对应 Agent：A2
- 对应 BP：P0
- 对应源文件：`references/source/source_manifest.yaml`
- 对应字段契约：`contracts/node_io_contract.yaml`
- 对应 runtime algorithm_rules：`runtime/algorithm_rules/baseline_rules.yaml`

# 输入字段

## hard_required
缺失则阻断：hotel_id, data_business_date

## soft_required
缺失可继续但必须输出 data_gap：historical_same_period, demand_index, available_rooms, target_occupancy_rate

## optional
增强判断，不阻断主链路：none

## candidate
候选字段，不稳定，不用于 live：none

## blocked_for_live
可用于诊断或 dry-run，不得用于正式执行：demo_data, sample_data, stale, missing_date

# 算法步骤

1. Load historical target, recent trend, day type, and market context.
2. Calculate daily target and hourly checkpoints.
3. Version baseline source and mark manual/candidate fields explicitly.
4. Route baseline to S16/S5/S3 without treating demo data as today fact.

# 判断规则

阈值与分级来自 `runtime/algorithm_rules/baseline_rules.yaml`：`{"checkpoint_hours": [12, 16, 20, 23], "manual_baseline_requires_audit": true}`。
冲突处理顺序：DataGate > freshness > approval/live guard > price/budget guard > skill-specific threshold。

# 降级规则

- When hard-required fields are missing, return missing_fields and confidence=low.
- When input is demo/sample/stale, return preview_only or dry_run and block formal approval/live.
- When source capability is read-only/manual, produce recommendation or task only.

# 输出结构

- confirmed outputs：daily_target, hourly_curve
- candidate outputs：baseline_version, confidence

# forbidden_actions / 禁止事项

- treat_demo_data_as_real_today_data
- create_formal_approval_from_demo_or_stale_data
- bypass_data_gate_or_approval_guard

# 测试样例

- 正常样例：见 `references/v20_behavior_cases.json` 的 normal/preview case。
- 缺字段样例：见 `references/v20_behavior_cases.json` 的 missing_hard_required case。
- demo/sample/stale 阻断样例：见 `references/v20_behavior_cases.json` 的 demo_preview case。
