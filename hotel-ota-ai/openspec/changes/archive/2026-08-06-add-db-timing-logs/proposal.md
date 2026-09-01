# 增加数据库模板耗时日志

## 背景

调价、修改价格护栏、查询可调商品等路径可能存在慢响应。当前缺少模板级耗时证据，容易在 MySQL、mapping、renderer、SQLite、插件回查等环节之间猜测原因。

## 目标

- 给 `database_template_result()` 增加模板级耗时 JSONL 日志。
- 默认关闭。
- 通过 `HOTEL_OTA_DB_TIMING_LOG=1` 开启。
- 日志不记录 DSN、SQL 明文、open_id 或敏感值。

## 非目标

- 不修改数据库结构。
- 不增加自由 SQL。
- 不默认打开性能日志。
