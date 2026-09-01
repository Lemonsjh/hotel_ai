## Why

酒店飞书入口插件缺少可验证的 OpenClaw 插件清单，且仓库单测不能证明生产消息在模型前被 claim。必须先固定安装契约和隔离验证，才能把入口鉴权作为安全边界。

## What Changes

- 增加符合 OpenClaw 2026.5.28 的插件 manifest 与安装级 smoke test。
- 要求酒店账号的授权、未授权、身份缺失和未知业务消息由 `inbound_claim` 固定处理，不进入 Agent/model。
- 明确插件与 S2 timer、cron env 无关，生产启用和回滚只通过独立运维步骤执行。

## Capabilities

### New Capabilities
- `feishu-inbound-plugin-installation`: 插件安装、加载、claim 与回滚的可验证交付契约。

### Modified Capabilities
- None.

## Impact

影响 `ops/openclaw-plugins/hotel-ota-feishu-auth/`、插件 Node 测试、部署清单和服务器运维说明；不修改 Feishu binding、模型或私有配置。
