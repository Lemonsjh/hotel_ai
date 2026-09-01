## Context

插件当前可做 handler 单测，但缺少 OpenClaw 安装清单和隔离加载验证。生产 Gateway 配置及 registry 位于服务器私有目录，不由仓库自动修改。

## Goals / Non-Goals

**Goals:** 固定目标版本的 manifest；在临时 OpenClaw Home 验证 install、validate 和 claim；为生产启用提供备份、验证和回滚步骤。

**Non-Goals:** 不安装生产插件、不清理服务器 registry、不重启 Gateway、不引入 S2 timer。

## Decisions

- manifest 的字段以目标服务器安装的 OpenClaw 2026.5.28 schema 为唯一依据，不能仅凭 `package.json` 猜测。
- claim handler 对目标酒店账号返回 `handled=true`；所有发送文本必须来自 runtime compact payload 且经过输出安全闸门。
- 生产 rollout 是人工批准后的独立步骤，隔离 smoke 不能替代真实 Feishu 授权/拒绝验证。

## Risks / Trade-offs

- 目标版本插件 schema 与本机 CLI 不一致 → 在服务器只读提取 schema 后再生成 manifest。
- claim 配置错误可能阻断业务群消息 → 先使用隔离账号 smoke，并保留 disable/uninstall 回滚步骤。
