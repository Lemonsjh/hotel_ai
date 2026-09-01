# S7 竞态监控 示例

## 飞书输入
> 竞对降价了我要不要跟？

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "competitor_price": null,
    "competitor_activity": null,
    "competitor_rank": null,
    "competitor_rating": null,
    "peer_competitiveness_score": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "warning_level": "watch",
  "next_skill": "S5"
}
```

## 最终中文回复样例
竞态监控已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/competition_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N007.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
