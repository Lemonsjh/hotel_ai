## Context

当前 MySQL V4 OTA 模板通过 `V4_TEMPLATE_TABLE_KEYS` 固定读取携程和美团表。`hotels.config_json.channels` 已存在，但没有接入分析读取路径。

## Goals / Non-Goals

**Goals:** 禁用渠道不参与 OTA 指标、评价、活动、商品和任务历史等分析读取；结果 metadata 暴露过滤状态，便于诊断。

**Non-Goals:** 不改价格任务写入允许渠道；不新增数据库表；不在模型输出层做字符串过滤来假装隐藏渠道。

## Decisions

- 解析 `hotels.config_json.channels` 时接受 `meituan`、`美团`、`Mtop`、`ctrip`、`携程` 等别名，统一复用 normalized query 的渠道归一逻辑。
- 当无法读取酒店配置或表不存在时，读取层 fail-open 保持旧行为，并在 `risk_flags` 标记 `ota_channel_config_unavailable`，避免因配置表缺失误杀真实数据。
- 当启用渠道集合存在时，读取层先按表 key 的平台归属过滤；显式请求已禁用渠道返回空结果并标记 `requested_ota_channel_disabled`。

## Risks / Trade-offs

- 配置读取失败时仍可能查询禁用渠道，属于可观测风险；后续可在生产配置稳定后收紧为 fail-closed。
- 仅过滤统一数据库读取层，少数不走 `database_template_result` 的旧路径需要后续单独审计。
