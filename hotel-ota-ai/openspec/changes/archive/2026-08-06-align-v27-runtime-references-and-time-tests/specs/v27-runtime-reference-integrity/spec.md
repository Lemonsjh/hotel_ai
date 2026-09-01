## ADDED Requirements

### Requirement: Active V27 引用
中性 contract loader 和 active algorithm rule metadata MUST 引用 `contracts/v27/`；仅显式 legacy 资产可以引用 V26 或顶层迁移文件。

#### Scenario: 旧 active 引用
- **WHEN** 校验发现 active runtime metadata 指向旧 contract 路径
- **THEN** drift 校验失败并报告该文件

### Requirement: 市场缺口降级
market context MUST 将事件、区域热度、天气、运营和进度的 required 缺口反映为 `partial` 或 `data_gap`。

#### Scenario: 未配置活动源
- **WHEN** events provider 未配置
- **THEN** market context 不得声明完整 fresh downstream 状态

### Requirement: 经验候选脱敏
经验候选 MUST 只持久化允许字段，且不得包含 DSN、token、身份标识或行级隐私值。

#### Scenario: 包含 DSN 的 summary
- **WHEN** runtime summary 含数据库连接字符串
- **THEN** candidate 校验拒绝或脱敏该值且不持久化原文
