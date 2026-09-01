# S17 客户订单分析 示例

## 飞书输入
> 分析一下今天订单的客户画像和渠道贡献。

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "order_id": null,
    "third_order_id": null,
    "order_status": null,
    "room_type_id": null,
    "room_nights": null,
    "checkin_time": null,
    "checkout_time": null,
    "payment_type": null,
    "channel_source": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "order_status": "reserved",
  "payment_type": "prepaid"
}
```

## 最终中文回复样例
客户订单分析已按多源依据完成 dry-run 判断。当前结论只作为建议，涉及真实执行时会先走 admin/owner 审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/customer_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N014.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
