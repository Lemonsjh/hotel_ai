结论：菜单流程被阻断。
数据：检查 `blocked_reason`、`auth_context`、`menu_id`。
证据：常见值包括 `menu_owner_mismatch`、`menu_expired`、`unknown_menu_command`、`missing_required_params`。
风险：阻断状态下不得补执行。
建议：修正身份、编号或参数后重新发起菜单。
审批：未进入审批流程。
