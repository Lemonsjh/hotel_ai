# S3 消息中台 示例

## 飞书输入
> 生成今天的飞书经营日报和审批卡片。

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "message_type": null,
    "target_role": null,
    "priority": null,
    "approval_required": null,
    "actions": null,
    "risk_level": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "target_role": "owner",
  "priority": "high"
}
```

## 最终中文回复样例
消息中台已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/message_templates_policy.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N018.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
