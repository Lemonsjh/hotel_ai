# S6 房价同步执行 示例

## 飞书输入
> 确认执行前先预览这次调价。

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "approval_id": null,
    "approved_by": null,
    "room_type_id": null,
    "channel": null,
    "normal_price": null,
    "weekend_price": null,
    "begin_date": null,
    "end_date": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "dry_run",
  "approval_required": true,
  "live_call": false
}
```

## 最终中文回复样例
房价同步执行已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/execution_guard.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N016.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
