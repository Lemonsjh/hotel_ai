## Why

生产 Gateway 的 `inbound_claim` 事件使用 OpenClaw 2026.5.28 canonical 字段，当前插件优先读取旧字段，可能放行酒店业务消息进入 Agent。V3 role-map preview 也仍按 legacy role 字段统计，造成错误诊断。

## What Changes

- 按 canonical event 归一化 Feishu account、会话、发送者、群聊标记和内容。
- 增加不含身份原值或消息内容的 claim 诊断。
- 修复 V3 role-map 的角色、成员、酒店和群绑定统计。
- 增加 Gateway 环境与 binding 集合一致性的只读检查。

## Impact

影响 Feishu 插件、鉴权 preview、CLI diagnostics、Node/Python 测试和部署说明；不修改服务器私有配置、Gateway 服务或 channel binding。
