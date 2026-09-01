## Context

S5/S6 已有底价、封顶价和 demo/live guard，但 `price_guard` 允许缺 old price，且 hash 缺 hotel scope。当前房型边界可来自数据库或输入，执行端尚未强制可信配置来源。

## Goals / Non-Goals

**Goals:** live 路径只能使用当前价格、权威 guard、hotel-bound payload 和独立审批人；全部缺失场景 fail-closed。

**Non-Goals:** 不启用 live、不开发房型价格配置 UI、不实现最小/最大金额阈值配置写入。

## Decisions

- demo/dry-run 可继续预览；任何 live request 缺 `old_price`、`hotel_id`、guard source 或新版本 hash 都直接拒绝。
- hash canonical fields 增加 `hotel_id` 与 guard version；旧 hash 不兼容 live。
- 审批记录保存 authenticated requester/approver identity 和 role；同 identity 审批被拒绝。

## Risks / Trade-offs

- 旧 pending approval 无法用于 live → 这是预期安全迁移，保留为历史只读。
- 权威 guard 未配置会阻断 live → 保持 default-off，要求先完成后续受控配置流程。
