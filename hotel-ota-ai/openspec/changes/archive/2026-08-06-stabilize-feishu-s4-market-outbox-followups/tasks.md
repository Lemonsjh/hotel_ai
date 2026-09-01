## 1. 飞书输出闸门与 S4 路由

- [x] 1.1 增加红灯测试：`chat_binding_status` 已绑定时 `send_allowed=true`，不泄露完整身份，不触发 `config_or_secret_export_not_allowed`。
- [x] 1.2 修复 `feishu_output_gate` 的配置导出误判，允许受控状态模板短语，继续阻断敏感原文。
- [x] 1.3 增加红灯测试：生产飞书 `s4` 使用 `hotel_id=puyue` 与 `rendered.template=market_context_demo`。
- [x] 1.4 修复 S4 路由使用 `auth_context.resolved_hotel_id`，并新增 `market_context_demo` 模板映射。

## 2. Open-Meteo、holiday provider 和活动 bridge

- [x] 2.1 增加 Open-Meteo 解析、WMO code、酒店经纬度、fallback 的测试。
- [x] 2.2 实现 `open_meteo` provider 与 canonical weather payload。
- [x] 2.3 增加节假日 provider 商用确认、缓存命中、fallback seed 的测试。
- [x] 2.4 实现 holiday remote provider 与 `holiday_calendar_cache`。
- [x] 2.5 增加 bridge 无 token、service id 不匹配、demo placeholder、verified_search 的测试。
- [x] 2.6 加固 `openclaw_bridge_http_search` 握手与 source quality。

## 3. Outbox 和价格护栏

- [x] 3.1 新增 MySQL additive migration，逐列补齐 mapping/task 字段。
- [x] 3.2 实现 outbox 查询缺 `hotel_name` 不 crash、按 `hotel_id` 优先过滤、缺隔离字段 warning。
- [x] 3.3 实现 mapping 表字段 introspection 与动态查询，并通过现有 outbox 回归。
- [x] 3.4 增加携程 `price_editable_flag=1.0000/0.0000` 测试。
- [x] 3.5 实现 `_truthy_editable_flag()`。
- [x] 3.6 增加平台/商品级价格护栏优先级测试。
- [x] 3.7 扩展 SQLite schema、resolver、S5/S6 调用和飞书查询。
- [x] 3.8 新增 `price_task_outbox_write` 飞书模板。

## 4. env、文档和验证

- [x] 4.1 更新 `config/env.example` 和 `env-check` 的 weather/holiday/event/outbox 状态。
- [x] 4.2 清理配置样例与根上下文中容易误导的市场源口径。
- [x] 4.3 更新部署文档和 manifest。
- [x] 4.4 运行 OpenSpec validate、V27 contract/drift、Node 插件测试、全量 Python 测试、`git diff --check`。
