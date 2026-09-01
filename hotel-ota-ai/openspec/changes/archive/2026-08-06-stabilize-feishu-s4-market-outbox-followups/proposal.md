## Why

当前单测已通过，但真实飞书链路仍暴露出几个生产试验前必须收敛的问题：

- `chat_binding_status` 是正常业务状态，却被输出闸门误判为配置导出。
- 飞书 S4 已经通过 SQLite Active Auth 解析到 `puyue`，但业务结果仍回落为 `puyue-demo`。
- S4 渲染元数据错误回落到 `business_snapshot`。
- 天气、节假日和活动来源仍缺少生产可信度分层：需要 Open-Meteo、远程节假日 provider 缓存，以及 bridge 握手校验。
- 知停调价 outbox 仍缺 MySQL 增量迁移、旧表字段兼容、携程 `price_editable_flag` 数字兼容、平台/商品级价格护栏和飞书 outbox 专用模板。
- 根上下文文档仍可能保留旧的 JSON 权限事实源或 direct API 调价口径。

## What Changes

- 修复飞书输出闸门允许受控权限/绑定/管理状态模板通过，同时继续阻断原始身份、密钥、DSN、SQL dump 和原始配置 JSON。
- S4 业务路由在生产飞书鉴权成功后强制使用 `auth_context.resolved_hotel_id`，并提供 `market_context_demo` 专用渲染模板。
- 新增 Open-Meteo provider、节假日远程 provider 和 SQLite holiday cache。
- 加固 `openclaw_bridge_http_search`，要求 token、service id、source type 和 demo 结果策略，未通过握手的结果只作为 untrusted/data_gap。
- 增加 outbox MySQL additive migration，outbox 查询按可用字段选择 `hotel_id`/`hotel_name`/warning fallback。
- 兼容携程 `price_editable_flag=1.0000` 等数字/字符串表示。
- 扩展 `price_guard_policies` 为平台/商品级护栏优先级，并让 S5/S6/飞书查询消费同一 resolver。
- 新增 `price_task_outbox_write` 飞书模板，明确“写入 PENDING 等待插件”，不声称 OTA 已生效。
- 更新 env-check、env.example、部署文档和 OpenClaw 根上下文。

## Impact

影响 `runtime/feishu_command_router.py`、`runtime/feishu_output_renderer.py`、`runtime/safety/feishu_output.py`、`runtime/market_sources.py`、`runtime/decisions/calendar.py`、`runtime/adapters/zhiting_price_task_outbox.py`、`runtime/control_plane.py`、`runtime/storage.py`、CLI env-check、配置示例、SQL 迁移、飞书模板、文档和测试。

本 change 不写 `/etc`，不连接生产 MySQL，不启用 `HOTEL_OTA_PRICE_TASK_WRITE_ENABLE=1`，不调用真实 OTA API，不重启 Gateway。
