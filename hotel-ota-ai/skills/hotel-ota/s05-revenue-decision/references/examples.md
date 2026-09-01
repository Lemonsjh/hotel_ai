# S5 智能收益决策示例

## 飞书输入

> 调价决策

## 回复模板

下面只演示结构，实际数值以 runtime 返回为准。

```text
S5 收益候选（真实数据只读）
目标入住日：2026-08-06｜计算时点：2026-08-06 19:01
候选 4 个｜可进入 S6 dry-run 0 个。
S15 依据：当前小时证据较弱，仅用于解释置信度，不改变调价判断。
大盘热度：0.88；市场不冷：否（门槛 ≥0.90）。

meituan｜璞韵大床房
当前原卖价 ¥478 → 候选 ¥478（0.00%）；仅收益参考。
房型证据：销售进度 -25pp，剩余库存 50%。
未形成正式调价：流量、二转或价格证据尚未满足对应方向条件。
时间证据：confidence=weak，仅作趋势参考。

meituan｜至臻・电竞双床房
当前原卖价 ¥525 → 候选 ¥525（0.00%）；仅收益参考。
房型证据：销售进度 +13.33pp，剩余库存 20%。
未形成正式调价：大盘热度低于市场不冷门槛。
规则状态：strong_pricing_rule_not_satisfied。

其余商品按相同方式分别说明；相同的市场或边界信息可以精简，但不能只列名称和价格，也不能把不同商品的原因合并。

边界
预计酒店收入仅供运营查看，不参与调价写入或审批。
S5 只生成候选和预览；正式候选交给 S6 重新校验。
```

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/revenue_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N015.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
