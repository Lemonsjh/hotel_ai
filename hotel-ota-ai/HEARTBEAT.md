# HEARTBEAT

## 当前运行补充

飞书权限先查 SQLite Active Auth，JSON 只作为 bootstrap / emergency fallback。数据库兼容读取走 `runtime/adapters/normalized_query.py`：`hotel_room_type_mapping` 是统一房型和平台商品身份事实源，`hotel_name` legacy fallback 只读，平台为空按 `walkin`。S15 只使用真实历史分时批次生成小时目标曲线；缺失小时保留缺口并标记采集覆盖不足，不使用默认累计比例或默认锚点补造生产事实。

本文件只记录 workspace 当前心跳提醒。它不是权限来源、业务数据来源或审批依据；项目根级规则以 `AGENTS.md` 为准。

## 当前阶段

当前项目处于生产闭环试运行阶段，同时保留本地 demo、dry-run 和 preview 能力。

## 本地 demo 提醒

本地演示可以使用 demo 数据，但必须清楚标注数据来源和 fallback 状态。演示结果只能用于 preview / dry-run / 报告预览，不能作为正式审批或真实执行依据。

演示前建议检查：

- `env-check` 安全。
- `demo-node --all` 覆盖 N001-N022。
- `demo-chain --all` 覆盖 SC01-SC10。
- `formal_approval_created=false`。
- `live_allowed=false`。

## 生产试运行提醒

生产飞书和真实数据链路以 runtime、受控数据源、审批记录和输出安全闸门为准。缺数据时报告数据缺口，不补造经营结论。

普通业务用户默认只看业务结论、风险、建议和下一步。调试字段只给开发者调试视图。
