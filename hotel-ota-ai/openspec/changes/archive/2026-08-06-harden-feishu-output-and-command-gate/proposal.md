## Why

安全闸门存在但最终 `send_payload` 未强制调用；部分普通模板、截断提示和维护命令仍可暴露内部实现。必须在发送边界集中拦截，而不是依赖模板作者或模型遵守约定。

## What Changes

- 将输出安全闸门接入 runtime 发送 payload 和插件发送前路径。
- 清理普通模板、根运行规则和截断提示中的内部字段与维护参数。
- 扩展维护/配置命令拒绝，生产飞书永久禁用 developer debug。

## Capabilities

### New Capabilities
- `feishu-safe-delivery`: 飞书最终文本的强制安全校验与稳定拒绝行为。

### Modified Capabilities
- None.

## Impact

影响飞书 renderer、router、插件发送逻辑、模板、AGENTS 运行规则和测试；不改变业务算法结果。
