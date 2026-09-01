# 技术方案

## 数据库模板耗时

在 `database_template_result()` 入口记录 `time.perf_counter()`，统一通过 `_finish_database_template_result()` 写日志。

日志路径：

- 默认：`HOTEL_OTA_LOG_DIR/database-template-timing.jsonl`
- 若未设置 `HOTEL_OTA_LOG_DIR`，使用 `DEFAULT_LOG_DIR/database-template-timing.jsonl`

字段：

- `timestamp`
- `template`
- `hotel_id`
- `status`
- `duration_ms`
- `source_status`
- `reason`
- `row_count`
- `risk_flags`

安全约束：

- 不写 SQL 明文。
- 不写 DSN。
- 不写 open_id/user_id/union_id。
- 不写原始行内容。

## 飞书总耗时

`safe_route_feishu_command()` 已有 `feishu-route.jsonl` 总耗时记录，本 change 先补数据库模板级证据。后续如需汇总 `db_timing_summary`，可在同一日志上下文中增加 correlation id 聚合。
