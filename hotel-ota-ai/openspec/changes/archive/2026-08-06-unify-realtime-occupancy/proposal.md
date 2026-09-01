# 统一实时出租率和销售基准线口径

## 背景

当前 S2、S5、S14、S16 对出租率和进度的计算来源不一致。部分路径仍使用历史日表、`stayover_rooms + new_arrival_rooms` 或 `maintenance_rooms + dirty_rooms` 作为不可售房，导致实时出租率、调价判断和节点进度诊断可能偏离真实经营口径。

## 目标

- 新增统一实时出租率口径，基于 `jd01`、`jd04`、`kf11` 明细或状态表。
- S2、S14、S5、S16 复用同一套实时出租率结果。
- S16 主判断从 `actual_room_nights` 改为 `actual_occupancy_rate_at_checkpoint` 对比 `target_occupancy_rate_at_checkpoint`。
- 历史日粒度继续使用 `jy01_hotel_statistics_daily`，`rs01_room_revenue_daily` 仅作明细校验和拆分。
- 销售基准线明确数据来源优先级和置信度，默认锚点只能作为低置信 fallback。

## 非目标

- 不修改真实数据库结构。
- 不新增自由 SQL 执行入口。
- 不让 `rs01` 冒充实时出租率或真实小时销售曲线。
- 不让低置信 fallback 自动触发调价。

## 影响范围

- `runtime/adapters/database.py`
- `runtime/decisions/pricing.py`
- `runtime/decisions/deviation.py`
- `runtime/decisions/baseline.py`
- `runtime/decisions/hourly_history.py`
- `runtime/s14_operation_diagnosis.py`
- `runtime/cli.py`
- 相关 tests
