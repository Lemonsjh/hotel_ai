# S15/S16 真实字段算法实现

## 1. 依赖边界

S15 与 S16 不消费 S2、S4、S5、S7、S9 或 S14 的运行结果。

生产依赖为：

```text
HOTEL_OTA_DB_DSN_<HOTEL_ID> / HOTEL_OTA_DB_DSN
  -> runtime/sales_progress/repository.py
  -> S15 baseline_service
  -> S16 deviation_service
```

字段名与表名由代码中的固定合同决定，不读取 `config/database-source.example.json` 或服务器 `database-source.json` 做字段映射。所有业务库访问均为参数化只读查询。

## 2. 销售进度共同事实

### 2.1 当前事实

表：`pms_room_type_forecast`

使用字段：

- `hotel_id`
- `stay_date`
- `snapshot_time`
- `room_type_id`
- `room_type_name`，仅展示
- `pms_room_type_id`，仅质量检查
- `total_rooms`
- `available_rooms`
- `occupied_rooms`，仅物理在住背景
- `overbooking_rooms`
- `room_revenue`
- `adr`
- `revpar`

当前表主键不含 `snapshot_time`。因此生产只能使用表中仍然保留、且 `snapshot_time <= as_of_datetime` 的当前批次；不能据此重放已经被覆盖的旧 forecast。

### 2.2 历史小时事实

表：`pms_room_type_hourly_status`

使用字段：

- `id`
- `hotel_id`
- `stay_date`
- `snapshot_hour`，真实类型为 datetime
- `snapshot_time`
- `room_type_id`
- `room_type_name`，仅展示
- `pms_room_type_id`，仅质量检查
- `total_rooms`
- `available_rooms`
- `occupied_rooms`
- `overbooking_rooms`

完整批次键：

```text
hotel_id + stay_date + snapshot_hour + snapshot_time
```

禁止为每个房型分别取 `MAX(snapshot_time)` 后拼接。目标小时没有 exact 完整批次时，只允许使用不超过 120 分钟的较早完整批次；禁止未来点、跨日点和线性插值。

### 2.3 统一公式

房型：

```text
base_committed_sold = max(total_rooms - available_rooms, 0)
committed_sold = max(total_rooms - available_rooms + overbooking_rooms, 0)
capacity_progress = committed_sold / total_rooms
physical_occupancy = occupied_rooms / total_rooms
```

酒店：

```text
hotel_committed_sold = sum(room.committed_sold)
hotel_total_rooms = sum(room.total_rooms)
hotel_capacity_progress = hotel_committed_sold / hotel_total_rooms
```

不得平均房型比例。`committed_sold` 和完成度允许超过 100%；小时 pickup 允许为负，不强制曲线单调。

## 3. S15 日终分母

### 3.1 房型日终

表：`jl01_room_type_performance_daily`

使用字段：

- `hotel_id`
- `business_date`
- `room_type_id`
- `room_type_name`
- `pms_room_type_id`
- `pms_rate_room_type_id`
- `room_nights`
- `occupancy_rate`
- `room_revenue`
- `adr`
- `revpar`
- `snapshot_time`

自然键为 `hotel_id + business_date + room_type_id`，取最新 `snapshot_time`。`room_type_id` 为空的行不得用名称或 PMS ID 补成 canonical 房型。

房型目标完成度：

```text
target_completion(D,H,R) = committed_sold(D,H,R) / jl01.room_nights(D,R)
```

### 3.2 酒店日终纵表

表：`jy01_hotel_statistics_daily`

只允许 exact 总计行：

```sql
dimension_type = '总营业指标'
AND dimension_name = '总营业指标'
```

使用字段：

- `hotel_id`
- `hotel_name`
- `source_platform`
- `business_date`
- `dimension_type`
- `dimension_name`
- `room_type_id`
- `room_count`
- `room_nights`
- `room_revenue`
- `occupancy_rate`
- `adr`
- `revpar`
- `sold_rooms`
- `remaining_rooms`
- `orders_today`
- `snapshot_time`

不得跨房型、渠道、客源等维度汇总整张纵表。酒店目标完成度使用 exact 总计 `room_nights`。同时计算 JL01 canonical 房型间夜合计；不一致时保留两套事实并输出 `hotel_room_type_final_conflicts`，不修改任何一方。

## 4. S15 日期分层

日期标签直接读取本项目本地 SQLite `calendar_days`：

- `weekday`
- `is_weekend`
- `is_holiday`
- `holiday_name`
- `holiday_group`
- `season_tag`
- `is_adjusted_workday`
- `school_vacation_tag`
- `local_event_count`
- `event_heat_level`
- `source_quality`

不调用 S4。

执行顺序：

1. P0：上一年批准窗口 + 同季节/节假日/星期，最少 3 天。
2. P1：最近 365 天同季节/节假日/星期，最少 6 天。
3. P2：同季节/节假日/week type，最少 8 天。
4. P3：同季节/节假日，最少 10 天。
5. P4：同星期，最少 6 天。
6. P5：同 week type，最少 4 天；不足时 cold start。

