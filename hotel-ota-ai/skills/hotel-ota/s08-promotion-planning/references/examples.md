# S8 推广通数据展示示例

## 飞书输入

> 查看本店 S8 推广通近30天数据。

## runtime 输出样例

```json
{
  "status": "ok",
  "skill_id": "S8",
  "summary": "已读取并展示推广通近30天数据，共 1 个投放单元。",
  "evidence": {
    "promotion_display": {
      "status": "ok",
      "source_status": "ok",
      "source_table": "meituan_ota_promotion_performance_30d",
      "data_business_date": "2026-08-06",
      "data_snapshot_time": "2026-08-07 09:30:00",
      "period_start_date": "2026-07-08",
      "period_end_date": "2026-08-06",
      "item_count": 1,
      "items": [
        {
          "plan_id": "plan-001",
          "plan_name": "计划A",
          "launch_id": "launch-001",
          "launch_name": "投放单元A",
          "promotion_name": "推广通",
          "period_start_date": "2026-07-08",
          "period_end_date": "2026-08-06",
          "snapshot_time": "2026-08-07 09:30:00",
          "spend_amount": 1000,
          "cash_spend_amount": 800,
          "exposure_count": 10000,
          "click_count": 500,
          "booking_order_count": 25,
          "room_night_count": 30,
          "booking_order_amount": 6000,
          "click_rate_pct": 5.0,
          "cost_per_click": 2.0,
          "cost_per_booking": 40.0,
          "cost_per_room_night": 33.3333,
          "average_booking_order_amount": 240.0,
          "promotion_adr": 200.0,
          "roas": 6.0,
          "promotion_amount_after_spend": 5000.0,
          "cash_roas": 7.5,
          "booking_conversion_rate_pct": 5.0
        }
      ]
    }
  },
  "recommendations": [],
  "actions": [],
  "approval_required": false,
  "write_performed": false,
  "live_allowed": false
}
```

## 中文展示示例

推广通近30天数据已读取。当前快照时间为 2026-08-07 09:30:00，统计周期为 2026-07-08 至 2026-08-06。

计划A / 投放单元A / 推广通：推广花费 1000，现金花费 800，曝光 10000，点击 500，预订订单 25，间夜 30，推广归因订单金额 6000，来源点击率 5.0%，来源 CPC 2.0；单次获客成本 40，每间夜成本 33.3333，推广预订单均价 240，推广 ADR 200，ROAS 6.0，现金 ROAS 7.5，推广花费后金额 5000，推广预订转化率 5.0%。

不追加“是否扩量、是否暂停、预算多少、出价多少”等建议。

## 不可计算示例

当 `booking_order_count=0` 时：

```json
{
  "cost_per_booking": "not_computable",
  "average_booking_order_amount": "not_computable"
}
```

当 `spend_amount=0` 时：

```json
{
  "roas": "not_computable"
}
```

不得展示无穷大，也不得改成 0。

## 无记录示例

```json
{
  "status": "ok",
  "skill_id": "S8",
  "summary": "当前最新快照没有可展示的推广通数据。",
  "evidence": {
    "promotion_display": {
      "status": "ok",
      "source_status": "no_rows",
      "source_table": "meituan_ota_promotion_performance_30d",
      "item_count": 0,
      "items": []
    }
  },
  "recommendations": [],
  "actions": [],
  "approval_required": false,
  "write_performed": false,
  "live_allowed": false
}
```

无记录不等于未开通、暂停或效果为 0。

## 禁止示例

以下内容不得出现在 S8 业务输出中：

- `promotion_status`
- OPEN / CLOSED / PENDING
- RUNNING / PAUSED
- “建议扩量”
- “建议暂停”
- “预算调整为……”
- “已创建审批”
- “已执行推广”
