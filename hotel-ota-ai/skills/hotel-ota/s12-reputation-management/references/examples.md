# S12 口碑管理 示例

## 飞书输入
> 这条差评要不要升级店长？

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "rating_total": null,
    "bad_review_rate": null,
    "review_content": null,
    "guest_impression_keywords": null,
    "bad_review_followup_status": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "severity": "medium",
  "needs_manager_escalation": true
}
```

## 最终中文回复样例
口碑管理已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/reputation_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N008.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
