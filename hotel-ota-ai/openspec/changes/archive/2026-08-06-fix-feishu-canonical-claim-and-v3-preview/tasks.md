## 1. Canonical claim

- [x] 1.1 为 OpenClaw canonical inbound event 增加 Node 红灯测试。
- [x] 1.2 修复 Feishu inbound 字段归一化，区分 `authChatId` 与 `sendTarget`。
- [x] 1.3 确认插件 diagnostics 只暴露字段存在性、账号匹配和 claim 决策，不输出原始身份值。
- [x] 1.4 覆盖 p2p 私聊：runtime `--chat-id` 使用 `oc_*` conversation，发送 target 使用 `user:ou_*`。
- [x] 1.5 插件在 routeRuntime 前尝试获取 Feishu member-info；可用时通过 `--member-info-json` 传给 Python，不可用时不阻断普通消息。

## 2. V3 preview and runtime diagnostics

- [x] 2.1 为 V3 role-map 统计和 SQLite Active Auth 查询增加 Python 测试。
- [x] 2.2 修复身份查询、成员权限查询和鉴权路径查询的 runtime-backed 受控输出。
- [x] 2.3 修复 blocked ROLE/CFG/BIND 渲染，禁止空申请号和空确认命令。
- [x] 2.4 更新根部 OpenClaw 上下文文件，明确 SQLite Active Auth、BIND、ROLE、CFG 和 `chat_bindings` 当前口径。
