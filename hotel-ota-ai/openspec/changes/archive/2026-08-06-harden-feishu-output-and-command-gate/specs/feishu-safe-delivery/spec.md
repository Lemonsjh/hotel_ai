## ADDED Requirements

### Requirement: 最终文本安全闸门
任何将发送到飞书的文本 MUST 在 runtime payload 和插件发送边界通过输出安全闸门。

#### Scenario: 敏感运行时文本
- **WHEN** 已渲染文本包含身份标识、服务器路径、配置、原始 JSON 或调试参数
- **THEN** 系统替换为安全拒绝文本且不发送原文本

### Requirement: 普通业务视图
普通飞书业务视图 MUST NOT 展示 model/provider、Agent、runtime command、coverage、calculation trace 或完整小时数组。

#### Scenario: 收益算法预览
- **WHEN** operator 或 owner 请求收益预览
- **THEN** 文本仅展示业务结论、价格边界、风险和 preview 安全状态

### Requirement: 维护请求拒绝
飞书业务入口 MUST 拒绝配置修改、模型切换、插件安装、Git 操作和服务重启请求。

#### Scenario: Git 清理请求
- **WHEN** 用户请求 `git stash`、`git clean` 或 `systemctl restart`
- **THEN** 系统返回固定维护拒绝且不执行操作
