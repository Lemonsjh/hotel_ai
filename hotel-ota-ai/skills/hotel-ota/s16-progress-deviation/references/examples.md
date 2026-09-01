# S16 进度偏差诊断 示例

## 飞书输入
> 当前进度落后原因是什么？

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "orders_today": null,
    "target_orders": null,
    "completion_rate": null,
    "occupancy_rate": null,
    "demand_index": null,
    "risk_flags": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "direction": "normal",
  "downstream_skill": "S14"
}
```

## 最终中文回复样例
进度偏差诊断已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/progress_deviation_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N011.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
