# S15 销售基准线 示例

## 飞书输入
> 生成今天的销售基准线和小时目标。

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "business_date": null,
    "historical_same_weekday": null,
    "historical_same_date_type": null,
    "holiday_history": null,
    "target_orders": null,
    "hourly_curve": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "target_orders": 15,
  "confidence": "medium"
}
```

## 最终中文回复样例
销售基准线已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/baseline_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N010.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
