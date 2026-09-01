## ADDED Requirements

### Requirement: OTA 分析读取遵守酒店渠道开关
生产 OTA 分析读取 MUST 在查询渠道表前应用酒店启用渠道配置。

#### Scenario: 酒店只启用美团
- **WHEN** `hotels.config_json.channels` 仅包含 `meituan`
- **THEN** OTA 业务指标、评价、活动和商品读取不得查询携程表
- **AND** 返回 metadata 标记启用渠道为 `meituan`

#### Scenario: 显式请求禁用渠道
- **WHEN** 请求 `source_platform=ctrip` 且酒店启用渠道不包含 `ctrip`
- **THEN** 读取结果为空
- **AND** 返回风险标记 `requested_ota_channel_disabled`

#### Scenario: 渠道配置不可用
- **WHEN** 酒店配置表不存在或 `config_json.channels` 无法读取
- **THEN** 读取层保持原有表查询行为
- **AND** 返回风险标记 `ota_channel_config_unavailable`
