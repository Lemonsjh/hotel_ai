# 审批结果模板

结论：审批 `{{approval_id}}` 当前状态为 `{{approval_status}}`。
证据：审批人 `{{approved_by}}`，更新时间 `{{updated_at}}`。
建议：如需执行，继续走 S6 dry-run、安全校验、live 开关检查。
风险：审批通过不等于已经真实写入渠道。
