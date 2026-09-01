# S9 流量峰谷分析 示例

## 飞书输入
> 今天几点是流量高峰，几点适合推广？

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "hourly_exposure": null,
    "hourly_views": null,
    "hourly_paid_orders": null,
    "payment_conversion_rate": null,
    "traffic_peak_windows": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "traffic_state": "strong",
  "next_skill": "S8"
}
```

## 最终中文回复样例
流量峰谷分析已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/traffic_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N020.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
