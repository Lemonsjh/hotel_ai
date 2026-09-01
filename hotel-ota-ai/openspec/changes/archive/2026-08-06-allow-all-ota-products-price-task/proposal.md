## Why

生产调价写入的是价格任务表，不是直接调用 OTA 实时改价接口。只要商品有有效商品 ID、可信映射和必要护栏，挂牌全日房、超级团购、钟点房和活动商品都应能进入任务表。

当前写路径仍把 `price_editable_flag=NULL` 和 `is_hour_room=1` 当成强阻断，导致可由插件处理的商品被错误拦截。

同时 `runtime.cli` 作为模块执行时缺少入口，`python -m runtime.cli --help` 和 `database-query` 无输出，影响生产手工验证。

## What Changes

- 给 `runtime.cli` 补齐模块入口。
- 调价任务表 readiness 删除 `price_editable_flag` 和 `is_hour_room` 强阻断。
- 保留可信映射、active、`room_type_id`、`source_product_id`、平台开关、价格护栏、审批确认、插件回查和写任务表开关等必要闸门。
- `price_editable_flag` 和 `is_hour_room` 继续作为信息字段保留到输出和任务行，不作为强阻断。

## Impact

- 影响 `runtime/cli.py`、`runtime/adapters/normalized_query.py`、`runtime/adapters/zhiting_price_task_outbox.py` 和相关测试。
- 不改变审批流程，不绕过价格护栏，不直接执行 live OTA 改价。
