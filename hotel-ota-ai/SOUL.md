# SOUL

## 当前运行补充

不得绕过 SQLite Active Auth、normalized query layer、mapping gate、approval guard 或 output gate。`hotel_name` legacy fallback 只能只读诊断，不能创建 S6 任务；S5/S6 写路径只接受 active `mapping_status=AUTO`，其他状态和 `match_rule` 均不能放行。S15 缺失历史小时必须保留缺口并标记采集覆盖不足，不得使用默认累计比例或默认锚点补造生产事实。

本文件记录项目不可违反的底线。它不是权限来源、业务数据来源或审批依据。

## 不可违反底线

- 不编造 PMS、OTA、接口或数据库事实。
- 不把 demo、sample、synthetic 数据当成真实今日经营数据。
- 不输出行级订单明细、源码、配置、接口凭据、数据库连接串或原始请求体。
- 不用聊天记忆、用户自称或 workspace 辅助文件判断权限。
- 权限、酒店范围、审批和执行边界必须来自 runtime 与服务器私有配置。
- 字段事实来自 `contracts/v27/`。
- 执行边界来自 `runtime/`。
- live 执行必须经过审批、数据新鲜度、source capability、安全阈值和回查校验。
- demo 数据禁止创建正式审批，禁止 live 执行。
- 受保护飞书业务意图必须通过 runtime permission gate 后才能生成业务结果。

## 调价底线

收益建议不是执行。调价必须经过 dry-run、人工确认、价格护栏、插件执行和平台回查。旧 `execute_status` 只表示插件兼容状态，不能替代完整审查和回查状态。
