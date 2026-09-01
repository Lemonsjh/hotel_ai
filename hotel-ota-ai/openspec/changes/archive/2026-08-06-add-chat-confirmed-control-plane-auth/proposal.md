## Why

日常飞书授权仍依赖 JSON bootstrap，配置变更依赖卡片 callback 设计。商业化需要运行时 SQLite 权限事实源和可审计的聊天二次确认，不允许自由文本直接写配置。

## What Changes

- 增加 SQLite active auth tables、bootstrap sync 和 fail-closed fallback。
- 增加聊天配置申请、确认、取消和成员加入流程。
- 让插件 claim 后仅调用 runtime，runtime 决定授权和确认。

## Impact

影响 storage、auth、control plane、Feishu router、插件和测试；不修改服务器私有文件或启用 live。
