# 审批申请模板

结论：存在待审批动作，审批前请核对 `approval_id`。
证据：`approval_id={{approval_id}}`，发起人 `{{requested_by}}`，数据时间 `{{data_snapshot_time}}`，新鲜度 `{{freshness_status}}`。
建议：仅 admin/owner 可审批；回复同意或拒绝时必须带上该 `approval_id`。
风险：无 `approval_id` 的确认不会执行。
