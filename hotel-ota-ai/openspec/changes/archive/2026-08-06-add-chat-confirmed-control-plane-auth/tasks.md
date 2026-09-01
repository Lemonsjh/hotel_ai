## 1. Active auth backend

- [x] 1.1 为 SQLite-first、bootstrap fallback、SQLite failure 增加测试。
- [x] 1.2 增加 auth tables、bootstrap sync 和 runtime auth resolver。
- [x] 1.3 插件 claim 后只调用 runtime，业务授权由 SQLite Active Auth 决定。

## 2. Chat confirmation

- [x] 2.1 为 request、confirm、cancel、expiry、operator/owner scope 增加测试。
- [x] 2.2 实现 sealed configuration request 状态机和审计。
- [x] 2.3 增加 Feishu intents、脱敏摘要和确认命令。
- [x] 2.4 私聊/群聊绑定通过 `BIND` 二次确认写入 `chat_bindings`。
