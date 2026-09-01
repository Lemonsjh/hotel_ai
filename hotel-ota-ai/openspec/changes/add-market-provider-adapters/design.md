## Decisions

- 天气依次尝试 OpenClaw weather、无密钥 provider、可选 QWeather；每个结果都保留来源、时间和质量。
- 活动搜索始终标记 `search_inferred/partial`，只能影响诊断提示和置信度。
- 节假日、调休和本地特殊日期只来自 seed，搜索仅能提出待确认草稿。
