# S4 环境行情感知 示例

## 飞书输入
> 今天需求是低谷还是旺日？

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "business_date": null,
    "holiday_type": null,
    "regional_event": null,
    "market_orders_today": null,
    "market_orders_last_week_same_time": null,
    "demand_index": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "demand_index": 58,
  "demand_level": "strong"
}
```

## 最终中文回复样例
环境行情感知已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/demand_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N006.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
