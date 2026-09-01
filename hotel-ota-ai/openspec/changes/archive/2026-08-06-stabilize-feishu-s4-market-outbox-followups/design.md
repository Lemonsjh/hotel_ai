## Decisions

### 飞书状态输出

输出闸门按“受控状态模板”和“敏感原文”分层。允许模板名或短语如 `SQLite Active Auth`、`chat_bindings`、`BIND`、`ROLE`、`CFG`，但不允许完整 `oc_...`、`ou_...`、DSN、token、password、API key、SQL dump 或原始配置 JSON。

### S4 酒店范围

生产飞书路径的 `hotel_id` 优先级为：

1. `auth_context.resolved_hotel_id`
2. 明确受信本地维护参数
3. 本地 demo 默认 `puyue-demo`

只要 `production_feishu` 且鉴权成功，任何受保护业务 intent 都不得回落到 `puyue-demo`。

### 市场来源

天气 provider 输出 canonical payload。Open-Meteo 可无密钥调用；若配置了 key，则附加 `apikey`。Open-Meteo 失败可 fallback 到 `wttr_http`，但必须标 `source_quality=partial`。

节假日远程 provider 只在配置启用时拉取并缓存到 SQLite；商业授权未确认时标 `trial_only/non_commercial_limited`，不得标为 commercial ready。远程失败时 fallback builtin seed，但必须暴露 `holiday_source=fallback_builtin_seed` 和错误原因。

活动 bridge 必须完成握手：token 已配置、`service_id` 匹配、`source_type` 合法。demo/test/placeholder/example.invalid 或缺握手字段时返回 `data_gap`，不进入商圈热度计算。

### Outbox 和价格护栏

MySQL 迁移只增加表/字段/索引，不删除不重命名。运行时查询先 introspect 字段，优先 `hotel_id`，其次 `hotel_name`，否则不引用缺失列并返回 warning。

价格护栏 resolver 优先级：

1. `platform_product`
2. `platform_room_type`
3. `hotel_room_type`
4. `default_policy`

任务写入开启时，如果没有任何 active guard，必须 blocked；preview 可使用 `default_policy` 但不得创建正式审批或 outbox task。

### 文档口径

根上下文文件只保留当前运行事实：SQLite Active Auth 是运行时权限事实源；`feishu-role-map.json` 是 bootstrap/fallback；正式调价路径是 zhiting task outbox；旧 direct API 仅为 deprecated/local debug。
