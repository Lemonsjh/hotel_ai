# 小时目标与周边活动接入计划

## 目标

把销售基准线从“只有日目标”升级为“日目标 + 分时累计目标曲线”，并把插件新表 `meituan_ota_nearby_event` 纳入周边活动上下文，供 S16 进度偏差、S5 收益决策、S6 调价安全门统一引用。

## 小时目标生成逻辑

小时目标不是每小时新增目标，而是截至指定小时的累计目标。

默认锚点：

| 时间 | 累计目标比例 |
| --- | ---: |
| 07:00 | 7% |
| 10:00 | 20% |
| 12:00 | 34% |
| 15:00 | 54% |
| 16:00 | 62% |
| 18:00 | 74% |
| 20:00 | 86% |
| 22:00 | 100% |

若日目标为 29 间夜，则生成：

| 时间 | 累计目标 |
| --- | ---: |
| 07:00 | 2 |
| 10:00 | 6 |
| 12:00 | 10 |
| 15:00 | 16 |
| 16:00 | 18 |
| 18:00 | 21 |
| 20:00 | 25 |
| 22:00 | 29 |

## 来源优先级

1. `sales_baseline.hourly_target_curve` / `hourly_curve`：最高优先级，`hourly_curve_source=sales_baseline`。
2. `daily_metrics.room_nights` 派生日目标：使用默认锚点曲线，`hourly_curve_source=derived_default_anchor`。
3. sample/demo 数据：使用默认样例曲线，`hourly_curve_source=synthetic_sample_curve`。

`derived_default_anchor` 只能用于进度节点判断和决策置信度，不能单独触发调价。

## 已实现

文件：`runtime/decisions/baseline.py`

已修复：当 MySQL `daily_metrics` 能生成日目标但没有显式小时曲线或可用历史订房时间分布时，不再输出 `hourly_curve_source=not_available`，而是生成 `hourly_curve_source=fallback_ratio_curve` 的默认累计小时目标。该曲线只用于 S15/S16 进度参考和缺口解释，`hourly_curve_policy.direct_execution_allowed=false`，不得称为真实历史曲线或作为 S5/S6 正式执行依据。

新增输出字段：

- `hourly_target_curve`
- `hourly_curve`
- `hourly_curve_source`
- `hourly_curve_policy`
- `progress_checkpoints`
- `progress_checkpoint_policy`
- `target_orders_basis=estimated_from_room_nights_1_to_1`

## 周边活动表接入计划

插件新增表：`meituan_ota_nearby_event`。当前可用字段包括：`snapshot_time`、`channel_source`、`hotel_name`、`poi_id`、`event_id`、`event_class_id`、`event_name`、`event_start_date`、`event_end_date`、`event_address`、`distance_km`、`countdown_days`。

建议统一映射：

| 表字段 | 统一字段 |
| --- | --- |
| `event_id` | `event_id` |
| `event_name` | `event_name` |
| `event_class_id` | `event_class_id` |
| `event_start_date` | `date` / `event_start_date` |
| `event_end_date` | `event_end_date` |
| `event_address` | `location` |
| `distance_km` | `distance_km` |
| `countdown_days` | `countdown_days` |
| `channel_source` | `source_platform` |
| `snapshot_time` | `data_snapshot_time` |

规则：

1. 只作为周边活动上下文和需求热度置信度证据。
2. 不允许单独触发涨价或调价执行。
3. 活动热度要结合距离、倒计时、节假日、经营进度、转化率共同判断。
4. 数据新鲜度优先使用最新 `snapshot_time`；过期活动不得用于当前日判断。

后续代码接入点：

1. `runtime/adapters/database.py` 增加 `nearby_event` 或 `ota_nearby_event` 模板。
2. `config/database-source.example.json` 增加 `meituan_nearby_event` table/columns mapping。
3. `runtime/market_sources.py` 增加 `database_nearby_event` provider，从数据库模板读取事件并转成 `build_event_context()` 的标准 events。
4. S5/S16 只读取 `event_signal/event_heat_level/local_event_count`，不能把单条活动作为直接调价信号。
