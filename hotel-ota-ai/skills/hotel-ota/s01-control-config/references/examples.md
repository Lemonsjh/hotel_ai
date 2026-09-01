# S1 总控配置 示例

## 飞书输入
> 初始化璞悦的酒店配置，检查价格底线和审批规则。

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "hotel_id": null,
    "hotel_name": null,
    "room_types": null,
    "strategy_mode": null,
    "price_floor_by_room_type": null,
    "approval_policy": null,
    "roles": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "config_status": "sample_seeded",
  "missing_config": [
    "live_api_credentials"
  ]
}
```

## 最终中文回复样例
总控配置已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/auth_policy.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N003.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
