# S2 经营房态采集 示例

## 飞书输入
> 今天璞悦经营情况怎么样？

## sample/manual/RPA 输入
```json
{
  "hotel_id": "puyue",
  "data_source_type": "sample_data",
  "field_quality": "inferred",
  "business_fields": {
    "occupancy_rate": null,
    "adr": null,
    "revpar": null,
    "available_rooms": null,
    "sold_rooms": null,
    "remaining_rooms": null,
    "orders_today": null,
    "risk_flags": null
  }
}
```

## runtime 输出样例
```json
{
  "status": "ok",
  "summary": "数据库今日经营快照：出租率 79.93%, ADR 135.83, RevPAR 108.26",
  "business_summary": {
    "template_id": "business-summary",
    "sections": {
      "conclusion": "数据库今日经营快照：出租率 79.93%, ADR 135.83, RevPAR 108.26",
      "evidence_date": {
        "data_business_date": "2026-06-07",
        "data_snapshot_time": "2026-06-07 10:00:00",
        "freshness_status": "fresh",
        "today_label_allowed": true
      },
      "core_metrics": {
        "occupancy_rate": 0.7993,
        "adr": 135.83,
        "revpar": 108.26
      },
      "risks": [],
      "recommended_actions": ["先确认数据日期和新鲜度，再解读经营结论。"],
      "approval_status": "仅可作为经营建议；真实调价仍需单独审批"
    }
  }
}
```

## 最终中文回复样例
结论：数据库今日经营快照：出租率 79.93%，ADR 135.83，RevPAR 108.26。
证据：营业日期 2026-06-07，快照时间 2026-06-07 10:00:00，新鲜度 fresh。
风险：暂无；如果数据不是今日实时口径，不能称为今日经营快报。
建议动作：先观察晚高峰转化；涉及调价、推广或房量动作时，先走 dry-run 和 admin/owner 审批。
审批状态：当前只是经营摘要，不是调价审批。

## V20 Demo Behavior Cases

- Algorithm rules: `runtime/algorithm_rules/operating_snapshot_rules.yaml`
- Structured cases: `references/v20_behavior_cases.json`
- Demo fixture: `examples/demo_data/nodes/N005.json`
- Required demo safety: `data_source_type=demo_data`, `approval_data_allowed=false`, `live_allowed=false`
