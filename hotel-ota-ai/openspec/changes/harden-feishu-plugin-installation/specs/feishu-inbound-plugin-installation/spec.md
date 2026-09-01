## ADDED Requirements

### Requirement: 插件安装契约
酒店飞书入口插件 MUST 提供目标 OpenClaw 版本可识别的插件 manifest，并在隔离 OpenClaw Home 中通过安装和配置校验。

#### Scenario: 隔离安装成功
- **WHEN** 在临时 OpenClaw Home 安装插件
- **THEN** 插件清单可识别且 `openclaw config validate` 通过

### Requirement: 模型前消息 claim
目标酒店账号的入站消息 MUST 在模型调用前完成身份校验、runtime route 或固定拒绝，并返回 `handled=true`。

#### Scenario: 未授权消息
- **WHEN** 目标酒店账号收到未授权或身份缺失的消息
- **THEN** 插件返回固定安全回复且不创建 Agent/model turn

### Requirement: 非默认定时器边界
插件 MUST NOT 安装、启用或依赖 S2 timer、cron env 或定时推送。

#### Scenario: 普通路由
- **WHEN** 未配置 S2 timer 或 cron env
- **THEN** 飞书按需 runtime 路由仍可用
