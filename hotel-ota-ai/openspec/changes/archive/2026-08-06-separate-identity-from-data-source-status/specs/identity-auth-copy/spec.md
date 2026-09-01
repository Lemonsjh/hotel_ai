## ADDED Requirements

### Requirement: 身份话术不混入经营数据源判断
系统 MUST 让身份类命令只回答鉴权和群绑定状态，不混入 demo/sample/live/MySQL 经营数据源判断。

#### Scenario: 查询身份
- **WHEN** 用户发送“我是谁”或等价身份命令
- **THEN** 输出 MUST 包含鉴权状态、当前角色、当前群绑定酒店和鉴权来源
- **AND** 输出 MUST 包含“本指令只检查身份和群绑定，不读取经营数据”
- **AND** 输出 MUST 提示如需确认真实数据源可发送“当前数据源”或“实时房态”
- **AND** 输出 MUST NOT 包含 `demo_data`、`sample_data`、`demo/dry-run/production_locked`
- **AND** 输出 MUST NOT 用正式审批/live 是否可用作为身份判断结论