当前 `calendar_days` 没有上一年批准窗口字段，因此生产加载器不会自行构造 P0。服务接口支持显式传入 `previous_year_window_start/end`；没有批准窗口时从 P1 开始，不推测窗口。

## 5. S15 基准输出

酒店与每个 canonical 房型分别生成 24 个小时点：

- 容量进度 median/P25/P80/mean/sample_count
- 目标完成度 median/P25/P80/mean/sample_count
- hour coverage
- object-level maturity

12/14/16/18/20/22 只是兼容展示点，不是算法只计算这六个小时。

有效目标：

```text
explicit target（未来接入时，0 也是有效值）
  -> 否则 selected dates 最终间夜 median
```

## 6. 房型成交价格

表：`rs01_room_revenue_daily`

源 SQL 只选择：

- `business_date`
- `room_type_id`
- `room_daily_price`
- `room_nights`
- `room_fee`
- `snapshot_time`

不选择房号、客人、订单或操作员字段。

按 `room_nights` 加权计算：

- weighted average
- weighted P20
- weighted median
- weighted P80
- min/max

## 7. OTA 纵表

表：

- `meituan_ota_business_metrics`
- `ctrip_ota_business_metrics`

行身份使用 `metric_code`，数值使用 `metric_value`，单位用 `metric_unit` 校验。`metric_name` 仅展示，不作为算法身份。

### 7.1 美团

主要绑定：

- `FLOW_EXPOSURE_UV` -> exposure UV
- `FLOW_INTENTION_UV` -> browse UV
- `FLOW_PAY_ORDER_CNT` -> paid orders
- `INTENTION_UV` 与 `PAY_ORDER_CNT` 仅作为重复值检查
- `PAY_ROOMNIGHT`、`PAY_AMT`、`PAY_ADR` 作为经营背景
- `DAY_ROOM_LOWEST_PRICE_AVG` 作为引流价趋势

派生：

```text
first_conversion = FLOW_INTENTION_UV / FLOW_EXPOSURE_UV
second_conversion = FLOW_PAY_ORDER_CNT / FLOW_INTENTION_UV
```

重复 code 口径冲突时不相加。

### 7.2 携程

主要绑定：

- `list_page_exposure_count`
- `detail_page_visitor_count`
- `order_submit_count`
- `booking_order_count`
- `booking_sales_amount`
- `ctrip_app_visitor_count`

派生：

```text
list_to_detail_ratio = detail_page_visitor_count / list_page_exposure_count
detail_to_submit_ratio = order_submit_count / detail_page_visitor_count
```

携程列表曝光是次数口径，不命名为 UV 转化。

### 7.3 30 日表

`meituan_ota_flow_conversion_30d` 和 `ctrip_ota_flow_conversion_30d` 只作为 `single_window_reference` 返回，绝不拆成逐日样本。

没有同范围真实市场分母时，下列对象明确 unavailable：

- market orders baseline
- hotel market share baseline
- stable market browse-pay baseline
- stable lead-price rank baseline

## 8. S16 当前事实和双线

S16 当前实际只来自 `pms_room_type_forecast` 的统一 committed 公式，不从 JD01/JD04/KF11 或 `occupied_rooms` 拼接。

酒店和每个房型同时计算：

```text
capacity delta pp
capacity expected sold
capacity room gap

target completion delta pp
expected sold at hour
checkpoint room gap
remaining target gap
```

每条线同时返回 baseline median/P25/P80。

阈值：

- `<= -25` severe slow
- `(-25, -15]` significant slow
- `(-15, -8)` slow
- `[-8, 8)` normal
- `[8, 15)` fast
- `>= 15` significant fast

双线解释：

- 两线都慢：`genuine_sales_lag`
- 目标慢、容量正常/快：`ambitious_target_gap`
- 目标正常/快、容量慢：`conservative_target_on_track`
- 两线正常/快：`on_track_or_ahead`

## 9. 房型结构

输出：

- slow/fast room-type count
- slow target share
- largest negative/positive gap room type
- `broad_based_slowdown`
- `room_type_structural_lag`
- `mix_offset_detected`

只有当前房型范围完整且所有目标线可计算时，才执行酒店 checkpoint gap 与房型 gap 合计的 `structure_reconciliation`。

## 10. 日期适用范围

- `as_of_date == target_stay_date`：允许按入住日当天小时曲线计算 S16。
- `as_of_date < target_stay_date`：返回 `future_stay_date_requires_lead_time_baseline`。
- `as_of_date > target_stay_date`：返回 `historical_current_fact_requires_hourly_replay`。

当前实现不会把未来入住日的提前预订状态与入住日当天小时曲线直接比较。

## 11. 运行与安全

- 业务库连接：`HOTEL_OTA_DB_DSN_<HOTEL_ID>` 优先，其次 `HOTEL_OTA_DB_DSN`。
- DSN 必须是 MySQL。
- 未配置连接时返回 `business_database_dsn_missing`，不启用样例结果。
- 只读查询失败时按数据族局部降级；核心小时数据缺失则阻断 S15 正式基准。
- 现有 SQLite `baselines` 只用于保存标准结果和兼容调用，不改变业务数据库。
