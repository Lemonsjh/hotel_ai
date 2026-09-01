# S10 ROI 决策 示例

## 飞书输入
> 这个推广 ROI 值不值得继续投？

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "promotion_cost": null,
    "promotion_revenue": null,
    "room_nights": null,
    "adr": null,
    "revpar": null,
    "commission": null,
    "refund_amount": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "decision": "observe",
  "field_quality": "manual_required"
}
```

## 最终中文回复样例
ROI 决策已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/roi_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N013.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
