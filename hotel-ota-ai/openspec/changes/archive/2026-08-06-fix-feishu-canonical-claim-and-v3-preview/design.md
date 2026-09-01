## Decisions

- 插件优先使用 `event.content`、`event.channel`、`event.accountId`、`event.conversationId`、`event.senderId` 和 `event.isGroup`；旧形状只作为兼容回退。
- 目标酒店账号一旦进入 handler，所有异常和拒绝均返回 `handled=true`，不得回落到 Agent。
- 诊断只输出布尔状态、数量和不可逆 hash，不记录账号、会话、身份或正文。
- V3 preview 从全局管理员、酒店 membership 和群绑定计算统计；legacy V1/V2 行为保持不变。
