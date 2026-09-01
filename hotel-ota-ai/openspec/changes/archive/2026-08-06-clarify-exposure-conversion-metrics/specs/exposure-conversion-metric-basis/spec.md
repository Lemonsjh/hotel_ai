## ADDED Requirements

### Requirement: 曝光指标必须带单位口径
OTA 诊断输出 MUST 区分 `曝光量` 和 `曝光人数`。

#### Scenario: 同时存在曝光量和曝光人数
- **WHEN** 指标行同时包含 `曝光量` 和 `曝光人数`
- **THEN** 系统优先使用 `曝光量`
- **AND** `exposure_unit` 为 `次`

#### Scenario: 只有曝光人数
- **WHEN** 指标行只有 `曝光人数`
- **THEN** 系统可以 fallback 使用该值
- **AND** `exposure_unit` 为 `人`

### Requirement: 支付转化率必须带口径
支付转化率输出 MUST 标记转化率口径。

#### Scenario: 浏览支付转化率
- **WHEN** 指标名为 `payment_conversion_rate`、`支付转化率` 或 `浏览支付转化率`
- **THEN** 输出 `payment_conversion_rate_basis=view_to_payment`
