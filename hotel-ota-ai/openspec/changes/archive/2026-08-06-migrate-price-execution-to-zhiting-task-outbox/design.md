## Decisions

- 任务表 outbox 是 S6 的唯一生产执行出口；旧 direct API path 保留为 deprecated compatibility，但默认 blocked。
- 仓库测试使用 SQLite 表模拟两张 MySQL 任务表和两张 OTA 商品映射表；生产部署提供 additive `ALTER TABLE` 和字段检查命令。
- S6 写入任务前必须满足：`admin/owner`、已绑定酒店、写入开关开启、二次确认/审批、active price guard、商品映射存在、平台允许、去重通过。
- 任务写入按 `channel_source` 分平台：`meituan` 写 `meituan_zhiting_price_task`；`ctrip` 写 `ctrip_zhiting_price_task`，携程必须保留 `product_cipher`。
- 平台护栏优先级后续可扩展为商品级/平台房型/酒店房型；本 change 先实现 resolver 字段和写入 gate，避免绕过现有 active policy。
- `read_price_task_status()` 只读回 `PENDING/SUCCESS/FAILED`，不得把 AI 写入任务解释为 OTA 已成功。

## Non-goals

- 不实现执行插件本身。
- 不直接执行 OTA/PMS API。
- 不自动修改生产 MySQL。
- 不通过飞书自由文本直接写数据库；仍需二次确认或审批。
