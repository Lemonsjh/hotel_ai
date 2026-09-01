# 技术方案

## 统一实时出租率

新增或扩展内部模板 `realtime_occupancy`，输出字段：

- `formula_version=jd01_jd04_kf11_realtime_occupancy_v1`
- `actual_occupancy_rate`
- `actual_numerator_rooms`
- `denominator_rooms`
- `numerator_components`
- `denominator_components`
- `maintenance_rooms`
- `dirty_rooms`
- `duplicate_risk`
- `as_of_time`
- `snapshot_time`

公式：

```text
分子 =
1. jd01 booking_status=已入住 且 departure_time > as_of_time
+ 2. jd01 booking_status=预订 且 DATE(arrival_time)=business_date
+ 3. jd04 checkout_time > as_of_time

分母 =
kf11 当天总房间数 - maintenance_rooms
```

去重规则：

- 优先 `room_no`
- 其次 `order_id`
- 如果缺去重键，输出 `duplicate_risk=true`

`dirty_rooms` 不扣分母，只作为风险字段输出。

## S2/S14/S5/S16 复用

- `expected_occupancy_result()` 改为调用统一实时出租率结果。
- `deviation()` 使用统一实时出租率作为 actual。
- `operation_diagnosis` 可以继续提供 OTA 指标，但经营概览优先补充统一实时出租率。
- 旧 `actual_room_nights`、`target_room_nights` 可保留为辅助证据，不作为 S16 主判断。

## 历史日与实时粒度

- 历史日主表：`jy01_hotel_statistics_daily`。
- 历史日明细校验：`rs01_room_revenue_daily`，汇总时必须过滤 `charge_subject='房费'`。
- 实时主表：`jd01`、`jd04`、`kf11`。
- `rs01.checkin_time` 只能标注为 `checkin_curve`，不能标注为 `booking_curve`。

## 销售基准线

日目标优先级：

1. `sales_baseline`
2. `jy01_hotel_statistics_daily`
3. `rs01_room_revenue_daily` 过滤 `charge_subject='房费'`
4. `daily_metrics`
5. 非生产 demo/local fallback

小时/分时曲线优先级：

1. 真实订单创建/预订时间，如 `jd01.booking_time/create_time/order_time/pay_time`
2. `reservation_snapshot.booking_time + arrival_time`
3. `rs01.checkin_time`，标注 `checkin_curve`
4. `DEFAULT_HOURLY_ANCHORS`，标注 `fallback_ratio_curve` 且 `confidence=low`

S16 目标曲线输出：

- `target_daily_occupancy_rate`
- `target_occupancy_rate_by_checkpoint`
- `checkpoint_target_occupancy_rate`
- `source_confidence`
- `fallback_curve_allows_auto_pricing=false` 当使用默认锚点或低置信曲线
