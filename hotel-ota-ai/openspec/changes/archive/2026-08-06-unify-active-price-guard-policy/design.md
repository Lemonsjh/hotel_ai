## Decisions

- 有效 SQLite policy 优先；仅在不存在 policy 时读取受控默认并标记 `source=default_policy`。
- `price_guard` 接收已解析的 directional policy，不从 YAML 或聊天输入推导生产限制。
- 飞书查询仅展示脱敏汇总；申请仍走现有 configuration request，绝不直接写 SQLite 或 `/etc`。
