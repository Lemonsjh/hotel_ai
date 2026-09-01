## ADDED Requirements

### Requirement: 生产飞书禁止显式 demo
生产飞书入口 MUST 拒绝所有显式 demo / 演示请求。

#### Scenario: 用户请求 demo
- **WHEN** `production_feishu=True`
- **AND** 用户消息显式包含 `demo` 或 `演示`
- **THEN** runtime 返回 blocked
- **AND** `blocked_reason` 为 `demo_not_allowed_in_production_feishu`
- **AND** 不返回 `demo_data`、`sample_data` 或 `synthetic_today_demo`

### Requirement: 生产飞书禁止 demo hotel
生产飞书入口 MUST 拒绝 `*-demo` 酒店标识。

#### Scenario: 用户请求 demo hotel
- **WHEN** `production_feishu=True`
- **AND** 用户消息包含 `hotel-a-demo` 这类 demo hotel id
- **THEN** runtime 返回 blocked
- **AND** `blocked_reason` 为 `demo_hotel_not_allowed_in_production_feishu`

### Requirement: 生产飞书禁止 demo fallback
生产飞书入口 MUST NOT 在缺少真实数据或真实酒店上下文时回退到 demo manifest 酒店。

#### Scenario: 生产飞书请求 demo fallback intent
- **WHEN** `production_feishu=True`
- **AND** 请求意图原本可在本地 demo fallback
- **THEN** runtime 返回 data_gap 或 blocked
- **AND** `allow_demo_fallback` 为 false
- **AND** 不产出演示业务结论
