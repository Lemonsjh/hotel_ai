# S15/S16 诊断型数据上下文边界

以下真实表包含可参考的数据，但不具备净承诺已售或市场总量的完整语义。S15 可读取并返回诊断上下文，S16 不得将其作为主偏差分子。

## 1. JD01 毛预订创建曲线

表：`jd01_booking_detail`

使用字段：

- `hotel_id`
- `booking_time`
- `arrival_time`
- `room_count`

源端只读聚合：

```sql
SELECT DATE(arrival_time) AS stay_date,
       HOUR(booking_time) AS booking_hour,
       SUM(COALESCE(room_count, 1)) AS gross_created_rooms,
       COUNT(*) AS booking_rows
FROM jd01_booking_detail
WHERE hotel_id = :hotel_id
  AND DATE(arrival_time) BETWEEN :start_date AND :end_date
  AND booking_time <= :as_of_datetime
GROUP BY DATE(arrival_time), HOUR(booking_time)
```

输出对象：`gross_booking_created_curve_context`。

用途仅为覆盖率、订单创建节奏和数据质量诊断。由于当前字段不能重建每次取消发生的历史时间，禁止用当前 `booking_status` 反推历史各小时的净承诺已售，也禁止替代 `pms_room_type_hourly_status`。

## 2. 携程用户画像小时分布

表：`ctrip_ota_userprofile_distribution`

固定过滤：

```sql
dimension_code = 'order_hourly_distribution'
```

使用字段：

- `hotel_id`
- `platform_scope`
- `snapshot_time`
- `dimension_code`
- `bucket_label`
- `rate_pct`
- `metric_value`
- `metric_unit`
- `rank_position`

输出对象：`gross_order_hour_distribution_context`。

校验 `rate_pct` 总和是否约为 100%。该对象没有按入住日拆分，不用于：

- `committed_sold`
- 入住日小时销售基准
- S16 容量或目标完成偏差

## 3. 携程竞争圈 30 日指标

表：`ctrip_ota_competition_metrics_30d`

使用字段：

- `metric_code`
- `metric_name`
- `metric_unit`
- `period_start_date`
- `period_end_date`
- `hotel_value`
- `previous_value`
- `competitor_avg`
- `competitor_rank`
- `previous_rank`
- `competition_circle_hotel_count`
- `snapshot_time`

输出对象：`peer_demand_proxy`。

它只表示滚动窗口的同行背景。禁止执行：

```text
competitor_avg × competition_circle_hotel_count
```

来推导真实市场订单总量，也不能据此产生稳定市场份额基准。

## 4. S16 字段语义分离

容量线只输出：

- `actual_capacity_progress`
- `capacity_progress_delta_pp`
- `capacity_expected_sold`
- `capacity_room_gap`
- `remaining_capacity_rooms`

目标线只输出：

- `actual_target_completion`
- `sales_progress_delta_pp`
- `expected_sold_at_hour`
- `checkpoint_room_gap`
- `remaining_target_gap`

`remaining_target_gap` 不得出现在容量线中，防止调用方将物理容量剩余和经营目标剩余混为同一概念。
